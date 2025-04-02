"""Support for Gaposa covers."""
import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import CONF_EMAIL

from pygaposa.gaposa import Gaposa
from pygaposa.model import Motor

from .const import DOMAIN
from .coordinator import GaposaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Gaposa covers based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    gaposa = hass.data[DOMAIN][entry.entry_id]["gaposa"]
    
    entities = []
    
    # Vérifier que l'index du client est valide
    selected_client, _ = gaposa.clients[0]
            
    # Add a cover entity for each motor
    for device in selected_client.devices:
        for room in device.rooms:
            for motor in room.motors:
                entities.append(
                    GaposaCover(
                        coordinator, 
                        motor, 
                        device.serial,
                        room.name,
                        entry.data[CONF_EMAIL]
                    )
                )
    
    async_add_entities(entities)


class GaposaCover(CoordinatorEntity, CoverEntity):
    """Representation of a Gaposa cover."""

    def __init__(
        self, 
        coordinator: GaposaCoordinator, 
        motor: Motor, 
        device_id: str, 
        room_name: str,
        user_email: str
    ) -> None:
        """Initialize the cover."""
        super().__init__(coordinator)
        self._motor = motor
        self._device_id = device_id
        self._room_name = room_name
        self._user_email = user_email
        
        # Set unique ID format
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{motor.id}"
        self._attr_name = f"{room_name} - {motor.name}"
        self._attr_device_class = CoverDeviceClass.BLIND
        
        # Support up, down, stop and position
        self._attr_supported_features = (
            CoverEntityFeature.OPEN 
            | CoverEntityFeature.CLOSE 
            | CoverEntityFeature.STOP
        )
        
        # Device info for device registry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer="Gaposa",
            name=f"Gaposa {device_id}",
            model="Gaposa Motor",
            via_device=(DOMAIN, user_email),
        )

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        # Check if motor position is 0% (fully closed) or 100% depending on direction
        if self._motor.percent == 0:
            return True
        # Not closed if we're moving or at any other position
        return False

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position of the cover."""
        # Convert to HA position (0 is closed, 100 is open)
        return self._motor.percent

    @property
    def is_opening(self) -> bool | None:
        """Return if the cover is opening."""
        return self._motor.running and self._motor.state == "UP"

    @property
    def is_closing(self) -> bool | None:
        """Return if the cover is closing."""
        return self._motor.running and self._motor.state == "DOWN"

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._motor.up()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close cover."""
        await self._motor.down()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self._motor.stop()
