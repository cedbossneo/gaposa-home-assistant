"""Support for Gaposa covers."""
from __future__ import annotations

import asyncio
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
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from .coordinator import GaposaDataUpdateCoordinator
from .const import DOMAIN, DEFAULT_TRAVEL_TIME
from .hub import GaposaHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Gaposa covers."""
    data = hass.data[DOMAIN][entry.entry_id]
    hub: GaposaHub = data["hub"]
    coordinator: GaposaDataUpdateCoordinator = data["coordinator"]

    # It's often better practice to let the coordinator handle the initial refresh
    # which happens automatically when it's created or when async_setup_entry runs.
    # Forcing it here might be okay if hub.motors isn't populated otherwise.
    # Consider if coordinator.last_update_success is True before adding entities.
    # await coordinator.async_config_entry_first_refresh() # Recommended way

    if not coordinator.last_update_success:
        _LOGGER.warning("Initial data fetch failed, cannot set up covers yet.")
        # You might want to set up a listener for the coordinator to finish its first refresh
        return

    entities = []
    # Access motors via coordinator.data which holds the latest fetched state
    motors_data = coordinator.data.get("motors", []) if coordinator.data else []
    _LOGGER.debug("Coordinator data has %d motors available", len(motors_data))

    for motor_data in motors_data:
        # Pass the motor data from the coordinator, not directly from hub
        # Assuming motor_data has id and name attributes
        _LOGGER.debug("Adding motor %s (ID: %s)", motor_data.name, motor_data.id)
        # Find the corresponding hub motor object if needed for commands,
        # or ensure motor_data itself has methods like up(), down()
        # This depends on how your GaposaHub and motor objects are structured
        motor_command_obj = next((m for m in hub.motors if m.id == motor_data.id), None)
        if motor_command_obj:
            entities.append(GaposaCover(coordinator, motor_command_obj, motor_data))
        else:
            _LOGGER.error("Could not find command object for motor ID %s", motor_data.id)

    if entities:
        _LOGGER.info("Adding %d cover entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.warning("No cover entities to add (check coordinator data and motor matching)")


class GaposaCover(CoordinatorEntity, CoverEntity):
    """Representation of a Gaposa cover (with timing-based position control)."""

    coordinator: GaposaDataUpdateCoordinator

    # Use _attr_ prefix for HA managed attributes
    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = (
            CoverEntityFeature.OPEN |
            CoverEntityFeature.CLOSE |
            CoverEntityFeature.STOP |
            CoverEntityFeature.SET_POSITION  # Enable position control
    )
    # Indicate that state updates are pushed from the coordinator
    _attr_should_poll = False

    def __init__(self, coordinator: GaposaDataUpdateCoordinator, motor_command_obj, initial_motor_data) -> None:
        """Initialize the cover."""
        super().__init__(coordinator)
        self._motor_command_obj = motor_command_obj
        self._motor_id = initial_motor_data.id
        self._attr_name = initial_motor_data.name
        self._attr_unique_id = f"{initial_motor_data.id}"

        # Position control timing variables
        self._travel_time = None
        self._movement_start_time = None
        self._movement_task = None
        self._target_position = None
        self._start_position = None

        # Initialize state attributes based on the initial data
        self._update_attrs(initial_motor_data)

        # Load calibration data from config options
        self._load_calibration_data()

    def _load_calibration_data(self) -> None:
        """Load calibration data from config entry options."""
        if self.coordinator.config_entry.options:
            entity_id = f"cover.{self.unique_id}"
            self._travel_time = self.coordinator.config_entry.options.get(entity_id, DEFAULT_TRAVEL_TIME)
            _LOGGER.debug("Loaded travel time for %s: %s seconds", self._attr_name, self._travel_time)
        else:
            self._travel_time = DEFAULT_TRAVEL_TIME
            _LOGGER.debug("Using default travel time for %s: %s seconds", self._attr_name, self._travel_time)

    @property
    def travel_time(self) -> float:
        """Return the calibrated travel time for this cover."""
        return self._travel_time or DEFAULT_TRAVEL_TIME

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Find the motor corresponding to this entity in the coordinator's data
        updated_motor_data = next((m for m in self.coordinator.data.get("motors", [])
                                   if m.id == self._motor_id), None)

        if updated_motor_data:
            _LOGGER.debug("Coordinator update received for %s", self._attr_name)
            # Update state based on the *actual* data received
            self._update_attrs(updated_motor_data)
            self.async_write_ha_state() # Update HA state
        else:
            _LOGGER.debug("No update in coordinator data for %s", self._attr_name)
            # Decide if you want to mark the entity unavailable, or just log
            # self._attr_available = False


    def _update_attrs(self, motor_data) -> None:
        """Update the attributes based on motor data from coordinator."""
        # Reset optimistic flags when real data comes in
        self._attr_is_opening = False
        self._attr_is_closing = False

        if hasattr(motor_data, 'percent'):
            # Assume Gaposa 0=closed, 100=open matches HA's 0=closed, 100=open
            # If Gaposa uses 0=open, 100=closed, invert here: 100 - motor_data.percent
            pos = motor_data.percent
            self._attr_current_cover_position = pos
            self._attr_is_closed = pos is not None and pos < 5 # Consider 0 as closed
            self._attr_available = True # Mark available if we have data
            _LOGGER.debug(
                "Updating %s (ID: %s) from coordinator: position=%s, closed=%s",
                self._attr_name, self._motor_id, self._attr_current_cover_position, self._attr_is_closed
            )
        else:
            _LOGGER.warning(
                "Motor %s has no 'percent' attribute in coordinator data. State unknown.",
                self._attr_name
            )
            # Decide how to handle missing position data
            self._attr_current_cover_position = None
            self._attr_is_closed = None
            # Maybe mark unavailable if position is critical?
            # self._attr_available = False

    # Remove the static is_opening / is_closing properties
    # Home Assistant uses the _attr_is_opening / _attr_is_closing attributes directly

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        _LOGGER.debug("Sending OPEN command to %s", self._attr_name)

        # Cancel any existing movement
        if self._movement_task and not self._movement_task.done():
            self._movement_task.cancel()

        try:
            await self._motor_command_obj.up()

            # --- OPTIMISTIC UPDATE ---
            self._attr_is_opening = True
            self._attr_is_closing = False
            # Don't set position to 100 immediately - let coordinator update handle actual position
            # Only update is_closed state
            self._attr_is_closed = False
            self.async_write_ha_state()
            # -------------------------

            # Request refresh to get actual state later
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Error sending OPEN command to %s: %s", self._attr_name, e)
            # Reset optimistic flags on error
            self._attr_is_opening = False
            self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        _LOGGER.debug("Sending CLOSE command to %s", self._attr_name)

        # Cancel any existing movement
        if self._movement_task and not self._movement_task.done():
            self._movement_task.cancel()

        try:
            await self._motor_command_obj.down()

            # --- OPTIMISTIC UPDATE ---
            self._attr_is_closing = True
            self._attr_is_opening = False
            # Don't set position to 0 immediately - let coordinator update handle actual position
            # Only update is_closed state
            self._attr_is_closed = True
            self.async_write_ha_state()
            # -------------------------

            # Request refresh to get actual state later
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Error sending CLOSE command to %s: %s", self._attr_name, e)
            # Reset optimistic flags on error
            self._attr_is_closing = False
            self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        _LOGGER.debug("Sending STOP command to %s", self._attr_name)

        # Cancel any existing movement
        if self._movement_task and not self._movement_task.done():
            self._movement_task.cancel()

        try:
            await self._motor_command_obj.stop()

            # --- OPTIMISTIC UPDATE ---
            # Stopping means it's no longer opening or closing
            self._attr_is_closing = False
            self._attr_is_opening = False
            # Don't change position - we don't know where it stopped
            self.async_write_ha_state()
            # -------------------------

            # Request refresh to get actual state later
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Error sending STOP command to %s: %s", self._attr_name, e)
            # Reset optimistic flags on error
            self._attr_is_opening = False
            self._attr_is_closing = False
            self.async_write_ha_state()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover to a specific position using timing."""
        target_position = kwargs[ATTR_POSITION]
        current_position = self._attr_current_cover_position or 0

        _LOGGER.debug(
            "Setting %s position from %s to %s (travel time: %s seconds)",
            self._attr_name, current_position, target_position, self.travel_time
        )

        # Cancel any existing movement
        if self._movement_task and not self._movement_task.done():
            self._movement_task.cancel()

        # Calculate movement parameters
        position_diff = abs(target_position - current_position)
        movement_time = (position_diff / 100.0) * self.travel_time

        if movement_time < 0.5:  # Too small movement, ignore
            _LOGGER.debug("Movement too small for %s, ignoring", self._attr_name)
            # Still update the position optimistically for small movements
            self._attr_current_cover_position = target_position
            self._attr_is_closed = target_position <= 5
            self.async_write_ha_state()
            return

        try:
            # Start movement
            if target_position > current_position:
                # Opening
                await self._motor_command_obj.up()
                self._attr_is_opening = True
                self._attr_is_closing = False
            else:
                # Closing
                await self._motor_command_obj.down()
                self._attr_is_opening = False
                self._attr_is_closing = True

            # Store movement parameters
            self._target_position = target_position
            self._start_position = current_position
            self._movement_start_time = self.hass.loop.time()

            # Update state optimistically for position control
            self._attr_current_cover_position = target_position
            self._attr_is_closed = target_position <= 5
            self.async_write_ha_state()

            # Schedule stop command
            self._movement_task = asyncio.create_task(
                self._stop_after_delay(movement_time)
            )

        except Exception as e:
            _LOGGER.error("Error setting position for %s: %s", self._attr_name, e)
            self._attr_is_opening = False
            self._attr_is_closing = False
            self.async_write_ha_state()

    async def _stop_after_delay(self, delay: float) -> None:
        """Stop the cover after a specified delay."""
        try:
            await asyncio.sleep(delay)
            await self._motor_command_obj.stop()

            # Update state
            self._attr_is_opening = False
            self._attr_is_closing = False
            self.async_write_ha_state()

            _LOGGER.debug("Stopped %s after %s seconds", self._attr_name, delay)

            # Request refresh to get actual state
            await self.coordinator.async_request_refresh()

        except asyncio.CancelledError:
            _LOGGER.debug("Movement cancelled for %s", self._attr_name)
        except Exception as e:
            _LOGGER.error("Error stopping %s: %s", self._attr_name, e)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._motor_id)},
            name=self._attr_name,
            manufacturer="Gaposa",
            model="Motorized Shade", # Consider making this more specific if possible
            # Link to the Hub device if you have one
            # via_device=(DOMAIN, self.coordinator.config_entry.entry_id),
        )

    # You might need these if you want fine-grained control, but usually
    # _attr_is_opening/closing combined with _attr_current_cover_position is enough
    @property
    def is_opening(self) -> bool | None:
        """Return if the cover is currently opening."""
        return self._attr_is_opening

    @property
    def is_closing(self) -> bool | None:
        """Return if the cover is currently closing."""
        return self._attr_is_closing
