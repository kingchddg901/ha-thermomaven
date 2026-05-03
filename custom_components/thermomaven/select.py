"""
/* ============================================================
 * select.py — ThermoMaven write-side dropdowns
 * ============================================================
 *
 * Per-base alarm volume selector. Three-position enum verified
 * live: high / medium / quiet. Backed by setting:modify cmdType.
 * ============================================================
 */
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, F_VOLUME, VOLUME_OPTIONS
from .coordinator import ThermoMavenCoordinator
from .sensor import _ThermoMavenEntity  # noqa: PLC2701


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ThermoMavenCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_devices: set[str] = set()

    @callback
    def _discover() -> None:
        new = []
        for device_id in coordinator.devices:
            if device_id not in known_devices:
                known_devices.add(device_id)
                new.append(_VolumeSelect(coordinator, device_id))
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.add_listener(None, _discover))


class _VolumeSelect(_ThermoMavenEntity, SelectEntity):
    _attr_translation_key = "base_volume_select"
    _attr_options = VOLUME_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ThermoMavenCoordinator, device_id: str):
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_volume_select"

    @property
    def current_option(self):
        v = self._status().get(F_VOLUME)
        return v if v in VOLUME_OPTIONS else None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_volume(self._device_id, option)
