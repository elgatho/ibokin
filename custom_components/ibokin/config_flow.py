"""Config flow — konfiguracja IBOKIN przez UI HA."""

from __future__ import annotations

import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import IboAuthError, IboClient, IboConnectionError
from .const import CONF_METER_ID, DEFAULT_METER_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_METER_ID, default=DEFAULT_METER_ID): cv.string,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    session = async_get_clientsession(hass)
    client = IboClient(session, data[CONF_USERNAME], data[CONF_PASSWORD])
    await client.verify_credentials()
    return {"title": f"IBOKIN ({data[CONF_USERNAME]})"}


class IboConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except IboAuthError:
                errors["base"] = "invalid_auth"
            except IboConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Nieoczekiwany błąd konfiguracji IBO")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    f"ibokin_{user_input[CONF_USERNAME].lower()}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return IboOptionsFlow(config_entry)


class IboOptionsFlow(config_entries.OptionsFlow):
    """Opcje: id licznika (hasło zmienia się przez usunięcie i rekonfigurację)."""

    def __init__(self, config_entry) -> None:
        self.entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_METER_ID,
                    default=self.entry.data.get(CONF_METER_ID, DEFAULT_METER_ID),
                ): cv.string,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
