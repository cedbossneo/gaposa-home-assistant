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
        
        # Activer toutes les fonctionnalités même si certains états sont incertains
        self._attr_supported_features = (
            CoverEntityFeature.OPEN | 
            CoverEntityFeature.CLOSE | 
            CoverEntityFeature.STOP |
            CoverEntityFeature.SET_POSITION
        )
        
        # Paramètre pour autoriser les actions même quand l'état est identique
        self._ignore_state = True
        
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
            self._attr_current_cover_position = self._motor.percent
            self._attr_is_closed = self._motor.percent < 5
            _LOGGER.debug(
                "Mise à jour du store %s (ID: %s): position=%s, fermé=%s",
                self._attr_name, self._motor_id, self._attr_current_cover_position, self._attr_is_closed
            )
        else:
            _LOGGER.warning(
                "Le store %s n'a pas d'attribut 'percent'. Attributs disponibles: %s",
                self._attr_name, dir(self._motor)
            )
            self._attr_current_cover_position = None
            self._attr_is_closed = None
    
    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening."""
        # Nous retournons toujours False car nous ne pouvons pas être certain 
        # de l'état d'ouverture en cours
        return False

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing."""
        # Nous retournons toujours False car nous ne pouvons pas être certain 
        # de l'état de fermeture en cours
        return False
    
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        _LOGGER.debug("Commande d'ouverture pour %s (ID: %s)", self._attr_name, self._motor_id)
        await self._motor.up()
        self._update_attrs()
        # Déclencher une mise à jour immédiate pour tous les appareils
        await self.coordinator.async_request_refresh()
    
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        _LOGGER.debug("Commande de fermeture pour %s (ID: %s)", self._attr_name, self._motor_id)
        await self._motor.down()
        self._update_attrs()
        # Déclencher une mise à jour immédiate pour tous les appareils
        await self.coordinator.async_request_refresh()
    
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        _LOGGER.debug("Commande d'arrêt pour %s (ID: %s)", self._attr_name, self._motor_id)
        await self._motor.stop()
        self._update_attrs()
        # Déclencher une mise à jour immédiate pour tous les appareils
        await self.coordinator.async_request_refresh()
    
    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover position."""
        position = kwargs.get(ATTR_POSITION, 50)
        _LOGGER.debug(
            "Définition de la position pour %s (ID: %s) à %s", 
            self._attr_name, self._motor_id, position
        )
        
        # Conversion de position selon la logique d'API de Gaposa
        device_position = position
        
        # Commandes simplifiées basées sur la position
        if device_position >= 95:  # Presque complètement ouvert
            await self._motor.up()
        elif device_position <= 5:  # Presque complètement fermé
            await self._motor.down()
        else:
            # Position intermédiaire - utiliser la position preset si disponible
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
