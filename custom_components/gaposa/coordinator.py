"""Data update coordinator for Gaposa integration."""
import asyncio
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from pygaposa.gaposa import Gaposa, GaposaAuthException

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Update interval (in seconds)
UPDATE_INTERVAL = 60


class GaposaCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, gaposa: Gaposa) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.gaposa = gaposa
        self.devices_data = {}
        self.motors_by_id = {}
    
    def get_motor(self, motor_id):
        """Get a motor by ID."""
        return self.motors_by_id.get(motor_id)

    async def _async_update_data(self):
        """Update data from Gaposa API."""
        try:
            # Update the Gaposa API data
            await self.gaposa.update()
            
            # Organize data for easy access
            data = {}
            motors_by_id = {}
            
            for client, user in self.gaposa.clients:
                # Update data for client devices
                await client.update()
                
                # Process each device
                for device in client.devices:
                    await device.update()
                    
                    # Store device data
                    device_data = {
                        "id": device.id,
                        "name": device.name,
                        "rooms": [],
                        "motors": [],
                    }
                    
                    # Process each room
                    for room in device.rooms:
                        room_data = {
                            "id": room.id,
                            "name": room.name,
                            "motors": [],
                        }
                        
                        # Process each motor in the room
                        for motor in room.motors:
                            # Store motor reference for direct access
                            motors_by_id[motor.id] = motor
                            
                            # Create motor data
                            motor_data = {
                                "id": motor.id,
                                "name": motor.name,
                                "location": motor.location,
                                "state": motor.state,
                                "percent": motor.percent,
                                "running": motor.running,
                                "paused": motor.paused,
                                "room": room.name,
                            }
                            
                            # Add motor to both room and device lists
                            room_data["motors"].append(motor_data)
                            device_data["motors"].append(motor_data)
                            
                        # Add room to device data
                        device_data["rooms"].append(room_data)
                    
                    # Store device data
                    data[device.id] = device_data
            
            # Update the motor lookup dictionary
            self.motors_by_id = motors_by_id
            self.devices_data = data
            
            return data
            
        except GaposaAuthException as err:
            _LOGGER.error("Authentication error: %s", err)
            raise ConfigEntryAuthFailed("Authentication failed") from err
        except Exception as err:
            _LOGGER.error("Error fetching data: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err
