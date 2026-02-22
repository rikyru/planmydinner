import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

# Import app, Base, and get_db from the application package
from planmydinner_addon.main import app
from planmydinner_addon.database import Base, get_db, UnitConversion, PantryItem, Recipe, UserProfile, ConsumedEntry, StructuredMealPlan
from planmydinner_addon.planner import PlannerEngine
from datetime import date, timedelta

# Use an in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Override the get_db dependency to use the test database
def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session")
def client():
    # This fixture yields the FastAPI test client
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def setup_database():
    # Create the tables in the test database
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # Seed UnitConversion for testing
    db.add(UnitConversion(unit="g", grams_equivalent=1.0))
    db.add(UnitConversion(unit="ml", ml_equivalent=1.0))
    db.add(UnitConversion(unit="cucchiaio", grams_equivalent=15.0, ml_equivalent=15.0))
    db.add(UnitConversion(unit="bicchiere", grams_equivalent=200.0, ml_equivalent=200.0))
    db.add(UnitConversion(unit="piatto", grams_equivalent=300.0, ml_equivalent=None)) # Add piatto conversion
    db.add(UnitConversion(unit="porzione", grams_equivalent=150.0, ml_equivalent=None))
    db.add(UnitConversion(unit="rotolo", grams_equivalent=None, ml_equivalent=None)) # For pasta sfoglia example
    db.commit()
    # Debug print for piatto
    committed_piatto_uc = db.query(UnitConversion).filter_by(unit="piatto").first()
    print(f"\n--- DEBUG: UnitConversion for 'piatto' after commit: unit={committed_piatto_uc.unit}, grams_equivalent={committed_piatto_uc.grams_equivalent}, ml_equivalent={committed_piatto_uc.ml_equivalent} ---")

    # Seed some pantry items
    db.add(PantryItem(id="pasta_item", name="Pasta", quantity=500.0, unit="g"))
    db.add(PantryItem(id="pomodoro_item", name="Pomodoro", quantity=400.0, unit="g"))
    db.add(PantryItem(id="sfoglia_item", name="Pasta Sfoglia", quantity=2.0, unit="rotolo"))
    db.add(PantryItem(id="ricotta_item", name="Ricotta", quantity=500.0, unit="g"))
    db.commit()

    # Seed a recipe
    recipe_data = {
        "id": "pasta_pomodoro_recipe",
        "name": "Pasta al Pomodoro",
        "description": "Semplice pasta con sugo di pomodoro.",
        "is_composed_dish": False,
        "content": [
            {"name": "Pasta", "food_group": "carboidrati", "quantities": {"persona_a": {"qty": 100, "unit": "g", "grams_equiv": 100.0}, "persona_b": {"qty": 120, "unit": "g", "grams_equiv": 120.0}}},
            {"name": "Pomodoro", "food_group": "verdure", "quantities": {"persona_a": {"qty": 200, "unit": "g", "grams_equiv": 200.0}, "persona_b": {"qty": 200, "unit": "g", "grams_equiv": 200.0}}}
        ],
        "steps": ["Cuocere la pasta.", "Preparare il sugo.", "Unire."],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["basso"], "cooking_methods": ["bollitura"]}
    }
    db.add(Recipe(**recipe_data))
    db.commit()

    yield db
    db.close()
    # Drop the tables after the test is done
    Base.metadata.drop_all(bind=engine)

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
    create_pantry_item_in_db(db_session, {"id": "pantry_flour", "name": "Farina", "quantity": 1000, "unit": "g", "expiration_date": (date.today() + timedelta(days=30)).isoformat()})
    create_pantry_item_in_db(db_session, {"id": "pantry_zucchine", "name": "Zucchine", "quantity": 500, "unit": "g", "expiration_date": (date.today() + timedelta(days=5)).isoformat()}) # Expiring soon
    
    # Seed Consumed Entries - only older ones for the general seeded database to allow anti-repetition to be tested selectively
    db_session.add(ConsumedEntry(id="cons_rec_1_old_a", profile_id="persona_a", date=(date.today() - timedelta(days=PlannerEngine.ANTI_REPETITION_DAYS + 1)).isoformat(), meal_type="cena", type="planned", consumed_recipe_id="rec_pasta_pesto_veg"))
    db_session.add(ConsumedEntry(id="cons_rec_1_old_b", profile_id="persona_b", date=(date.today() - timedelta(days=PlannerEngine.ANTI_REPETITION_DAYS + 1)).isoformat(), meal_type="cena", type="planned", consumed_recipe_id="rec_pasta_pesto_veg"))

    # Seed StructuredMealPlan
    meal_plan_A_data = {
        "id": "plan_a",
        "profile_id": "persona_a",
        "start_date": (date.today() - timedelta(days=2)).isoformat(),
        "daily_plans": [
            {"date": (date.today() + timedelta(days=i)).isoformat(), "meals": [
                {"meal_type": "pranzo", "items": [{"item_name": "Pasta", "food_group": "carboidrati", "quantity": 80, "unit": "g"}]},
                {"meal_type": "cena", "items": [{"item_name": "Tofu", "food_group": "proteine", "quantity": 150, "unit": "g"}]}
            ]} for i in range(7)
        ]
    }
    db_session.add(StructuredMealPlan(**meal_plan_A_data))
    
    meal_plan_B_data = {
        "id": "plan_b",
        "profile_id": "persona_b",
        "start_date": (date.today() - timedelta(days=2)).isoformat(),
        "daily_plans": [
            {"date": (date.today() + timedelta(days=i)).isoformat(), "meals": [
                {"meal_type": "pranzo", "items": [{"item_name": "Pasta", "food_group": "carboidrati", "quantity": 100, "unit": "g"}]},
                {"meal_type": "cena", "items": [{"item_name": "Pollo", "food_group": "proteine", "quantity": 150, "unit": "g"}]}
            ]} for i in range(7)
        ]
    }
    db_session.add(StructuredMealPlan(**meal_plan_B_data))

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
    create_pantry_item_in_db(db_session, {"id": "pantry_flour", "name": "Farina", "quantity": 1000, "unit": "g", "expiration_date": (date.today() + timedelta(days=30)).isoformat()})
    create_pantry_item_in_db(db_session, {"id": "pantry_zucchine", "name": "Zucchine", "quantity": 500, "unit": "g", "expiration_date": (date.today() + timedelta(days=5)).isoformat()}) # Expiring soon
    
    # Add a recent consumption for rec_pasta_pesto_veg to trigger anti-repetition for relevant tests
    db_session.add(ConsumedEntry(id="cons_rec_1_recent_a", profile_id="persona_a", date=(date.today() - timedelta(days=1)).isoformat(), meal_type="pranzo", type="planned", consumed_recipe_id="rec_pasta_pesto_veg"))
    db_session.add(ConsumedEntry(id="cons_rec_1_recent_b", profile_id="persona_b", date=(date.today() - timedelta(days=1)).isoformat(), meal_type="pranzo", type="planned", consumed_recipe_id="rec_pasta_pesto_veg"))
    
    db_session.commit()

    yield db_session
