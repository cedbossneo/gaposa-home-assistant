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
    """Representation of a Gaposa cover (with optimistic mode)."""

    coordinator: GaposaDataUpdateCoordinator

    # Use _attr_ prefix for HA managed attributes
    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = (
            CoverEntityFeature.OPEN |
            CoverEntityFeature.CLOSE |
            CoverEntityFeature.STOP
    )
    # Indicate that state updates are pushed from the coordinator
    _attr_should_poll = False
    # No need for a custom _ignore_state flag

    def __init__(self, coordinator: GaposaDataUpdateCoordinator, motor_command_obj, initial_motor_data) -> None:
        """Initialize the cover."""
        super().__init__(coordinator)
        # self._hub = hub # Maybe not needed if commands are on motor obj
        self._motor_command_obj = motor_command_obj # Use this for sending commands
        self._motor_id = initial_motor_data.id
        self._attr_name = initial_motor_data.name
        self._attr_unique_id = f"{initial_motor_data.id}"

        # Initialize state attributes based on the *initial* data
        self._update_attrs(initial_motor_data) # Pass initial data

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
        _LOGGER.debug("Optimistic: Sending OPEN command to %s", self._attr_name)
        try:
            await self._motor_command_obj.up()

            # --- OPTIMISTIC UPDATE ---
            self._attr_is_opening = True
            self._attr_is_closing = False
            # Assume it goes to fully open, or None if you don't want to guess position
            self._attr_current_cover_position = 100
            self._attr_is_closed = False
            self.async_write_ha_state() # Update HA state immediately
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
        _LOGGER.debug("Optimistic: Sending CLOSE command to %s", self._attr_name)
        try:
            await self._motor_command_obj.down()

            # --- OPTIMISTIC UPDATE ---
            self._attr_is_closing = True
            self._attr_is_opening = False
            # Assume it goes to fully closed
            self._attr_current_cover_position = 0
            self._attr_is_closed = True
            self.async_write_ha_state() # Update HA state immediately
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
        _LOGGER.debug("Optimistic: Sending STOP command to %s", self._attr_name)
        try:
            await self._motor_command_obj.stop()

            # --- OPTIMISTIC UPDATE ---
            # Stopping means it's no longer opening or closing
            self._attr_is_closing = False
            self._attr_is_opening = False
            # We don't know the position after stop, so don't change _attr_current_cover_position
            # unless the stop command *always* results in a known state (unlikely)
            # Keep _attr_is_closed as it was before stop.
            self.async_write_ha_state() # Update HA state immediately
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
        """Set the cover position."""
        position = kwargs[ATTR_POSITION] # No need for .get() if feature is supported
        _LOGGER.debug(
            "Optimistic: Sending SET_POSITION %s command to %s",
            position, self._attr_name
        )

        # --- Choose command based on position ---
        # (Your existing logic seems fine, assumes preset handles intermediate)
        try:
            if position >= 95:
                await self._motor_command_obj.up()
            elif position <= 5:
                await self._motor_command_obj.down()
            else:
                # Check if your motor object actually supports a position command
                # If it only has UP/DOWN/STOP/PRESET, setting exact position isn't possible
                # Maybe just call preset for any intermediate value?
                if hasattr(self._motor_command_obj, 'set_position'):
                    # Assuming set_position takes HA standard 0-100
                    await self._motor_command_obj.set_position(position)
                elif hasattr(self._motor_command_obj, 'preset'):
                    _LOGGER.warning("Motor %s has no set_position, using preset for position %s", self._attr_name, position)
                    await self._motor_command_obj.preset() # Or maybe stop? Depends on device.
                else:
                    _LOGGER.error("Motor %s cannot be set to position %s", self._attr_name, position)
                    return # Don't do optimistic update if command fails

            # --- OPTIMISTIC UPDATE ---
            self._attr_current_cover_position = position # Assume it reaches the target
            self._attr_is_closed = position <= 5
            # We don't know if it's opening or closing to reach the position
            self._attr_is_opening = False # Safer to set both false
            self._attr_is_closing = False
            self.async_write_ha_state() # Update HA state immediately
            # -------------------------

            # Request refresh to get actual state later
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Error sending SET_POSITION command to %s: %s", self._attr_name, e)
            # Reset optimistic flags on error? Maybe not needed for position.


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
