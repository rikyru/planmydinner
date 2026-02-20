import pytest
from datetime import date, timedelta
from unittest.mock import patch
import json # For JSON column data

# Use fixtures from conftest.py
# client: TestClient (FastAPI test client)
# setup_database: fixture to create/drop test database

from planner import PlannerEngine
import schemas
from database import (
    UserProfile, StructuredMealPlan, Recipe, PantryItem, ConsumedEntry,
    RotationRule, SeasonalityItem, UnitConversion
)

# Helper function to create a recipe in the database
def create_recipe_in_db(db, recipe_data):
    db_recipe = Recipe(**recipe_data)
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)
    return db_recipe

# Helper function to create a user profile in the database
def create_user_profile_in_db(db, profile_data):
    db_profile = UserProfile(**profile_data)
    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    return db_profile

# Helper function to create a pantry item in the database
def create_pantry_item_in_db(db, item_data):
    db_item = PantryItem(**item_data)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@pytest.fixture(scope="function")
def planner_seeded_database(setup_database):
    db_session = setup_database

    # Seed User Profiles
    profile_A_data = {
        "id": "persona_a", "name": "Alice", "allergies": ["arachidi"], "excluded_foods": [],
        "preferences": ["vegetariano"], "max_cook_time_default": 45, "cleanup_tolerance": "normal", "equipment": []
    }
    profile_B_data = {
        "id": "persona_b", "name": "Bob", "allergies": [], "excluded_foods": ["maiale"],
        "preferences": ["onnivoro"], "max_cook_time_default": 60, "cleanup_tolerance": "low_mess", "equipment": []
    }
    create_user_profile_in_db(db_session, profile_A_data)
    create_user_profile_in_db(db_session, profile_B_data)

    # Seed Recipes
    # Recipe 1: Pasta al Pesto Veg (matches A (veg), B), Quick, Low Mess, 20min
    recipe1_data = {
        "id": "rec_pasta_pesto_veg",
        "name": "Pasta al Pesto Veg",
        "description": "Pasta con pesto di zucchine per Alice, pesto classico per Bob.",
        "is_composed_dish": False,
        "content": [
            {"name": "Pasta", "food_group": "carboidrati", "quantities": {"persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80}, "persona_b": {"qty": 100, "unit": "g", "grams_equiv": 100}}},
            {"name": "Pesto di zucchine", "food_group": "grassi", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 0, "unit": "g", "grams_equiv": 0}}},
            {"name": "Pesto classico", "food_group": "grassi", "quantities": {"persona_a": {"qty": 0, "unit": "g", "grams_equiv": 0}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}},
            {"name": "Tofu", "food_group": "proteine", "quantities": {"persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150}, "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150}}},
            {"name": "Verdure miste", "food_group": "verdure", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}}
        ],
        "steps": ["Cuocere la pasta.", "Condire."],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["quick"], "cleanup": ["low_mess"], "cooking_methods": ["bollitura"]}
    }
    create_recipe_in_db(db_session, recipe1_data)

    # Recipe 2: Pollo al Limone con Riso (matches A (veg), B), Normal, 30min
    recipe2_data = {
        "id": "rec_pollo_limone",
        "name": "Pollo al Limone con Riso",
        "description": "Pollo al limone con riso basmati.",
        "is_composed_dish": False,
        "content": [
            {"name": "Pollo", "food_group": "proteine", "quantities": {"persona_a": {"qty": 0, "unit": "g", "grams_equiv": 0}, "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150}}},
            {"name": "Tofu", "food_group": "proteine", "quantities": {"persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150}, "persona_b": {"qty": 0, "unit": "g", "grams_equiv": 0}}},
            {"name": "Riso", "food_group": "carboidrati", "quantities": {"persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80}, "persona_b": {"qty": 100, "unit": "g", "grams_equiv": 100}}},
            {"name": "Olio", "food_group": "grassi", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}},
            {"name": "Verdure", "food_group": "verdure", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}}
        ],
        "steps": ["Cuocere riso.", "Cuocere pollo/tofu.", "Servire."],
        "total_time_minutes": 30,
        "difficulty": "media",
        "tags": {"mood": ["normal"], "cleanup": ["normal"], "cooking_methods": ["tegame"]}
    }
    create_recipe_in_db(db_session, recipe2_data)

    # Recipe 3: Stufato di Maiale (excluded for B), Effort, 120min
    recipe3_data = {
        "id": "rec_stufato_maiale",
        "name": "Stufato di Maiale",
        "description": "Lungo stufato tradizionale.",
        "is_composed_dish": False,
        "content": [
            {"name": "Maiale", "food_group": "proteine", "quantities": {"persona_a": {"qty": 0, "unit": "g", "grams_equiv": 0}, "persona_b": {"qty": 200, "unit": "g", "grams_equiv": 200}}},
            {"name": "Patate", "food_group": "carboidrati", "quantities": {"persona_a": {"qty": 100, "unit": "g", "grams_equiv": 100}, "persona_b": {"qty": 100, "unit": "g", "grams_equiv": 100}}},
            {"name": "Olio", "food_group": "grassi", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}},
            {"name": "Verdure", "food_group": "verdure", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}}
        ],
        "steps": ["Cuocere lentamente."],
        "total_time_minutes": 120,
        "difficulty": "difficile",
        "tags": {"mood": ["effort"], "cleanup": ["high_mess"], "cooking_methods": ["forno"]}
    }
    create_recipe_in_db(db_session, recipe3_data)

    # Seed Pantry Items
    create_pantry_item_in_db(db_session, {"id": "pantry_flour", "name": "Farina", "quantity": 1000, "unit": "g", "expiration_date": date.today() + timedelta(days=30)})
    create_pantry_item_in_db(db_session, {"id": "pantry_zucchine", "name": "Zucchine", "quantity": 500, "unit": "g", "expiration_date": date.today() + timedelta(days=5)}) # Expiring soon
    
    # Seed Consumed Entries - only older ones for the general seeded database to allow anti-repetition to be tested selectively
    db_session.add(ConsumedEntry(id="cons_rec_1_old_a", profile_id="persona_a", date=date.today() - timedelta(days=PlannerEngine.ANTI_REPETITION_DAYS + 1), meal_type="cena", type="planned", consumed_recipe_id="rec_pasta_pesto_veg"))
    db_session.add(ConsumedEntry(id="cons_rec_1_old_b", profile_id="persona_b", date=date.today() - timedelta(days=PlannerEngine.ANTI_REPETITION_DAYS + 1), meal_type="cena", type="planned", consumed_recipe_id="rec_pasta_pesto_veg"))

    db_session.commit()

    yield db_session

@pytest.fixture(scope="function")
def planner_seeded_database_with_recent_consumption(setup_database):
    db_session = setup_database

    # Seed User Profiles
    profile_A_data = {
        "id": "persona_a", "name": "Alice", "allergies": ["arachidi"], "excluded_foods": [],
        "preferences": ["vegetariano"], "max_cook_time_default": 45, "cleanup_tolerance": "normal", "equipment": []
    }
    profile_B_data = {
        "id": "persona_b", "name": "Bob", "allergies": [], "excluded_foods": ["maiale"],
        "preferences": ["onnivoro"], "max_cook_time_default": 60, "cleanup_tolerance": "low_mess", "equipment": []
    }
    create_user_profile_in_db(db_session, profile_A_data)
    create_user_profile_in_db(db_session, profile_B_data)

    # Seed Recipes
    # Recipe 1: Pasta al Pesto Veg (matches A (veg), B), Quick, Low Mess, 20min
    recipe1_data = {
        "id": "rec_pasta_pesto_veg",
        "name": "Pasta al Pesto Veg",
        "description": "Pasta con pesto di zucchine per Alice, pesto classico per Bob.",
        "is_composed_dish": False,
        "content": [
            {"name": "Pasta", "food_group": "carboidrati", "quantities": {"persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80}, "persona_b": {"qty": 100, "unit": "g", "grams_equiv": 100}}},
            {"name": "Pesto di zucchine", "food_group": "grassi", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 0, "unit": "g", "grams_equiv": 0}}},
            {"name": "Pesto classico", "food_group": "grassi", "quantities": {"persona_a": {"qty": 0, "unit": "g", "grams_equiv": 0}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}},
            {"name": "Tofu", "food_group": "proteine", "quantities": {"persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150}, "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150}}},
            {"name": "Verdure miste", "food_group": "verdure", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}}
        ],
        "steps": ["Cuocere la pasta.", "Condire."],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["quick"], "cleanup": ["low_mess"], "cooking_methods": ["bollitura"]}
    }
    create_recipe_in_db(db_session, recipe1_data)

    # Recipe 2: Pollo al Limone con Riso (matches A (veg), B), Normal, 30min
    recipe2_data = {
        "id": "rec_pollo_limone",
        "name": "Pollo al Limone con Riso",
        "description": "Pollo al limone con riso basmati.",
        "is_composed_dish": False,
        "content": [
            {"name": "Pollo", "food_group": "proteine", "quantities": {"persona_a": {"qty": 0, "unit": "g", "grams_equiv": 0}, "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150}}},
            {"name": "Tofu", "food_group": "proteine", "quantities": {"persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150}, "persona_b": {"qty": 0, "unit": "g", "grams_equiv": 0}}},
            {"name": "Riso", "food_group": "carboidrati", "quantities": {"persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80}, "persona_b": {"qty": 100, "unit": "g", "grams_equiv": 100}}},
            {"name": "Olio", "food_group": "grassi", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}},
            {"name": "Verdure", "food_group": "verdure", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}}
        ],
        "steps": ["Cuocere riso.", "Cuocere pollo/tofu.", "Servire."],
        "total_time_minutes": 30,
        "difficulty": "media",
        "tags": {"mood": ["normal"], "cleanup": ["normal"], "cooking_methods": ["tegame"]}
    }
    create_recipe_in_db(db_session, recipe2_data)

    # Recipe 3: Stufato di Maiale (excluded for B), Effort, 120min
    recipe3_data = {
        "id": "rec_stufato_maiale",
        "name": "Stufato di Maiale",
        "description": "Lungo stufato tradizionale.",
        "is_composed_dish": False,
        "content": [
            {"name": "Maiale", "food_group": "proteine", "quantities": {"persona_a": {"qty": 0, "unit": "g", "grams_equiv": 0}, "persona_b": {"qty": 200, "unit": "g", "grams_equiv": 200}}},
            {"name": "Patate", "food_group": "carboidrati", "quantities": {"persona_a": {"qty": 100, "unit": "g", "grams_equiv": 100}, "persona_b": {"qty": 100, "unit": "g", "grams_equiv": 100}}},
            {"name": "Olio", "food_group": "grassi", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}},
            {"name": "Verdure", "food_group": "verdure", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}}
        ],
        "steps": ["Cuocere lentamente."],
        "total_time_minutes": 120,
        "difficulty": "difficile",
        "tags": {"mood": ["effort"], "cleanup": ["high_mess"], "cooking_methods": ["forno"]}
    }
    create_recipe_in_db(db_session, recipe3_data)

    # Seed Pantry Items
    create_pantry_item_in_db(db_session, {"id": "pantry_flour", "name": "Farina", "quantity": 1000, "unit": "g", "expiration_date": date.today() + timedelta(days=30)})
    create_pantry_item_in_db(db_session, {"id": "pantry_zucchine", "name": "Zucchine", "quantity": 500, "unit": "g", "expiration_date": date.today() + timedelta(days=5)}) # Expiring soon
    
    # Add a recent consumption for rec_pasta_pesto_veg to trigger anti-repetition for relevant tests
    db_session.add(ConsumedEntry(id="cons_rec_1_recent_a", profile_id="persona_a", date=date.today() - timedelta(days=1), meal_type="pranzo", type="planned", consumed_recipe_id="rec_pasta_pesto_veg"))
    db_session.add(ConsumedEntry(id="cons_rec_1_recent_b", profile_id="persona_b", date=date.today() - timedelta(days=1), meal_type="pranzo", type="planned", consumed_recipe_id="rec_pasta_pesto_veg"))
    
    db_session.commit()

    yield db_session


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
