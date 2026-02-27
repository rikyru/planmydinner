from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid

from .. import schemas
from ..database import get_db, Recipe, CandidateRecipe

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

@router.get("/detail/{recipe_id}", response_model=schemas.Recipe)
def get_recipe_detail(recipe_id: str, db: Session = Depends(get_db)):
    """
    Retrieve full recipe detail (content with quantities) from Recipe or CandidateRecipe.
    Used by the UI to display meal components and ingredient doses.
    """
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe:
        return db_recipe  # schemas.Recipe has from_attributes=True

    candidate = db.query(CandidateRecipe).filter(CandidateRecipe.id == recipe_id).first()
    if candidate:
        data = candidate.recipe_data if isinstance(candidate.recipe_data, dict) else candidate.recipe_data.model_dump()
        # Inject the candidate's own id so schemas.Recipe validation passes
        return {**data, "id": recipe_id}

    raise HTTPException(status_code=404, detail=f"Recipe {recipe_id} not found")


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

@router.post("/candidate/{candidate_recipe_id}/approve", response_model=schemas.Recipe)
def approve_candidate_recipe(candidate_recipe_id: str, db: Session = Depends(get_db)):
    """
    Approves a candidate recipe, converting it into a full recipe. The candidate recipe's status is updated to "approved".
    """
    db_candidate = db.query(CandidateRecipe).filter(CandidateRecipe.id == candidate_recipe_id).first()
    if not db_candidate:
        raise HTTPException(status_code=404, detail="Candidate Recipe not found")
    
    # Ensure recipe_data is loaded correctly from JSON
    recipe_create_data = schemas.RecipeCreate(**db_candidate.recipe_data)
    
    # Create the new Recipe, using the ID from the candidate recipe's data or generate a new one
    db_recipe_id = recipe_create_data.id if recipe_create_data.id else str(uuid.uuid4())

    # Check if a recipe with this ID already exists
    if db.query(Recipe).filter(Recipe.id == db_recipe_id).first():
        raise HTTPException(status_code=400, detail=f"A recipe with ID {db_recipe_id} already exists.")

    db_recipe = Recipe(**recipe_create_data.model_dump(), id=db_recipe_id)
        
    db.add(db_recipe)
    
    # Update candidate status
    db_candidate.status = "approved"
    db.add(db_candidate)

    db.commit()
    db.refresh(db_recipe)
    
    return db_recipe
