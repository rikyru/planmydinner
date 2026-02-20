"""The Plan My Dinner integration."""
from __future__ import annotations
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, PLATFORMS
from .api_client import PlanMyDinnerApiClient

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Plan My Dinner from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    host = entry.data["host"]
    port = entry.data["port"]
    session = async_get_clientsession(hass)
    
    api_client = PlanMyDinnerApiClient(host, port, session)
    hass.data[DOMAIN][entry.entry_id] = api_client

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_pantry_add(call: ServiceCall):
        """Handle the service call to add a pantry item."""
        name = call.data.get("name")
        quantity = call.data.get("quantity")
        unit = call.data.get("unit")
        if name and quantity and unit:
            await api_client.add_pantry_item(name, quantity, unit)
            # Optionally, you can refresh a sensor here
        else:
            _LOGGER.error("Service pantry.add_item requires name, quantity, and unit")

    async def handle_mark_consumed(call: ServiceCall):
        """Handle the service call to mark a meal as consumed."""
        # This is a simplified version for the MVP
        profile_id = call.data.get("profile_id")
        meal_date = call.data.get("date")
        meal_type = call.data.get("meal_type")
        recipe_id = call.data.get("recipe_id")
        await api_client.mark_consumed_planned(profile_id, meal_date, meal_type, recipe_id)

    async def handle_override_consumed(call: ServiceCall):
        """Handle the service call for an override."""
        # Simplified for MVP
        profile_id = call.data.get("profile_id")
        meal_date = call.data.get("date")
        meal_type = call.data.get("meal_type")
        free_text_name = call.data.get("free_text_name")
        override_details = {"free_text_name": free_text_name} # Simplified
        await api_client.mark_consumed_override(profile_id, meal_date, meal_type, override_details)

    async def handle_generate_week(call: ServiceCall):
        """Handle the service call to generate a weekly meal plan."""
        profile_id_A = call.data.get("profile_id_A")
        profile_id_B = call.data.get("profile_id_B")
        current_date = call.data.get("current_date")
        if profile_id_A and profile_id_B and current_date:
            await api_client.generate_weekly_plan(profile_id_A, profile_id_B, current_date)
        else:
            _LOGGER.error("Service mealplan.generate_week requires profile_id_A, profile_id_B, and current_date.")

    async def handle_change_recipe(call: ServiceCall):
        """Handle the service call to suggest alternative recipes."""
        profile_id_A = call.data.get("profile_id_A")
        profile_id_B = call.data.get("profile_id_B")
        meal_type = call.data.get("meal_type")
        current_date = call.data.get("current_date")
        mood = call.data.get("mood")
        cleanup = call.data.get("cleanup")
        max_time_minutes = call.data.get("max_time_minutes")
        if profile_id_A and profile_id_B and meal_type and current_date:
            await api_client.suggest_recipes_for_meal(profile_id_A, profile_id_B, meal_type, current_date, mood, cleanup, max_time_minutes)
        else:
            _LOGGER.error("Service mealplan.change_recipe requires profile_id_A, profile_id_B, meal_type, and current_date.")

    async def handle_apply_recipe_option(call: ServiceCall):
        """Handle the service call to apply a chosen recipe to the plan."""
        profile_id_A = call.data.get("profile_id_A")
        profile_id_B = call.data.get("profile_id_B")
        meal_type = call.data.get("meal_type")
        current_date = call.data.get("current_date")
        recipe_id = call.data.get("recipe_id")
        if profile_id_A and profile_id_B and meal_type and current_date and recipe_id:
            await api_client.apply_recipe_to_plan(profile_id_A, profile_id_B, meal_type, current_date, recipe_id)
        else:
            _LOGGER.error("Service mealplan.apply_recipe_option requires profile_id_A, profile_id_B, meal_type, current_date, and recipe_id.")


    hass.services.async_register(DOMAIN, "add_pantry_item", handle_pantry_add)
    hass.services.async_register(DOMAIN, "mark_consumed", handle_mark_consumed)
    hass.services.async_register(DOMAIN, "override_consumed", handle_override_consumed)
    hass.services.async_register(DOMAIN, "generate_week", handle_generate_week)
    hass.services.async_register(DOMAIN, "change_recipe", handle_change_recipe)
    hass.services.async_register(DOMAIN, "apply_recipe_option", handle_apply_recipe_option)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    # Unregister services
    hass.services.async_remove(DOMAIN, "add_pantry_item")
    hass.services.async_remove(DOMAIN, "mark_consumed")
    hass.services.async_remove(DOMAIN, "override_consumed")
    hass.services.async_remove(DOMAIN, "generate_week")
    hass.services.async_remove(DOMAIN, "change_recipe")
    hass.services.async_remove(DOMAIN, "apply_recipe_option")
    
    return unload_ok