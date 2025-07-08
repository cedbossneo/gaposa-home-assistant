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

from .const import DOMAIN, CONF_TRAVEL_TIME, CONF_CALIBRATION_DATA
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

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            if user_input.get("action") == "calibrate":
                self.calibration_data["cover_to_calibrate"] = user_input["cover_to_calibrate"]
                return await self.async_step_start_calibration()
            elif user_input.get("action") == "view_calibrations":
                return await self.async_step_view_calibrations()

        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        covers = {e.entity_id: e.original_name or e.name for e in entries if e.entity_id.startswith("cover.")}

        if not covers:
            return self.async_abort(reason="no_covers_found")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): vol.In({
                        "calibrate": "Calibrate a cover",
                        "view_calibrations": "View current calibrations"
                    }),
                    vol.Required("cover_to_calibrate"): vol.In(covers),
                }
            ),
            description_placeholders={
                "info": "Use calibration to set the travel time for position control. This tells Home Assistant how long it takes for your cover to travel from fully closed to fully open."
            }
        )

    async def async_step_view_calibrations(self, user_input=None):
        """Show current calibration data."""
        if user_input is not None:
            return await self.async_step_init()

        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )

        calibration_info = []
        for entry in entries:
            if entry.entity_id.startswith("cover."):
                travel_time = self.options.get(entry.entity_id, "Not calibrated")
                if isinstance(travel_time, (int, float)):
                    travel_time = f"{travel_time:.1f} seconds"
                calibration_info.append(f"{entry.original_name or entry.name}: {travel_time}")

        return self.async_show_form(
            step_id="view_calibrations",
            data_schema=vol.Schema({
                vol.Required("back", default=True): bool,
            }),
            description_placeholders={
                "calibrations": "\n".join(calibration_info) if calibration_info else "No covers found"
            }
        )

    async def async_step_start_calibration(self, user_input=None):
        """Show the start calibration screen."""
        if user_input is not None:
            if user_input.get("start_calibration"):
                # First, ensure the cover is fully closed
                await self.hass.services.async_call(
                    "cover",
                    "close_cover",
                    {"entity_id": self.calibration_data["cover_to_calibrate"]},
                    blocking=True,
                )
                # Wait a moment for the close command to complete
                await asyncio.sleep(2)

                # Now start timing from closed to open
                self.calibration_data["start_time"] = time.time()
                await self.hass.services.async_call(
                    "cover",
                    "open_cover",
                    {"entity_id": self.calibration_data["cover_to_calibrate"]},
                    blocking=False,
                )
                return await self.async_step_calibration_inprogress()
            else:
                return await self.async_step_init()

        entity_registry = er.async_get(self.hass)
        entry = entity_registry.async_get(self.calibration_data["cover_to_calibrate"])
        cover_name = entry.original_name or entry.name if entry else "Unknown"

        return self.async_show_form(
            step_id="start_calibration",
            data_schema=vol.Schema({
                vol.Required("start_calibration", default=False): bool,
            }),
            description_placeholders={
                "cover_name": cover_name,
                "instructions": (
                    "This will calibrate the travel time for position control.\n\n"
                    "Steps:\n"
                    "1. The cover will first close completely\n"
                    "2. Then it will start opening\n"
                    "3. Click 'Stop Calibration' when the cover is fully open\n\n"
                    "Make sure the cover has a clear path and won't be obstructed."
                )
            }
        )

    async def async_step_calibration_inprogress(self, user_input=None):
        """Handle the calibration in progress."""
        if user_input is not None:
            if user_input.get("stop_calibration"):
                end_time = time.time()
                travel_time = end_time - self.calibration_data["start_time"]

                # Stop the cover
                await self.hass.services.async_call(
                    "cover",
                    "stop_cover",
                    {"entity_id": self.calibration_data["cover_to_calibrate"]},
                    blocking=True,
                )

                # Store the calibration
                self.options[self.calibration_data["cover_to_calibrate"]] = travel_time

                return await self.async_step_calibration_complete({"travel_time": travel_time})
            elif user_input.get("cancel_calibration"):
                # Stop the cover and cancel
                await self.hass.services.async_call(
                    "cover",
                    "stop_cover",
                    {"entity_id": self.calibration_data["cover_to_calibrate"]},
                    blocking=True,
                )
                return await self.async_step_init()

        elapsed_time = time.time() - self.calibration_data["start_time"]

        return self.async_show_form(
            step_id="calibration_inprogress",
            data_schema=vol.Schema({
                vol.Required("stop_calibration", default=False): bool,
                vol.Required("cancel_calibration", default=False): bool,
            }),
            description_placeholders={
                "elapsed_time": f"{elapsed_time:.1f}",
                "instructions": (
                    "The cover is now opening. Click 'Stop Calibration' when it reaches "
                    "the fully open position, or 'Cancel' to abort the calibration."
                )
            }
        )

    async def async_step_calibration_complete(self, user_input=None):
        """Show calibration completion."""
        if user_input is not None:
            if user_input.get("save"):
                return self.async_create_entry(title="", data=self.options)
            elif user_input.get("recalibrate"):
                return await self.async_step_start_calibration()
            else:
                return await self.async_step_init()

        travel_time = user_input.get("travel_time", 0) if user_input else 0
        entity_registry = er.async_get(self.hass)
        entry = entity_registry.async_get(self.calibration_data["cover_to_calibrate"])
        cover_name = entry.original_name or entry.name if entry else "Unknown"

        return self.async_show_form(
            step_id="calibration_complete",
            data_schema=vol.Schema({
                vol.Required("save", default=True): bool,
                vol.Required("recalibrate", default=False): bool,
            }),
            description_placeholders={
                "cover_name": cover_name,
                "travel_time": f"{travel_time:.1f}",
                "result": (
                    f"Calibration complete! The travel time for {cover_name} "
                    f"has been measured as {travel_time:.1f} seconds.\n\n"
                    "This will now be used for position control. You can recalibrate "
                    "at any time if needed."
                )
            }
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
