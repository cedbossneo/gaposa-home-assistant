"""Config flow for Gaposa integration."""
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from pygaposa.gaposa import Gaposa, GaposaAuthException

from .const import DOMAIN, API_KEY, CONF_CLIENT

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    session = async_get_clientsession(hass)
    gaposa = Gaposa(API_KEY, websession=session)

    try:
        await gaposa.login(data[CONF_EMAIL], data[CONF_PASSWORD])
    except GaposaAuthException as ex:
        _LOGGER.error("Authentication failed: %s", ex)
        raise InvalidAuth from ex
    finally:
        await gaposa.close()

    # Toujours utiliser le premier client
    first_client, _ = gaposa.clients[0]
    return {"title": f"Gaposa ({first_client.name})", "client_id": first_client.id}


class GaposaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gaposa."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._auth_data = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                
                # Créer l'entrée avec le premier client
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        **user_input,
                        CONF_CLIENT: info["client_id"],
                    },
                )
            
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
