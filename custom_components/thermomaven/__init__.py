"""
/* ============================================================
 * __init__.py — ThermoMaven Integration Entry Point
 * ============================================================
 *
 * Creates one coordinator per config entry. Coordinator owns
 * the MQTT connection and dispatches realtime device state to
 * the entity platforms.
 * ============================================================
 */
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import ThermoMavenCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = ThermoMavenCoordinator(hass, entry)
    try:
        await coordinator.async_start()
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryNotReady(f"ThermoMaven setup failed: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator: ThermoMavenCoordinator | None = (
        hass.data.get(DOMAIN, {}).get(entry.entry_id)
    )
    if coordinator is not None:
        await coordinator.async_stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
