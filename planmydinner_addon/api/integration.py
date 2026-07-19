"""
Superficie ufficiale per integrazioni esterne (es. OpenFit).

GET /integration/summary — in una sola chiamata: aderenza, conteggi pasti
liberi/saltati e kcal + macro per giorno con medie del periodo.
Il payload è versionato (campo "version"): i campi esistenti non cambiano
significato tra release; eventuali aggiunte sono retro-compatibili.
"""
import json
import logging
from datetime import date, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db, CandidateRecipe, ConsumedEntry, GeneratedWeeklyPlan, PlanRules, Recipe
from ..nutrition import NUTRITION_KEYS, compute_recipe_nutrition
from .planner import compute_adherence_stats

_LOGGER = logging.getLogger(__name__)

SUMMARY_VERSION = 1
_MAX_RANGE_DAYS = 366

router = APIRouter(
    prefix="/integration",
    tags=["integration"],
)


def _get_recipe_content(db: Session, recipe_id: str) -> Optional[Any]:
    """Restituisce il content (lista ingredienti) di una Recipe o CandidateRecipe."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if recipe:
        return recipe.content
    candidate = db.query(CandidateRecipe).filter(CandidateRecipe.id == recipe_id).first()
    if candidate:
        data = candidate.recipe_data
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                return None
        if isinstance(data, dict):
            return data.get("content")
    return None


@router.get("/today-status")
def get_today_status(
    profile_id: str,
    target_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """
    Stato dei pasti del giorno: cosa è pianificato e cosa risulta già registrato.
    Pensato per il sensore HA "pasti da registrare" (notifiche promemoria).
    Un pasto è "registrato" se esiste un ConsumedEntry per (profilo, data, pasto)
    oppure se lo slot è già marcato mensa / pasto libero / non mangiato.
    """
    d = target_date or date.today()
    iso = d.isoformat()

    from .planner import _find_plan_covering_date
    plan = _find_plan_covering_date(db, profile_id, d)
    meals = []
    if plan:
        daily = next((dp for dp in plan.daily_plans or [] if dp.get("date") == iso), None)
        for meal in (daily or {}).get("meals", []):
            items = meal.get("items", [])
            if not items:
                continue
            fg = items[0].get("food_group")
            meals.append({
                "meal_type": meal.get("meal_type"),
                "name": items[0].get("item_name"),
                "slot_status": fg,
                "logged": fg in ("mensa", "free_meal", "not_eaten"),
            })

    logged_types = {
        e.meal_type
        for e in db.query(ConsumedEntry).filter(
            ConsumedEntry.profile_id == profile_id,
            ConsumedEntry.date == iso,
        ).all()
    }
    for m in meals:
        if m["meal_type"] in logged_types:
            m["logged"] = True

    unlogged = [m["meal_type"] for m in meals if not m["logged"]]
    return {
        "date": iso,
        "meals": meals,
        "unlogged": unlogged,
        "unlogged_count": len(unlogged),
    }


@router.get("/plan-targets")
def get_plan_targets(request: Request, profile_id: str, db: Session = Depends(get_db)):
    """
    Obiettivi giornalieri TEORICI derivati dal piano della nutrizionista:
    media kcal/macro dei giorni del piano generato più recente (solo slot con
    ricetta pianificata, escluse le deviazioni mensa/liberi/saltati) + pasti
    fissi assunti (colazione/spuntini). Utile come base per i target.
    """
    llm_gateway = getattr(request.app.state, "llm_gateway", None)

    plan = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id,
    ).order_by(GeneratedWeeklyPlan.generated_at.desc()).first()
    if not plan:
        return {"targets": None, "detail": "Nessun piano generato."}

    def _recipe_nutrition(recipe_id: str):
        content = _get_recipe_content(db, recipe_id)
        if not content:
            return None
        try:
            return compute_recipe_nutrition(content, profile_id, llm_gateway=llm_gateway)
        except Exception:
            return None

    # Pasti fissi assunti ogni giorno
    from .routine import get_routine_meals
    routine_total = {k: 0.0 for k in NUTRITION_KEYS}
    for slot, meal in get_routine_meals(db, profile_id).items():
        if not meal["default_on"]:
            continue
        try:
            n = compute_recipe_nutrition(meal["content"], profile_id, llm_gateway=llm_gateway)
        except Exception:
            n = None
        if n:
            for k in NUTRITION_KEYS:
                routine_total[k] += n[k]

    day_totals = []
    for dp in plan.daily_plans or []:
        day = None
        for meal in dp.get("meals", []):
            items = meal.get("items", [])
            if not items or not items[0].get("recipe_id") or \
                    items[0].get("food_group") in ("mensa", "free_meal", "not_eaten"):
                continue   # solo il piano originale, non le deviazioni
            n = _recipe_nutrition(items[0]["recipe_id"])
            if n:
                if day is None:
                    day = {k: 0.0 for k in NUTRITION_KEYS}
                for k in NUTRITION_KEYS:
                    day[k] += n[k]
        if day:
            day_totals.append(day)

    if not day_totals:
        return {"targets": None, "detail": "Nessuna ricetta pianificata con dati nutrizionali."}

    targets = {
        k: round(sum(d[k] for d in day_totals) / len(day_totals) + routine_total[k], 1)
        for k in NUTRITION_KEYS
    }
    return {"targets": targets, "days_sampled": len(day_totals),
            "routine_included": any(v > 0 for v in routine_total.values())}


@router.get("/summary")
def get_integration_summary(
    request: Request,
    profile_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """
    Sintesi per integrazioni esterne su un periodo:
    aderenza, pasti liberi/saltati e nutrizione (kcal + macro) per giorno.

    Risponde sempre 200, anche senza dati nel periodo (campi a 0/None).
    """
    if start_date is None:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())  # lunedì corrente
    if end_date is None:
        end_date = start_date + timedelta(days=6)
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date must be >= start_date")
    if (end_date - start_date).days + 1 > _MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"Range too large (max {_MAX_RANGE_DAYS} days)")

    adherence = compute_adherence_stats(db, profile_id, start_date, end_date)

    llm_gateway = getattr(request.app.state, "llm_gateway", None)

    # Mappa date → pasti dal piano più recente che copre ogni giorno
    plans = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id,
    ).order_by(GeneratedWeeklyPlan.generated_at.desc()).all()

    meals_by_date: Dict[str, list] = {}
    for plan in plans:
        for dp in plan.daily_plans or []:
            d = dp.get("date")
            if d and d not in meals_by_date:  # il piano più recente vince
                meals_by_date[d] = dp.get("meals", [])

    nutrition_cache: Dict[str, Optional[Dict[str, Any]]] = {}

    def _nutrition_for_recipe(recipe_id: str) -> Optional[Dict[str, Any]]:
        if recipe_id not in nutrition_cache:
            content = _get_recipe_content(db, recipe_id)
            try:
                nutrition_cache[recipe_id] = compute_recipe_nutrition(
                    content, profile_id, llm_gateway=llm_gateway
                ) if content else None
            except Exception:
                _LOGGER.exception(f"Nutrition computation failed for recipe {recipe_id}")
                nutrition_cache[recipe_id] = None
        return nutrition_cache[recipe_id]

    # Pasti fissi (colazione/spuntini): assunti nei giorni senza eccezioni,
    # slot opt-in (es. dopo cena) contati solo se registrati.
    from .routine import SLOTS as ROUTINE_SLOTS, get_routine_meals
    routine_meals = get_routine_meals(db, profile_id)
    routine_nutrition: Dict[str, Optional[Dict[str, Any]]] = {}
    for slot, meal in routine_meals.items():
        try:
            routine_nutrition[slot] = compute_recipe_nutrition(
                meal["content"], profile_id, llm_gateway=llm_gateway
            )
        except Exception:
            routine_nutrition[slot] = None

    slot_entries: Dict[tuple, list] = {}
    for e in db.query(ConsumedEntry).filter(
        ConsumedEntry.profile_id == profile_id,
        ConsumedEntry.date >= start_date.isoformat(),
        ConsumedEntry.date <= end_date.isoformat(),
        ConsumedEntry.meal_type.in_(list(ROUTINE_SLOTS.keys())),
    ).all():
        slot_entries.setdefault((e.date, e.meal_type), []).append(e)

    def _routine_for_day(iso: str) -> Optional[Dict[str, float]]:
        total = None
        for slot in ROUTINE_SLOTS:
            meal = routine_meals.get(slot)
            entries = slot_entries.get((iso, slot), [])
            if any(e.type == "skipped" for e in entries):
                continue
            logged = [e for e in entries if e.type != "skipped" and e.consumed_recipe_id]
            n = None
            if logged:
                n = _nutrition_for_recipe(logged[0].consumed_recipe_id)
            elif meal and meal["default_on"]:
                n = routine_nutrition.get(slot)
            if n:
                if total is None:
                    total = {k: 0.0 for k in NUTRITION_KEYS}
                for k in NUTRITION_KEYS:
                    total[k] += n[k]
        return total

    days = []
    totals = {k: 0.0 for k in NUTRITION_KEYS}
    days_with_data = 0
    current = start_date
    while current <= end_date:
        iso = current.isoformat()
        meals = meals_by_date.get(iso, [])
        planned = 0
        free_meals = 0
        not_eaten = 0
        day_nutrition: Optional[Dict[str, float]] = None
        coverages = []
        for meal in meals:
            items = meal.get("items", [])
            if not items:
                continue
            fg = items[0].get("food_group")
            if fg == "free_meal":
                free_meals += 1
                continue
            if fg == "not_eaten":
                not_eaten += 1
                continue
            planned += 1
            recipe_id = items[0].get("recipe_id")
            if not recipe_id:
                continue
            nutrition = _nutrition_for_recipe(recipe_id)
            if nutrition:
                if day_nutrition is None:
                    day_nutrition = {k: 0.0 for k in NUTRITION_KEYS}
                for k in NUTRITION_KEYS:
                    day_nutrition[k] += nutrition[k]
                coverages.append(nutrition.get("coverage", 1.0))

        # Aggiungi i pasti fissi del giorno (colazione/spuntini assunti + opt-in registrati)
        routine_day = _routine_for_day(iso)
        if routine_day is not None:
            if day_nutrition is None:
                day_nutrition = {k: 0.0 for k in NUTRITION_KEYS}
            for k in NUTRITION_KEYS:
                day_nutrition[k] += routine_day[k]

        day_entry: Dict[str, Any] = {
            "date": iso,
            "meals_planned": planned,
            "free_meals": free_meals,
            "not_eaten": not_eaten,
            "nutrition": None,
            "routine_kcal": round(routine_day["kcal"], 1) if routine_day else 0,
        }
        if day_nutrition is not None:
            day_entry["nutrition"] = {k: round(day_nutrition[k], 1) for k in NUTRITION_KEYS}
            day_entry["nutrition"]["coverage"] = round(sum(coverages) / len(coverages), 2) if coverages else 1.0
            for k in NUTRITION_KEYS:
                totals[k] += day_nutrition[k]
            days_with_data += 1
        days.append(day_entry)
        current += timedelta(days=1)

    averages: Optional[Dict[str, Any]] = None
    if days_with_data:
        averages = {k: round(totals[k] / days_with_data, 1) for k in NUTRITION_KEYS}
        averages["days_with_data"] = days_with_data

    # Obiettivi giornalieri (se impostati nelle PlanRules del profilo)
    rules_row = db.query(PlanRules).filter(
        PlanRules.profile_id == profile_id
    ).order_by(PlanRules.imported_at.desc()).first()
    targets = rules_row.nutrition_targets if rules_row else None

    return {
        "version": SUMMARY_VERSION,
        "profile_id": profile_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "adherence": adherence,
        "days": days,
        "averages": averages,
        "targets": targets,
    }
