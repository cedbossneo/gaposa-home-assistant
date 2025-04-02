"""Support for Gaposa covers."""
from __future__ import annotations

import logging
from typing import Any

from pygaposa.gaposa import Gaposa
from pygaposa.device import Device

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Gaposa covers."""
    gaposa = hass.data[DOMAIN][entry.entry_id]
    
    # Obtenir tous les appareils
    devices = []
    for client, _ in gaposa.clients:
        for device in client.devices:
            devices.append(GaposaCover(hass, gaposa, device))
    
    if devices:
        async_add_entities(devices)


class GaposaCover(CoverEntity):
    """Representation of a Gaposa cover."""

    def __init__(self, hass: HomeAssistant, gaposa: Gaposa, device: Device) -> None:
        """Initialize the cover."""
        self._gaposa = gaposa
        self._device = device
        self._attr_name = device.name
        self._attr_unique_id = f"{device.id}"
        self._attr_device_class = CoverDeviceClass.SHADE
        self._attr_supported_features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | 
            CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION
        )
        
        # Mise à jour initiale
        self._update_attrs()
    
    def _update_attrs(self) -> None:
        """Update the attributes based on device status."""
        if hasattr(self._device, 'position'):
            # Position inversée: 0 = fermé, 100 = ouvert dans HA
            self._attr_current_cover_position = 100 - self._device.position
            self._attr_is_closed = self._device.position >= 95
        else:
            self._attr_current_cover_position = None
            self._attr_is_closed = None
    
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._device.open()
        self._update_attrs()
    
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._device.close()
        self._update_attrs()
    
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self._device.stop()
        self._update_attrs()
    
    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover position."""
        position = kwargs.get(ATTR_POSITION, 50)
        # Conversion de position: 0 = fermé, 100 = ouvert dans HA
        device_position = 100 - position
        await self._device.set_position(device_position)
        self._update_attrs()
    
    async def async_update(self) -> None:
        """Update the cover status."""
        await self._device.update()
        self._update_attrs()
    
    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=self._device.name,
            manufacturer="Gaposa",
            model=getattr(self._device, "model", "Unknown"),
        )
