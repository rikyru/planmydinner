import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.planmydinner.api_client import PlanMyDinnerApiClient

@pytest.mark.asyncio
async def test_api_client_url_construction():
    """Test that the API client constructs URLs correctly with current_date."""

    async def _request_mock(*args, **kwargs):
        async def __aenter__(*a, **kw):
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"status": "ok"}
            return mock_response
        async def __aexit__(*a, **kw):
            pass
        
        m = MagicMock()
        m.__aenter__ = AsyncMock(side_effect=__aenter__)
        m.__aexit__ = AsyncMock(side_effect=__aexit__)
        return m

    mock_session = AsyncMock()
    mock_session.request = AsyncMock(side_effect=_request_mock)

    api_client = PlanMyDinnerApiClient("localhost", 8000, mock_session)

    # Test generate_weekly_plan
    await api_client.generate_weekly_plan("a", "b", "2026-02-24")
    mock_session.request.assert_called_with(
        "POST", "http://localhost:8000/planner/generate-week?profile_id_A=a&profile_id_B=b&current_date=2026-02-24"
    )

    # Test suggest_recipes_for_meal
    await api_client.suggest_recipes_for_meal("a", "b", "cena", "2026-02-24", max_time_minutes=30)
    mock_session.request.assert_called_with(
        "POST", "http://localhost:8000/planner/change-recipe?profile_id_A=a&profile_id_B=b&meal_type=cena&current_date=2026-02-24&max_time_minutes=30"
    )

    # Test apply_recipe_to_plan
    await api_client.apply_recipe_to_plan("a", "b", "cena", "2026-02-24", "rec1")
    mock_session.request.assert_called_with(
        "POST", "http://localhost:8000/planner/apply-recipe-option?profile_id_A=a&profile_id_B=b&meal_type=cena&current_date=2026-02-24&recipe_id=rec1"
    )
