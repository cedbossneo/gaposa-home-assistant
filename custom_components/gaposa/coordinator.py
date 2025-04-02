"""Data update coordinator for Gaposa integration."""
import asyncio
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.exceptions import ConfigEntryAuthFailed

from pygaposa.gaposa import Gaposa, GaposaAuthException

_LOGGER = logging.getLogger(__name__)


class GaposaCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, gaposa: Gaposa) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name="gaposa",
            update_interval=timedelta(seconds=60),
        )
        self.gaposa = gaposa
        self.data = {}
        self.devices = []

    async def _async_update_data(self):
        """Update data from Gaposa API."""
        try:
            await self.gaposa.update()
            
            # Organize data for easy access
            data = {}
            
            for client, user in self.gaposa.clients:
                # Update data for client devices
                await client.update()
                
                for device in client.devices:
                    await device.update()
                    
                    # Store rooms and their motors for each device
                    device_data = {
                        "id": device.id,
                        "name": device.name,
                        "rooms": []
                    }
                    
                    for room in device.rooms:
                        room_data = {
                            "id": room.id,
                            "name": room.name,
                            "motors": []
                        }
                        
                        for motor in room.motors:
                            motor_data = {
                                "id": motor.id,
                                "name": motor.name,
                                "location": motor.location,
                                "state": motor.state,
                                "percent": motor.percent,
                                "running": motor.running,
                                "paused": motor.paused
                            }
                            room_data["motors"].append(motor_data)
                            
                        device_data["rooms"].append(room_data)
                    
                    data[device.id] = device_data
            
            return data
            
        except GaposaAuthException as err:
            _LOGGER.error("Authentication error: %s", err)
            raise ConfigEntryAuthFailed("Authentication failed") from err
        except Exception as err:
            _LOGGER.error("Error fetching data: %s", err)
            raise
