"""
/* ============================================================
 * number.py — ThermoMaven write-side number entities
 * ============================================================
 *
 * Per-probe target-temperature slider. Reads the current target
 * from the probe's setParams[0].setTemperature; on user write,
 * fires a cooking:action(START) command that mutates the running
 * cook (preserves cookUuid + cookingMode + startClient) so the
 * device just picks up the new target without restarting the cook.
 *
 * Range: 80–500 °F, 1 °F steps. Server itself doesn't enforce
 * bounds — these are sane HA-UI defaults.
 * ============================================================
 */
"""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    F_PROBE_COLOR,
    F_PROBES,
    F_SET_PARAMS,
    F_SET_TEMPERATURE,
    TARGET_TEMP_MAX,
    TARGET_TEMP_MIN,
    TARGET_TEMP_STEP,
    TEMP_SCALE,
)
from .coordinator import ThermoMavenCoordinator
from .sensor import _ProbeEntity, _probe_label  # noqa: PLC2701

_LOGGER = logging.getLogger(__name__)


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
            for probe in (dev.get("status") or {}).get(F_PROBES) or []:
                color = probe.get(F_PROBE_COLOR)
                if not color:
                    continue
                key = f"{device_id}:{color}"
                if key in known_keys:
                    continue
                known_keys.add(key)
                new.append(_ProbeTargetTempNumber(coordinator, device_id, color))
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.add_listener(None, _discover))


class _ProbeTargetTempNumber(_ProbeEntity, NumberEntity):
    _attr_native_min_value = TARGET_TEMP_MIN
    _attr_native_max_value = TARGET_TEMP_MAX
    _attr_native_step = TARGET_TEMP_STEP
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: ThermoMavenCoordinator, device_id: str, color: str):
        super().__init__(coordinator, device_id, color, "target_temp_set")

    @property
    def native_value(self):
        params = self._val(F_SET_PARAMS) or []
        if params and isinstance(params, list) and isinstance(params[0], dict):
            raw = params[0].get(F_SET_TEMPERATURE)
            return raw / TEMP_SCALE if isinstance(raw, (int, float)) else None
        return None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_target_temp(
            self._device_id, self._color, float(value)
        )
