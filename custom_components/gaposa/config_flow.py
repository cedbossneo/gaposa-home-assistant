import logging
import time
from typing import Any
import asyncio

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant import exceptions
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, CONF_TRAVEL_TIME, CONF_CALIBRATION_DATA, CONF_OPEN_TIME, CONF_CLOSE_TIME
from .hub import GaposaHub

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    hub = GaposaHub(hass, data[CONF_EMAIL], data[CONF_PASSWORD])

    if not await hub.test_connection():
        raise CannotConnect

    await hub.connect()  # Pour récupérer les informations du client

    # Utiliser le premier client (nous n'avons pas besoin de stocker l'ID)
    title = "Gaposa"
    if hub.api and hub.api.clients:
        first_client, _ = hub.api.clients[0]
        title = f"Gaposa ({first_client.name})"

    await hub.close()

    return {"title": title}


class GaposaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gaposa."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                # Créer l'entrée
                return self.async_create_entry(
                    title=info["title"],
                    data=user_input
                )

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        self.calibration_data = {}
        self.current_cover_info = {}

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            action = user_input.get("action")
            if action == "calibrate":
                self.calibration_data["cover_to_calibrate"] = user_input["cover_to_calibrate"]
                # Get cover info for better UX
                entity_registry = er.async_get(self.hass)
                entry = entity_registry.async_get(user_input["cover_to_calibrate"])
                self.current_cover_info = {
                    "entity_id": user_input["cover_to_calibrate"],
                    "name": entry.original_name or entry.name if entry else "Unknown"
                }
                return await self.async_step_calibration_instructions()
            elif action == "view_calibrations":
                return await self.async_step_view_calibrations()
            elif action == "manual_set":
                self.calibration_data["cover_to_calibrate"] = user_input["cover_to_calibrate"]
                entity_registry = er.async_get(self.hass)
                entry = entity_registry.async_get(user_input["cover_to_calibrate"])
                self.current_cover_info = {
                    "entity_id": user_input["cover_to_calibrate"],
                    "name": entry.original_name or entry.name if entry else "Unknown"
                }
                return await self.async_step_manual_calibration()

        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        covers = {e.entity_id: f"{e.original_name or e.name} {'✓' if self.options.get(e.entity_id) else '⚠️'}"
                 for e in entries if e.entity_id.startswith("cover.")}

        if not covers:
            return self.async_abort(reason="no_covers_found")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): vol.In({
                        "calibrate": "🎯 Auto-calibrate a cover",
                        "manual_set": "⚙️ Manually set travel time",
                        "view_calibrations": "📋 View current calibrations"
                    }),
                    vol.Required("cover_to_calibrate"): vol.In(covers),
                }
            ),
            description_placeholders={
                "info": (
                    "Position control requires calibration to work accurately.\n\n"
                    "✓ = Calibrated\n⚠️ = Needs calibration\n\n"
                    "Choose an action to configure your covers."
                )
            }
        )

    async def async_step_calibration_instructions(self, user_input=None):
        """Show calibration instructions and safety warnings."""
        if user_input is not None:
            if user_input.get("understand_and_continue"):
                return await self.async_step_select_calibration_direction()
            else:
                return await self.async_step_init()

        cover_name = self.current_cover_info.get("name", "Unknown")
        entity_id = self.current_cover_info["entity_id"]

        # Check current calibration status
        open_key = f"{entity_id}_open"
        close_key = f"{entity_id}_close"
        open_time = self.options.get(open_key)
        close_time = self.options.get(close_key)

        status_parts = []
        if open_time:
            status_parts.append(f"Open: {open_time:.1f}s ✓")
        else:
            status_parts.append("Open: Not calibrated ⚠️")

        if close_time:
            status_parts.append(f"Close: {close_time:.1f}s ✓")
        else:
            status_parts.append("Close: Not calibrated ⚠️")

        return self.async_show_form(
            step_id="calibration_instructions",
            data_schema=vol.Schema({
                vol.Required("understand_and_continue", default=False): bool,
            }),
            description_placeholders={
                "cover_name": cover_name,
                "current_status": " | ".join(status_parts),
                "instructions": (
                    "⚠️ SAFETY INSTRUCTIONS ⚠️\n\n"
                    "Before starting calibration:\n"
                    "• Ensure the cover path is completely clear\n"
                    "• Remove any obstacles or obstructions\n"
                    "• Make sure no one is near the cover\n"
                    "• Have the stop button ready if needed\n\n"
                    "CALIBRATION PROCESS:\n"
                    "You'll calibrate both OPEN and CLOSE directions separately.\n"
                    "Each direction may have different timing due to gravity and motor characteristics.\n\n"
                    "For each direction:\n"
                    "1. Cover moves to starting position\n"
                    "2. Cover starts moving in calibration direction\n"
                    "3. You click 'STOP' when fully open/closed\n"
                    "4. Time is measured and saved"
                )
            }
        )

    async def async_step_select_calibration_direction(self, user_input=None):
        """Select which direction(s) to calibrate."""
        if user_input is not None:
            direction = user_input.get("direction")
            self.calibration_data["direction"] = direction

            if direction == "both":
                # Track that we're calibrating both directions
                self.calibration_data["calibrating_both"] = True
                self.calibration_data["original_direction"] = "both"
                # Start with open direction first
                self.calibration_data["direction"] = "open"
                return await self.async_step_start_calibration()
            else:
                # Single direction calibration
                self.calibration_data["calibrating_both"] = False
                self.calibration_data["original_direction"] = direction
                return await self.async_step_start_calibration()

        entity_id = self.current_cover_info["entity_id"]
        open_key = f"{entity_id}_open"
        close_key = f"{entity_id}_close"

        # Check what needs calibration
        needs_open = not self.options.get(open_key)
        needs_close = not self.options.get(close_key)

        direction_options = {}
        if needs_open and needs_close:
            direction_options["both"] = "📐 Both directions (recommended)"
            direction_options["open"] = "📈 Opening only"
            direction_options["close"] = "📉 Closing only"
        elif needs_open:
            direction_options["open"] = "📈 Opening (not calibrated)"
            direction_options["both"] = "📐 Both directions (recalibrate all)"
        elif needs_close:
            direction_options["close"] = "📉 Closing (not calibrated)"
            direction_options["both"] = "📐 Both directions (recalibrate all)"
        else:
            direction_options["both"] = "📐 Both directions (recalibrate)"
            direction_options["open"] = "📈 Opening (recalibrate)"
            direction_options["close"] = "📉 Closing (recalibrate)"

        return self.async_show_form(
            step_id="select_calibration_direction",
            data_schema=vol.Schema({
                vol.Required("direction"): vol.In(direction_options),
            }),
            description_placeholders={
                "cover_name": self.current_cover_info.get("name", "Unknown"),
                "info": (
                    "Choose which direction(s) to calibrate.\n\n"
                    "Open and close times are often different due to:\n"
                    "• Gravity assistance when closing\n"
                    "• Motor characteristics\n"
                    "• Mechanical resistance\n\n"
                    "For best accuracy, calibrate both directions."
                )
            }
        )

    async def async_step_manual_calibration(self, user_input=None):
        """Allow manual setting of travel time."""
        if user_input is not None:
            travel_time = user_input.get("travel_time")
            if travel_time and 5 <= travel_time <= 300:  # 5s to 5min range
                self.options[self.current_cover_info["entity_id"]] = travel_time
                return self.async_create_entry(
                    title="",
                    data=self.options,
                    description=f"Travel time set to {travel_time} seconds for {self.current_cover_info['name']}"
                )
            else:
                return self.async_show_form(
                    step_id="manual_calibration",
                    data_schema=vol.Schema({
                        vol.Required("travel_time", default=30): vol.All(vol.Coerce(int), vol.Range(min=5, max=300)),
                    }),
                    errors={"travel_time": "invalid_range"},
                    description_placeholders={
                        "cover_name": self.current_cover_info.get("name", "Unknown"),
                        "info": "Travel time must be between 5 and 300 seconds."
                    }
                )

        current_calibration = self.options.get(self.current_cover_info["entity_id"], 30)

        return self.async_show_form(
            step_id="manual_calibration",
            data_schema=vol.Schema({
                vol.Required("travel_time", default=int(current_calibration)): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=300)
                ),
            }),
            description_placeholders={
                "cover_name": self.current_cover_info.get("name", "Unknown"),
                "info": (
                    "Enter the time in seconds it takes for this cover to travel "
                    "from fully closed to fully open.\n\n"
                    "If you're unsure, use auto-calibration instead.\n\n"
                    "Range: 5-300 seconds"
                )
            }
        )

    async def async_step_start_calibration(self, user_input=None):
        """Start the calibration process."""
        if user_input is not None:
            if user_input.get("start_calibration"):
                direction = self.calibration_data["direction"]

                if direction == "open":
                    # For open calibration, start from closed position
                    await self.hass.services.async_call(
                        "cover",
                        "close_cover",
                        {"entity_id": self.calibration_data["cover_to_calibrate"]},
                        blocking=True,
                    )
                    await asyncio.sleep(3)  # Wait for close to complete

                    # Start timing and open
                    self.calibration_data["start_time"] = time.time()
                    await self.hass.services.async_call(
                        "cover",
                        "open_cover",
                        {"entity_id": self.calibration_data["cover_to_calibrate"]},
                        blocking=False,
                    )
                else:  # close
                    # For close calibration, start from open position
                    await self.hass.services.async_call(
                        "cover",
                        "open_cover",
                        {"entity_id": self.calibration_data["cover_to_calibrate"]},
                        blocking=True,
                    )
                    await asyncio.sleep(3)  # Wait for open to complete

                    # Start timing and close
                    self.calibration_data["start_time"] = time.time()
                    await self.hass.services.async_call(
                        "cover",
                        "close_cover",
                        {"entity_id": self.calibration_data["cover_to_calibrate"]},
                        blocking=False,
                    )

                return await self.async_step_calibration_inprogress()
            else:
                return await self.async_step_select_calibration_direction()

        direction = self.calibration_data["direction"]
        cover_name = self.current_cover_info.get("name", "Unknown")

        if direction == "open":
            instruction_text = (
                "CALIBRATING: OPENING DIRECTION\n\n"
                "Process:\n"
                "1. Cover will close completely first\n"
                "2. Cover will start opening\n"
                "3. Click 'Stop Calibration' when fully OPEN\n\n"
                "This measures opening time (closed → open)."
            )
        else:  # close
            instruction_text = (
                "CALIBRATING: CLOSING DIRECTION\n\n"
                "Process:\n"
                "1. Cover will open completely first\n"
                "2. Cover will start closing\n"
                "3. Click 'Stop Calibration' when fully CLOSED\n\n"
                "This measures closing time (open → closed)."
            )

        return self.async_show_form(
            step_id="start_calibration",
            data_schema=vol.Schema({
                vol.Required("start_calibration", default=False): bool,
            }),
            description_placeholders={
                "cover_name": cover_name,
                "direction": direction.upper(),
                "instructions": instruction_text
            }
        )

    async def async_step_calibration_inprogress(self, user_input=None):
        """Handle the calibration in progress."""
        if user_input is not None:
            if user_input.get("stop_calibration"):
                end_time = time.time()
                travel_time = end_time - self.calibration_data["start_time"]
                direction = self.calibration_data["direction"]

                # Stop the cover
                await self.hass.services.async_call(
                    "cover",
                    "stop_cover",
                    {"entity_id": self.calibration_data["cover_to_calibrate"]},
                    blocking=True,
                )

                # Store the calibration for this direction
                entity_id = self.calibration_data["cover_to_calibrate"]
                if direction == "open":
                    self.options[f"{entity_id}_open"] = travel_time
                else:  # close
                    self.options[f"{entity_id}_close"] = travel_time

                # Track which direction we just calibrated
                self.calibration_data["last_calibrated_direction"] = direction

                # Check if we need to calibrate the other direction
                if self.calibration_data.get("calibrating_both", False):
                    if direction == "open":
                        # We just finished open, now do close
                        self.calibration_data["direction"] = "close"
                        return await self.async_step_start_calibration()
                    else:
                        # We finished both directions
                        self.calibration_data["calibrating_both"] = False
                        return await self.async_step_calibration_complete()
                else:
                    return await self.async_step_calibration_complete()

            elif user_input.get("cancel_calibration"):
                # Stop the cover and cancel
                await self.hass.services.async_call(
                    "cover",
                    "stop_cover",
                    {"entity_id": self.calibration_data["cover_to_calibrate"]},
                    blocking=True,
                )
                return await self.async_step_select_calibration_direction()

        elapsed_time = time.time() - self.calibration_data["start_time"]
        direction = self.calibration_data["direction"]

        return self.async_show_form(
            step_id="calibration_inprogress",
            data_schema=vol.Schema({
                vol.Required("stop_calibration", default=False): bool,
                vol.Required("cancel_calibration", default=False): bool,
            }),
            description_placeholders={
                "elapsed_time": f"{elapsed_time:.1f}",
                "direction": direction.upper(),
                "instructions": (
                    f"The cover is now {direction}ing. Click 'Stop Calibration' when it reaches "
                    f"the fully {'OPEN' if direction == 'open' else 'CLOSED'} position, or 'Cancel' to abort."
                )
            }
        )

    async def async_step_calibration_complete(self, user_input=None):
        """Show calibration completion."""
        if user_input is not None:
            if user_input.get("save"):
                return self.async_create_entry(title="", data=self.options)
            elif user_input.get("calibrate_other"):
                # Calibrate the other direction
                current_direction = self.calibration_data.get("last_calibrated_direction", "open")
                self.calibration_data["direction"] = "close" if current_direction == "open" else "open"
                return await self.async_step_start_calibration()
            elif user_input.get("recalibrate"):
                return await self.async_step_select_calibration_direction()
            else:
                return await self.async_step_init()

        # Get calibration results from stored data
        entity_id = self.calibration_data["cover_to_calibrate"]
        cover_name = self.current_cover_info.get("name", "Unknown")

        # Determine what we just calibrated
        last_direction = self.calibration_data.get("last_calibrated_direction", "open")
        was_both_calibration = self.calibration_data.get("original_direction") == "both"

        # Get current calibration status
        open_time = self.options.get(f"{entity_id}_open")
        close_time = self.options.get(f"{entity_id}_close")

        schema_dict = {
            "save": bool,
            "recalibrate": bool,
        }

        # Build result text
        if was_both_calibration:
            result_text = "✅ BOTH directions calibration complete!\n\n"
            if open_time:
                result_text += f"Opening time: {open_time:.1f} seconds\n"
            if close_time:
                result_text += f"Closing time: {close_time:.1f} seconds\n"
            result_text += "\nBoth directions are now calibrated for accurate position control."
        else:
            last_time = open_time if last_direction == "open" else close_time
            result_text = f"✅ {last_direction.upper()} calibration complete!\n\n"
            if last_time:
                result_text += f"Time measured: {last_time:.1f} seconds\n\n"

            # Check if other direction needs calibration
            other_direction = "close" if last_direction == "open" else "open"
            other_time = close_time if last_direction == "open" else open_time

            if not other_time:
                result_text += f"You can now calibrate the {other_direction.upper()} direction for full accuracy, or save with just {last_direction.upper()} calibrated."
                schema_dict["calibrate_other"] = bool
            else:
                result_text += "Both directions are now calibrated."

        return self.async_show_form(
            step_id="calibration_complete",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "cover_name": cover_name,
                "result": result_text
            }
        )

    async def async_step_view_calibrations(self, user_input=None):
        """Show current calibration data with enhanced details."""
        if user_input is not None:
            if user_input.get("delete_calibration"):
                cover_to_delete = user_input.get("cover_to_delete")
                if cover_to_delete:
                    # Delete both open and close calibrations for this cover
                    if f"{cover_to_delete}_open" in self.options:
                        del self.options[f"{cover_to_delete}_open"]
                    if f"{cover_to_delete}_close" in self.options:
                        del self.options[f"{cover_to_delete}_close"]
                    # Also delete legacy single travel time if exists
                    if cover_to_delete in self.options:
                        del self.options[cover_to_delete]
                    return self.async_create_entry(
                        title="",
                        data=self.options,
                        description=f"Calibration deleted for {cover_to_delete}"
                    )
            return await self.async_step_init()

        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )

        calibration_info = []
        uncalibrated_covers = []
        covers_to_delete = {}

        for entry in entries:
            if entry.entity_id.startswith("cover."):
                name = entry.original_name or entry.name
                entity_id = entry.entity_id

                # Check for separate open/close times
                open_time = self.options.get(f"{entity_id}_open")
                close_time = self.options.get(f"{entity_id}_close")
                legacy_time = self.options.get(entity_id)

                calibration_parts = []
                has_calibration = False

                if open_time and isinstance(open_time, (int, float)):
                    calibration_parts.append(f"Open: {open_time:.1f}s")
                    has_calibration = True

                if close_time and isinstance(close_time, (int, float)):
                    calibration_parts.append(f"Close: {close_time:.1f}s")
                    has_calibration = True

                if legacy_time and isinstance(legacy_time, (int, float)) and not has_calibration:
                    calibration_parts.append(f"Legacy: {legacy_time:.1f}s")
                    has_calibration = True

                if has_calibration:
                    status_str = " | ".join(calibration_parts)
                    calibration_info.append(f"{name}: {status_str}")
                    covers_to_delete[entity_id] = f"{name} ({status_str})"
                else:
                    uncalibrated_covers.append(name)

        # Build display text
        display_parts = []
        if calibration_info:
            display_parts.append("📊 CALIBRATED COVERS:")
            display_parts.extend(calibration_info)

        if uncalibrated_covers:
            if display_parts:
                display_parts.append("")
            display_parts.append("⚠️ UNCALIBRATED COVERS:")
            display_parts.extend(uncalibrated_covers)

        if not calibration_info and not uncalibrated_covers:
            display_parts.append("No covers found")

        schema_dict = {"back": bool}
        if covers_to_delete:
            schema_dict["delete_calibration"] = bool
            schema_dict["cover_to_delete"] = vol.In(covers_to_delete)

        return self.async_show_form(
            step_id="view_calibrations",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "calibrations": "\n".join(display_parts),
                "summary": f"Total covers: {len(calibration_info) + len(uncalibrated_covers)}, Calibrated: {len(calibration_info)}, Need calibration: {len(uncalibrated_covers)}"
            }
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
