"""Config flow for Plan My Dinner integration."""
from __future__ import annotations
import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_PROFILE_A, CONF_PROFILE_B

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="localhost"): str,
        vol.Required(CONF_PORT, default=8000): int,
        vol.Required(CONF_PROFILE_A, default="persona_a"): str,
        vol.Optional(CONF_PROFILE_B, default="persona_b"): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Plan My Dinner."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            session = async_get_clientsession(self.hass)
            try:
                async with session.get(
                    f"http://{host}:{port}/profiles",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status >= 500:
                        errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Plan My Dinner ({host}:{port})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
