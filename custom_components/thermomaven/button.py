"""
/* ============================================================
 * button.py — ThermoMaven write-side action buttons
 * ============================================================
 *
 * Per-probe Finish / Stop. Both fire cooking:action with the
 * running cookUuid. Note: the device may silently no-op these
 * while the probe is still inserted/docked — receipt may report
 * `success` without state actually changing. UX-wise the buttons
 * are best understood as "tell the device I'm done"; the user
 * still needs to remove the probe from food for the cook to
 * actually end.
 * ============================================================
 */
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, F_COOK_UUID, F_PROBE_COLOR, F_PROBES
from .coordinator import ThermoMavenCoordinator
from .sensor import _ProbeEntity  # noqa: PLC2701

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
                new.append(_FinishCookButton(coordinator, device_id, color))
                new.append(_StopCookButton(coordinator, device_id, color))
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.add_listener(None, _discover))


class _CookActionButton(_ProbeEntity, ButtonEntity):
    """Common base — buttons should only be available when there's an active cook."""

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        # Only meaningful while a cook is running.
        return bool(self._val(F_COOK_UUID))


class _FinishCookButton(_CookActionButton):
    def __init__(self, coordinator, device_id, color):
        super().__init__(coordinator, device_id, color, "finish_cook")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_finish_cook(self._device_id, self._color)
        except RuntimeError as err:
            _LOGGER.warning("finish_cook ignored: %s", err)


class _StopCookButton(_CookActionButton):
    def __init__(self, coordinator, device_id, color):
        super().__init__(coordinator, device_id, color, "stop_cook")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_stop_cook(self._device_id, self._color)
        except RuntimeError as err:
            _LOGGER.warning("stop_cook ignored: %s", err)
