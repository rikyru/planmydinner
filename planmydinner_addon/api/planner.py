from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import date

from .. import schemas
from ..database import get_db
from ..planner import PlannerEngine

router = APIRouter(
    prefix="/planner",
    tags=["planner"],
)

@router.post("/generate-week", response_model=List[schemas.DailyPlannedMeals])
def generate_weekly_plan(
    profile_id_A: str,
    profile_id_B: str,
    current_date: date = date.today(),
    db: Session = Depends(get_db)
):
    """
    Generate a full weekly meal plan for both profiles.
    """
    planner = PlannerEngine(db)
    weekly_plan = planner.generate_weekly_plan(profile_id_A, profile_id_B, current_date)
    if not weekly_plan:
        raise HTTPException(status_code=404, detail="Could not generate a weekly plan.")
    return weekly_plan

@router.post("/change-recipe", response_model=List[schemas.ChangeRecipeOption])
def change_recipe(
    profile_id_A: str,
    profile_id_B: str,
    meal_type: str,
    current_date: date = date.today(),
    mood: str = "normal",
    cleanup: str = "normal",
    max_time_minutes: int = 60,
    db: Session = Depends(get_db)
):
    """
    Suggest 3 alternative recipes for a specific meal, filtered and ranked.
    """
    request_params = {
        "mood": mood,
        "cleanup": cleanup,
        "max_time_minutes": max_time_minutes
    }
    planner = PlannerEngine(db)
    options = planner.suggest_recipes_for_meal(
        profile_id_A, profile_id_B, meal_type, current_date, request_params
    )
    if not options:
        raise HTTPException(status_code=404, detail="No alternative recipes found.")
    return options

@router.post("/apply-recipe-option")
def apply_recipe_option(
    profile_id_A: str,
    profile_id_B: str,
    meal_type: str,
    current_date: date,
    recipe_id: str,
    db: Session = Depends(get_db)
):
    """
    Applies a chosen recipe to the meal plan for a specific date and meal type.
    """
    planner = PlannerEngine(db)
    success = planner.apply_recipe_to_plan(profile_id_A, profile_id_B, meal_type, current_date, recipe_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to apply recipe to plan.")
    return {"message": "Recipe applied to plan successfully."}
