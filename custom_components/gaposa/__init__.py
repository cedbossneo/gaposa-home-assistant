"""The Gaposa integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .hub import GaposaHub
from .coordinator import GaposaDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Liste des plateformes que cette intégration prend en charge
PLATFORMS = [Platform.COVER]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Gaposa component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gaposa from a config entry."""
    # Créer l'instance du hub Gaposa
    hub = GaposaHub(
        hass,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD]
    )
    
    # Connecter au service Gaposa
    if not await hub.connect():
        return False
    
    # Créer le coordinateur qui va gérer les mises à jour périodiques
    coordinator = GaposaDataUpdateCoordinator(hass, hub)
    
    # Effectuer une première mise à jour
    await coordinator.async_config_entry_first_refresh()
    
    # Stocker le hub et le coordinateur dans les données de hass
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "hub": hub,
        "coordinator": coordinator,
    }
    
    # Configuration des plateformes
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Ajouter un listener pour le déchargement de l'entrée
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok and entry.entry_id in hass.data[DOMAIN]:
        hub = hass.data[DOMAIN][entry.entry_id]["hub"]
        await hub.close()
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)
