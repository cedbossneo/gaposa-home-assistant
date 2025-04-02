"""Support for Gaposa covers."""
from __future__ import annotations

import logging
from typing import Any, cast

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
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from .coordinator import GaposaDataUpdateCoordinator
from .const import DOMAIN
from .hub import GaposaHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Gaposa covers."""
    data = hass.data[DOMAIN][entry.entry_id]
    hub: GaposaHub = data["hub"]
    coordinator: GaposaDataUpdateCoordinator = data["coordinator"]
    
    # Forcer une mise à jour des données pour s'assurer d'avoir les moteurs
    await coordinator.async_refresh()
    
    # Création des entités pour chaque moteur
    entities = []
    _LOGGER.debug("Nombre de moteurs disponibles: %d", len(hub.motors))
    
    for motor in hub.motors:
        _LOGGER.debug("Ajout du moteur %s (ID: %s)", motor.name, motor.id)
        entities.append(GaposaCover(coordinator, hub, motor))
    
    if entities:
        _LOGGER.info("Ajout de %d entités cover", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.warning("Aucune entité cover à ajouter")


class GaposaCover(CoordinatorEntity, CoverEntity):
    """Representation of a Gaposa cover."""

    coordinator: GaposaDataUpdateCoordinator

    def __init__(self, coordinator: GaposaDataUpdateCoordinator, hub: GaposaHub, motor) -> None:
        """Initialize the cover."""
        super().__init__(coordinator)
        self._hub = hub
        self._motor = motor
        self._motor_id = motor.id
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
        # Trouver le moteur correspondant dans les données mises à jour
        for motor in self.coordinator.data["motors"]:
            if motor.id == self._motor_id:
                self._motor = motor
                self._update_attrs()
                break
        self.async_write_ha_state()
    
    def _update_attrs(self) -> None:
        """Update the attributes based on motor status."""
        if hasattr(self._motor, 'percent'):
            # Position inversée: 0 = fermé, 100 = ouvert dans HA
            self._attr_current_cover_position = 100 - self._motor.percent
            self._attr_is_closed = self._motor.percent >= 95
            _LOGGER.debug(
                "Mise à jour du moteur %s (ID: %s): position=%s, fermé=%s",
                self._attr_name, self._motor_id, self._attr_current_cover_position, self._attr_is_closed
            )
        else:
            _LOGGER.warning(
                "Le moteur %s n'a pas d'attribut 'percent'. Attributs disponibles: %s",
                self._attr_name, dir(self._motor)
            )
            self._attr_current_cover_position = None
            self._attr_is_closed = None
    
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._motor.up()
        self._update_attrs()
        # Déclencher une mise à jour immédiate pour tous les appareils
        await self.coordinator.async_request_refresh()
    
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._motor.down()
        self._update_attrs()
        # Déclencher une mise à jour immédiate pour tous les appareils
        await self.coordinator.async_request_refresh()
    
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self._motor.stop()
        self._update_attrs()
        # Déclencher une mise à jour immédiate pour tous les appareils
        await self.coordinator.async_request_refresh()
    
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
        # Déclencher une mise à jour immédiate pour tous les appareils
        await self.coordinator.async_request_refresh()
    
    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._motor_id)},
            name=self._attr_name,
            manufacturer="Gaposa",
            model="Motorized Shade",
        )
