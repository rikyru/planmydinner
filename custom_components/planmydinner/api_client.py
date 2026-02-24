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
        _LOGGER.debug("Requesting URL: %s", url)
        try:
            async with self.session.request(method, url, **kwargs) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            _LOGGER.error("API request error: %s", err)
            raise

    async def add_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Add an item to the pantry."""
        return await self._request("POST", "/pantry/items", json=item)

    async def update_item(self, item_id: int, item: Dict[str, Any]) -> Dict[str, Any]:
        """Update an item in the pantry."""
        return await self._request("PUT", f"/pantry/items/{item_id}", json=item)
    
    async def remove_item(self, item_id: int) -> Dict[str, Any]:
        """Remove an item from the pantry."""
        return await self._request("DELETE", f"/pantry/items/{item_id}")
        
    async def get_pantry_items(self) -> Dict[str, Any]:
        """Get all items from the pantry."""
        return await self._request("GET", "/pantry/items")

    async def get_recipes(self) -> Dict[str, Any]:
        """Get all recipes from the catalog."""
        return await self._request("GET", "/recipes")

    async def add_recipe(self, recipe: Dict[str, Any]) -> Dict[str, Any]:
        """Add a recipe to the catalog."""
        return await self._request("POST", "/recipes", json=recipe)
    
    async def update_recipe(self, recipe_id: int, recipe: Dict[str, Any]) -> Dict[str, Any]:
        """Update a recipe in the catalog."""
        return await self._request("PUT", f"/recipes/{recipe_id}", json=recipe)
    
    async def delete_recipe(self, recipe_id: int) -> Dict[str, Any]:
        """Delete a recipe from the catalog."""
        return await self._request("DELETE", f"/recipes/{recipe_id}")

    async def get_shopping_list(self, profile_id_A: str, profile_id_B: str, start_date: str) -> Dict[str, Any]:
        """Get the shopping list for a given week."""
        return await self._request("GET", f"/shopping-list?profile_id_A={profile_id_A}&profile_id_B={profile_id_B}&start_date={start_date}")



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


