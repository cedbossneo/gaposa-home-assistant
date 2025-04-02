"""Support for Gaposa covers."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import GaposaHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Gaposa covers."""
    hub: GaposaHub = hass.data[DOMAIN][entry.entry_id]
    
    # Forcer une mise à jour des données pour s'assurer d'avoir les moteurs
    await hub.update_data()
    
    # Création des entités pour chaque moteur
    entities = []
    _LOGGER.debug("Nombre de moteurs disponibles: %d", len(hub.motors))
    
    for motor in hub.motors:
        _LOGGER.debug("Ajout du moteur %s (ID: %s)", motor.name, motor.id)
        entities.append(GaposaCover(hub, motor))
    
    if entities:
        _LOGGER.info("Ajout de %d entités cover", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.warning("Aucune entité cover à ajouter")


class GaposaCover(CoverEntity):
    """Representation of a Gaposa cover."""

    def __init__(self, hub: GaposaHub, motor) -> None:
        """Initialize the cover."""
        self._hub = hub
        self._motor = motor
        self._attr_name = motor.name
        self._attr_unique_id = f"{motor.id}"
        self._attr_device_class = CoverDeviceClass.SHADE
        self._attr_supported_features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | 
            CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION
        )
        
        # Mise à jour initiale
        self._update_attrs()
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attrs()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self._hub.register_callback(self._handle_coordinator_update)
    
    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        self._hub.remove_callback(self._handle_coordinator_update)
    
    def _update_attrs(self) -> None:
        """Update the attributes based on motor status."""
        if hasattr(self._motor, 'percent'):
            # Position inversée: 0 = fermé, 100 = ouvert dans HA
            self._attr_current_cover_position = 100 - self._motor.percent
            self._attr_is_closed = self._motor.percent >= 95
        else:
            self._attr_current_cover_position = None
            self._attr_is_closed = None
    
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._motor.up()
        self._update_attrs()
    
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._motor.down()
        self._update_attrs()
    
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self._motor.stop()
        self._update_attrs()
    
    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover position."""
        position = kwargs.get(ATTR_POSITION, 50)
        # Conversion de position: 0 = fermé, 100 = ouvert dans HA
        device_position = 100 - position
        # Utilisez la position directement puisque set_position n'existe pas dans l'API
        if device_position == 0:
            await self._motor.up()
        elif device_position == 100:
            await self._motor.down()
        else:
            # Si vous avez besoin d'une méthode pour définir une position spécifique
            # vous devrez l'implémenter
            await self._motor.preset()
        self._update_attrs()
    
    async def async_update(self) -> None:
        """Update the cover status."""
        await self._hub.update_data()
    
    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._motor.id)},
            name=self._motor.name,
            manufacturer="Gaposa",
            model="Motorized Shade",
        )
