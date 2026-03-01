from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any
from datetime import date, timedelta
import uuid
import copy

from pydantic import BaseModel as _BaseModel
from .. import schemas
from .. import database
from ..database import get_db, GeneratedWeeklyPlan
from ..planner import PlannerEngine


class CustomMealBody(_BaseModel):
    title: str
    protein_name: str
    protein_grams: float
    carb_name: str
    carb_grams: float
    veg_name: Optional[str] = None
    veg_grams: float = 100
    notes: Optional[str] = None


class PlanRulesUpdate(_BaseModel):
    carb_target: Optional[Dict[str, float]] = None
    protein_target: Optional[Dict[str, float]] = None
    frequency_targets: Optional[Dict[str, Any]] = None


class FreeMealBody(_BaseModel):
    title: str
    notes: str = ""

router = APIRouter(
    prefix="/planner",
    tags=["planner"],
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_plan_covering_date(db: Session, profile_id_A: str, target_date: date) -> Optional[GeneratedWeeklyPlan]:
    """Find any saved GeneratedWeeklyPlan whose 7-day window covers target_date."""
    plans = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id_A,
    ).all()
    for plan in plans:
        plan_start = date.fromisoformat(plan.week_start_date)
        if plan_start <= target_date <= plan_start + timedelta(days=6):
            return plan
    return None


def _save_generated_plan(db: Session, profile_id_A: str, profile_id_B: Optional[str],
                         start_date: date, daily_plans: List[schemas.DailyPlannedMeals]) -> GeneratedWeeklyPlan:
    """Persist a generated weekly plan keyed by exact start_date (no Monday-snapping)."""
    existing = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id_A,
        GeneratedWeeklyPlan.week_start_date == start_date.isoformat()
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
            week_start_date=start_date.isoformat(),
            generated_at=date.today().isoformat(),
            daily_plans=serialized,
        )
        db.add(existing)
    db.commit()
    return existing


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/generate-week", response_model=List[schemas.DailyPlannedMeals])
def generate_weekly_plan(
    request: Request,
    profile_id_A: str,
    profile_id_B: str,
    current_date: date = date.today(),
    db: Session = Depends(get_db)
):
    """Force-generate a 7-day plan from current_date and save it."""
    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)
    weekly_plan = planner.generate_weekly_plan(profile_id_A, profile_id_B, current_date)
    if not weekly_plan:
        raise HTTPException(status_code=404, detail="Could not generate a weekly plan.")
    _save_generated_plan(db, profile_id_A, profile_id_B, current_date, weekly_plan)
    return weekly_plan


@router.get("/weekly-plan", response_model=List[schemas.DailyPlannedMeals])
def get_weekly_plan(
    request: Request,
    profile_id_A: str,
    profile_id_B: Optional[str] = None,
    start_date: date = date.today(),
    db: Session = Depends(get_db)
):
    """
    Get the 7-day plan starting from start_date (rolling, no Monday-snapping).
    Returns cached version if available; otherwise generates, saves, and returns.
    """
    cached = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id_A,
        GeneratedWeeklyPlan.week_start_date == start_date.isoformat()
    ).first()
    if cached:
        return [schemas.DailyPlannedMeals.model_validate(dp) for dp in cached.daily_plans]

    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)
    weekly_plan = planner.generate_weekly_plan(profile_id_A, profile_id_B, start_date)
    if not weekly_plan:
        raise HTTPException(
            status_code=404,
            detail=f"Could not generate a weekly plan. Make sure an active meal plan exists for '{profile_id_A}'."
        )
    _save_generated_plan(db, profile_id_A, profile_id_B, start_date, weekly_plan)
    return weekly_plan


@router.get("/plan-for-date")
def get_plan_for_date(
    profile_id_A: str,
    profile_id_B: Optional[str] = None,
    target_date: date = date.today(),
    db: Session = Depends(get_db)
):
    """
    Find and return the saved weekly plan that covers target_date.
    Returns {start_date, daily_plans} so the UI knows which rolling window is active.
    Returns null if no plan covers target_date.
    """
    plan = _find_plan_covering_date(db, profile_id_A, target_date)
    if not plan:
        return None
    return {
        "start_date": plan.week_start_date,
        "profile_id_B": plan.profile_id_B,
        "daily_plans": [schemas.DailyPlannedMeals.model_validate(dp) for dp in plan.daily_plans],
    }


@router.get("/rules")
def get_plan_rules(
    profile_id_A: str,
    db: Session = Depends(get_db)
):
    """
    Returns rotation rules, grammi targets, and PlanRules (if available) for a profile.
    UI uses this to display the 'Regole del Piano' panel.
    """
    planner = PlannerEngine(db)

    # Try PlanRules first (derived from imported plan)
    plan_rules_db = db.query(database.PlanRules).filter(
        database.PlanRules.profile_id == profile_id_A
    ).order_by(database.PlanRules.imported_at.desc()).first()
    plan_rules_data = None
    if plan_rules_db:
        plan_rules_data = {
            "carb_target": plan_rules_db.carb_target,
            "protein_target": plan_rules_db.protein_target,
            "carb_options": plan_rules_db.carb_options,
            "protein_options": plan_rules_db.protein_options,
            "frequency_targets": plan_rules_db.frequency_targets,
            "imported_at": plan_rules_db.imported_at,
        }

    # Legacy: StructuredMealPlan rotation_rules and grammi_targets
    plan = planner._get_latest_meal_plan(profile_id_A)
    if not plan:
        return {"rotation_rules": [], "grammi_targets": {}, "plan_rules": plan_rules_data}

    grammi_targets: Dict[str, Any] = {}
    for dp in plan.daily_plans[:1]:
        for meal in dp.meals:
            targets = {}
            for item in meal.items:
                if item.quantity > 0:
                    fg = item.food_group
                    if fg not in targets:
                        targets[fg] = {"qty": item.quantity, "unit": item.unit}
            grammi_targets[meal.meal_type] = targets

    rules = [
        {
            "food_group_or_item": r.food_group_or_item,
            "min_per_week": r.min_per_week,
            "max_per_week": r.max_per_week,
            "is_hard_constraint": r.is_hard_constraint,
        }
        for r in (plan.rotation_rules or [])
    ]
    return {"rotation_rules": rules, "grammi_targets": grammi_targets, "plan_rules": plan_rules_data}


@router.put("/rules/{profile_id}")
def update_plan_rules(profile_id: str, body: PlanRulesUpdate, db: Session = Depends(get_db)):
    """
    Aggiorna (o crea) i vincoli del piano per un profilo:
    carb_target, protein_target, frequency_targets.
    """
    from datetime import datetime
    plan_rules = db.query(database.PlanRules).filter(
        database.PlanRules.profile_id == profile_id
    ).order_by(database.PlanRules.imported_at.desc()).first()
    if not plan_rules:
        plan_rules = database.PlanRules(
            id=str(uuid.uuid4()),
            profile_id=profile_id,
            imported_at=datetime.now().isoformat(),
        )
    if body.carb_target is not None:
        plan_rules.carb_target = body.carb_target
    if body.protein_target is not None:
        plan_rules.protein_target = body.protein_target
    if body.frequency_targets is not None:
        plan_rules.frequency_targets = body.frequency_targets
    plan_rules.imported_at = datetime.now().isoformat()
    db.add(plan_rules)
    db.commit()
    return {"status": "ok"}


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
    """Suggest up to 3 alternative complete recipes for a meal."""
    request_params = {"mood": mood, "cleanup": cleanup, "max_time_minutes": max_time_minutes}
    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)

    weekly_plan_A = planner._get_latest_meal_plan(profile_id_A)
    if not weekly_plan_A:
        raise HTTPException(status_code=404, detail=f"No meal plan for '{profile_id_A}'.")

    weekly_plan_B = planner._get_latest_meal_plan(profile_id_B)
    if not weekly_plan_B:
        weekly_plan_B = schemas.StructuredMealPlan(
            id="dummy_plan_B", profile_id=profile_id_B,
            start_date=current_date.isoformat(), rotation_rules=[], allowed_cooking_methods=[],
            daily_plans=[schemas.DailyPlannedMeals(
                date=(current_date + timedelta(days=i)).isoformat(),
                meals=[
                    schemas.PlannedMeal(meal_type="pranzo", items=[]),
                    schemas.PlannedMeal(meal_type="cena", items=[]),
                ]
            ) for i in range(7)]
        )

    # Match by weekday so this works for any rolling date, not just plan's original dates
    daily_plan_A = next((d for d in weekly_plan_A.daily_plans if date.fromisoformat(d.date).weekday() == current_date.weekday()), None)
    daily_plan_B = next((d for d in weekly_plan_B.daily_plans if date.fromisoformat(d.date).weekday() == current_date.weekday()), None)

    if not daily_plan_A:
        raise HTTPException(status_code=404, detail="No daily plan for the specified date.")
    if not daily_plan_B:
        daily_plan_B = schemas.DailyPlannedMeals(date=current_date.isoformat(), meals=[])

    meal_plan_A = next((m for m in daily_plan_A.meals if m.meal_type == meal_type), None)
    meal_plan_B = next((m for m in daily_plan_B.meals if m.meal_type == meal_type), None)

    if not meal_plan_A:
        raise HTTPException(status_code=404, detail=f"No '{meal_type}' plan for the specified date.")
    if not meal_plan_B:
        meal_plan_B = schemas.PlannedMeal(meal_type=meal_type, items=[])

    options = planner.suggest_recipes_for_meal(
        meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, request_params
    )
    if not options:
        raise HTTPException(status_code=404, detail="No alternative recipes found.")
    return options


@router.post("/change-component", response_model=List[schemas.ChangeRecipeOption])
def change_component(
    request: Request,
    profile_id_A: str,
    profile_id_B: str,
    meal_type: str,
    current_date: date,
    recipe_id: str,
    component: str,  # 'carb' or 'protein'
    db: Session = Depends(get_db)
):
    """
    Return recipe options with only one component swapped (carb or protein).
    Preserves the other component and uses exact target grams from the plan.
    """
    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)

    weekly_plan_A = planner._get_latest_meal_plan(profile_id_A)
    if not weekly_plan_A:
        raise HTTPException(status_code=404, detail=f"No meal plan for '{profile_id_A}'.")

    # Match by weekday so this works for any rolling date
    daily_plan_A = next((d for d in weekly_plan_A.daily_plans if date.fromisoformat(d.date).weekday() == current_date.weekday()), None)
    if not daily_plan_A:
        raise HTTPException(status_code=404, detail="No daily plan for this weekday.")

    meal_plan_A = next((m for m in daily_plan_A.meals if m.meal_type == meal_type), None)
    if not meal_plan_A:
        raise HTTPException(status_code=404, detail=f"No '{meal_type}' plan for this date.")

    profile_A = planner._get_user_profile(profile_id_A)
    profile_B = planner._get_user_profile(profile_id_B)
    if not profile_A:
        raise HTTPException(status_code=404, detail="Profile A not found.")
    if not profile_B:
        profile_B = schemas.UserProfile(id=profile_id_B, name="Dummy")

    options = planner.get_component_alternatives(recipe_id, component, meal_plan_A, profile_A, profile_B)
    if not options:
        raise HTTPException(status_code=404, detail=f"No alternatives found for component '{component}'.")
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
    """Applies a chosen recipe to the meal plan for a specific date and meal type."""
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
    """Retrieve an active StructuredMealPlan for a specific profile and date."""
    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)
    plan = planner._get_active_meal_plan(profile_id, plan_date)
    if not plan:
        raise HTTPException(status_code=404, detail="No active meal plan found.")
    return plan


@router.post("/set-custom-meal")
def set_custom_meal(
    profile_id_A: str,
    profile_id_B: str,
    meal_type: str,
    current_date: date,
    body: CustomMealBody,
    db: Session = Depends(get_db)
):
    """Create a custom structured meal and apply it to the plan for the given date/meal_type."""
    planner = PlannerEngine(db)
    profile_A = planner._get_user_profile(profile_id_A)
    profile_B = planner._get_user_profile(profile_id_B)
    if not profile_A:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id_A}' not found.")
    if not profile_B:
        profile_B = schemas.UserProfile(id=profile_id_B, name="Dummy")

    def _make_qty(grams: float) -> dict:
        return {"qty": float(grams), "unit": "g", "grams_equiv": float(grams)}

    content = [
        {
            "name": body.carb_name,
            "food_group": "carboidrati",
            "quantities": {
                profile_A.id: _make_qty(body.carb_grams),
                profile_B.id: _make_qty(body.carb_grams),
            },
        },
        {
            "name": body.protein_name,
            "food_group": "proteina",
            "quantities": {
                profile_A.id: _make_qty(body.protein_grams),
                profile_B.id: _make_qty(body.protein_grams),
            },
        },
    ]
    if body.veg_name:
        content.append({
            "name": body.veg_name,
            "food_group": "verdure",
            "quantities": {
                profile_A.id: _make_qty(body.veg_grams),
                profile_B.id: _make_qty(body.veg_grams),
            },
        })

    recipe_data = {
        "name": body.title,
        "description": body.notes or "",
        "is_composed_dish": False,
        "content": content,
        "steps": [],
        "total_time_minutes": 30,
        "difficulty": "facile",
        "tags": {"manual": ["true"], "cooking_methods": ["tegame"], "mood": ["normale"], "cleanup": ["facile"]},
    }

    candidate_id = str(uuid.uuid4())
    db_candidate = database.CandidateRecipe(
        id=candidate_id,
        status="approved",
        recipe_data=recipe_data,
    )
    db.add(db_candidate)
    db.commit()

    success = planner.apply_recipe_to_plan(profile_id_A, profile_id_B, meal_type, current_date, candidate_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to apply custom meal to plan.")
    return {"message": "Custom meal applied.", "recipe_id": candidate_id}


@router.post("/free-meal")
def set_free_meal(
    profile_id_A: str,
    profile_id_B: str,
    meal_type: str,
    current_date: date,
    body: FreeMealBody,
    db: Session = Depends(get_db)
):
    """Mark a meal slot as a free meal (not tracked nutritionally)."""
    plan = _find_plan_covering_date(db, profile_id_A, current_date)
    if not plan:
        raise HTTPException(status_code=404, detail="No plan covers this date.")
    updated = copy.deepcopy(plan.daily_plans)
    for day in updated:
        if day["date"] == current_date.isoformat():
            for meal in day.get("meals", []):
                if meal["meal_type"] == meal_type:
                    meal["items"] = [{
                        "item_name": body.title,
                        "food_group": "free_meal",
                        "quantity": 0,
                        "unit": "",
                        "is_estimated_unit": False,
                        "alternatives": [],
                        "recipe_id": None,
                    }]
    plan.daily_plans = updated
    db.add(plan)
    db.commit()
    return {"message": "Free meal set."}


@router.delete("/free-meal")
def cancel_free_meal(
    profile_id_A: str,
    profile_id_B: str,
    meal_type: str,
    current_date: date,
    db: Session = Depends(get_db)
):
    """Cancel a free meal slot, restoring it to empty so user can assign a recipe."""
    plan = _find_plan_covering_date(db, profile_id_A, current_date)
    if not plan:
        raise HTTPException(status_code=404, detail="No plan covers this date.")
    updated = copy.deepcopy(plan.daily_plans)
    for day in updated:
        if day["date"] == current_date.isoformat():
            for meal in day.get("meals", []):
                if meal["meal_type"] == meal_type:
                    meal["items"] = []
    plan.daily_plans = updated
    db.add(plan)
    db.commit()
    return {"message": "Free meal cancelled."}


@router.get("/adherence")
def get_adherence(
    profile_id_A: str,
    start_date: Optional[date] = Query(default=None),
    days: int = 7,
    db: Session = Depends(get_db)
):
    """
    Returns weekly adherence stats for profile_id_A.
    Defaults to the current week (Monday → Sunday).
    """
    if start_date is None:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())  # Monday
    end_date = start_date + timedelta(days=days - 1)
    today = date.today()

    planned_slots = 0
    free_meals = 0
    plans = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id_A
    ).all()

    for plan in plans:
        for dp in plan.daily_plans:
            d = date.fromisoformat(dp["date"])
            if start_date <= d <= end_date:
                for meal in dp.get("meals", []):
                    planned_slots += 1
                    items = meal.get("items", [])
                    if items and items[0].get("food_group") == "free_meal":
                        free_meals += 1

    consumed_dates_meals: set = set()

    # Explicit ConsumedEntry marks (user clicked "Ho mangiato")
    explicit = db.query(database.ConsumedEntry).filter(
        database.ConsumedEntry.profile_id == profile_id_A,
        database.ConsumedEntry.type == "planned",
        database.ConsumedEntry.consumed_recipe_id != None,
        func.julianday(database.ConsumedEntry.date) >= func.julianday(start_date.isoformat()),
        func.julianday(database.ConsumedEntry.date) <= func.julianday(end_date.isoformat()),
    ).all()
    for e in explicit:
        consumed_dates_meals.add((e.date, e.meal_type))

    # Past slots with a recipe_id → assume eaten (optimistic)
    for plan in plans:
        for dp in plan.daily_plans:
            d = date.fromisoformat(dp["date"])
            if start_date <= d < today:
                for meal in dp.get("meals", []):
                    items = meal.get("items", [])
                    if items and items[0].get("recipe_id") and items[0].get("food_group") != "free_meal":
                        consumed_dates_meals.add((dp["date"], meal["meal_type"]))

    in_plan_consumed = len(consumed_dates_meals)
    score = round(in_plan_consumed / planned_slots, 2) if planned_slots > 0 else 0.0

    return {
        "planned_slots": planned_slots,
        "free_meals": free_meals,
        "in_plan_consumed": in_plan_consumed,
        "adherence_score": score,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
