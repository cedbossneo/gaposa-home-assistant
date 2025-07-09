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
from .pygaposa.motor import Motor
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from .coordinator import GaposaDataUpdateCoordinator
from .const import DOMAIN, DEFAULT_TRAVEL_TIME, DEFAULT_OPEN_TIME, DEFAULT_CLOSE_TIME
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

    def __init__(self, coordinator: GaposaDataUpdateCoordinator, motor_command_obj: Motor, initial_motor_data) -> None:
        """Initialize the cover."""
        super().__init__(coordinator)
        self._motor_command_obj = motor_command_obj
        self._motor_id = initial_motor_data.id
        self._attr_name = initial_motor_data.name
        self._attr_unique_id = f"{initial_motor_data.id}"

        # Position control timing variables
        self._open_time = None
        self._close_time = None
        self._movement_start_time = None
        self._movement_task = None
        self._target_position = None
        self._start_position = None
        self._is_open_calibrated = False
        self._is_close_calibrated = False
        self._position_update_task = None
        self._last_position_control_time = None  # Track when we last did position control

        # Initialize state attributes based on the initial data
        self._update_attrs(initial_motor_data)

        # Don't load calibration data here - entity_id is not available yet
        # It will be loaded in async_added_to_hass when entity_id is available

    async def async_added_to_hass(self) -> None:
        """Entity has been added to hass."""
        await super().async_added_to_hass()
        # Now we can load calibration data since entity_id is available
        self._load_calibration_data()

    def _load_calibration_data(self) -> None:
        """Load calibration data from config entry options."""
        if self.coordinator.config_entry.options:
            # Use the actual entity_id, not a constructed one
            entity_id = self.entity_id
            # Try to load separate open/close times
            open_key = f"{entity_id}_open"
            close_key = f"{entity_id}_close"

            stored_open_time = self.coordinator.config_entry.options.get(open_key)
            stored_close_time = self.coordinator.config_entry.options.get(close_key)

            # Load open time
            if stored_open_time and isinstance(stored_open_time, (int, float)) and stored_open_time > 0:
                self._open_time = stored_open_time
                self._is_open_calibrated = True
                _LOGGER.debug("Loaded calibrated open time for %s: %s seconds", self._attr_name, self._open_time)
            else:
                self._open_time = DEFAULT_OPEN_TIME
                self._is_open_calibrated = False
                _LOGGER.debug("No valid open calibration for %s, using default: %s seconds", self._attr_name, self._open_time)

            # Load close time
            if stored_close_time and isinstance(stored_close_time, (int, float)) and stored_close_time > 0:
                self._close_time = stored_close_time
                self._is_close_calibrated = True
                _LOGGER.debug("Loaded calibrated close time for %s: %s seconds", self._attr_name, self._close_time)
            else:
                self._close_time = DEFAULT_CLOSE_TIME
                self._is_close_calibrated = False
                _LOGGER.debug("No valid close calibration for %s, using default: %s seconds", self._attr_name, self._close_time)

            # For backward compatibility, check for old single travel_time
            if not self._is_open_calibrated and not self._is_close_calibrated:
                old_travel_time = self.coordinator.config_entry.options.get(entity_id)
                if old_travel_time and isinstance(old_travel_time, (int, float)) and old_travel_time > 0:
                    self._open_time = old_travel_time
                    self._close_time = old_travel_time * 0.85  # Assume close is 15% faster
                    _LOGGER.debug("Using legacy travel time for %s: open=%ss, close=%ss",
                                self._attr_name, self._open_time, self._close_time)
        else:
            self._open_time = DEFAULT_OPEN_TIME
            self._close_time = DEFAULT_CLOSE_TIME
            self._is_open_calibrated = False
            self._is_close_calibrated = False
            _LOGGER.debug("No calibration data for %s, using defaults: open=%ss, close=%ss",
                        self._attr_name, self._open_time, self._close_time)

    @property
    def open_time(self) -> float:
        """Return the calibrated open time for this cover."""
        return self._open_time or DEFAULT_OPEN_TIME

    @property
    def close_time(self) -> float:
        """Return the calibrated close time for this cover."""
        return self._close_time or DEFAULT_CLOSE_TIME

    @property
    def is_calibrated(self) -> bool:
        """Return if this cover has been calibrated (both directions)."""
        return self._is_open_calibrated and self._is_close_calibrated

    @property
    def is_open_calibrated(self) -> bool:
        """Return if the open direction has been calibrated."""
        return self._is_open_calibrated

    @property
    def is_close_calibrated(self) -> bool:
        """Return if the close direction has been calibrated."""
        return self._is_close_calibrated

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "open_time": self.open_time,
            "close_time": self.close_time,
            "is_open_calibrated": self.is_open_calibrated,
            "is_close_calibrated": self.is_close_calibrated,
            "is_fully_calibrated": self.is_calibrated,
            "calibration_needed": not self.is_calibrated,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Find the motor corresponding to this entity in the coordinator's data
        updated_motor_data = next((m for m in self.coordinator.data.get("motors", [])
                                   if m.id == self._motor_id), None)

        if updated_motor_data:
            _LOGGER.debug("Coordinator update received for %s", self._attr_name)

            # If we're in the middle of a calculated movement, don't override our position
            if self._movement_task and not self._movement_task.done():
                _LOGGER.debug("Ignoring coordinator position update during calculated movement for %s", self._attr_name)
                # Still update availability but keep our calculated position
                self._attr_available = True
                # Only update movement flags if they conflict with reality
                if hasattr(updated_motor_data, 'percent'):
                    real_pos = updated_motor_data.percent
                    _LOGGER.debug("Real position from coordinator: %s, our calculated: %s",
                                real_pos, self._attr_current_cover_position)
            else:
                # No active movement, safe to update from coordinator
                self._update_attrs(updated_motor_data)

            self.async_write_ha_state()
        else:
            _LOGGER.debug("No update in coordinator data for %s", self._attr_name)

    def _update_attrs(self, motor_data) -> None:
        """Update the attributes based on motor data from coordinator."""
        # Only reset movement flags if we're not in an active calculated movement
        if not self._movement_task or self._movement_task.done():
            self._attr_is_opening = False
            self._attr_is_closing = False

        if hasattr(motor_data, 'percent'):
            # Assume Gaposa 0=closed, 100=open matches HA's 0=closed, 100=open
            # If Gaposa uses 0=open, 100=closed, invert here: 100 - motor_data.percent
            pos = motor_data.percent

            # Check if we should ignore this coordinator update
            should_ignore_position = False

            # If we're in the middle of a calculated movement, ignore position updates
            if self._movement_task and not self._movement_task.done():
                should_ignore_position = True

            # If we recently completed position control, ignore for a grace period
            elif self._last_position_control_time:
                import time
                time_since_control = time.time() - self._last_position_control_time
                if time_since_control < 30:  # 30 second grace period
                    should_ignore_position = True
                    _LOGGER.debug(
                        "Ignoring coordinator position update for %s (%.1fs since position control, grace period active)",
                        self._attr_name, time_since_control
                    )

            if should_ignore_position:
                _LOGGER.debug(
                    "Coordinator has position %s for %s, but keeping calculated position %s",
                    pos, self._attr_name, self._attr_current_cover_position
                )
            else:
                # Safe to update from coordinator
                self._attr_current_cover_position = pos
                self._attr_is_closed = pos is not None and pos < 5 # Consider 0 as closed
                _LOGGER.debug(
                    "Updating %s (ID: %s) from coordinator: position=%s, closed=%s",
                    self._attr_name, self._motor_id, self._attr_current_cover_position, self._attr_is_closed
                )

            self._attr_available = True # Mark available if we have data
        else:
            _LOGGER.warning(
                "Motor %s has no 'percent' attribute in coordinator data. State unknown.",
                self._attr_name
            )
            # Decide how to handle missing position data
            if not self._movement_task or self._movement_task.done():
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

        # Determine movement direction and get appropriate timing
        is_opening = target_position > current_position
        movement_direction = "opening" if is_opening else "closing"

        # Get the appropriate travel time based on direction
        if is_opening:
            travel_time = self.open_time
            is_direction_calibrated = self.is_open_calibrated
        else:
            travel_time = self.close_time
            is_direction_calibrated = self.is_close_calibrated

        # Warn if this direction is not calibrated
        if not is_direction_calibrated:
            _LOGGER.warning(
                "Cover %s %s direction is not calibrated. Position control may be inaccurate. "
                "Please calibrate through the integration options.",
                self._attr_name, movement_direction
            )

        _LOGGER.debug(
            "Setting %s position from %s to %s (%s: %s seconds, calibrated: %s)",
            self._attr_name, current_position, target_position, movement_direction, travel_time, is_direction_calibrated
        )

        # Cancel any existing movement
        await self._cancel_movement()

        # Calculate movement parameters using direction-specific timing
        position_diff = abs(target_position - current_position)
        movement_time = (position_diff / 100.0) * travel_time

        if movement_time < 0.5:  # Too small movement, ignore
            _LOGGER.debug("Movement too small for %s, ignoring", self._attr_name)
            # Still update the position optimistically for small movements
            self._attr_current_cover_position = target_position
            self._attr_is_closed = target_position <= 5
            self.async_write_ha_state()
            return

        try:
            # Start movement
            if is_opening:
                # Opening
                await self._motor_command_obj.up(waitForUpdate=False)
                self._attr_is_opening = True
                self._attr_is_closing = False
            else:
                # Closing
                await self._motor_command_obj.down(waitForUpdate=False)
                self._attr_is_opening = False
                self._attr_is_closing = True

            # Store movement parameters
            self._target_position = target_position
            self._start_position = current_position
            self._movement_start_time = self.hass.loop.time()

            # DON'T update position immediately - let real-time tracking handle it
            # Only update movement state
            self._attr_is_closed = False  # Cover is moving, not closed
            self.async_write_ha_state()

            # Start real-time position tracking
            self._position_update_task = asyncio.create_task(
                self._track_position_realtime(movement_time)
            )

            # Schedule stop command
            self._movement_task = asyncio.create_task(
                self._stop_after_delay(movement_time)
            )

        except Exception as e:
            _LOGGER.error("Error setting position for %s: %s", self._attr_name, e)
            self._attr_is_opening = False
            self._attr_is_closing = False
            self.async_write_ha_state()

    async def _cancel_movement(self) -> None:
        """Cancel any existing movement tasks."""
        if self._movement_task and not self._movement_task.done():
            self._movement_task.cancel()
        if self._position_update_task and not self._position_update_task.done():
            self._position_update_task.cancel()

    async def _track_position_realtime(self, total_time: float) -> None:
        """Track position in real-time during movement."""
        try:
            start_time = self.hass.loop.time()
            last_update_time = start_time

            while True:
                await asyncio.sleep(0.2)  # Update every 200ms for smoother tracking
                elapsed = self.hass.loop.time() - start_time

                if elapsed >= total_time:
                    # Set final position and break
                    self._attr_current_cover_position = self._target_position
                    self._attr_is_closed = self._target_position <= 5
                    self.async_write_ha_state()
                    break

                # Calculate current position based on elapsed time
                progress = elapsed / total_time
                position_diff = self._target_position - self._start_position
                current_estimated_position = self._start_position + (position_diff * progress)

                # Update position every 200ms
                self._attr_current_cover_position = int(current_estimated_position)
                self._attr_is_closed = current_estimated_position <= 5

                # Only write state if enough time has passed or significant position change
                now = self.hass.loop.time()
                if now - last_update_time >= 0.5:  # Update UI every 500ms
                    self.async_write_ha_state()
                    last_update_time = now

        except asyncio.CancelledError:
            _LOGGER.debug("Real-time position tracking cancelled for %s", self._attr_name)
        except Exception as e:
            _LOGGER.error("Error in real-time position tracking for %s: %s", self._attr_name, e)

    async def _stop_after_delay(self, delay: float) -> None:
        """Stop the cover after a specified delay."""
        try:
            _LOGGER.debug("Will stop %s after %s seconds", self._attr_name, delay)
            await asyncio.sleep(delay)

            _LOGGER.debug("Stopping %s now after %s seconds", self._attr_name, delay)

            # Send stop command as "fire and forget" - don't wait for response
            try:
                # Create the stop task but don't wait for it
                await self._motor_command_obj.stop(waitForUpdate=False)
                _LOGGER.debug("Stop command sent to %s (not waiting for response)", self._attr_name)
                # Let it run in background, we don't care about the response
            except Exception as e:
                _LOGGER.error("Error sending stop command to %s: %s", self._attr_name, e)

            # Update state immediately - movement is complete
            self._attr_is_opening = False
            self._attr_is_closing = False

            # Set final position
            self._attr_current_cover_position = self._target_position
            self._attr_is_closed = self._target_position <= 5

            # Mark the time we completed position control to prevent coordinator override
            import time
            self._last_position_control_time = time.time()

            _LOGGER.debug("Stopped %s at target position %s", self._attr_name, self._target_position)
            self.async_write_ha_state()

            # Cancel position tracking since we're done
            if self._position_update_task and not self._position_update_task.done():
                self._position_update_task.cancel()

            # Don't immediately request refresh - keep our calculated position
            # The coordinator will update naturally, but we'll be smart about when to accept updates
            _LOGGER.debug("Movement complete for %s, keeping calculated position %s",
                         self._attr_name, self._target_position)

        except asyncio.CancelledError:
            _LOGGER.debug("Movement cancelled for %s", self._attr_name)
            # Reset movement flags immediately on cancellation
            self._attr_is_opening = False
            self._attr_is_closing = False
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error("Error stopping %s: %s", self._attr_name, e)
            # Reset movement flags on error
            self._attr_is_opening = False
            self._attr_is_closing = False
            self.async_write_ha_state()

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
