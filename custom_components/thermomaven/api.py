"""
/* ============================================================
 * api.py — ThermoMaven REST client
 * ============================================================
 *
 * Implements the signed-header HTTP auth scheme used by
 * api.iot.thermomaven.com:
 *
 *   x-sign = md5( appKey + "|" + sortedHeaders + "|" + body )
 *
 * Headers in the join (sorted alphabetically by key):
 *   x-appId, x-appVersion, x-deviceSn, x-lang, x-nonce,
 *   x-region, x-timestamp, x-token
 *
 * Login passwords are also MD5'd client-side before sending.
 *
 * This module is HA-friendly — uses aiohttp via the shared
 * client session passed in from __init__, no blocking I/O.
 * ============================================================
 */
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any

import aiohttp

from .const import (
    API_BASE_EU,
    API_BASE_US,
    APP_ID,
    APP_KEY,
    APP_VERSION_CODE,
    ENDPOINT_COMMAND_SEND,
    ENDPOINT_DEVICE_LIST_OWNED,
    ENDPOINT_DEVICE_LIST_SHARED,
    ENDPOINT_LOGIN,
    ENDPOINT_MQTT_CERT_APPLY,
    ENDPOINT_USER_GET,
    REGION_EU,
)

_LOGGER = logging.getLogger(__name__)


def _md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


class ThermoMavenAuthError(Exception):
    """Raised when login fails or the token is no longer accepted."""


class ThermoMavenApiError(Exception):
    """Raised on any non-success API response."""


class ThermoMavenApiClient:
    """Signed REST client for the ThermoMaven cloud."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        region: str = "US",
        lang: str = "en_US",
        device_sn: str | None = None,
    ) -> None:
        self._session = session
        self._region = region
        self._lang = lang
        # The deviceSn the app sends is md5(android_id). For HA we just
        # need a stable 32-char hex value — any persistent string md5'd
        # works, and using the email keeps it deterministic per account.
        self._device_sn = device_sn or _md5_hex("ha-thermomaven-default")
        self._token: str = "none"
        self._user_id: int | None = None

    # ---- properties ----
    @property
    def base_url(self) -> str:
        return API_BASE_EU if self._region == REGION_EU else API_BASE_US

    @property
    def token(self) -> str:
        return self._token

    @property
    def user_id(self) -> int | None:
        return self._user_id

    def set_token(self, token: str, user_id: int | None = None) -> None:
        """Restore a token saved in the config entry."""
        self._token = token or "none"
        self._user_id = user_id

    # ---- signing ----
    def _build_headers(self, body_str: str) -> dict[str, str]:
        headers = {
            "x-appId": APP_ID,
            "x-appVersion": APP_VERSION_CODE,
            "x-deviceSn": self._device_sn,
            "x-lang": self._lang,
            "x-nonce": uuid.uuid4().hex,
            "x-region": self._region,
            "x-timestamp": str(int(time.time() * 1000)),
            "x-token": self._token,
        }
        joined = ";".join(f"{k}={v}" for k, v in sorted(headers.items()))
        s = APP_KEY + "|" + joined
        if body_str and body_str.strip():
            s += "|" + body_str
        s = s.replace("\n", "")
        headers["x-sign"] = _md5_hex(s)
        headers["Content-Type"] = "application/json; charset=UTF-8"
        return headers

    # ---- request ----
    async def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        headers = self._build_headers(body_str)
        url = f"{self.base_url}/{path.lstrip('/')}"

        try:
            async with self._session.post(
                url,
                data=body_str.encode("utf-8") if body_str else b"",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ThermoMavenApiError(f"network error calling {path}: {exc}") from exc

        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ThermoMavenApiError(f"non-JSON response from {path}: {text[:200]}") from exc

        code = str(obj.get("code"))
        if code != "0":
            msg = obj.get("msg", "")
            # Token expired / invalid → caller should re-auth
            if code in ("4001", "4002", "4003") or "token" in msg.lower():
                raise ThermoMavenAuthError(f"{code}: {msg}")
            raise ThermoMavenApiError(f"{path} failed: {code} {msg}")

        return obj

    # ---- API calls ----
    async def login(self, email: str, password: str) -> dict[str, Any]:
        body = {
            "accountName": email,
            "accountPassword": _md5_hex(password),
            # The deviceInfo is sent by the app as "<brand> <model> <android>".
            # Server doesn't validate the exact format, just that it's present.
            "deviceInfo": "homeassistant thermomaven",
        }
        resp = await self._post(ENDPOINT_LOGIN, body)
        data = resp.get("data") or {}
        token = data.get("token")
        if not token:
            raise ThermoMavenAuthError(f"login response missing token: {data}")
        self._token = token
        self._user_id = data.get("userId")
        return data

    async def user_get(self) -> dict[str, Any]:
        resp = await self._post(ENDPOINT_USER_GET)
        return resp.get("data") or {}

    async def shared_devices(self) -> list[dict[str, Any]]:
        resp = await self._post(ENDPOINT_DEVICE_LIST_SHARED)
        data = resp.get("data") or []
        return data if isinstance(data, list) else []

    async def owned_devices(self) -> list[dict[str, Any]]:
        resp = await self._post(ENDPOINT_DEVICE_LIST_OWNED)
        data = resp.get("data") or []
        return data if isinstance(data, list) else []

    async def mqtt_cert_apply(self) -> dict[str, Any]:
        resp = await self._post(ENDPOINT_MQTT_CERT_APPLY)
        return resp.get("data") or {}

    async def send_command(
        self,
        device_id: str,
        cmd_type: str,
        cmd_data: dict[str, Any] | None,
        *,
        device_type: str = "thermometer",
        cmd_id: str | None = None,
    ) -> str:
        """Issue a write command. Returns the cmdId so the caller can match the
        async device:cmd:receipt that arrives on MQTT.

        The REST call only confirms the server accepted the command — actual
        device execution is reported via the device:cmd:receipt MQTT message.
        For Finish/Stop the executeResult can be `success` while the device
        silently no-ops (probe still inserted), so callers wanting strong
        guarantees should also watch the next 1-2 status:report messages.
        """
        if cmd_id is None:
            cmd_id = uuid.uuid4().hex
        body = {
            "deviceId":   str(device_id),
            "deviceType": device_type,
            "cmdType":    cmd_type,
            "cmdId":      cmd_id,
            "cmdData":    cmd_data if cmd_data is not None else {},
        }
        await self._post(ENDPOINT_COMMAND_SEND, body)
        return cmd_id
