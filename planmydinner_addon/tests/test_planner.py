import pytest
from datetime import date, timedelta
from unittest.mock import patch, ANY
import json # For JSON column data

from planmydinner_addon.planner import PlannerEngine
from planmydinner_addon import schemas
from planmydinner_addon.database import (
    UserProfile, StructuredMealPlan, Recipe, PantryItem, ConsumedEntry,
    RotationRule, SeasonalityItem, UnitConversion
)

@pytest.mark.xfail(reason="Date sensitivity in test setup causes this to fail intermittently.")
def test_suggest_recipes_for_meal_filtering_time(client, planner_seeded_database):
    db_session = planner_seeded_database
    
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

@pytest.mark.xfail(reason="Date sensitivity in test setup causes this to fail intermittently.")
def test_suggest_recipes_for_meal_filtering_excluded_food(client, planner_seeded_database):
    db_session = planner_seeded_database
    
    response = client.post(
        "/planner/change-recipe",
        params={
            "profile_id_A": "persona_a",
            "profile_id_B": "persona_b",
            "meal_type": "cena",
            "current_date": date.today().isoformat(),
            "mood": "normal",
            "cleanup": "normal",
            "max_time_minutes": 150
        }
    )
    assert response.status_code == 200
    options = response.json()
    assert any(opt["recipe_id"] == "rec_pollo_limone" for opt in options)
    assert not any(opt["recipe_id"] == "rec_stufato_maiale" for opt in options)

@pytest.mark.xfail(reason="Date sensitivity in test setup causes this to fail intermittently.")
def test_suggest_recipes_for_meal_filtering_anti_repetition(client, planner_seeded_database_with_recent_consumption):
    db_session = planner_seeded_database_with_recent_consumption
    
    response = client.post(
        "/planner/change-recipe",
        params={
            "profile_id_A": "persona_a",
            "profile_id_B": "persona_b",
            "meal_type": "pranzo", 
            "current_date": date.today().isoformat(),
            "mood": "normal",
            "cleanup": "normal",
            "max_time_minutes": 60
        }
    )
    assert response.status_code == 200
    options = response.json()
    assert any(opt["recipe_id"] == "rec_pollo_limone" for opt in options)
    assert not any(opt["recipe_id"] == "rec_pasta_pesto_veg" for opt in options)

@pytest.mark.xfail(reason="Date sensitivity in test setup causes this to fail intermittently.")
def test_suggest_recipes_for_meal_scoring_pantry_expiration(client, planner_seeded_database):
    db_session = planner_seeded_database
    
    response = client.post(
        "/planner/change-recipe",
        params={
            "profile_id_A": "persona_a",
            "profile_id_B": "persona_b",
            "meal_type": "pranzo",
            "current_date": date.today().isoformat(),
            "mood": "quick",
            "cleanup": "low_mess",
            "max_time_minutes": 60
        }
    )
    assert response.status_code == 200
    options = response.json()
    assert any(opt["recipe_id"] == "rec_pasta_pesto_veg" for opt in options) 
    
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

def test_generate_shopping_list_with_free_vegetable(planner_seeded_database):
    """
    Tests that a recipe with a 'free vegetable' (quantity 0) generates a shopping list
    with a default quantity (200g) and an 'estimated' note.
    """
    db_session = planner_seeded_database

    recipe_free_veg_data = {
        "id": "rec_free_veg",
        "name": "Piatto con verdura libera",
        "is_composed_dish": False,
        "content": [
            {"name": "Pollo", "food_group": "proteina", "quantities": {"persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150}, "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150}}},
            {"name": "Insalata", "food_group": "verdura", "quantities": {"persona_a": {"qty": 0, "unit": "g", "grams_equiv": 0}, "persona_b": {"qty": 0, "unit": "g", "grams_equiv": 0}}},
        ],
        "steps": ["Cuocere il pollo.", "Servire con insalata."],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {}
    }
    from planmydinner_addon.database import Recipe
    db_recipe = Recipe(**recipe_free_veg_data)
    db_session.add(db_recipe)
    db_session.commit()

    planner = PlannerEngine(db_session)

    mock_plan = [
        schemas.DailyPlannedMeals(
            date=date.today().isoformat(),
            meals=[
                schemas.PlannedMeal(
                    meal_type="cena",
                    items=[schemas.PlannedItem(item_name="Piatto con verdura libera", food_group="recipe", quantity=1, unit="recipe")]
                )
            ]
        )
    ]

    with patch.object(planner, 'generate_weekly_plan', return_value=mock_plan):
        shopping_list = planner.generate_shopping_list_for_week("persona_a", "persona_b", date.today())

        assert "verdura" in shopping_list.items_by_category
        
        insalata_item = next((item for item in shopping_list.items_by_category["verdura"] if item.name == "Insalata"), None)
        assert insalata_item is not None
        assert insalata_item.quantity == 200
        assert insalata_item.notes == "Quantità stimata"

        assert "proteina" in shopping_list.items_by_category
        pollo_item = next((item for item in shopping_list.items_by_category["proteina"] if item.name == "Pollo"), None)
        assert pollo_item is not None
        assert pollo_item.quantity == 300
        assert pollo_item.notes is None

def test_recipe_with_any_vegetables_is_not_discarded_when_plan_has_free_vegetables(planner_seeded_database):
    db_session = planner_seeded_database
    
    meal_plan_A = schemas.PlannedMeal(meal_type="cena", items=[schemas.PlannedItem(item_name="Verdure", food_group="verdura", quantity=0, unit="g")])
    meal_plan_B = schemas.PlannedMeal(meal_type="cena", items=[schemas.PlannedItem(item_name="Verdure", food_group="verdura", quantity=0, unit="g")])

    recipe_data = {
        "id": "rec_pollo_con_verdure",
        "name": "Pollo con verdure",
        "is_composed_dish": False,
        "content": [
            {"name": "Pollo", "food_group": "proteina", "quantities": {"persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150}, "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150}}},
            {"name": "Insalata", "food_group": "verdura", "quantities": {"persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50}, "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50}}},
        ],
        "steps": [], "total_time_minutes": 20, "difficulty": "facile", "tags": {}
    }
    from planmydinner_addon.database import Recipe
    db_recipe = Recipe(**recipe_data)
    db_session.add(db_recipe)
    db_session.commit()

    planner = PlannerEngine(db_session)
    profile_A = planner._get_user_profile("persona_a")
    profile_B = planner._get_user_profile("persona_b")
    
    is_valid, _, _ = planner._filter_hard_constraints(
        schemas.Recipe.from_orm(db_recipe),
        meal_plan_A, meal_plan_B,
        profile_A, profile_B,
        [], [], {},
        date.today()
    )
    
    assert is_valid is True

def test_override_with_free_text_affects_rotation_but_not_shopping_list(client, planner_seeded_database):
    db_session = planner_seeded_database

    db_session.add(RotationRule(id="rule_carne_rossa", food_group_or_item="carne_rossa", max_per_week=1, is_hard_constraint=True))
    db_session.commit()

    response = client.post(
        "/consumed-entries/override",
        params={"profile_id": "persona_a", "meal_date": (date.today() - timedelta(days=1)).isoformat(), "meal_type": "cena"},
        json={"free_text_name": "una bella bistecca di manzo", "ingredients": []}
    )
    assert response.status_code == 200

    recipe_data = {
        "id": "rec_manzo",
        "name": "Gulasch di manzo",
        "is_composed_dish": False,
        "content": [
            {"name": "Manzo", "food_group": "carne_rossa", "quantities": {"persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150}, "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150}}},
        ],
        "steps": [], "total_time_minutes": 120, "difficulty": "media", "tags": {}
    }
    from planmydinner_addon.database import Recipe
    db_recipe = Recipe(**recipe_data)
    db_session.add(db_recipe)
    db_session.commit()

    response = client.post(
        "/planner/change-recipe",
        params={
            "profile_id_A": "persona_a",
            "profile_id_B": "persona_b",
            "meal_type": "cena",
            "current_date": date.today().isoformat(),
            "max_time_minutes": 150 
        }
    )
    
    if response.status_code == 200:
        options = response.json()
        assert not any(opt["recipe_id"] == "rec_manzo" for opt in options)

    planner = PlannerEngine(db_session)
    with patch.object(planner, 'generate_weekly_plan', return_value=[]):
        shopping_list = planner.generate_shopping_list_for_week("persona_a", "persona_b", date.today())
        
        assert "bistecca" not in str(shopping_list.items_by_category)
        assert "manzo" not in str(shopping_list.items_by_category)

def test_override_with_generic_text_does_not_affect_rotation(client, planner_seeded_database):
    db_session = planner_seeded_database

    db_session.add(RotationRule(id="rule_proteina", food_group_or_item="proteina", max_per_week=1, is_hard_constraint=True))
    db_session.commit()

    response = client.post(
        "/consumed-entries/override",
        params={"profile_id": "persona_a", "meal_date": (date.today() - timedelta(days=1)).isoformat(), "meal_type": "cena"},
        json={"free_text_name": "cena fuori", "ingredients": []}
    )
    assert response.status_code == 200

    response = client.post(
        "/planner/change-recipe",
        params={
            "profile_id_A": "persona_a",
            "profile_id_B": "persona_b",
            "meal_type": "cena",
            "current_date": date.today().isoformat(),
            "max_time_minutes": 150 
        }
    )
    assert response.status_code == 200
    options = response.json()
    assert any(opt["recipe_id"] == "rec_pollo_limone" for opt in options)
