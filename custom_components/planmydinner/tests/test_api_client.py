import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from custom_components.planmydinner.api_client import PlanMyDinnerApiClient

@pytest.mark.asyncio
async def test_api_client_url_construction():
    """Test that the API client constructs URLs correctly with current_date."""

    # Mock the _request method of the API client directly
    with patch.object(PlanMyDinnerApiClient, '_request', new_callable=AsyncMock) as mock_request_method:
        mock_request_method.return_value = {"status": "ok"} # Configure return value for the mock

        api_client = PlanMyDinnerApiClient("localhost", 8000, MagicMock()) # session will be mocked in _request
    
        # Test generate_weekly_plan
        await api_client.generate_weekly_plan("a", "b", "2026-02-24")
        mock_request_method.assert_any_call(
            "POST", "/planner/generate-week?profile_id_A=a&profile_id_B=b&current_date=2026-02-24"
        )

        # Test suggest_recipes_for_meal
        await api_client.suggest_recipes_for_meal("a", "b", "cena", "2026-02-24", max_time_minutes=30)
        mock_request_method.assert_any_call(
            "POST", "/planner/change-recipe?profile_id_A=a&profile_id_B=b&meal_type=cena&current_date=2026-02-24&max_time_minutes=30"
        )

        # Test apply_recipe_to_plan
        await api_client.apply_recipe_to_plan("a", "b", "cena", "2026-02-24", "rec1")
        mock_request_method.assert_any_call(
            "POST", "/planner/apply-recipe-option?profile_id_A=a&profile_id_B=b&meal_type=cena&current_date=2026-02-24&recipe_id=rec1"
        )
