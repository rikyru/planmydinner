"""Config flow for Plan My Dinner integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import DOMAIN

class ConfigFlow(config_entries.ConfigFlow, domain="planmydinner"):
    """Handle a config flow for Plan My Dinner."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Here you would typically validate the connection to the add-on
            # For now, we just accept the input.
            # Example validation:
            # try:
            #     await self.hass.async_add_executor_job(
            #         my_api_client.test_connection, user_input[CONF_HOST], user_input[CONF_PORT]
            #     )
            # except CannotConnect:
            #     errors["base"] = "cannot_connect"
            # else:
            return self.async_create_entry(title="Plan My Dinner", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default="localhost"): str,
                    vol.Required(CONF_PORT, default=8000): int,
                }
            ),
            errors=errors,
        )
