"""Sensor platform for Plan My Dinner."""
from __future__ import annotations
import logging
from datetime import date

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PlanMyDinnerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: PlanMyDinnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        WebUISensor(entry),
        MealPlanTodaySensor(coordinator, entry),
        MealPlanWeekSensor(coordinator, entry),
        ShoppingListSensor(coordinator, entry),
        PantrySensor(coordinator, entry),
        MealsToLogSensor(coordinator, entry),
    ])


class WebUISensor(SensorEntity):
    """Static sensor exposing the Web UI URL."""

    def __init__(self, entry: ConfigEntry) -> None:
        host = entry.data["host"]
        port = entry.data["port"]
        self._attr_name = "Plan My Dinner Web UI"
        self._attr_unique_id = f"{entry.entry_id}_web_ui"
        self._attr_native_value = f"http://{host}:{port}"
        self._attr_icon = "mdi:web"


class _PlanMyDinnerSensor(CoordinatorEntity, SensorEntity):
    """Base class for coordinator-backed sensors."""

    def __init__(self, coordinator: PlanMyDinnerCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._key = key

    @property
    def _data(self):
        return (self.coordinator.data or {}).get(self._key)


class MealsToLogSensor(_PlanMyDinnerSensor):
    """Numero di pasti di oggi non ancora registrati (per notifiche promemoria)."""

    def __init__(self, coordinator: PlanMyDinnerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "today_status")
        self._attr_name = "Plan My Dinner Pasti Da Registrare"
        self._attr_unique_id = f"{entry.entry_id}_meals_to_log"
        self._attr_icon = "mdi:clipboard-alert-outline"

    @property
    def native_value(self) -> int | None:
        data = self._data
        if not data:
            return None
        return data.get("unlogged_count", 0)

    @property
    def extra_state_attributes(self) -> dict:
        data = self._data or {}
        return {
            "date": data.get("date"),
            "unlogged": data.get("unlogged", []),
            "meals": data.get("meals", []),
            "vacation": data.get("vacation", False),
        }


class MealPlanTodaySensor(_PlanMyDinnerSensor):
    """Today's meals (pranzo + cena)."""

    def __init__(self, coordinator: PlanMyDinnerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "today")
        self._attr_name = "Plan My Dinner Today"
        self._attr_unique_id = f"{entry.entry_id}_today"
        self._attr_icon = "mdi:food"

    @property
    def native_value(self) -> str:
        data = self._data
        if not data:
            return "no_plan"
        today_iso = date.today().isoformat()
        daily_plans = data.get("daily_plans", [])
        today_plan = next((d for d in daily_plans if d.get("date") == today_iso), None)
        if not today_plan or not today_plan.get("meals"):
            return "no_plan"
        meal_names = []
        for meal in today_plan["meals"]:
            items = meal.get("items", [])
            if items:
                meal_names.append(items[0].get("item_name", ""))
        return ", ".join(filter(None, meal_names)) or "planned"

    @property
    def extra_state_attributes(self) -> dict:
        data = self._data
        if not data:
            return {}
        today_iso = date.today().isoformat()
        daily_plans = data.get("daily_plans", [])
        today_plan = next((d for d in daily_plans if d.get("date") == today_iso), None)
        if not today_plan:
            return {}
        meals = {}
        for meal in today_plan.get("meals", []):
            meal_type = meal.get("meal_type", "")
            items = [i.get("item_name") for i in meal.get("items", [])]
            meals[meal_type] = items
        return {"meals": meals, "start_date": data.get("start_date")}


class MealPlanWeekSensor(_PlanMyDinnerSensor):
    """Weekly plan summary."""

    def __init__(self, coordinator: PlanMyDinnerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "week")
        self._attr_name = "Plan My Dinner Week"
        self._attr_unique_id = f"{entry.entry_id}_week"
        self._attr_icon = "mdi:calendar-week"
        self._profile_id_A = coordinator.profile_id_A
        self._profile_id_B = coordinator.profile_id_B

    @property
    def native_value(self) -> str:
        data = self._data
        if not data:
            return "no_plan"
        days = len(data) if isinstance(data, list) else len(data.get("daily_plans", []))
        return f"{days}_days" if days else "no_plan"

    @property
    def extra_state_attributes(self) -> dict:
        data = self._data
        if not data:
            return {}
        if isinstance(data, list):
            daily_plans = data
        else:
            daily_plans = data.get("daily_plans", [])
        summary = {}
        for day in daily_plans:
            d = day.get("date", "")
            meal_names = []
            for meal in day.get("meals", []):
                items = meal.get("items", [])
                if items:
                    meal_names.append(f"{meal.get('meal_type')}: {items[0].get('item_name','')}")
            summary[d] = meal_names
        return {
            "days": summary,
            "profile_id_A": self._profile_id_A,
            "profile_id_B": self._profile_id_B,
        }


class ShoppingListSensor(_PlanMyDinnerSensor):
    """Number of items in the shopping list."""

    def __init__(self, coordinator: PlanMyDinnerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "shopping")
        self._attr_name = "Plan My Dinner Shopping"
        self._attr_unique_id = f"{entry.entry_id}_shopping"
        self._attr_icon = "mdi:cart"
        self._attr_native_unit_of_measurement = "items"

    @property
    def native_value(self) -> int | None:
        data = self._data
        if not data:
            return 0
        by_cat = data.get("items_by_category", {})
        return sum(len(v) for v in by_cat.values())

    @property
    def extra_state_attributes(self) -> dict:
        data = self._data
        if not data:
            return {}
        return {"items_by_category": data.get("items_by_category", {})}


class PantrySensor(_PlanMyDinnerSensor):
    """Number of pantry items."""

    def __init__(self, coordinator: PlanMyDinnerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "pantry")
        self._attr_name = "Plan My Dinner Pantry"
        self._attr_unique_id = f"{entry.entry_id}_pantry"
        self._attr_icon = "mdi:fridge"
        self._attr_native_unit_of_measurement = "items"

    @property
    def native_value(self) -> int:
        data = self._data
        return len(data) if data else 0

    @property
    def extra_state_attributes(self) -> dict:
        data = self._data
        if not data:
            return {}
        return {"items": [{"name": i.get("name"), "quantity": i.get("quantity"), "unit": i.get("unit")} for i in data]}
