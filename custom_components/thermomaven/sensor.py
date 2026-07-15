"""
/* ============================================================
 * sensor.py — ThermoMaven entities
 * ============================================================
 *
 * One HA "device" per ThermoMaven base station. Sensors fall in
 * two groups:
 *
 *   Base-station sensors:
 *     - WiFi RSSI (dBm)
 *     - Battery (%)
 *     - Battery status (string: normal/low)
 *     - Connection status (string: ble/wifi/both)
 *     - Volume (string)
 *     - Online status (string: online/offline)
 *     - Last seen (timestamp)
 *
 *   Per-probe sensors (one set per probe in the device's probes[] array):
 *     - Current temperature (°F or °C, configurable on device)
 *     - Ambient temperature
 *     - Target temperature (from setParams[0])
 *     - Battery (%)
 *     - Cooking state (string: idle/cooking/done/...)
 *     - Cooking mode (string: smart/manual)
 *     - Time elapsed (s)
 *     - Time remaining (s)
 *     - Total cook time (s)
 *     - Cook UUID (changes per cook session)
 *     - Probe label (user-set "probeNotes")
 *
 * Probes are discovered on first status:report and added dynamically.
 * Devices are discovered on first user:device:list snapshot.
 * ============================================================
 */
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_MODEL_NAMES,
    DOMAIN,
    F_AREA_TEMPERATURE,
    F_BATTERY_STATUS,
    F_BATTERY_VALUE,
    F_CONNECT_STATUS,
    F_COOKING_MODE,
    F_COOKING_STATE,
    F_COOK_UUID,
    F_CUR_AMBIENT_TEMPERATURE,
    F_CUR_COOK_SEC,
    F_CUR_REMAINED_SEC,
    F_CUR_TEMPERATURE,
    F_DEVICE_ID,
    F_DEVICE_MODEL,
    F_DEVICE_NAME,
    F_DEVICE_SN,
    F_FIRMWARE_VERSION_CODE,
    F_GLOBAL_STATUS,
    F_PROBE_COLOR,
    F_PROBE_NOTES,
    F_PROBES,
    F_SET_PARAMS,
    F_SET_TEMPERATURE,
    F_TOTAL_COOK_SEC,
    F_VOLUME,
    F_WIFI_RSSI,
    MANUFACTURER,
    TEMP_SCALE,
)
from .coordinator import ThermoMavenCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ThermoMavenCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_keys: set[str] = set()  # "<deviceId>" + "<deviceId>:<probeColor>"

    @callback
    def _discover() -> None:
        new_entities: list[SensorEntity] = []
        for device_id, dev in coordinator.devices.items():
            if device_id not in known_keys:
                known_keys.add(device_id)
                new_entities.extend(_build_base_sensors(coordinator, device_id))
            status = dev.get("status") or {}
            for probe in status.get(F_PROBES) or []:
                color = probe.get(F_PROBE_COLOR)
                if not color:
                    continue
                key = f"{device_id}:{color}"
                if key in known_keys:
                    continue
                known_keys.add(key)
                new_entities.extend(_build_probe_sensors(coordinator, device_id, color))
        if new_entities:
            async_add_entities(new_entities)

    # Run once with whatever the coordinator already has, then on every update.
    _discover()
    entry.async_on_unload(coordinator.add_listener(None, _discover))


# ============================================================
# Base entity
# ============================================================
class _ThermoMavenEntity(Entity):
    """Base entity that wires into the coordinator's per-device listener.

    Intentionally extends only `Entity` — the platform-specific entity type
    (SensorEntity / BinarySensorEntity / SelectEntity / NumberEntity /
    ButtonEntity) is mixed in per-subclass. Making this a SensorEntity
    would pollute the other platforms with sensor-specific behavior — most
    visibly, HA's SensorEntity guard rejects `EntityCategory.CONFIG`, so a
    select/number that tried to be a CONFIG entity would fail to register.
    See fix for issue #1.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: ThermoMavenCoordinator, device_id: str) -> None:
        self.coordinator = coordinator
        self._device_id = device_id

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.add_listener(self._device_id, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        dev = self.coordinator.get_device(self._device_id)
        if not dev:
            return False
        status = dev.get("status") or {}
        return status.get(F_GLOBAL_STATUS, "online") != "offline"

    @property
    def device_info(self) -> DeviceInfo:
        dev = self.coordinator.get_device(self._device_id) or {}
        info = dev.get("info") or {}
        model = info.get(F_DEVICE_MODEL)
        return DeviceInfo(
            identifiers={(DOMAIN, info.get(F_DEVICE_SN) or self._device_id)},
            manufacturer=MANUFACTURER,
            model=DEVICE_MODEL_NAMES.get(model, model),
            name=info.get(F_DEVICE_NAME) or "ThermoMaven",
            sw_version=str(info.get(F_FIRMWARE_VERSION_CODE) or ""),
        )

    def _status(self) -> dict[str, Any]:
        dev = self.coordinator.get_device(self._device_id) or {}
        return dev.get("status") or {}

    def _probe(self, color: str) -> dict[str, Any] | None:
        for p in self._status().get(F_PROBES) or []:
            if p.get(F_PROBE_COLOR) == color:
                return p
        return None


# ============================================================
# Base-station sensors
# ============================================================
def _build_base_sensors(
    coordinator: ThermoMavenCoordinator, device_id: str
) -> list[SensorEntity]:
    return [
        _BaseBatterySensor(coordinator, device_id),
        _BaseBatteryStatusSensor(coordinator, device_id),
        _BaseRssiSensor(coordinator, device_id),
        _BaseConnectStatusSensor(coordinator, device_id),
        _BaseVolumeSensor(coordinator, device_id),
        _BaseOnlineStatusSensor(coordinator, device_id),
    ]


class _BaseBatterySensor(_ThermoMavenEntity, SensorEntity):
    _attr_translation_key = "base_battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_base_battery"

    @property
    def native_value(self):
        return self._status().get(F_BATTERY_VALUE)


class _BaseBatteryStatusSensor(_ThermoMavenEntity, SensorEntity):
    _attr_translation_key = "base_battery_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_base_battery_status"

    @property
    def native_value(self):
        return self._status().get(F_BATTERY_STATUS)


class _BaseRssiSensor(_ThermoMavenEntity, SensorEntity):
    _attr_translation_key = "base_wifi_rssi"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_base_wifi_rssi"

    @property
    def native_value(self):
        return self._status().get(F_WIFI_RSSI)


class _BaseConnectStatusSensor(_ThermoMavenEntity, SensorEntity):
    _attr_translation_key = "base_connect_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_base_connect_status"

    @property
    def native_value(self):
        return self._status().get(F_CONNECT_STATUS)


class _BaseVolumeSensor(_ThermoMavenEntity, SensorEntity):
    _attr_translation_key = "base_volume"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_base_volume"

    @property
    def native_value(self):
        return self._status().get(F_VOLUME)


class _BaseOnlineStatusSensor(_ThermoMavenEntity, SensorEntity):
    _attr_translation_key = "base_online_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_base_online_status"

    @property
    def native_value(self):
        return self._status().get(F_GLOBAL_STATUS)


# ============================================================
# Probe sensors
# ============================================================
def _build_probe_sensors(
    coordinator: ThermoMavenCoordinator, device_id: str, color: str
) -> list[SensorEntity]:
    sensors: list[SensorEntity] = [
        # `current` is the device-chosen "effective" meat reading — equals one of T1..T5.
        # The full multi-zone array is exposed both as five individual T1..T5 sensors
        # below AND as the `area_temperature` extra-state-attribute on this entity, so
        # users can graph the array on a single card or alert off any zone.
        _ProbeTempSensor(coordinator, device_id, color, "current"),
        _ProbeTempSensor(coordinator, device_id, color, "ambient"),
        _ProbeTempSensor(coordinator, device_id, color, "target"),
        _ProbeBatterySensor(coordinator, device_id, color),
        _ProbeStateSensor(coordinator, device_id, color, F_COOKING_STATE, "cooking_state"),
        _ProbeStateSensor(coordinator, device_id, color, F_COOKING_MODE, "cooking_mode"),
        _ProbeStateSensor(coordinator, device_id, color, F_COOK_UUID, "cook_uuid"),
        _ProbeStateSensor(coordinator, device_id, color, F_PROBE_NOTES, "probe_notes"),
        _ProbeTimeSensor(coordinator, device_id, color, "elapsed"),
        _ProbeTimeSensor(coordinator, device_id, color, "remaining"),
        _ProbeTimeSensor(coordinator, device_id, color, "total"),
    ]
    # Five thermistors along the probe shaft. Index 0 = T1 (tip), index 4 = T5 (rear).
    # These let users build their own "center of meat" / "coldest zone" / median templates
    # which is the whole point of a multi-zone probe vs single-tip thermometers.
    for idx in range(5):
        sensors.append(_ProbeZoneTempSensor(coordinator, device_id, color, idx))
    return sensors


class _ProbeEntity(_ThermoMavenEntity):
    """Common to all probe sensors — adds color suffix to unique_id and translation context."""

    def __init__(self, coordinator, device_id, color, slug):
        super().__init__(coordinator, device_id)
        self._color = color
        self._attr_translation_key = f"probe_{slug}"
        self._attr_translation_placeholders = {"probe": _probe_label(color)}
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{color}_{slug}"

    def _val(self, key: str):
        p = self._probe(self._color)
        if not p:
            return None
        return p.get(key)


class _ProbeTempSensor(_ProbeEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    # The device emits whatever unit it's configured for (F or C). The asset
    # JSON we fetched at login could tell us, but we'd have to wire it through.
    # Default to F since the user is in the US — override via the device app.
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_suggested_display_precision = 1

    _FIELDS = {
        "current": F_CUR_TEMPERATURE,
        "ambient": F_CUR_AMBIENT_TEMPERATURE,
        # target is not at top of the probe dict — see native_value override
    }

    def __init__(self, coordinator, device_id, color, kind):
        super().__init__(coordinator, device_id, color, f"temp_{kind}")
        self._kind = kind

    @property
    def native_value(self):
        if self._kind == "target":
            params = self._val(F_SET_PARAMS) or []
            if params and isinstance(params, list):
                raw = params[0].get(F_SET_TEMPERATURE) if isinstance(params[0], dict) else None
                return raw / TEMP_SCALE if isinstance(raw, (int, float)) else None
            return None
        raw = self._val(self._FIELDS[self._kind])
        return raw / TEMP_SCALE if isinstance(raw, (int, float)) else None

    @property
    def extra_state_attributes(self):
        # Expose the multi-zone array + a "which zones are actually in the meat"
        # heuristic on the "current" entity. Lets users build smart median/coldest
        # templates that work for both 18h briskets (probe fully inserted, all 5
        # in meat) and quick steaks (only T1..T3 in meat, T4-T5 reading air).
        if self._kind != "current":
            return None
        zones = self._val(F_AREA_TEMPERATURE)
        ambient_raw = self._val(F_CUR_AMBIENT_TEMPERATURE)
        if not isinstance(zones, list) or not zones:
            return None
        scaled = [z / TEMP_SCALE if isinstance(z, (int, float)) else None for z in zones]
        ambient = ambient_raw / TEMP_SCALE if isinstance(ambient_raw, (int, float)) else None

        # Heuristic: a zone is "in the meat" when it reads sufficiently different
        # from ambient (meat is either much colder during the cook or much hotter
        # during a sear). Walk back from T1 — only count CONTIGUOUS zones starting
        # at the tip, since the inserted portion is always tip-first.
        # Threshold: 5°F. Tighter than that triggers false negatives near ambient
        # crossings (meat reaching grill temp during long cooks).
        in_meat: list[float] = []
        if ambient is not None:
            for z in scaled:
                if z is None or abs(z - ambient) < 5.0:
                    break
                in_meat.append(z)

        attrs: dict[str, Any] = {
            "area_temperature": scaled,
            "zone_min": min((z for z in scaled if z is not None), default=None),
            "zone_max": max((z for z in scaled if z is not None), default=None),
            "ambient": ambient,
            "zones_in_meat": len(in_meat),
        }
        if in_meat:
            sorted_in = sorted(in_meat)
            attrs["meat_coldest"] = sorted_in[0]              # food-safety relevant
            attrs["meat_hottest"] = sorted_in[-1]
            attrs["meat_median"]  = sorted_in[len(sorted_in) // 2]
        return attrs


class _ProbeZoneTempSensor(_ProbeEntity, SensorEntity):
    """One of T1..T5 — the five thermistors along the probe shaft.

    Index 0 = T1 (tip of probe, deepest insertion = coldest if probe is buried
    in the meat). Indices 1..4 = T2..T5 walking toward the rear/handle.

    Letting users graph these individually unlocks the multi-zone use case the
    WT11/P1 was designed for: the median or center-zone reading is more reliable
    than the device's algorithm-chosen `curTemperature` when the probe insertion
    depth changes mid-cook (e.g. probe slides out or meat shrinks).
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, device_id, color, zone_index: int):
        # zone_index is 0..4; user-facing label is T1..T5 (1-indexed).
        super().__init__(coordinator, device_id, color, f"temp_t{zone_index + 1}")
        self._zone = zone_index

    @property
    def native_value(self):
        zones = self._val(F_AREA_TEMPERATURE)
        if not isinstance(zones, list) or len(zones) <= self._zone:
            return None
        raw = zones[self._zone]
        return raw / TEMP_SCALE if isinstance(raw, (int, float)) else None


class _ProbeBatterySensor(_ProbeEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id, color):
        super().__init__(coordinator, device_id, color, "battery")

    @property
    def native_value(self):
        return self._val(F_BATTERY_VALUE)


class _ProbeStateSensor(_ProbeEntity, SensorEntity):
    """Generic string passthrough — cookingState, cookingMode, cookUuid, probeNotes."""

    def __init__(self, coordinator, device_id, color, field, slug):
        super().__init__(coordinator, device_id, color, slug)
        self._field = field

    @property
    def native_value(self):
        return self._val(self._field)


class _ProbeTimeSensor(_ProbeEntity, SensorEntity):
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT

    _FIELDS = {
        "elapsed":   F_CUR_COOK_SEC,
        "remaining": F_CUR_REMAINED_SEC,
        "total":     F_TOTAL_COOK_SEC,
    }

    def __init__(self, coordinator, device_id, color, kind):
        super().__init__(coordinator, device_id, color, f"time_{kind}")
        self._kind = kind

    @property
    def native_value(self):
        return self._val(self._FIELDS[self._kind])


def _probe_label(color: str) -> str:
    """Convert "probe1" → "Probe 1" for translation placeholder use."""
    if color and color.startswith("probe") and color[5:].isdigit():
        return f"Probe {color[5:]}"
    return color or "Probe"
