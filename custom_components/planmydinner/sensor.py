"""Sensor platform for Plan My Dinner."""
from __future__ import annotations
import logging
from datetime import date

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .api_client import PlanMyDinnerApiClient

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    api_client: PlanMyDinnerApiClient = hass.data[DOMAIN][entry.entry_id]
    sensors = [
        PantrySummarySensor(api_client, entry),
        MealPlanTodaySensor(api_client, entry),
        MealPlanWeekSensor(api_client, entry),
        ShoppingListAggregatedSensor(api_client, entry),
    ]
    async_add_entities(sensors, update_before_add=True)


class PantrySummarySensor(SensorEntity):
    """Representation of a Pantry Summary sensor."""

    def __init__(self, api_client: PlanMyDinnerApiClient, entry: ConfigEntry):
        """Initialize the sensor."""
        self._api_client = api_client
        self._attr_name = "Pantry Summary"
        self._attr_unique_id = f"{entry.entry_id}_pantry_summary"
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            pantry_items = await self._api_client.get_pantry_items()
            self._attr_native_value = len(pantry_items)
            self._attr_extra_state_attributes["items"] = pantry_items
            self._attr_available = True
        except Exception as e:
            _LOGGER.error("Error updating Pantry Summary sensor: %s", e)
            self._attr_available = False
            self._attr_native_value = None

class MealPlanTodaySensor(SensorEntity):
    """Representation of today's meal plan sensor."""

    def __init__(self, api_client: PlanMyDinnerApiClient, entry: ConfigEntry):
        """Initialize the sensor."""
        self._api_client = api_client
        self._attr_name = "Meal Plan Today"
        self._attr_unique_id = f"{entry.entry_id}_meal_plan_today"
        self._attr_native_value = "No plan"
        self._attr_extra_state_attributes = {}

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            # For MVP, assuming fixed profiles A and B, and current date
            # In V1, this would fetch the specific day's plan from StructuredMealPlan
            today_date = date.today().isoformat()
            weekly_plan = await self._api_client.generate_weekly_plan(
                "persona_a", "persona_b", today_date # These should be dynamic in V1
            )
            
            # Simple representation for MVP
            if weekly_plan:
                # Find today's plan
                today_entry = next((day for day in weekly_plan if day.get("date") == today_date), None)
                if today_entry and today_entry.get("meals"):
                    self._attr_native_value = "Planned"
                    self._attr_extra_state_attributes["meals"] = today_entry["meals"]
                else:
                    self._attr_native_value = "No plan"
                    self._attr_extra_state_attributes = {}
            else:
                self._attr_native_value = "No plan"
                self._attr_extra_state_attributes = {}

            self._attr_available = True
        except Exception as e:
            _LOGGER.error("Error updating Meal Plan Today sensor: %s", e)
            self._attr_available = False
            self._attr_native_value = None

class MealPlanWeekSensor(SensorEntity):
    """Representation of the weekly meal plan sensor."""

    def __init__(self, api_client: PlanMyDinnerApiClient, entry: ConfigEntry):
        """Initialize the sensor."""
        self._api_client = api_client
        self._attr_name = "Meal Plan Week"
        self._attr_unique_id = f"{entry.entry_id}_meal_plan_week"
        self._attr_native_value = "No plan"
        self._attr_extra_state_attributes = {}

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            # For MVP, assuming fixed profiles A and B, and current date
            # In V1, this would fetch the full week's plan from StructuredMealPlan
            current_date = date.today().isoformat()
            weekly_plan = await self._api_client.generate_weekly_plan(
                "persona_a", "persona_b", current_date # These should be dynamic in V1
            )

            if weekly_plan:
                self._attr_native_value = "Planned"
                self._attr_extra_state_attributes["weekly_plan"] = weekly_plan
            else:
                self._attr_native_value = "No plan"
                self._attr_extra_state_attributes = {}

            self._attr_available = True
        except Exception as e:
            _LOGGER.error("Error updating Meal Plan Week sensor: %s", e)
            self._attr_available = False
            self._attr_native_value = None

class ShoppingListAggregatedSensor(SensorEntity):
    """Representation of the aggregated shopping list sensor."""

    def __init__(self, api_client: PlanMyDinnerApiClient, entry: ConfigEntry):
        """Initialize the sensor."""
        self._api_client = api_client
        self._attr_name = "Shopping List Aggregated"
        self._attr_unique_id = f"{entry.entry_id}_shopping_list_aggregated"
        self._attr_native_value = "Empty"
        self._attr_extra_state_attributes = {}

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            # For MVP, this is a placeholder. Shopping list generation is V1+
            self._attr_native_value = "Generated"
            self._attr_extra_state_attributes["items"] = [
                {"name": "Placeholder Item 1", "quantity": 1, "unit": "kg"},
                {"name": "Placeholder Item 2", "quantity": 2, "unit": "units"},
            ]
            self._attr_available = True
        except Exception as e:
            _LOGGER.error("Error updating Shopping List Aggregated sensor: %s", e)
            self._attr_available = False
            self._attr_native_value = None


