"""API Client for the Plan My Dinner Add-on."""
import aiohttp
import logging
from typing import Any, Dict, Optional

_LOGGER = logging.getLogger(__name__)

class PlanMyDinnerApiClient:
    """Client to handle communication with the Plan My Dinner add-on."""

    def __init__(self, host: str, port: int, session: aiohttp.ClientSession):
        """Initialize the API client."""
        self.base_url = f"http://{host}:{port}"
        self.session = session

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """Make a request to the add-on API."""
        url = f"{self.base_url}{path}"
        try:
            async with self.session.request(method, url, **kwargs) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            _LOGGER.error("API request error: %s", err)
            raise

    async def add_pantry_item(self, name: str, quantity: float, unit: str) -> Dict[str, Any]:
        """Add an item to the pantry."""
        payload = {"name": name, "quantity": quantity, "unit": unit}
        return await self._request("POST", "/pantry/items", json=payload)
    
    async def get_pantry_items(self) -> Dict[str, Any]:
        """Get all items from the pantry."""
        return await self._request("GET", "/pantry/items")

    async def mark_consumed_planned(self, profile_id: str, meal_date: str, meal_type: str, recipe_id: str) -> Dict[str, Any]:
        """Mark a planned meal as consumed."""
        path = f"/consumed-entries/mark-planned?profile_id={profile_id}&meal_date={meal_date}&meal_type={meal_type}&recipe_id={recipe_id}"
        return await self._request("POST", path)

    async def mark_consumed_override(self, profile_id: str, meal_date: str, meal_type: str, override_details: Dict) -> Dict[str, Any]:
        """Mark a meal as consumed with override details."""
        path = f"/consumed-entries/override?profile_id={profile_id}&meal_date={meal_date}&meal_type={meal_type}"
        return await self._request("POST", path, json=override_details)

    async def generate_weekly_plan(self, profile_id_A: str, profile_id_B: str, current_date: str) -> Dict[str, Any]:
        """Generate a full weekly meal plan."""
        path = f"/planner/generate-week?profile_id_A={profile_id_A}&profile_id_B={profile_id_B}&current_date={current_date}"
        return await self._request("POST", path)

    async def suggest_recipes_for_meal(
        self,
        profile_id_A: str,
        profile_id_B: str,
        meal_type: str,
        current_date: str,
        mood: Optional[str] = None,
        cleanup: Optional[str] = None,
        max_time_minutes: Optional[int] = None
    ) -> Dict[str, Any]:
        """Suggest alternative recipes for a specific meal."""
        path = f"/planner/change-recipe?profile_id_A={profile_id_A}&profile_id_B={profile_id_B}&meal_type={meal_type}&current_date={current_date}"
        if mood:
            path += f"&mood={mood}"
        if cleanup:
            path += f"&cleanup={cleanup}"
        if max_time_minutes is not None:
            path += f"&max_time_minutes={max_time_minutes}"
        return await self._request("POST", path)

    async def apply_recipe_to_plan(
        self,
        profile_id_A: str,
        profile_id_B: str,
        meal_type: str,
        current_date: str,
        recipe_id: str
    ) -> Dict[str, Any]:
        """Apply a chosen recipe to the meal plan."""
        path = f"/planner/apply-recipe-option?profile_id_A={profile_id_A}&profile_id_B={profile_id_B}&meal_type={meal_type}&current_date={current_date}&recipe_id={recipe_id}"
        return await self._request("POST", path)


