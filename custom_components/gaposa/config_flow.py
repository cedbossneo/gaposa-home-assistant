"""Config flow for Gaposa integration."""
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant import exceptions

from pygaposa.gaposa import Gaposa, GaposaAuthException

from .const import DOMAIN, API_KEY

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.
    
    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    session = async_get_clientsession(hass)
    gaposa = Gaposa(API_KEY, websession=session)

    try:
        await gaposa.login(data[CONF_EMAIL], data[CONF_PASSWORD])
    except GaposaAuthException as ex:
        _LOGGER.error("Authentication failed: %s", ex)
        raise InvalidAuth from ex
    except Exception as ex:
        _LOGGER.exception("Unexpected exception")
        raise CannotConnect from ex
    finally:
        await gaposa.close()

    # Utiliser le premier client (nous n'avons pas besoin de stocker l'ID)
    first_client, _ = gaposa.clients[0]
    return {
        "title": f"Gaposa ({first_client.name})"
    }


class GaposaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gaposa."""

    VERSION = 1
    # Connection class indicates to HA if this integration can work with or without internet
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                
                # Créer l'entrée (pas besoin de stocker l'ID du client)
                return self.async_create_entry(
                    title=info["title"],
                    data=user_input
                )
            
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
