"""The Gaposa integration."""
import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryNotReady

from pygaposa.gaposa import Gaposa, GaposaAuthException

from .const import DOMAIN, API_KEY
from .coordinator import GaposaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER]
SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gaposa from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    session = async_get_clientsession(hass)

    gaposa = Gaposa(API_KEY, websession=session)

    try:
        await gaposa.login(email, password)        
    except GaposaAuthException as ex:
        _LOGGER.error("Authentication failed: %s", ex)
        return False
    except Exception as ex:
        _LOGGER.error("Failed to connect to Gaposa API: %s", ex)
        raise ConfigEntryNotReady from ex

    # Create coordinator for data updates
    coordinator = GaposaCoordinator(hass, gaposa)
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "gaposa": gaposa
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        gaposa = hass.data[DOMAIN][entry.entry_id]["gaposa"]
        await gaposa.close()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
