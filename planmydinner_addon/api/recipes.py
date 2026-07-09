from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional, Any, Dict
import uuid

from pydantic import BaseModel as _BaseModel
from .. import schemas
from ..database import get_db, Recipe, CandidateRecipe, UserProfile
from ..nutrition import compute_recipe_nutrition


class BulkIngredient(_BaseModel):
    name: str
    food_group: str
    grams: float


class BulkRecipeItem(_BaseModel):
    name: str
    time: int = 30
    difficulty: str = "facile"
    mood: str = "normale"
    cooking: str = "tegame"
    ingredients: List[BulkIngredient]


class BulkImportResult(_BaseModel):
    created: int
    skipped: int
    errors: List[str]

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

    # Tag ricette aggiunte manualmente: peso alto nel planner
    if recipe_data.get("tags") is None:
        recipe_data["tags"] = {}
    recipe_data["tags"]["manual"] = ["true"]

    db_recipe = Recipe(**recipe_data)
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)
    return db_recipe

@router.post("/bulk", response_model=BulkImportResult)
def bulk_import_recipes(
    items: List[BulkRecipeItem],
    profile_a_id: str = "persona_a",
    profile_b_id: str = "persona_b",
    db: Session = Depends(get_db),
):
    """
    Importa in blocco una lista di ricette nel formato semplificato.
    Ogni ricetta viene taggata come 'manual' → peso alto nel planner.
    Ricette con lo stesso nome vengono saltate.
    """
    created = 0
    skipped = 0
    errors: List[str] = []

    _DIFFICULTY_MAP = {
        "easy": "facile", "facile": "facile",
        "medium": "media", "media": "media",
        "hard": "difficile", "difficile": "difficile",
    }

    def _qty(g: float) -> dict:
        return {"qty": float(g), "unit": "g", "grams_equiv": float(g)}

    for item in items:
        try:
            # Controlla duplicati per nome
            existing = db.query(Recipe).filter(Recipe.name == item.name).first()
            if existing:
                skipped += 1
                continue

            difficulty = _DIFFICULTY_MAP.get(item.difficulty.lower(), "sconosciuto")

            content = [
                {
                    "name": ing.name,
                    "food_group": ing.food_group,
                    "quantities": {
                        profile_a_id: _qty(ing.grams),
                        profile_b_id: _qty(ing.grams),
                    },
                }
                for ing in item.ingredients
            ]
            recipe_data = {
                "id": str(uuid.uuid4()),
                "name": item.name,
                "description": "",
                "is_composed_dish": False,
                "content": content,
                "steps": [],
                "total_time_minutes": item.time,
                "difficulty": difficulty,
                "tags": {
                    "manual": ["true"],
                    "mood": [item.mood],
                    "cooking_methods": [item.cooking],
                    "cleanup": ["facile"],
                },
            }
            db.add(Recipe(**recipe_data))
            created += 1
        except Exception as e:
            errors.append(f"{item.name}: {e}")

    db.commit()
    return BulkImportResult(created=created, skipped=skipped, errors=errors)


@router.get("/")
def read_recipes(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Retrieve all recipes, skipping any with invalid data.
    """
    db_recipes = db.query(Recipe).offset(skip).limit(limit).all()
    result = []
    for r in db_recipes:
        try:
            validated = schemas.Recipe.from_orm(r)
            result.append(validated.model_dump())
        except Exception:
            # Ricetta con dati non conformi: restituisce raw per permettere la visualizzazione/modifica
            result.append({
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "is_composed_dish": r.is_composed_dish or False,
                "content": r.content or [],
                "steps": r.steps or [],
                "total_time_minutes": r.total_time_minutes or 0,
                "difficulty": r.difficulty or "sconosciuto",
                "tags": r.tags or {},
            })
    return result

@router.delete("/all")
def delete_all_recipes(db: Session = Depends(get_db)):
    """
    Delete all recipes from the database.
    """
    count = db.query(Recipe).count()
    db.query(Recipe).delete()
    db.commit()
    return {"deleted": count}


def _attach_nutrition_per_portion(validated: schemas.Recipe, db: Session, llm_gateway=None) -> schemas.Recipe:
    """Calcola i macro per porzione per ogni profilo e li allega alla risposta (best-effort)."""
    try:
        profile_ids = [p.id for p in db.query(UserProfile).all()]
        content = validated.model_dump()["content"]
        if not profile_ids and isinstance(content, list) and content:
            profile_ids = list((content[0].get("quantities") or {}).keys())
        per_portion = {}
        for pid in profile_ids:
            nutrition = compute_recipe_nutrition(content, pid, llm_gateway=llm_gateway)
            if nutrition:
                per_portion[pid] = nutrition
        validated.nutrition_per_portion = per_portion or None
    except Exception:
        validated.nutrition_per_portion = None
    return validated


@router.get("/detail/{recipe_id}", response_model=schemas.Recipe)
def get_recipe_detail(recipe_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Retrieve full recipe detail (content with quantities) from Recipe or CandidateRecipe.
    Used by the UI to display meal components and ingredient doses.
    Includes nutrition_per_portion (kcal + macro per profilo) when computable.
    """
    llm_gateway = getattr(request.app.state, "llm_gateway", None)

    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe:
        validated = schemas.Recipe.model_validate(db_recipe)
        return _attach_nutrition_per_portion(validated, db, llm_gateway)

    candidate = db.query(CandidateRecipe).filter(CandidateRecipe.id == recipe_id).first()
    if candidate:
        data = candidate.recipe_data if isinstance(candidate.recipe_data, dict) else candidate.recipe_data.model_dump()
        # Inject the candidate's own id so schemas.Recipe validation passes
        validated = schemas.Recipe.model_validate({**data, "id": recipe_id})
        return _attach_nutrition_per_portion(validated, db, llm_gateway)

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
