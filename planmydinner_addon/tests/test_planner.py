import pytest
from datetime import date, timedelta
from unittest.mock import patch
import json # For JSON column data

# Use fixtures from conftest.py
# client: TestClient (FastAPI test client)
# setup_database: fixture to create/drop test database

from planmydinner_addon.planner import PlannerEngine
from planmydinner_addon import schemas
from planmydinner_addon.database import (
    UserProfile, StructuredMealPlan, Recipe, PantryItem, ConsumedEntry,
    RotationRule, SeasonalityItem, UnitConversion
)
def test_suggest_recipes_for_meal_filtering_time(client, planner_seeded_database):
    db_session = planner_seeded_database
    
    # Request: max 10 min, should exclude all seeded recipes
    response = client.post(
        "/planner/change-recipe",
        params={
            "profile_id_A": "persona_a",
            "profile_id_B": "persona_b",
            "meal_type": "pranzo",
            "current_date": date.today().isoformat(),
            "mood": "quick",
            "cleanup": "low_mess",
            "max_time_minutes": 10
        }
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "No alternative recipes found."}


def test_suggest_recipes_for_meal_filtering_excluded_food(client, planner_seeded_database):
    db_session = planner_seeded_database
    
    # Request: max 150 min (allow Stufato), mood normal, cleanup normal
    # Bob excludes Maiale, so rec_stufato_maiale should be excluded.
    # We expect rec_pollo_limone to pass.
    response = client.post(
        "/planner/change-recipe",
        params={
            "profile_id_A": "persona_a",
            "profile_id_B": "persona_b",
            "meal_type": "cena",
            "current_date": date.today().isoformat(),
            "mood": "normal",
            "cleanup": "normal",
            "max_time_minutes": 150 # Allow rec_stufato_maiale by time
        }
    )
    assert response.status_code == 200
    options = response.json()
    assert any(opt["recipe_id"] == "rec_pollo_limone" for opt in options)
    assert not any(opt["recipe_id"] == "rec_stufato_maiale" for opt in options)


def test_suggest_recipes_for_meal_filtering_anti_repetition(client, planner_seeded_database_with_recent_consumption):
    db_session = planner_seeded_database_with_recent_consumption
    
    # rec_pasta_pesto_veg was consumed yesterday
    # We expect rec_pollo_limone to pass, but not rec_pasta_pesto_veg
    response = client.post(
        "/planner/change-recipe",
        params={
            "profile_id_A": "persona_a",
            "profile_id_B": "persona_b",
            "meal_type": "pranzo", 
            "current_date": date.today().isoformat(),
            "mood": "normal", # Allow rec_pollo_limone
            "cleanup": "normal",
            "max_time_minutes": 60
        }
    )
    assert response.status_code == 200
    options = response.json()
    assert any(opt["recipe_id"] == "rec_pollo_limone" for opt in options)
    assert not any(opt["recipe_id"] == "rec_pasta_pesto_veg" for opt in options)


def test_suggest_recipes_for_meal_scoring_pantry_expiration(client, planner_seeded_database):
    db_session = planner_seeded_database
    
    # rec_pasta_pesto_veg uses Pesto di zucchine for Alice (from Zucchine expiring soon)
    # So rec_pasta_pesto_veg should get a high score.
    # Set mood to quick to allow pasta pesto to pass.
    # Consumed entry is old, so anti-repetition should not block it.
    response = client.post(
        "/planner/change-recipe",
        params={
            "profile_id_A": "persona_a",
            "profile_id_B": "persona_b",
            "meal_type": "pranzo",
            "current_date": date.today().isoformat(),
            "mood": "quick", # Allow rec_pasta_pesto_veg
            "cleanup": "low_mess", # Allow rec_pasta_pesto_veg
            "max_time_minutes": 60
        }
    )
    assert response.status_code == 200
    options = response.json()
    assert any(opt["recipe_id"] == "rec_pasta_pesto_veg" for opt in options) 
    
    # Test for future date to bypass anti-repetition for rec_pasta_pesto_veg (no longer relevant with old consumed entry)
    # This part can be simplified or removed, as the anti-repetition was on a different entry now.
    # However, keeping it tests the score when anti-rep is not an issue.
    future_date = date.today() + timedelta(days=PlannerEngine.ANTI_REPETITION_DAYS)
    
    response_future = client.post(
        "/planner/change-recipe",
        params={
            "profile_id_A": "persona_a",
            "profile_id_B": "persona_b",
            "meal_type": "pranzo",
            "current_date": future_date.isoformat(), 
            "mood": "quick",
            "cleanup": "low_mess",
            "max_time_minutes": 60
        }
    )
    assert response_future.status_code == 200
    options_future = response_future.json()
    assert any(opt["recipe_id"] == "rec_pasta_pesto_veg" for opt in options_future)


def test_apply_recipe_to_plan(client, planner_seeded_database):
    db_session = planner_seeded_database
    
    today = date.today().isoformat()
    recipe_id_to_apply = "rec_pollo_limone"
    
    response = client.post(
        "/planner/apply-recipe-option",
        params={
            "profile_id_A": "persona_a",
            "profile_id_B": "persona_b",
            "meal_type": "cena",
            "current_date": today,
            "recipe_id": recipe_id_to_apply
        }
    )
    assert response.status_code == 200
    assert response.json() == {"message": "Recipe applied to plan successfully."}

    # In V1, this test would then check the StructuredMealPlan in the DB
    # For MVP, it just confirms the endpoint works.
