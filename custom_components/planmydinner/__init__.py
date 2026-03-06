"""The Plan My Dinner integration."""
from __future__ import annotations
import logging
from datetime import date

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, PLATFORMS, CONF_PROFILE_A, CONF_PROFILE_B
from .api_client import PlanMyDinnerApiClient
from .coordinator import PlanMyDinnerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Plan My Dinner from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data["host"]
    port = entry.data["port"]
    profile_id_A = entry.data.get(CONF_PROFILE_A, "persona_a")
    profile_id_B = entry.data.get(CONF_PROFILE_B, "persona_b")

    session = async_get_clientsession(hass)
    api_client = PlanMyDinnerApiClient(host, port, session)

    coordinator = PlanMyDinnerCoordinator(hass, api_client, profile_id_A, profile_id_B)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- Services ---

    async def handle_generate_week(call: ServiceCall) -> None:
        """Generate a weekly meal plan (algorithmic, no AI)."""
        pA = call.data.get("profile_id_A", profile_id_A)
        pB = call.data.get("profile_id_B", profile_id_B)
        current_date = call.data.get("current_date", date.today().isoformat())
        try:
            await api_client.generate_weekly_plan(pA, pB, current_date)
            await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("generate_week failed: %s", e)

    async def handle_generate_week_ai(call: ServiceCall) -> None:
        """Generate a weekly meal plan using AI (per_slot or full_week mode)."""
        pA = call.data.get("profile_id_A", profile_id_A)
        pB = call.data.get("profile_id_B", profile_id_B)
        current_date = call.data.get("current_date", date.today().isoformat())
        ai_mode = call.data.get("ai_mode")  # None → read from DB settings
        try:
            path = f"/planner/generate-week?profile_id_A={pA}&profile_id_B={pB}&current_date={current_date}"
            if ai_mode:
                path += f"&ai_mode={ai_mode}"
            await api_client._request("POST", path)
            await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("generate_week_ai failed: %s", e)

    async def handle_mark_consumed(call: ServiceCall) -> None:
        """Mark a planned meal as consumed."""
        profile_id = call.data.get("profile_id", profile_id_A)
        meal_date = call.data.get("meal_date", date.today().isoformat())
        meal_type = call.data.get("meal_type")
        recipe_id = call.data.get("recipe_id")
        if meal_type and recipe_id:
            try:
                await api_client.mark_consumed_planned(profile_id, meal_date, meal_type, recipe_id)
                await coordinator.async_request_refresh()
            except Exception as e:
                _LOGGER.error("mark_consumed failed: %s", e)
        else:
            _LOGGER.error("mark_consumed requires meal_type and recipe_id")

    async def handle_add_pantry_item(call: ServiceCall) -> None:
        """Add an item to the pantry."""
        item = call.data.get("item")
        if item:
            try:
                await api_client.add_item(item)
                await coordinator.async_request_refresh()
            except Exception as e:
                _LOGGER.error("add_pantry_item failed: %s", e)
        else:
            _LOGGER.error("add_pantry_item requires item")

    async def handle_remove_pantry_item(call: ServiceCall) -> None:
        """Remove an item from the pantry."""
        item_id = call.data.get("item_id")
        if item_id:
            try:
                await api_client.remove_item(item_id)
                await coordinator.async_request_refresh()
            except Exception as e:
                _LOGGER.error("remove_pantry_item failed: %s", e)
        else:
            _LOGGER.error("remove_pantry_item requires item_id")

    hass.services.async_register(DOMAIN, "generate_week", handle_generate_week)
    hass.services.async_register(DOMAIN, "generate_week_ai", handle_generate_week_ai)
    hass.services.async_register(DOMAIN, "mark_consumed", handle_mark_consumed)
    hass.services.async_register(DOMAIN, "add_pantry_item", handle_add_pantry_item)
    hass.services.async_register(DOMAIN, "remove_pantry_item", handle_remove_pantry_item)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    for svc in ("generate_week", "generate_week_ai", "mark_consumed", "add_pantry_item", "remove_pantry_item"):
        hass.services.async_remove(DOMAIN, svc)
    return unload_ok
