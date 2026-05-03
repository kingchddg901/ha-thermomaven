"""
/* ============================================================
 * config_flow.py — ThermoMaven setup flow
 * ============================================================
 *
 * Single step: email + password + region → validates by performing
 * an actual login against api.iot.thermomaven.com. On success the
 * token + userId are stored in the config entry so the coordinator
 * can avoid a re-login on every restart.
 * ============================================================
 */
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    ThermoMavenApiClient,
    ThermoMavenApiError,
    ThermoMavenAuthError,
)
from .const import (
    CONF_REGION,
    CONF_TOKEN,
    CONF_USER_ID,
    DOMAIN,
    REGION_DEFAULT,
    REGION_EU,
    REGION_US,
)

_LOGGER = logging.getLogger(__name__)


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_REGION, default=REGION_DEFAULT): vol.In([REGION_US, REGION_EU]),
    }
)


class ThermoMavenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Email + password setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            password = user_input[CONF_PASSWORD]
            region = user_input.get(CONF_REGION, REGION_DEFAULT)

            await self.async_set_unique_id(f"thermomaven::{email}")
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = ThermoMavenApiClient(session, region=region)

            try:
                await client.login(email, password)
            except ThermoMavenAuthError as err:
                _LOGGER.warning("ThermoMaven auth failed for %s: %s", email, err)
                errors["base"] = "invalid_auth"
            except ThermoMavenApiError as err:
                _LOGGER.warning("ThermoMaven API error during setup: %s", err)
                errors["base"] = "cannot_connect"

            if not errors:
                return self.async_create_entry(
                    title=email,
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                        CONF_REGION: region,
                        CONF_TOKEN: client.token,
                        CONF_USER_ID: client.user_id,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
