from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid

import schemas
from database import get_db, Recipe

router = APIRouter(
    prefix="/recipes",
    tags=["recipes"],
)

@router.post("/", response_model=schemas.Recipe)
def create_recipe(recipe: schemas.RecipeCreate, db: Session = Depends(get_db)):
    """
    Create a new recipe.
    """
    # If ID is not provided in the request, generate one
    recipe_id = recipe.id if recipe.id else str(uuid.uuid4())
    
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe:
        raise HTTPException(status_code=400, detail="Recipe with this ID already exists")
    
    # Create the SQLAlchemy model instance
    # Ensure the ID from the Pydantic model is used, or the generated one
    recipe_data = recipe.model_dump()
    recipe_data["id"] = recipe_id # Ensure the ID is set from our determined recipe_id
    
    db_recipe = Recipe(**recipe_data)
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)
    return db_recipe

@router.get("/", response_model=List[schemas.Recipe])
def read_recipes(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Retrieve all recipes.
    """
    recipes = db.query(Recipe).offset(skip).limit(limit).all()
    return recipes

@router.get("/{recipe_id}", response_model=schemas.Recipe)
def read_recipe(recipe_id: str, db: Session = Depends(get_db)):
    """
    Retrieve a single recipe by ID.
    """
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return db_recipe

@router.put("/{recipe_id}", response_model=schemas.Recipe)
def update_recipe(recipe_id: str, recipe: schemas.RecipeCreate, db: Session = Depends(get_db)):
    """
    Update an existing recipe.
    """
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    
    update_data = recipe.model_dump(exclude_unset=True)
    # Ensure ID is not updated
    if "id" in update_data:
        del update_data["id"]

    for key, value in update_data.items():
        setattr(db_recipe, key, value)
        
    db.commit()
    db.refresh(db_recipe)
    return db_recipe

@router.delete("/{recipe_id}", response_model=schemas.Recipe)
def delete_recipe(recipe_id: str, db: Session = Depends(get_db)):
    """
    Delete a recipe.
    """
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    db.delete(db_recipe)
    db.commit()
    return db_recipe
