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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gaposa from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Get the connection parameters from the config entry
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    
    # Create API session
    session = async_get_clientsession(hass)
    gaposa = Gaposa(API_KEY, websession=session)

    try:
        # Connect to the Gaposa API
        await gaposa.login(email, password)
        
        # Vérifier que nous avons au moins un client
        if not gaposa.clients:
            _LOGGER.error("No clients found for this account")
            return False
            
    except GaposaAuthException as ex:
        _LOGGER.error("Authentication failed: %s", ex)
        return False
    except Exception as ex:
        _LOGGER.error("Failed to connect to Gaposa API: %s", ex)
        raise ConfigEntryNotReady from ex

    # Create coordinator for data updates
    coordinator = GaposaCoordinator(hass, gaposa)
    
    # Fetch initial data
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as ex:
        await gaposa.close()
        raise ex

    # Store the instances in hass data for retrieval by the platform entities
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "gaposa": gaposa
    }

    # Set up all platforms for this device/entry
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Create an entry update listener to handle changes to the entry
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload entities for this entry/device
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    # If unloading was successful, remove the entry from hass.data
    if unload_ok:
        gaposa = hass.data[DOMAIN][entry.entry_id]["gaposa"]
        await gaposa.close()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
