"""Portion scaling to hit a daily energy target (``PlanRules.nutrition_targets``).

Recipe-based meals carry their grams inside the shared catalogue recipe, so to
change a day's energy without mutating recipes used elsewhere we set a per-meal
``scale`` factor on the generated plan. The nutrition computation and the
shopping list honour it, keeping portions and groceries consistent.

A target is optional. Without a ``kcal`` target every meal stays at ``scale``
1.0 — exactly the historical behaviour. The factor is clamped to a sensible
band so a target can nudge portions, not turn a plate into a joke.
"""
import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .database import CandidateRecipe, PlanRules, Recipe
from .nutrition import compute_recipe_nutrition

_LOGGER = logging.getLogger(__name__)

SCALE_MIN = 0.6
SCALE_MAX = 1.4
# Meal slots that are deviations, not a planned recipe: never scaled.
_DEVIATION_FG = ("mensa", "free_meal", "not_eaten")


def get_nutrition_targets(db: Session, profile_id: str) -> Optional[Dict[str, float]]:
    """The daily kcal/macro targets stored for a profile (most recent rules)."""
    row = (
        db.query(PlanRules)
        .filter(PlanRules.profile_id == profile_id)
        .order_by(PlanRules.imported_at.desc())
        .first()
    )
    return row.nutrition_targets if row and row.nutrition_targets else None


def _recipe_content(db: Session, recipe_id: str) -> Optional[Any]:
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


def _routine_kcal(db: Session, profile_id: str, llm_gateway: Any) -> float:
    """kcal of the fixed daily meals (breakfast/snacks that are on by default)."""
    from .api.routine import get_routine_meals

    total = 0.0
    for _slot, meal in get_routine_meals(db, profile_id).items():
        if not meal.get("default_on"):
            continue
        try:
            n = compute_recipe_nutrition(meal["content"], profile_id, llm_gateway=llm_gateway)
        except Exception:
            n = None
        if n:
            total += n["kcal"]
    return total


def apply_nutrition_scaling(
    db: Session,
    profile_id: str,
    daily_plans: List[Any],
    llm_gateway: Any = None,
    today: Optional[date] = None,
) -> List[Any]:
    """Set each meal's ``scale`` so the day's energy approaches the target.

    ``daily_plans`` is a list of ``schemas.DailyPlannedMeals`` (mutated in
    place and returned). Every meal is first normalised to ``scale`` 1.0, so
    re-running is idempotent. With no kcal target set, that normalisation is
    all that happens. Past days are left at 1.0 so portions of meals that were
    already eaten are never rewritten.
    """
    # Normalise first — a re-generation must not inherit stale scales.
    for dp in daily_plans:
        for meal in dp.meals:
            meal.scale = 1.0

    targets = get_nutrition_targets(db, profile_id)
    target_kcal = (targets or {}).get("kcal")
    if not target_kcal or target_kcal <= 0:
        return daily_plans

    today = today or date.today()
    routine_kcal = _routine_kcal(db, profile_id, llm_gateway)
    budget = max(target_kcal - routine_kcal, 0.0)

    nut_cache: Dict[str, Optional[float]] = {}

    def _meal_kcal(recipe_id: str) -> Optional[float]:
        if recipe_id not in nut_cache:
            content = _recipe_content(db, recipe_id)
            try:
                n = compute_recipe_nutrition(content, profile_id, llm_gateway=llm_gateway) if content else None
            except Exception:
                n = None
            nut_cache[recipe_id] = n["kcal"] if n else None
        return nut_cache[recipe_id]

    for dp in daily_plans:
        try:
            day = date.fromisoformat(dp.date)
        except Exception:
            day = None
        if day is not None and day < today:
            continue  # don't rewrite portions of already-consumed days

        scalable = []
        planned_kcal = 0.0
        for meal in dp.meals:
            if not meal.items:
                continue
            first = meal.items[0]
            if first.food_group in _DEVIATION_FG or not first.recipe_id:
                continue
            kcal = _meal_kcal(first.recipe_id)
            if kcal and kcal > 0:
                scalable.append(meal)
                planned_kcal += kcal

        if not scalable or planned_kcal <= 0:
            continue

        scale = max(SCALE_MIN, min(SCALE_MAX, budget / planned_kcal))
        for meal in scalable:
            meal.scale = round(scale, 3)

    return daily_plans
