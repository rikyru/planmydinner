import logging
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, JSON, Boolean, Text, func
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from typing import List, Dict, Any # Added for type hinting

_LOGGER = logging.getLogger(__name__)

import os
_data_dir = os.getenv("DATA_DIR", ".")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_data_dir}/database.db")

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Define SQLAlchemy models based on the JSON schema

class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    allergies = Column(JSON)
    excluded_foods = Column(JSON)
    preferences = Column(JSON)
    max_cook_time_default = Column(Integer)
    cleanup_tolerance = Column(String)
    equipment = Column(JSON)

class PantryItem(Base):
    __tablename__ = "pantry_items"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    quantity = Column(Float)
    unit = Column(String)
    category = Column(String, nullable=True)
    expiration_date = Column(String, nullable=True)
    synonyms = Column(JSON)

class ConsumedEntry(Base):
    __tablename__ = "consumed_entries"

    id = Column(String, primary_key=True, index=True)
    profile_id = Column(String, index=True)
    date = Column(String, index=True)
    meal_type = Column(String)
    type = Column(String) # 'planned' or 'override'
    consumed_recipe_id = Column(String, nullable=True)
    override_details = Column(JSON, nullable=True)

class UnitConversion(Base):
    __tablename__ = "unit_conversions"

    unit = Column(String, primary_key=True, index=True)
    grams_equivalent = Column(Float, nullable=True)
    ml_equivalent = Column(Float, nullable=True)

class RotationRule(Base):
    __tablename__ = "rotation_rules"

    id = Column(String, primary_key=True, index=True) # UUID for rule
    profile_id = Column(String, index=True) # Which profile this rule applies to
    food_group_or_item = Column(String, index=True)
    max_per_week = Column(Integer, nullable=True)
    min_per_week = Column(Integer, nullable=True)
    is_hard_constraint = Column(Boolean, default=True)

class SeasonalityItem(Base):
    __tablename__ = "seasonality_items"

    ingredient_name = Column(String, primary_key=True, index=True)
    months_in_season = Column(JSON) # List of integers [1, 2, ..., 12]

class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(Text, nullable=True)
    is_composed_dish = Column(Boolean, default=False)
    content = Column(JSON) # This will store either RecipeIngredient list or ComposedDishContent
    steps = Column(JSON)
    total_time_minutes = Column(Integer)
    difficulty = Column(String)
    tags = Column(JSON) # Stores mood, cleanup, cooking_methods, other tags
    llm_generated_metadata = Column(JSON, nullable=True) # Optional metadata if LLM generated/enriched

class CandidateRecipe(Base):
    __tablename__ = "candidate_recipes"

    id = Column(String, primary_key=True, index=True)
    status = Column(String, default="draft_free_text") # 'draft_free_text', 'draft_structured', 'approved'
    usage_count = Column(Integer, default=0)
    origin_override_id = Column(String, nullable=True) # Links to ConsumedEntry that originated it
    recipe_data = Column(JSON) # Stores the Recipe data in JSON format

class StructuredMealPlan(Base):
    __tablename__ = "structured_meal_plans"

    id = Column(String, primary_key=True, index=True) # UUID for the plan (e.g., weekly plan ID)
    profile_id = Column(String, index=True)
    start_date = Column(String)
    rotation_rules = Column(JSON) # Stored as JSON copy of RotationRule objects, or IDs
    allowed_cooking_methods = Column(JSON)
    daily_plans = Column(JSON) # Stores DailyPlannedMeals objects as JSON


class GeneratedWeeklyPlan(Base):
    __tablename__ = "generated_weekly_plans"

    id = Column(String, primary_key=True)
    profile_id_A = Column(String, index=True)
    profile_id_B = Column(String, nullable=True)
    week_start_date = Column(String, index=True)  # ISO Monday della settimana
    generated_at = Column(String)
    daily_plans = Column(JSON)  # List[DailyPlannedMeals] serializzata


class PlanRules(Base):
    __tablename__ = "plan_rules"

    id = Column(String, primary_key=True)
    profile_id = Column(String, index=True)
    imported_at = Column(String)        # ISO date
    carb_target = Column(JSON)          # {"pranzo": 80, "cena": 60}
    protein_target = Column(JSON)       # {"pranzo": 150, "cena": 130}
    carb_options = Column(JSON)         # {"pranzo": ["pasta","riso"], "cena": [...]}
    protein_options = Column(JSON)      # {"pranzo": ["pollo","pesce"], "cena": [...]}
    frequency_targets = Column(JSON)    # {"carne_bianca": {"min":2,"max":3,"hard_max":null}}


def consume_ingredients_from_pantry(db: Session, ingredients_data: List[Dict[str, Any]]):
    """
    Deducts quantities of ingredients from the pantry.
    `ingredients_data` should be a list of dictionaries, each with 'name', 'quantity', and 'unit'.
    """
    for ingredient in ingredients_data:
        item_name = ingredient["name"]
        qty_to_consume = ingredient["quantity"]
        unit_to_consume = ingredient["unit"]

        # Find the pantry item, case-insensitive for name, and matching unit
        pantry_item = db.query(PantryItem).filter(
            func.lower(PantryItem.name) == func.lower(item_name),
            func.lower(PantryItem.unit) == func.lower(unit_to_consume)
        ).first()

        if pantry_item:
            if pantry_item.quantity >= qty_to_consume:
                pantry_item.quantity -= qty_to_consume
                db.add(pantry_item)
                _LOGGER.info(f"Consumed {qty_to_consume} {unit_to_consume} of {item_name} from pantry. Remaining: {pantry_item.quantity}")
            else:
                _LOGGER.warning(f"Not enough {item_name} in pantry to consume {qty_to_consume} {unit_to_consume}. Consuming {pantry_item.quantity} and setting remaining to 0.")
                pantry_item.quantity = 0
                db.add(pantry_item)
            db.commit()
            db.refresh(pantry_item)
        else:
            _LOGGER.warning(f"Ingredient '{item_name}' with unit '{unit_to_consume}' not found in pantry to consume.")

def create_db_and_tables():
    """
    Initializes the database and creates all tables defined in the Base metadata.
    This function should be called on application startup.
    """
    Base.metadata.create_all(bind=engine)

# Dependency to get a DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()