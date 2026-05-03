"""
/* ============================================================
 * coordinator.py — ThermoMaven MQTT-driven data coordinator
 * ============================================================
 *
 * One coordinator per config entry. Owns:
 *   - the REST client (login, cert apply)
 *   - the AWS IoT MQTT subscription
 *   - the in-memory device + probe state cache
 *   - listener bookkeeping for entities
 *
 * Architecture:
 *   - Entry setup → REST login → REST mqtt_cert_apply → download
 *     .p12 → split to PEM → start paho MQTT in a worker thread
 *   - paho's `on_message` schedules a coroutine on the HA loop
 *     to update state and notify entity listeners
 *   - Entities subscribe via `add_listener(deviceId, callback)`;
 *     callback is invoked whenever that device's state changes
 *
 * Why paho-mqtt in a thread (not aiomqtt): the cert is delivered
 * as a .p12 keystore, and paho's `tls_set_context()` accepts a
 * pre-built ssl.SSLContext that matches AWS IoT's mTLS quirks.
 * Threading layer is short and well-isolated.
 * ============================================================
 */
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import ssl
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp
import paho.mqtt.client as mqtt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import NoEncryption, pkcs12

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ThermoMavenApiClient, ThermoMavenAuthError
from .const import (
    ACTION_FINISH,
    ACTION_START,
    ACTION_STOP,
    AMAZON_ROOT_CA1,
    CMD_DEVICE_CMD_RECEIPT,
    CMD_TYPE_COOKING_ACTION_SUFFIX,
    CMD_TYPE_SETTING_MODIFY_SUFFIX,
    CMD_TYPE_STATUS_SUFFIX,
    CMD_USER_DEVICE_LIST,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_EMAIL,
    DOMAIN,
    EVENT_COMMAND_RECEIPT,
    F_CMD_DATA,
    F_CMD_TYPE,
    F_COOKING_MODE,
    F_COOK_UUID,
    F_DEVICE_ID,
    F_DEVICE_MODEL,
    F_DEVICE_NAME,
    F_DEVICE_SN,
    F_DEVICES,
    F_FIRMWARE_VERSION_CODE,
    F_LAST_STATUS_CMD,
    F_PROBES,
    F_PROBE_COLOR,
    F_SET_PARAMS,
    F_SET_TEMPERATURE,
    F_START_CLIENT,
    F_SUB_TOPICS,
    MQTT_ENDPOINT,
    MQTT_KEEPALIVE,
    MQTT_PORT,
    START_CLIENT_HA,
    TEMP_SCALE,
)

_LOGGER = logging.getLogger(__name__)


def _md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


class ThermoMavenCoordinator:
    """Owns the MQTT connection and aggregated device state for one account."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._session: aiohttp.ClientSession = async_get_clientsession(hass)
        self._email: str = entry.data[CONF_EMAIL]
        self._password: str = entry.data[CONF_PASSWORD]
        self._region: str = entry.data.get(CONF_REGION, "US")
        # Stable per-account device fingerprint (matches official app's md5(android_id))
        self._device_sn = _md5_hex(f"ha-thermomaven-{self._email}")
        self.api = ThermoMavenApiClient(
            self._session, region=self._region, device_sn=self._device_sn
        )

        # State cache keyed by deviceId.
        # Value shape:
        #   { "info":   {<top-level device attrs from user:device:list>},
        #     "status": {<latest cmdData from <model>:status:report>},
        #     "last_seen": <epoch seconds>,
        #     "topic": "device/<model>/<deviceId>/pub" }
        self._devices: dict[str, dict[str, Any]] = {}
        self._listeners: dict[str, set[Callable[[], None]]] = {}
        self._global_listeners: set[Callable[[], None]] = set()

        self._mqtt: mqtt.Client | None = None
        self._mqtt_thread: threading.Thread | None = None
        self._mqtt_topics: list[str] = []
        self._tmp_dir: tempfile.TemporaryDirectory | None = None
        self._client_id: str = ""
        self._stopping = False

    # ---- public listener API used by entity platforms ----
    @callback
    def add_listener(self, device_id: str | None, cb: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to state updates. Pass device_id=None for any-device updates."""
        if device_id is None:
            self._global_listeners.add(cb)

            def _remove_g():
                self._global_listeners.discard(cb)

            return _remove_g
        bucket = self._listeners.setdefault(device_id, set())
        bucket.add(cb)

        def _remove():
            bucket.discard(cb)

        return _remove

    # ---- public state accessors ----
    @property
    def devices(self) -> dict[str, dict[str, Any]]:
        return self._devices

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        return self._devices.get(device_id)

    # ---- lifecycle ----
    async def async_start(self) -> None:
        """Login, apply for cert, then start the MQTT thread."""
        # Re-use a saved token if we have one — otherwise login.
        if (saved_token := self.entry.data.get("token")):
            self.api.set_token(saved_token, self.entry.data.get("user_id"))
        try:
            cert_data = await self.api.mqtt_cert_apply()
        except ThermoMavenAuthError:
            cert_data = None
        if not cert_data:
            await self.api.login(self._email, self._password)
            # Persist the new token + user_id back to the config entry.
            new_data = dict(self.entry.data)
            new_data["token"] = self.api.token
            new_data["user_id"] = self.api.user_id
            self.hass.config_entries.async_update_entry(self.entry, data=new_data)
            cert_data = await self.api.mqtt_cert_apply()

        self._client_id = cert_data["clientId"]
        initial_topics = list(cert_data.get("subTopics") or [])
        self._mqtt_topics = list(initial_topics)

        # Download and split the .p12 in a thread (HTTP + crypto are blocking).
        cert_path, key_path, ca_path = await self.hass.async_add_executor_job(
            self._download_and_extract_p12, cert_data
        )

        # Build the MQTT client and start the loop in a worker thread.
        self._mqtt = mqtt.Client(
            client_id=self._client_id,
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.set_alpn_protocols(["x-amzn-mqtt-ca"])
        ctx.load_verify_locations(cafile=ca_path)
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        self._mqtt.tls_set_context(ctx)
        self._mqtt.reconnect_delay_set(min_delay=5, max_delay=120)
        self._mqtt.on_connect = self._on_connect
        self._mqtt.on_disconnect = self._on_disconnect
        self._mqtt.on_message = self._on_message

        # Connect synchronously — paho will internally call loop_forever in the thread.
        await self.hass.async_add_executor_job(
            self._mqtt.connect, MQTT_ENDPOINT, MQTT_PORT, MQTT_KEEPALIVE
        )
        self._mqtt_thread = threading.Thread(
            target=self._mqtt.loop_forever,
            name=f"thermomaven-{self._client_id[-12:]}",
            daemon=True,
        )
        self._mqtt_thread.start()
        _LOGGER.info("ThermoMaven MQTT loop started (clientId=%s)", self._client_id)

    async def async_stop(self) -> None:
        self._stopping = True
        if self._mqtt is not None:
            try:
                self._mqtt.disconnect()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._mqtt.loop_stop()
            except Exception:  # noqa: BLE001
                pass
        if self._tmp_dir is not None:
            try:
                self._tmp_dir.cleanup()
            except Exception:  # noqa: BLE001
                pass
            self._tmp_dir = None

    # ---- p12 handling (executor) ----
    def _download_and_extract_p12(
        self, cert_data: dict[str, Any]
    ) -> tuple[str, str, str]:
        import requests  # locally — avoid pulling at module load time

        url = cert_data["p12Url"]
        expected_md5 = cert_data["p12Md5"]
        password = cert_data["p12Password"].encode("utf-8")
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.content
        actual = hashlib.md5(data).hexdigest()
        if actual.lower() != expected_md5.lower():
            raise RuntimeError(
                f"p12 MD5 mismatch: got {actual}, expected {expected_md5}"
            )
        key, cert, additional = pkcs12.load_key_and_certificates(data, password)
        if cert is None or key is None:
            raise RuntimeError("p12 missing client certificate or private key")

        self._tmp_dir = tempfile.TemporaryDirectory(prefix="thermomaven_")
        d = Path(self._tmp_dir.name)
        cert_path = d / "client.crt.pem"
        key_path = d / "client.key.pem"
        ca_path = d / "ca.pem"

        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=NoEncryption(),
            )
        )
        if additional:
            ca_pem = b"".join(
                c.public_bytes(serialization.Encoding.PEM) for c in additional
            )
            ca_path.write_bytes(ca_pem)
        else:
            ca_path.write_bytes(AMAZON_ROOT_CA1.encode("utf-8"))

        return str(cert_path), str(key_path), str(ca_path)

    # ---- paho callbacks (run in MQTT thread) ----
    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            _LOGGER.error("ThermoMaven MQTT connect failed rc=%s", rc)
            return
        for t in self._mqtt_topics:
            client.subscribe(t, qos=1)
        _LOGGER.info("ThermoMaven MQTT connected; subscribed %s", self._mqtt_topics)

    def _on_disconnect(self, client, userdata, rc):
        if not self._stopping:
            _LOGGER.warning("ThermoMaven MQTT disconnected rc=%s; auto-reconnecting", rc)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _LOGGER.debug("non-JSON MQTT message on %s, skipping", msg.topic)
            return
        # Hop back to the HA event loop for state updates.
        self.hass.loop.call_soon_threadsafe(self._handle_payload, msg.topic, payload)

    # ---- HA-thread handler ----
    @callback
    def _handle_payload(self, topic: str, payload: dict[str, Any]) -> None:
        cmd_type = payload.get(F_CMD_TYPE, "")

        if cmd_type == CMD_USER_DEVICE_LIST:
            self._handle_device_list(payload)
            return

        if cmd_type == CMD_DEVICE_CMD_RECEIPT:
            # Surface every command receipt as an HA event so automations can
            # react. Keep the cache but don't update probe state — the next
            # status:report will carry the new state if the command worked.
            self.hass.bus.async_fire(EVENT_COMMAND_RECEIPT, payload)
            return

        if cmd_type.endswith(CMD_TYPE_STATUS_SUFFIX):
            self._handle_status_report(topic, payload)
            return

        _LOGGER.debug("unhandled cmdType=%s topic=%s", cmd_type, topic)

    def _handle_device_list(self, payload: dict[str, Any]) -> None:
        cmd_data = payload.get(F_CMD_DATA) or {}
        devices = cmd_data.get(F_DEVICES) or []
        for d in devices:
            device_id = d.get(F_DEVICE_ID)
            if not device_id:
                continue
            entry = self._devices.setdefault(device_id, {})
            entry["info"] = {
                F_DEVICE_ID: device_id,
                F_DEVICE_SN: d.get(F_DEVICE_SN),
                F_DEVICE_NAME: d.get(F_DEVICE_NAME),
                F_DEVICE_MODEL: d.get(F_DEVICE_MODEL),
                F_FIRMWARE_VERSION_CODE: d.get(F_FIRMWARE_VERSION_CODE),
                "deviceLogo": d.get("deviceLogo"),
            }
            entry["topic"] = (d.get(F_SUB_TOPICS) or [None])[0]

            # Initial status from the snapshot's lastStatusCmd.
            last = d.get(F_LAST_STATUS_CMD) or {}
            last_cmd_data = last.get(F_CMD_DATA)
            if last_cmd_data:
                entry["status"] = last_cmd_data
                entry["last_seen"] = last.get("serverTimeSecond") or last.get("serverTime")

            # Auto-subscribe to any per-device topic we haven't already.
            for t in d.get(F_SUB_TOPICS) or []:
                if t and t not in self._mqtt_topics:
                    self._mqtt_topics.append(t)
                    if self._mqtt is not None:
                        self._mqtt.subscribe(t, qos=1)
                        _LOGGER.debug("auto-subscribed %s", t)

        self._notify_global()
        for device_id in self._devices:
            self._notify(device_id)

    def _handle_status_report(self, topic: str, payload: dict[str, Any]) -> None:
        device_id = payload.get(F_DEVICE_ID)
        if not device_id:
            # Try parsing from topic: device/<model>/<deviceId>/pub
            parts = topic.split("/")
            if len(parts) >= 3:
                device_id = parts[2]
        if not device_id:
            return
        entry = self._devices.setdefault(device_id, {"info": {}, "topic": topic})
        cmd_data = payload.get(F_CMD_DATA) or {}
        entry["status"] = cmd_data
        entry["last_seen"] = payload.get("serverTimeSecond") or payload.get("deviceTimeSecond")
        # Keep info populated even when only delta arrives.
        info = entry.setdefault("info", {})
        info.setdefault(F_DEVICE_ID, device_id)
        info.setdefault(F_DEVICE_MODEL, payload.get(F_DEVICE_MODEL))
        self._notify(device_id)
        self._notify_global()

    @callback
    def _notify(self, device_id: str) -> None:
        for cb in list(self._listeners.get(device_id, ())):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("listener for %s raised", device_id)

    @callback
    def _notify_global(self) -> None:
        for cb in list(self._global_listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("global listener raised")

    # ============================================================
    # Command helpers (write path)
    # ============================================================
    # All write commands go through `app/command/send`. The REST 200 only
    # confirms the server queued the command; actual device execution lands
    # later as a `device:cmd:receipt` MQTT message — already surfaced as the
    # `thermomaven_command_receipt` HA event for automation use.
    #
    # The helpers below encapsulate the per-cmdType cmdData shapes verified
    # live on 2026-05-02 against a real WT11. Per-model cmdType strings are
    # built as f"{deviceModel}:<verb>".

    def _cmd_type(self, device_id: str, suffix: str) -> str:
        info = (self.get_device(device_id) or {}).get("info") or {}
        model = info.get(F_DEVICE_MODEL) or "WT11"
        return f"{model}{suffix}"

    def _probe(self, device_id: str, probe_color: str) -> dict[str, Any] | None:
        status = (self.get_device(device_id) or {}).get("status") or {}
        for p in status.get(F_PROBES) or []:
            if p.get(F_PROBE_COLOR) == probe_color:
                return p
        return None

    async def async_set_volume(self, device_id: str, volume: str) -> str:
        """Change the alarm volume on the base. `volume` ∈ {high, medium, quiet}."""
        cmd_type = self._cmd_type(device_id, CMD_TYPE_SETTING_MODIFY_SUFFIX)
        return await self.api.send_command(device_id, cmd_type, {"volume": volume})

    async def async_set_target_temp(
        self, device_id: str, probe_color: str, temp_f: float
    ) -> str:
        """Mutate the target temperature on the running cook (preserves cookUuid).

        If there's no running cook we still send action=START with a fresh uuid,
        which the device interprets as "begin a new manual cook with this target".
        """
        probe = self._probe(device_id, probe_color)
        cooking_mode = (probe or {}).get(F_COOKING_MODE) or "smart"
        cook_uuid    = (probe or {}).get(F_COOK_UUID)
        start_client = (probe or {}).get(F_START_CLIENT) or START_CLIENT_HA
        is_mutate = bool(cook_uuid)

        if not cook_uuid:
            # Generate a fresh cook session (start cook from scratch).
            import uuid as _uuid
            cook_uuid = _uuid.uuid4().hex

        cmd_data: dict[str, Any] = {
            "probeColor":    probe_color,
            "cookingAction": ACTION_START,
            "cookingMode":   cooking_mode,
            "cookUuid":      cook_uuid,
            "startClient":   start_client,
            "setParams":     [{"setTemperature": int(round(temp_f * TEMP_SCALE))}],
        }
        # When mutating a cook started ON the device, the JS app sets cookingData
        # to null — we replicate exactly to stay schema-compatible.
        if is_mutate and start_client == "device":
            cmd_data["cookingData"] = None
        else:
            cmd_data["cookingData"] = {
                "dataType":  "manual",
                "dataId":    "",
                "dataName":  "Home Assistant cook",
                "dataImgUrl": "",
            }
        cmd_type = self._cmd_type(device_id, CMD_TYPE_COOKING_ACTION_SUFFIX)
        return await self.api.send_command(device_id, cmd_type, cmd_data)

    async def async_finish_cook(self, device_id: str, probe_color: str) -> str:
        """Send Finish (action=5) for the running cook. NOTE: receipt may say
        success while the device silently no-ops if the probe is still inserted/
        docked — automation should also watch for cookingState transition.
        """
        probe = self._probe(device_id, probe_color) or {}
        cook_uuid = probe.get(F_COOK_UUID)
        if not cook_uuid:
            raise RuntimeError("no active cook to finish")
        cmd_data = {
            "probeColor":    probe_color,
            "cookingAction": ACTION_FINISH,
            "cookUuid":      cook_uuid,
        }
        cmd_type = self._cmd_type(device_id, CMD_TYPE_COOKING_ACTION_SUFFIX)
        return await self.api.send_command(device_id, cmd_type, cmd_data)

    async def async_stop_cook(self, device_id: str, probe_color: str) -> str:
        """Send Stop (action=2). Same caveat as Finish — only takes real effect
        once the probe is removed."""
        probe = self._probe(device_id, probe_color) or {}
        cook_uuid = probe.get(F_COOK_UUID)
        if not cook_uuid:
            raise RuntimeError("no active cook to stop")
        cmd_data = {
            "probeColor":    probe_color,
            "cookingAction": ACTION_STOP,
            "cookUuid":      cook_uuid,
        }
        cmd_type = self._cmd_type(device_id, CMD_TYPE_COOKING_ACTION_SUFFIX)
        return await self.api.send_command(device_id, cmd_type, cmd_data)
