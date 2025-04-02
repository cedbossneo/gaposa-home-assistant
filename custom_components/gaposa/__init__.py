"""The Gaposa integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from pygaposa.gaposa import Gaposa

from .const import DOMAIN, API_KEY

_LOGGER = logging.getLogger(__name__)

# Liste des plateformes que cette intégration prend en charge
# À ajuster selon vos besoins (cover, switch, etc.)
PLATFORMS = [Platform.COVER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gaposa from a config entry."""
    session = async_get_clientsession(hass)
    
    # Créer l'instance Gaposa
    gaposa = Gaposa(API_KEY, websession=session)
    
    # Connexion au service Gaposa
    await gaposa.login(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    
    # Stocker l'objet Gaposa dans les données de hass pour les plateformes
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = gaposa
    
    # Configuration des plateformes
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Enregistrer une fonction de nettoyage pour fermer la session lorsque l'entrée est supprimée
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Déchargement des plateformes
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # Récupération et fermeture de l'instance Gaposa
        gaposa = hass.data[DOMAIN].pop(entry.entry_id)
        await gaposa.close()
    
    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Gaposa component from yaml configuration."""
    # Cette fonction est nécessaire mais nous utilisons config_entries
    return True
