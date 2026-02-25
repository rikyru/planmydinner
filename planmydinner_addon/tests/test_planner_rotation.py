import pytest
from unittest.mock import MagicMock, PropertyMock
from planmydinner_addon.planner import PlannerEngine
from planmydinner_addon import schemas
from datetime import date, timedelta

@pytest.fixture
def db_session_mock():
    db = MagicMock()
    # Mock rotation rules query
    db.query.return_value.filter.return_value.all.return_value = [
        schemas.RotationRule(id="1", food_group_or_item="proteine", max_per_week=2, is_hard_constraint=True),
        schemas.RotationRule(id="2", food_group_or_item="pollo", max_per_week=1, is_hard_constraint=True)
    ]
    return db

@pytest.fixture
def planner(db_session_mock):
    return PlannerEngine(db_session_mock)

# --- Mock Data ---
@pytest.fixture
def mock_profiles():
    profile_A = schemas.UserProfile(id="A", name="A", allergies=[], excluded_foods=[])
    profile_B = schemas.UserProfile(id="B", name="B", allergies=[], excluded_foods=[])
    return profile_A, profile_B

@pytest.fixture
def mock_meal_plans():
    plan_A = schemas.PlannedMeal(meal_type="cena", items=[schemas.PlannedItem(item_name="any", food_group="proteine", quantity=150, unit="g")])
    plan_B = schemas.PlannedMeal(meal_type="cena", items=[schemas.PlannedItem(item_name="any", food_group="proteine", quantity=200, unit="g")])
    return plan_A, plan_B

@pytest.fixture
def chicken_recipe():
    return schemas.Recipe(
        id="rec-pollo", name="Pollo alla griglia",
        content=[
            schemas.RecipeIngredient(name="pollo", food_group="proteine", quantities={
                "persona_a": schemas.QuantityPerProfile(qty=150, unit="g", grams_equiv=150),
                "persona_b": schemas.QuantityPerProfile(qty=200, unit="g", grams_equiv=200)
            })
        ],
        total_time_minutes=30, difficulty="facile", is_composed_dish=False, steps=[], tags={}
    )

@pytest.fixture
def fish_recipe():
    return schemas.Recipe(
        id="rec-salmone", name="Salmone al forno",
        content=[
            schemas.RecipeIngredient(name="salmone", food_group="proteine", quantities={
                "persona_a": schemas.QuantityPerProfile(qty=150, unit="g", grams_equiv=150),
                "persona_b": schemas.QuantityPerProfile(qty=200, unit="g", grams_equiv=200)
            })
        ],
        total_time_minutes=30, difficulty="facile", is_composed_dish=False, steps=[], tags={}
    )


def test_rotation_rule_pass(planner, chicken_recipe, mock_profiles, mock_meal_plans):
    """Test that a recipe passes when rotation limits are not exceeded."""
    profile_A, profile_B = mock_profiles
    plan_A, plan_B = mock_meal_plans
    
    # No consumed entries
    consumed_A, consumed_B = [], []
    
    is_valid, _, _ = planner._filter_hard_constraints(
        chicken_recipe, plan_A, plan_B, profile_A, profile_B, consumed_A, consumed_B, {}, date.today()
    )
    assert is_valid is True

def test_rotation_rule_fail_food_group(planner, fish_recipe, mock_profiles, mock_meal_plans):
    """Test that a recipe fails if its food group exceeds the weekly max."""
    profile_A, profile_B = mock_profiles
    plan_A, plan_B = mock_meal_plans
    
    # Already consumed 'proteine' twice this week
    consumed_A = [
        schemas.ConsumedEntry(id="c1", profile_id="A", date=(date.today() - timedelta(days=1)).isoformat(), meal_type="cena", type="override", override_details=schemas.OverrideConsumedDetails(free_text_name="uova")), # 1 proteine
        schemas.ConsumedEntry(id="c2", profile_id="A", date=(date.today() - timedelta(days=2)).isoformat(), meal_type="cena", type="override", override_details=schemas.OverrideConsumedDetails(free_text_name="tofu")) # 2 proteine
    ]
    consumed_B = []

    # Mock DB query for consumed recipes (not needed here as we use free_text)
    planner.db.query.return_value.filter.return_value.first.return_value = None

    is_valid, _, _ = planner._filter_hard_constraints(
        fish_recipe, plan_A, plan_B, profile_A, profile_B, consumed_A, consumed_B, {}, date.today()
    )
    print(f"\n--- DEBUG rotation test ---")
    print(f"Recipe: {fish_recipe.name}, id: {fish_recipe.id}")
    print(f"Consumed A: {consumed_A}")
    print(f"Is valid: {is_valid}")
    assert is_valid is False

def test_rotation_rule_fail_specific_item(planner, chicken_recipe, mock_profiles, mock_meal_plans):
    """Test that a recipe fails if the specific item exceeds the weekly max."""
    profile_A, profile_B = mock_profiles
    plan_A, plan_B = mock_meal_plans

    # Already consumed 'pollo' once this week via a recipe
    consumed_A = [
         schemas.ConsumedEntry(id="c1", profile_id="A", date=(date.today() - timedelta(days=1)).isoformat(), meal_type="cena", type="planned", consumed_recipe_id="rec-pollo-passato")
    ]
    consumed_B = []

    # Mock the DB query inside the filter to return the consumed recipe
    mock_consumed_recipe = schemas.Recipe(
        id="rec-pollo-passato", name="Pollo fritto",
        content=[schemas.RecipeIngredient(name="pollo", food_group="proteine", quantities={})],
        total_time_minutes=30, difficulty="facile", is_composed_dish=False, steps=[], tags={}
    )
    planner.db.query.return_value.filter.return_value.first.return_value = mock_consumed_recipe

    is_valid, _, _ = planner._filter_hard_constraints(
        chicken_recipe, plan_A, plan_B, profile_A, profile_B, consumed_A, consumed_B, {}, date.today()
    )
    assert is_valid is False
