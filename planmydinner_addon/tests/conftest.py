import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

# Import app, Base, and get_db from the application package
from main import app
from database import Base, get_db, UnitConversion, PantryItem, Recipe

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
            {"name": "Pasta", "food_group": "carboidrati", "quantities": {"persona_a": {"qty": 100, "unit": "g", "grams_equiv": 100.0}}},
            {"name": "Pomodoro", "food_group": "verdure", "quantities": {"persona_a": {"qty": 200, "unit": "g", "grams_equiv": 200.0}}}
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
