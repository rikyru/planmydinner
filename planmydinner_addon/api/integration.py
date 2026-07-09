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

from ..database import get_db, CandidateRecipe, GeneratedWeeklyPlan, Recipe
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

        day_entry: Dict[str, Any] = {
            "date": iso,
            "meals_planned": planned,
            "free_meals": free_meals,
            "not_eaten": not_eaten,
            "nutrition": None,
        }
        if day_nutrition is not None:
            day_entry["nutrition"] = {k: round(day_nutrition[k], 1) for k in NUTRITION_KEYS}
            day_entry["nutrition"]["coverage"] = round(sum(coverages) / len(coverages), 2)
            for k in NUTRITION_KEYS:
                totals[k] += day_nutrition[k]
            days_with_data += 1
        days.append(day_entry)
        current += timedelta(days=1)

    averages: Optional[Dict[str, Any]] = None
    if days_with_data:
        averages = {k: round(totals[k] / days_with_data, 1) for k in NUTRITION_KEYS}
        averages["days_with_data"] = days_with_data

    return {
        "version": SUMMARY_VERSION,
        "profile_id": profile_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "adherence": adherence,
        "days": days,
        "averages": averages,
    }
