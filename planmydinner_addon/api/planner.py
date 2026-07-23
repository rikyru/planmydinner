from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any
from datetime import date, timedelta
import uuid
import copy
import logging

_LOGGER = logging.getLogger(__name__)

from pydantic import BaseModel as _BaseModel
from .. import schemas
from .. import database
from ..database import get_db, GeneratedWeeklyPlan
from ..planner import PlannerEngine, _LLM_CALL_LOG, _LLM_CALL_LOG_MAX


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
    carb_options: Optional[Dict[str, List[str]]] = None
    protein_options: Optional[Dict[str, List[str]]] = None
    frequency_targets: Optional[Dict[str, Any]] = None
    veg_target: Optional[Dict[str, Any]] = None
    free_meal_quota: Optional[int] = None
    nutrition_targets: Optional[Dict[str, float]] = None


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
    """Find the most recently generated plan whose 7-day window covers target_date."""
    plans = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id_A,
    ).order_by(GeneratedWeeklyPlan.generated_at.desc()).all()
    for plan in plans:
        plan_start = date.fromisoformat(plan.week_start_date)
        if plan_start <= target_date <= plan_start + timedelta(days=6):
            return plan
    return None


def _save_generated_plan(db: Session, profile_id_A: str, profile_id_B: Optional[str],
                         start_date: date, daily_plans: List[schemas.DailyPlannedMeals]) -> GeneratedWeeklyPlan:
    """Persist a generated weekly plan, replacing any overlapping existing plans."""
    # Delete all plans for this profile whose window overlaps with [start_date, start_date+6].
    # A plan with week_start W overlaps if W <= start_date+6 AND W+6 >= start_date,
    # i.e. W is in [start_date-6, start_date+6].
    end_date = start_date + timedelta(days=6)
    overlap_min = (start_date - timedelta(days=6)).isoformat()
    overlap_max = end_date.isoformat()
    old_plans = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id_A,
        GeneratedWeeklyPlan.week_start_date >= overlap_min,
        GeneratedWeeklyPlan.week_start_date <= overlap_max,
    ).all()
    for old in old_plans:
        db.delete(old)

    serialized = [dp.model_dump() for dp in daily_plans]
    new_plan = GeneratedWeeklyPlan(
        id=str(uuid.uuid4()),
        profile_id_A=profile_id_A,
        profile_id_B=profile_id_B,
        week_start_date=start_date.isoformat(),
        generated_at=date.today().isoformat(),
        daily_plans=serialized,
    )
    db.add(new_plan)
    db.commit()
    return new_plan


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/generate-week", response_model=List[schemas.DailyPlannedMeals])
def generate_weekly_plan(
    request: Request,
    profile_id_A: str,
    profile_id_B: str,
    current_date: date = date.today(),
    fantasy_mode: bool = False,
    ai_mode: Optional[str] = None,   # "off" | "per_slot" | "full_week" | None (use setting)
    db: Session = Depends(get_db)
):
    """Force-generate a 7-day plan from current_date and save it.

    ai_mode: if None, reads llm_generation_mode from AppSettings.
    Pass ai_mode explicitly to override the stored setting.
    """
    # Resolve effective ai_mode: explicit param > stored setting
    effective_ai_mode = ai_mode
    if effective_ai_mode is None:
        from ..database import AppSettings as AppSettingsDB
        settings_row = db.query(AppSettingsDB).filter(AppSettingsDB.id == 1).first()
        effective_ai_mode = (settings_row.llm_generation_mode if settings_row else None) or "off"

    # "off" means pure algorithmic (no ai_mode override)
    planner_ai_mode = None if effective_ai_mode == "off" else effective_ai_mode

    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)
    weekly_plan = planner.generate_weekly_plan(
        profile_id_A, profile_id_B, current_date,
        fantasy_mode=fantasy_mode,
        ai_mode=planner_ai_mode,
    )
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

    READ-ONLY: never generates or saves anything. A GET must not have side
    effects — auto-generating here used to silently delete any existing plan
    overlapping the requested window (via _save_generated_plan's overlap
    cleanup), wiping user edits (mensa entries, free meals...) the moment
    someone viewed a date that didn't exactly match a stored week_start_date.
    Use POST /planner/generate-week to explicitly generate a plan.
    """
    cached = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id_A,
        GeneratedWeeklyPlan.week_start_date == start_date.isoformat()
    ).first()
    if not cached:
        # Nessuna finestra che parte esattamente da start_date: cerca un piano
        # esistente la cui finestra copra comunque questa data (es. rolling
        # window non Monday-aligned) prima di arrendersi con 404.
        cached = _find_plan_covering_date(db, profile_id_A, start_date)
    if not cached:
        raise HTTPException(
            status_code=404,
            detail=f"No stored weekly plan covers {start_date.isoformat()} for '{profile_id_A}'."
        )
    try:
        return [schemas.DailyPlannedMeals.model_validate(dp) for dp in cached.daily_plans]
    except Exception:
        _LOGGER.exception(
            f"Stored weekly plan for '{profile_id_A}' ({start_date}) failed validation."
        )
        raise HTTPException(status_code=500, detail="Stored weekly plan is corrupted.")


@router.get("/generated-week")
def get_generated_week(
    profile_id_A: str,
    profile_id_B: Optional[str] = None,
    start_date: date = date.today(),
    db: Session = Depends(get_db)
):
    """
    Read-only: returns the stored weekly plan for start_date, or null if none exists.
    Never triggers generation. Safe to poll frequently (e.g. from HA coordinator).
    """
    cached = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id_A,
        GeneratedWeeklyPlan.week_start_date == start_date.isoformat()
    ).first()
    if not cached:
        return None
    try:
        return {
            "start_date": cached.week_start_date,
            "profile_id_B": cached.profile_id_B,
            "daily_plans": [schemas.DailyPlannedMeals.model_validate(dp) for dp in cached.daily_plans],
        }
    except Exception:
        # Piano salvato corrotto: per il coordinator HA equivale a "nessun piano"
        _LOGGER.exception(f"Stored weekly plan for '{profile_id_A}' failed validation in /generated-week.")
        return None


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


@router.get("/llm-log")
def get_llm_log(last: int = 20):
    """
    Restituisce gli ultimi N chiamate LLM con prompt e risposta grezza.
    Utile per verificare cosa viene chiesto all'AI e cosa risponde.
    ?last=N  (default 20, max 50)
    """
    n = min(last, _LLM_CALL_LOG_MAX)
    entries = _LLM_CALL_LOG[-n:] if _LLM_CALL_LOG else []
    return {
        "total_logged": len(_LLM_CALL_LOG),
        "returned": len(entries),
        "calls": list(reversed(entries)),  # most recent first
    }


@router.get("/debug-generate")
def debug_generate(
    request: Request,
    profile_id_A: str,
    profile_id_B: Optional[str] = None,
    start_date: date = date.today(),
    db: Session = Depends(get_db)
):
    """
    Dry-run generation: returns the full selection trace for each slot (14 total).
    Does NOT save anything to DB. Use this to diagnose why the same recipes are picked.

    Each slot in the response includes:
    - date, meal_type, target_protein_category
    - n_total_recipes: total recipes in DB
    - hard_constraint_pass / hard_constraint_fail: recipe names
    - protein_limit_filtered, used_ids_filtered, protein_cat_excluded,
      target_protein_narrowed, protein_item_filtered: names removed at each stage
    - scored_recipes: [{name, id, score}] sorted descending
    - n_final_candidates: how many were left after all filters
    - selected_name / selected_id: the recipe that would be chosen
    - protein_cat_counts_before: weekly protein counts at the time of this slot
    """
    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)
    trace = planner.debug_generate_weekly_plan(profile_id_A, profile_id_B, start_date)
    filled = sum(1 for s in trace if s.get("selected_id"))
    empty = sum(1 for s in trace if "selected_id" in s and not s["selected_id"])
    return {
        "summary": {
            "total_slots": len(trace),
            "filled": filled,
            "empty": empty,
            "profile_id_A": profile_id_A,
            "profile_id_B": profile_id_B,
            "start_date": start_date.isoformat(),
        },
        "slots": trace,
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
            "veg_target": plan_rules_db.veg_target,
            "free_meal_quota": plan_rules_db.free_meal_quota,
            "nutrition_targets": plan_rules_db.nutrition_targets,
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


@router.get("/debug-status")
def debug_status(
    profile_id_A: str,
    profile_id_B: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Diagnostica pre-generazione: mostra lo stato di PlanRules, pool ricette,
    CandidateRecipe, piano strutturale legacy, e la sequenza proteica che verrebbe
    costruita. Utile per capire perché il piano è vuoto o monotono.
    """
    from ..planner import PlannerEngine

    planner = PlannerEngine(db)

    # ── 1. PlanRules ──────────────────────────────────────────────────────
    plan_rules_db = db.query(database.PlanRules).filter(
        database.PlanRules.profile_id == profile_id_A
    ).order_by(database.PlanRules.imported_at.desc()).first()

    plan_rules_info = None
    protein_sequence = []
    if plan_rules_db:
        freq = plan_rules_db.frequency_targets or {}
        protein_sequence = PlannerEngine._build_protein_sequence(freq, n_slots=14)
        plan_rules_info = {
            "id": plan_rules_db.id,
            "imported_at": plan_rules_db.imported_at,
            "carb_target": plan_rules_db.carb_target,
            "protein_target": plan_rules_db.protein_target,
            "frequency_targets": freq,
            "veg_target": plan_rules_db.veg_target,
            "free_meal_quota": plan_rules_db.free_meal_quota,
            "carb_options_count": len(plan_rules_db.carb_options or {}),
            "protein_options_count": len(plan_rules_db.protein_options or {}),
        }

    # ── 2. Legacy StructuredMealPlan ──────────────────────────────────────
    legacy_plan = planner._get_latest_meal_plan(profile_id_A)
    legacy_info = None
    if legacy_plan:
        legacy_info = {
            "id": legacy_plan.id,
            "start_date": legacy_plan.start_date,
            "days": len(legacy_plan.daily_plans),
            "rotation_rules": len(legacy_plan.rotation_rules or []),
        }

    # ── 3. Generation path ────────────────────────────────────────────────
    generation_path = "plan_rules" if plan_rules_db else ("legacy" if legacy_plan else "none")

    # ── 4. Recipe pool ────────────────────────────────────────────────────
    all_recipes = planner._get_all_recipes()
    manual_count = sum(1 for r in all_recipes if "true" in (r.tags or {}).get("manual", []))
    food_groups_found: Dict[str, int] = {}
    for r in all_recipes:
        try:
            content = r.content if isinstance(r.content, list) else []
            for ing in content:
                fg = getattr(ing, "food_group", None) or (ing.get("food_group") if isinstance(ing, dict) else None)
                if fg == "proteine":
                    # Try to get protein item name for category mapping
                    pass
        except Exception:
            pass
    difficulties: Dict[str, int] = {}
    for r in all_recipes:
        difficulties[r.difficulty] = difficulties.get(r.difficulty, 0) + 1

    recipe_names = [r.name for r in all_recipes[:30]]

    # ── 5. CandidateRecipe ────────────────────────────────────────────────
    candidates = db.query(database.CandidateRecipe).all()
    candidate_by_status: Dict[str, int] = {}
    for c in candidates:
        candidate_by_status[c.status] = candidate_by_status.get(c.status, 0) + 1

    return {
        "generation_path": generation_path,
        "plan_rules": plan_rules_info,
        "legacy_plan": legacy_info,
        "protein_sequence_14": protein_sequence,
        "recipe_pool": {
            "total": len(all_recipes),
            "manual": manual_count,
            "by_difficulty": difficulties,
            "names_sample": recipe_names,
        },
        "candidate_recipes": {
            "total": len(candidates),
            "by_status": candidate_by_status,
        },
    }


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
    if body.carb_options is not None:
        plan_rules.carb_options = body.carb_options
    if body.protein_options is not None:
        plan_rules.protein_options = body.protein_options
    if body.frequency_targets is not None:
        plan_rules.frequency_targets = body.frequency_targets
    if body.veg_target is not None:
        plan_rules.veg_target = body.veg_target
    if body.free_meal_quota is not None:
        plan_rules.free_meal_quota = body.free_meal_quota
    if body.nutrition_targets is not None:
        plan_rules.nutrition_targets = body.nutrition_targets
    plan_rules.imported_at = datetime.now().isoformat()
    db.add(plan_rules)
    db.commit()
    return {"status": "ok"}


@router.get("/veg-portions")
def get_veg_portions():
    """Restituisce la tabella di equivalenze grammi/porzione per ogni verdura (valori di default)."""
    return PlannerEngine._VEG_PORTION_GRAMS


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
    use_llm_fill: bool = False,
    target_count: int = 5,
    db: Session = Depends(get_db)
):
    """Suggest alternative recipes for a meal.

    Di default propone solo ricette dal catalogo (le proprie), senza chiamare
    l'AI — veloce e senza costo. Passa use_llm_fill=true (con target_count
    alzato di conseguenza) per aggiungere proposte generate dall'AI: usato dal
    pulsante "Proponi N con AI" nella UI. Le opzioni generate dall'AI hanno
    divergence_strategy == "llm_generated"; il resto è catalogo.
    Se il catalogo non ha nessuna ricetta compatibile, l'AI scatta comunque
    come rete di sicurezza (una sola proposta) anche a use_llm_fill=False.
    """
    request_params = {"mood": mood, "cleanup": cleanup, "max_time_minutes": max_time_minutes}
    planner = PlannerEngine(db, llm_gateway=request.app.state.llm_gateway)

    # Build meal_plan_A from PlanRules if available (richer LLM prompt), else fall back to StructuredMealPlan
    plan_rules = planner._get_latest_plan_rules(profile_id_A)
    if plan_rules:
        meal_plan_A = planner._rules_to_planned_meal(plan_rules, meal_type, target_cat=None)
        meal_plan_B = schemas.PlannedMeal(meal_type=meal_type, items=[])
    else:
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
        meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, request_params,
        target_count=target_count, use_llm_fill=use_llm_fill,
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

    # Ricetta vera (tabella recipes), non un candidato interno al motore:
    # così compare nella pagina Ricette e resta modificabile/riusabile.
    # Dedupe per nome (case-insensitive): registrare di nuovo lo stesso pasto
    # personalizzato aggiorna la ricetta esistente invece di duplicarla.
    existing = db.query(database.Recipe).filter(
        func.lower(database.Recipe.name) == body.title.strip().lower()
    ).first()
    if existing:
        for key, value in recipe_data.items():
            setattr(existing, key, value)
        recipe_id = existing.id
        db.add(existing)
    else:
        recipe_id = str(uuid.uuid4())
        db.add(database.Recipe(id=recipe_id, **recipe_data))
    db.commit()

    success = planner.apply_recipe_to_plan(profile_id_A, profile_id_B, meal_type, current_date, recipe_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to apply custom meal to plan.")
    return {"message": "Custom meal applied.", "recipe_id": recipe_id}


@router.post("/free-meal")
def set_free_meal(
    request: Request,
    profile_id_A: str,
    profile_id_B: str,
    meal_type: str,
    current_date: date,
    body: FreeMealBody,
    db: Session = Depends(get_db)
):
    """
    Mark a meal slot as a free meal. Prova a stimare kcal/macro dalla
    descrizione (best-effort, via LLM, es. "kebab" -> ingredienti + grammi
    ipotizzati): se riesce, il pasto libero non viene più escluso dalle
    medie del periodo in /integration/summary. Se la stima non è
    disponibile (LLM spento) resta "ignoto" come prima.
    """
    plan = _find_plan_covering_date(db, profile_id_A, current_date)
    if not plan:
        raise HTTPException(status_code=404, detail="No plan covers this date.")

    recipe_id = None
    gw = getattr(request.app.state, "llm_gateway", None)
    if gw is not None and getattr(gw, "_client", None) is not None:
        description = f"{body.title} {body.notes}".strip()
        try:
            result = gw.estimate_meal_from_text(description)
        except Exception:
            _LOGGER.exception(f"Stima pasto libero fallita per '{description}'")
            result = None
        if result:
            content = [
                {
                    "name": ing["name"],
                    "food_group": ing["food_group"],
                    "quantities": {profile_id_A: {"qty": ing["grams"], "unit": "g", "grams_equiv": ing["grams"]}},
                }
                for ing in result["ingredients"] if ing.get("grams", 0) > 0
            ]
            if content:
                cand = database.CandidateRecipe(
                    id=str(uuid.uuid4()),
                    status="draft_structured",
                    recipe_data={
                        "name": result["name"],
                        "description": f"Pasto libero (stima automatica): {body.title}",
                        "is_composed_dish": False,
                        "content": content,
                        "steps": [],
                        "total_time_minutes": 0,
                        "difficulty": "sconosciuto",
                        "tags": {"free_meal_estimate": ["true"]},
                    },
                )
                db.add(cand)
                db.commit()
                recipe_id = cand.id

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
                        "recipe_id": recipe_id,
                    }]
    plan.daily_plans = updated
    db.add(plan)
    db.commit()
    return {"message": "Free meal set.", "estimated": recipe_id is not None}


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


@router.post("/not-eaten")
def set_not_eaten(
    profile_id_A: str,
    profile_id_B: str,
    meal_type: str,
    current_date: date,
    db: Session = Depends(get_db)
):
    """Mark a past meal slot as not eaten (reduces adherence score)."""
    plan = _find_plan_covering_date(db, profile_id_A, current_date)
    if not plan:
        raise HTTPException(status_code=404, detail="No plan covers this date.")
    updated = copy.deepcopy(plan.daily_plans)
    for day in updated:
        if day["date"] == current_date.isoformat():
            for meal in day.get("meals", []):
                if meal["meal_type"] == meal_type:
                    meal["items"] = [{
                        "item_name": "Non mangiato",
                        "food_group": "not_eaten",
                        "quantity": 0,
                        "unit": "",
                        "is_estimated_unit": False,
                        "alternatives": [],
                        "recipe_id": None,
                    }]
    plan.daily_plans = updated
    db.add(plan)
    db.commit()
    return {"message": "Meal marked as not eaten."}


@router.delete("/not-eaten")
def cancel_not_eaten(
    profile_id_A: str,
    profile_id_B: str,
    meal_type: str,
    current_date: date,
    db: Session = Depends(get_db)
):
    """Cancel a not-eaten mark, restoring the slot to empty."""
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
    return {"message": "Not-eaten mark cancelled."}


def compute_adherence_stats(db: Session, profile_id_A: str, start_date: date, end_date: date) -> Dict[str, Any]:
    """Calcola le statistiche di aderenza nel periodo [start_date, end_date].

    Logica condivisa fra GET /planner/adherence e GET /integration/summary.
    """
    today = date.today()

    planned_slots = 0
    free_meals = 0
    not_eaten_slots = 0
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
                    if items:
                        fg = items[0].get("food_group")
                        if fg == "free_meal":
                            free_meals += 1
                        elif fg == "not_eaten":
                            not_eaten_slots += 1

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

    # Past slots with a recipe_id → assume eaten (optimistic), exclude free_meal and not_eaten
    for plan in plans:
        for dp in plan.daily_plans:
            d = date.fromisoformat(dp["date"])
            if start_date <= d < today:
                for meal in dp.get("meals", []):
                    items = meal.get("items", [])
                    if items and items[0].get("recipe_id") and \
                            items[0].get("food_group") not in ("free_meal", "not_eaten"):
                        consumed_dates_meals.add((dp["date"], meal["meal_type"]))

    in_plan_consumed = len(consumed_dates_meals)
    score = round(in_plan_consumed / planned_slots, 2) if planned_slots > 0 else 0.0

    # Fetch free_meal_quota from PlanRules
    plan_rules_db = db.query(database.PlanRules).filter(
        database.PlanRules.profile_id == profile_id_A
    ).order_by(database.PlanRules.imported_at.desc()).first()
    free_meal_quota = plan_rules_db.free_meal_quota if plan_rules_db else None

    return {
        "planned_slots": planned_slots,
        "free_meals": free_meals,
        "not_eaten_slots": not_eaten_slots,
        "in_plan_consumed": in_plan_consumed,
        "adherence_score": score,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "free_meal_quota": free_meal_quota,
    }


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
    return compute_adherence_stats(db, profile_id_A, start_date, end_date)
