from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid
from datetime import date
import logging # Added import

_LOGGER = logging.getLogger(__name__) # Added logger setup

import schemas
from database import get_db, ConsumedEntry, Recipe, consume_ingredients_from_pantry

router = APIRouter(
    prefix="/consumed-entries",
    tags=["consumption"],
)

@router.post("/", response_model=schemas.ConsumedEntry)
def create_consumed_entry(entry: schemas.ConsumedEntryCreate, db: Session = Depends(get_db)):
    """
    Create a new consumed entry. This is a generic endpoint.
    Specific endpoints for 'planned' and 'override' are likely more useful.
    """
    db_entry = ConsumedEntry(**entry.model_dump(), id=str(uuid.uuid4()))
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry

@router.post("/mark-planned", response_model=schemas.ConsumedEntry)
def mark_meal_as_consumed_planned(profile_id: str, meal_date: date, meal_type: str, recipe_id: str, db: Session = Depends(get_db)):
    """
    Mark a planned meal as consumed.
    """
    entry_data = schemas.ConsumedEntryCreate(
        profile_id=profile_id,
        date=meal_date,
        meal_type=meal_type,
        type="planned",
        consumed_recipe_id=recipe_id
    )
    db_entry = ConsumedEntry(**entry_data.model_dump(), id=str(uuid.uuid4()))
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)

    # --- Consume ingredients from pantry ---
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe:
        ingredients_to_consume_data = []
        # _LOGGER.debug(f"Raw recipe content for {db_recipe.name}: {db_recipe.content}") # Debugging
        
        # Access content as a dictionary first
        recipe_content_dict = db_recipe.content
        
        if db_recipe.is_composed_dish and "components" in recipe_content_dict:
            # Handle composed dish - extract from components
            for component_item in recipe_content_dict["components"]: # Iterate through components if it's a list
                if "quantities" in component_item and profile_id in component_item["quantities"]:
                    qty_data = component_item["quantities"][profile_id]
                    ingredients_to_consume_data.append({
                        "name": component_item["name"],
                        "quantity": qty_data["qty"],
                        "unit": qty_data["unit"]
                    })
        elif isinstance(db_recipe.content, list): # List of RecipeIngredient
            for ingredient_item in db_recipe.content: # Iterate through each ingredient in the list
                if "quantities" in ingredient_item and profile_id in ingredient_item["quantities"]:
                    qty_data = ingredient_item["quantities"][profile_id]
                    ingredients_to_consume_data.append({
                        "name": ingredient_item["name"],
                        "quantity": qty_data["qty"],
                        "unit": qty_data["unit"]
                    })
        
        if ingredients_to_consume_data:
            consume_ingredients_from_pantry(db, ingredients_to_consume_data)
        else:
            _LOGGER.warning(f"No ingredients found for recipe {recipe_id} and profile {profile_id} or recipe content format unrecognized.")
    else:
        _LOGGER.warning(f"Recipe {recipe_id} not found when trying to consume planned meal ingredients.")
    
    return db_entry


@router.post("/override", response_model=schemas.ConsumedEntry)
def mark_meal_as_consumed_override(profile_id: str, meal_date: date, meal_type: str, override_details: schemas.OverrideConsumedDetails, db: Session = Depends(get_db)):
    """
    Mark a meal as consumed with override details.
    """
    entry_data = schemas.ConsumedEntryCreate(
        profile_id=profile_id,
        date=meal_date,
        meal_type=meal_type,
        type="override",
        override_details=override_details
    )
    db_entry = ConsumedEntry(**entry_data.model_dump(), id=str(uuid.uuid4()))
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)

    # --- Consume ingredients from pantry based on override details ---
    if override_details.ingredients:
        ingredients_to_consume_data = []
        for ing in override_details.ingredients:
            ingredients_to_consume_data.append({
                "name": ing.name,
                "quantity": ing.qty,
                "unit": ing.unit
            })
        if ingredients_to_consume_data:
            consume_ingredients_from_pantry(db, ingredients_to_consume_data)
    else:
        _LOGGER.debug("No ingredients specified in override_details to consume from pantry.")
    
    # Here, you would also trigger the logic to create a 'CandidateRecipe'
    # For now, we just save the consumption entry.
    return db_entry


@router.get("/", response_model=List[schemas.ConsumedEntry])
def read_consumed_entries(profile_id: str = None, start_date: date = None, end_date: date = None, db: Session = Depends(get_db)):
    """
    Retrieve consumed entries, with optional filters.
    """
    query = db.query(ConsumedEntry)
    if profile_id:
        query = query.filter(ConsumedEntry.profile_id == profile_id)
    if start_date:
        query = query.filter(ConsumedEntry.date >= start_date)
    if end_date:
        query = query.filter(ConsumedEntry.date <= end_date)
    
    entries = query.all()
    return entries