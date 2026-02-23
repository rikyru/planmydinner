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
    async def handle_add_item(call: ServiceCall):
        """Handle the service call to add a pantry item."""
        item = call.data.get("item")
        if item:
            await api_client.add_item(item)
        else:
            _LOGGER.error("Service add_item requires an item")

    async def handle_update_item(call: ServiceCall):
        """Handle the service call to update a pantry item."""
        item_id = call.data.get("item_id")
        item = call.data.get("item")
        if item_id and item:
            await api_client.update_item(item_id, item)
        else:
            _LOGGER.error("Service update_item requires an item_id and an item")
            
    async def handle_remove_item(call: ServiceCall):
        """Handle the service call to remove a pantry item."""
        item_id = call.data.get("item_id")
        if item_id:
            await api_client.remove_item(item_id)
        else:
            _LOGGER.error("Service remove_item requires an item_id")

    async def handle_add_recipe(call: ServiceCall):
        """Handle the service call to add a recipe."""
        recipe = call.data.get("recipe")
        if recipe:
            await api_client.add_recipe(recipe)
        else:
            _LOGGER.error("Service add_recipe requires a recipe")
            
    async def handle_update_recipe(call: ServiceCall):
        """Handle the service call to update a recipe."""
        recipe_id = call.data.get("recipe_id")
        recipe = call.data.get("recipe")
        if recipe_id and recipe:
            await api_client.update_recipe(recipe_id, recipe)
        else:
            _LOGGER.error("Service update_recipe requires a recipe_id and a recipe")
            
    async def handle_delete_recipe(call: ServiceCall):
        """Handle the service call to delete a recipe."""
        recipe_id = call.data.get("recipe_id")
        if recipe_id:
            await api_client.delete_recipe(recipe_id)
        else:
            _LOGGER.error("Service delete_recipe requires a recipe_id")

    hass.services.async_register(DOMAIN, "add_item", handle_add_item)
    hass.services.async_register(DOMAIN, "update_item", handle_update_item)
    hass.services.async_register(DOMAIN, "remove_item", handle_remove_item)
    hass.services.async_register(DOMAIN, "add_recipe", handle_add_recipe)
    hass.services.async_register(DOMAIN, "update_recipe", handle_update_recipe)
    hass.services.async_register(DOMAIN, "delete_recipe", handle_delete_recipe)

    async def handle_mark_consumed(call: ServiceCall):
        """Handle the service call to mark a meal as consumed."""
        profile_id = call.data.get("profile_id")
        meal_date = call.data.get("meal_date")
        meal_type = call.data.get("meal_type")
        recipe_id = call.data.get("recipe_id")
        if profile_id and meal_date and meal_type and recipe_id:
            try:
                await api_client.mark_consumed_planned(profile_id, meal_date, meal_type, recipe_id)
            except Exception as e:
                _LOGGER.error("Error calling mark_consumed_planned: %s", e)
        else:
            _LOGGER.error("Service mark_consumed requires profile_id, meal_date, meal_type, and recipe_id")

    async def handle_override_consumed(call: ServiceCall):
        """Handle the service call to override a consumed meal."""
        profile_id = call.data.get("profile_id")
        meal_date = call.data.get("meal_date")
        meal_type = call.data.get("meal_type")
        override_details = call.data.get("override_details")
        if profile_id and meal_date and meal_type and override_details:
            try:
                await api_client.mark_consumed_override(profile_id, meal_date, meal_type, override_details)
            except Exception as e:
                _LOGGER.error("Error calling mark_consumed_override: %s", e)
        else:
            _LOGGER.error("Service override_consumed requires profile_id, meal_date, meal_type, and override_details")

    async def handle_generate_week(call: ServiceCall):
        """Handle the service call to generate a weekly plan."""
        profile_id_A = call.data.get("profile_id_A")
        profile_id_B = call.data.get("profile_id_B")
        current_date = call.data.get("current_date")
        if profile_id_A and profile_id_B and current_date:
            try:
                await api_client.generate_weekly_plan(profile_id_A, profile_id_B, current_date)
            except Exception as e:
                _LOGGER.error("Error calling generate_weekly_plan: %s", e)
        else:
            _LOGGER.error("Service generate_week requires profile_id_A, profile_id_B, and current_date")

    async def handle_change_recipe(call: ServiceCall):
        """Handle the service call to change a recipe."""
        profile_id_A = call.data.get("profile_id_A")
        profile_id_B = call.data.get("profile_id_B")
        meal_type = call.data.get("meal_type")
        current_date = call.data.get("current_date")
        mood = call.data.get("mood")
        cleanup = call.data.get("cleanup")
        max_time_minutes = call.data.get("max_time_minutes")
        if profile_id_A and profile_id_B and meal_type and current_date:
            try:
                await api_client.suggest_recipes_for_meal(profile_id_A, profile_id_B, meal_type, current_date, mood, cleanup, max_time_minutes)
            except Exception as e:
                _LOGGER.error("Error calling suggest_recipes_for_meal: %s", e)
        else:
            _LOGGER.error("Service change_recipe requires profile_id_A, profile_id_B, meal_type, and current_date")

    async def handle_apply_recipe_option(call: ServiceCall):
        """Handle the service call to apply a recipe option."""
        profile_id_A = call.data.get("profile_id_A")
        profile_id_B = call.data.get("profile_id_B")
        meal_type = call.data.get("meal_type")
        current_date = call.data.get("current_date")
        recipe_id = call.data.get("recipe_id")
        if profile_id_A and profile_id_B and meal_type and current_date and recipe_id:
            try:
                await api_client.apply_recipe_to_plan(profile_id_A, profile_id_B, meal_type, current_date, recipe_id)
            except Exception as e:
                _LOGGER.error("Error calling apply_recipe_to_plan: %s", e)
        else:
            _LOGGER.error("Service apply_recipe_option requires profile_id_A, profile_id_B, meal_type, current_date, and recipe_id")

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
    hass.services.async_remove(DOMAIN, "add_item")
    hass.services.async_remove(DOMAIN, "update_item")
    hass.services.async_remove(DOMAIN, "remove_item")
    hass.services.async_remove(DOMAIN, "add_recipe")
    hass.services.async_remove(DOMAIN, "update_recipe")
    hass.services.async_remove(DOMAIN, "delete_recipe")
    hass.services.async_remove(DOMAIN, "mark_consumed")
    hass.services.async_remove(DOMAIN, "override_consumed")
    hass.services.async_remove(DOMAIN, "generate_week")
    hass.services.async_remove(DOMAIN, "change_recipe")
    hass.services.async_remove(DOMAIN, "apply_recipe_option")
    
    return unload_ok