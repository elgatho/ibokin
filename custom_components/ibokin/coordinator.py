"""DataUpdateCoordinator — jedno odświeżenie dla obu sensorów."""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import IboAuthError, IboClient, IboConnectionError
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class IboCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        meter_id: str,
        scan_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self.client = IboClient(session, username, password)
        self.meter_id = meter_id
        super().__init__(
            hass,
            _LOGGER,
            name="ibokin",
            update_interval=scan_interval,
        )

    async def _async_update_data(self) -> dict:
        try:
            return await self.client.async_fetch_all(self.meter_id)
        except IboAuthError as err:
            raise UpdateFailed(f"Błąd uwierzytelnienia IBO: {err}") from err
        except IboConnectionError as err:
            raise UpdateFailed(f"Błąd połączenia z IBO: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Nieoczekiwany błąd IBO: {err}") from err
