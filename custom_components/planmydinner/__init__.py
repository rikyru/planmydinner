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