"""Hub for connecting to Gaposa."""
import logging
from typing import Any, Callable, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

# Importer depuis le sous-module local
from .pygaposa.gaposa import Gaposa, GaposaAuthException 
from .pygaposa.motor import Motor

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
            _LOGGER.warning("Tentative de mise à jour sans connexion active")
            return

        try:
            _LOGGER.debug("Mise à jour des données Gaposa")
            await self.api.update()
            
            # Récupérer tous les moteurs
            old_motors_count = len(self._motors)
            self._motors = []
            
            for client_idx, (client, _) in enumerate(self.api.clients):
                _LOGGER.debug("Client %d: %s", client_idx, client.name)
                await client.update()
                
                for device_idx, device in enumerate(client.devices):
                    _LOGGER.debug("Appareil %d: %s", device_idx, device.name)
                    await device.update()
                    
                    # Lister les moteurs directement attachés au device
                    _LOGGER.debug("Moteurs de l'appareil: %d", len(device.motors))
                    for motor in device.motors:
                        _LOGGER.debug("Moteur trouvé: %s (ID: %s)", motor.name, motor.id)
                        self._motors.append(motor)
                    
                    # Lister les rooms pour trouver les autres moteurs
                    _LOGGER.debug("Nombre de rooms: %d", len(device.rooms))
                    for room_idx, room in enumerate(device.rooms):
                        _LOGGER.debug("Room %d: %s", room_idx, room.name)
                        
                        # Récupérer les moteurs des rooms
                        _LOGGER.debug("Moteurs dans la room %s: %d", room.name, len(room.motors))
                        for motor in room.motors:
                            if not any(m.id == motor.id for m in self._motors):
                                _LOGGER.debug("Ajout du moteur de room: %s (ID: %s)", motor.name, motor.id)
                                self._motors.append(motor)
                    
                    # Recherche dans les groupes également
                    _LOGGER.debug("Nombre de groupes: %d", len(device.groups))
                    for group_idx, group in enumerate(device.groups):
                        _LOGGER.debug("Groupe %d: %s", group_idx, group.name)
                        
                        # Récupérer les moteurs des groupes
                        _LOGGER.debug("Moteurs dans le groupe %s: %d", group.name, len(group.motors))
                        for motor in group.motors:
                            if not any(m.id == motor.id for m in self._motors):
                                _LOGGER.debug("Ajout du moteur de groupe: %s (ID: %s)", motor.name, motor.id)
                                self._motors.append(motor)
            
            _LOGGER.info("Nombre total de moteurs trouvés: %d", len(self._motors))
                        
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
