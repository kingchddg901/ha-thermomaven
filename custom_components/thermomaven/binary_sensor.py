"""
/* ============================================================
 * binary_sensor.py — ThermoMaven binary states
 * ============================================================
 *
 * One sensor per probe for the boolean status flags:
 *   - "Cooking"  — `cooking` field, on while a cook session is active
 *   - "Overheat" — `overheat` field, on when probe exceeded its target
 *
 * Plus one base-station-level "Online" / "WiFi configured" pair so
 * users can drive automations off the connection state without
 * parsing the string-valued sensor.
 * ============================================================
 */
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    F_COOKING,
    F_GLOBAL_STATUS,
    F_HAS_WIFI_CONFIG,
    F_OVERHEAT,
    F_PROBE_COLOR,
    F_PROBES,
)
from .coordinator import ThermoMavenCoordinator
from .sensor import _ProbeEntity, _ThermoMavenEntity, _probe_label  # noqa: PLC2701


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ThermoMavenCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_keys: set[str] = set()

    @callback
    def _discover() -> None:
        new = []
        for device_id, dev in coordinator.devices.items():
            if device_id not in known_keys:
                known_keys.add(device_id)
                new.append(_BaseOnlineBinary(coordinator, device_id))
                new.append(_BaseWifiConfiguredBinary(coordinator, device_id))
            for probe in (dev.get("status") or {}).get(F_PROBES) or []:
                color = probe.get(F_PROBE_COLOR)
                if not color:
                    continue
                key = f"{device_id}:{color}"
                if key in known_keys:
                    continue
                known_keys.add(key)
                new.append(_ProbeCookingBinary(coordinator, device_id, color))
                new.append(_ProbeOverheatBinary(coordinator, device_id, color))
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.add_listener(None, _discover))


class _BaseOnlineBinary(_ThermoMavenEntity, BinarySensorEntity):
    _attr_translation_key = "base_online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_base_online"

    @property
    def is_on(self):
        return (self._status().get(F_GLOBAL_STATUS) == "online")


class _BaseWifiConfiguredBinary(_ThermoMavenEntity, BinarySensorEntity):
    _attr_translation_key = "base_wifi_configured"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_base_wifi_configured"

    @property
    def is_on(self):
        return bool(self._status().get(F_HAS_WIFI_CONFIG))


class _ProbeCookingBinary(_ProbeEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator, device_id, color):
        super().__init__(coordinator, device_id, color, "cooking")

    @property
    def is_on(self):
        return bool(self._val(F_COOKING))


class _ProbeOverheatBinary(_ProbeEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, device_id, color):
        super().__init__(coordinator, device_id, color, "overheat")

    @property
    def is_on(self):
        return bool(self._val(F_OVERHEAT))
