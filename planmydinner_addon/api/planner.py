from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date
import uuid

from .. import schemas
from ..database import get_db, GeneratedWeeklyPlan
from ..planner import PlannerEngine, get_week_start

router = APIRouter(
    prefix="/planner",
    tags=["planner"],
)


def _save_generated_plan(db: Session, profile_id_A: str, profile_id_B: Optional[str],
                         week_start: date, daily_plans: List[schemas.DailyPlannedMeals]) -> GeneratedWeeklyPlan:
    """Persist a generated weekly plan, overwriting any existing one for the same week+profiles."""
    existing = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id_A,
        GeneratedWeeklyPlan.week_start_date == week_start.isoformat()
    ).first()
    serialized = [dp.model_dump() for dp in daily_plans]
    if existing:
        existing.profile_id_B = profile_id_B
        existing.generated_at = date.today().isoformat()
        existing.daily_plans = serialized
        db.add(existing)
    else:
        existing = GeneratedWeeklyPlan(
            id=str(uuid.uuid4()),
            profile_id_A=profile_id_A,
            profile_id_B=profile_id_B,
            week_start_date=week_start.isoformat(),
            generated_at=date.today().isoformat(),
            daily_plans=serialized,
        )
        db.add(existing)
    db.commit()
    return existing


@router.post("/generate-week", response_model=List[schemas.DailyPlannedMeals])
def generate_weekly_plan(
    request: Request,
    profile_id_A: str,
    profile_id_B: str,
    current_date: date = date.today(),
    db: Session = Depends(get_db)
):
    """
    Force-generate a full weekly meal plan for both profiles and save it to DB.
    """
    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)
    weekly_plan = planner.generate_weekly_plan(profile_id_A, profile_id_B, current_date)
    if not weekly_plan:
        raise HTTPException(status_code=404, detail="Could not generate a weekly plan.")
    week_start = get_week_start(current_date)
    _save_generated_plan(db, profile_id_A, profile_id_B, week_start, weekly_plan)
    return weekly_plan


@router.post("/change-recipe", response_model=List[schemas.ChangeRecipeOption])
def change_recipe(
    request: Request,
    profile_id_A: str,
    profile_id_B: str,
    meal_type: str,
    current_date: date = date.today(),
    mood: str = "",
    cleanup: str = "",
    max_time_minutes: int = 120,
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
    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)

    # Fetch the active meal plan for the given date to find the target meal composition
    weekly_plan_A = planner._get_active_meal_plan(profile_id_A, current_date)
    if not weekly_plan_A:
        raise HTTPException(status_code=404, detail=f"No active meal plan for primary profile '{profile_id_A}'.")

    weekly_plan_B = planner._get_active_meal_plan(profile_id_B, current_date)
    # Se profilo B non ha un piano, usa piano vuoto (dummy) per non bloccare
    if not weekly_plan_B:
        from datetime import timedelta
        from .. import schemas as _schemas
        weekly_plan_B = _schemas.StructuredMealPlan(
            id="dummy_plan_B", profile_id=profile_id_B,
            start_date=current_date.isoformat(), rotation_rules=[], allowed_cooking_methods=[],
            daily_plans=[_schemas.DailyPlannedMeals(
                date=(current_date + timedelta(days=i)).isoformat(),
                meals=[
                    _schemas.PlannedMeal(meal_type="pranzo", items=[]),
                    _schemas.PlannedMeal(meal_type="cena", items=[]),
                ]
            ) for i in range(7)]
        )

    daily_plan_A = next((d for d in weekly_plan_A.daily_plans if date.fromisoformat(d.date) == current_date), None)
    daily_plan_B = next((d for d in weekly_plan_B.daily_plans if date.fromisoformat(d.date) == current_date), None)

    if not daily_plan_A:
        raise HTTPException(status_code=404, detail="No daily plan found for the specified date.")
    if not daily_plan_B:
        daily_plan_B = schemas.DailyPlannedMeals(date=current_date.isoformat(), meals=[])

    meal_plan_A = next((m for m in daily_plan_A.meals if m.meal_type == meal_type), None)
    meal_plan_B = next((m for m in daily_plan_B.meals if m.meal_type == meal_type), None)

    if not meal_plan_A:
        raise HTTPException(status_code=404, detail=f"No '{meal_type}' plan found for the specified date.")
    if not meal_plan_B:
        meal_plan_B = schemas.PlannedMeal(meal_type=meal_type, items=[])

    options = planner.suggest_recipes_for_meal(
        meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, request_params
    )
    if not options:
        raise HTTPException(status_code=404, detail="No alternative recipes found.")
    return options


@router.post("/apply-recipe-option")
def apply_recipe_option(
    request: Request,
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
    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)
    success = planner.apply_recipe_to_plan(profile_id_A, profile_id_B, meal_type, current_date, recipe_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to apply recipe to plan.")
    return {"message": "Recipe applied to plan successfully."}


@router.get("/plan", response_model=schemas.StructuredMealPlan)
def get_meal_plan(
    request: Request,
    profile_id: str,
    plan_date: date = date.today(),
    db: Session = Depends(get_db)
):
    """
    Retrieve an active meal plan for a specific profile and date.
    """
    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)
    plan = planner._get_active_meal_plan(profile_id, plan_date)
    if not plan:
        raise HTTPException(status_code=404, detail="No active meal plan found for the specified profile and date.")
    return plan


@router.get("/weekly-plan", response_model=List[schemas.DailyPlannedMeals])
def get_weekly_plan(
    request: Request,
    profile_id_A: str,
    profile_id_B: Optional[str] = None,
    start_date: date = date.today(),
    db: Session = Depends(get_db)
):
    """
    Get the generated weekly meal plan. Returns cached version if available;
    otherwise generates, saves, and returns.
    """
    week_start = get_week_start(start_date)
    cached = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id_A,
        GeneratedWeeklyPlan.week_start_date == week_start.isoformat()
    ).first()
    if cached:
        return [schemas.DailyPlannedMeals.model_validate(dp) for dp in cached.daily_plans]

    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)
    weekly_plan = planner.generate_weekly_plan(profile_id_A, profile_id_B, start_date)
    if not weekly_plan:
        raise HTTPException(
            status_code=404,
            detail=f"Could not generate a weekly plan. Make sure an active meal plan exists for the primary profile '{profile_id_A}'."
        )
    _save_generated_plan(db, profile_id_A, profile_id_B, week_start, weekly_plan)
    return weekly_plan
