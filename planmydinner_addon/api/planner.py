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

    # Fetch the active meal plan for the given date to find the target meal composition
    weekly_plan_A = planner._get_active_meal_plan(profile_id_A, current_date)
    weekly_plan_B = planner._get_active_meal_plan(profile_id_B, current_date)

    if not weekly_plan_A or not weekly_plan_B:
        raise HTTPException(status_code=404, detail="Could not find active meal plans for one or both profiles.")

    daily_plan_A = next((d for d in weekly_plan_A.daily_plans if date.fromisoformat(d.date) == current_date), None)
    daily_plan_B = next((d for d in weekly_plan_B.daily_plans if date.fromisoformat(d.date) == current_date), None)

    if not daily_plan_A or not daily_plan_B:
        raise HTTPException(status_code=404, detail="Could not find daily plans for the specified date.")
        
    meal_plan_A = next((m for m in daily_plan_A.meals if m.meal_type == meal_type), None)
    meal_plan_B = next((m for m in daily_plan_B.meals if m.meal_type == meal_type), None)

    if not meal_plan_A or not meal_plan_B:
        raise HTTPException(status_code=404, detail=f"Could not find meal plans for meal type '{meal_type}'.")

    options = planner.suggest_recipes_for_meal(
        meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, request_params
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
