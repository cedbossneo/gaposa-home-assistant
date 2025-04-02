"""Data update coordinator for Gaposa integration."""
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .pygaposa.gaposa import GaposaAuthException
from .hub import GaposaHub
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class GaposaDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, hub: GaposaHub) -> None:
        """Initialize."""
        self.hub = hub
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    async def _async_update_data(self):
        """Update data via hub."""
        try:
            await self.hub.update_data()
            return {
                "motors": self.hub.motors,
                "is_connected": self.hub.is_connected
            }
        except GaposaAuthException as error:
            raise ConfigEntryAuthFailed(f"Authentication error: {error}") from error
        except Exception as error:
            raise UpdateFailed(f"Error communicating with API: {error}") from error
