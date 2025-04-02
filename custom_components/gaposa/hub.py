"""Hub for connecting to Gaposa."""
import logging
from typing import Any, Callable, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from pygaposa.gaposa import Gaposa, GaposaAuthException
from pygaposa.motor import Motor

from .const import API_KEY

_LOGGER = logging.getLogger(__name__)


class GaposaHub:
    """Gaposa hub for Home Assistant."""

    def __init__(self, hass: HomeAssistant, email: str, password: str) -> None:
        """Initialize the hub."""
        self.hass = hass
        self.email = email
        self.password = password
        self.api: Optional[Gaposa] = None
        self._callbacks: List[Callable[[], None]] = []
        self._motors: List[Motor] = []
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        """Return true if connected to Gaposa."""
        return self._is_connected

    @property
    def motors(self) -> List[Motor]:
        """Return all available motors."""
        return self._motors

    async def connect(self) -> bool:
        """Connect to Gaposa."""
        session = async_get_clientsession(self.hass)
        self.api = Gaposa(API_KEY, websession=session)
        
        try:
            await self.api.login(self.email, self.password)
            self._is_connected = True
            await self.update_data()
            return True
        except GaposaAuthException as ex:
            _LOGGER.error("Authentication failed: %s", ex)
            self._is_connected = False
            return False
        except Exception as ex:
            _LOGGER.exception("Unexpected exception: %s", ex)
            self._is_connected = False
            return False

    async def update_data(self) -> None:
        """Update data from Gaposa."""
        if not self.api or not self._is_connected:
            return

        try:
            await self.api.update()
            
            # Récupérer tous les moteurs
            self._motors = []
            for client, _ in self.api.clients:
                await client.update()
                for device in client.devices:
                    await device.update()
                    for motor in device.motors:
                        self._motors.append(motor)
                        
            # Notifier les listeners
            for callback in self._callbacks:
                callback()
        except Exception as ex:
            _LOGGER.exception("Failed to update data: %s", ex)

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when data changes."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def test_connection(self) -> bool:
        """Test connectivity to Gaposa."""
        try:
            session = async_get_clientsession(self.hass)
            api = Gaposa(API_KEY, websession=session)
            await api.login(self.email, self.password)
            await api.close()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close connection to API."""
        if self.api:
            await self.api.close()
            self.api = None
        self._is_connected = False
