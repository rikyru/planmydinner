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
from .nutrition import DEFAULT_COOKING_FAT_G, compute_recipe_nutrition, recipe_nutrition_split

_LOGGER = logging.getLogger(__name__)

SCALE_MIN = 0.6
SCALE_MAX = 1.4
# Meal slots that are deviations, not a planned recipe: never scaled.
_DEVIATION_FG = ("mensa", "free_meal", "not_eaten")


def _latest_rules(db: Session, profile_id: str):
    return (
        db.query(PlanRules)
        .filter(PlanRules.profile_id == profile_id)
        .order_by(PlanRules.imported_at.desc())
        .first()
    )


def get_nutrition_targets(db: Session, profile_id: str) -> Optional[Dict[str, float]]:
    """The daily kcal/macro targets stored for a profile (most recent rules)."""
    row = _latest_rules(db, profile_id)
    return row.nutrition_targets if row and row.nutrition_targets else None


def day_target_kcal(flat: Optional[Dict[str, float]], by_date: Optional[Dict[str, Any]],
                    iso: str) -> Optional[float]:
    """Target kcal per uno specifico giorno: usa la periodizzazione (by_date) se
    presente per quella data, altrimenti il target piatto. Così i giorni di
    allenamento intenso possono avere più kcal del giorno di riposo."""
    if by_date and iso in by_date and (by_date[iso] or {}).get("kcal"):
        return float(by_date[iso]["kcal"])
    if flat and flat.get("kcal"):
        return float(flat["kcal"])
    return None


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

    rules = _latest_rules(db, profile_id)
    targets = rules.nutrition_targets if rules else None
    by_date = rules.nutrition_targets_by_date if rules else None
    if not (targets and targets.get("kcal")) and not by_date:
        return daily_plans
    # In a cut the caller asks not to inflate portions (allow_upscale=0): a
    # deficit may only shrink a meal, never grow it beyond its planned size,
    # so a too-low base plan is never blown up to chase the target.
    allow_upscale = bool((targets or {}).get("allow_upscale", 1.0))

    today = today or date.today()
    routine_kcal = _routine_kcal(db, profile_id, llm_gateway)

    # Per meal: (kcal fisse = proteine/verdure/grassi, kcal scalabili = carboidrati).
    split_cache: Dict[str, Optional[tuple]] = {}

    def _meal_split(recipe_id: str):
        if recipe_id not in split_cache:
            content = _recipe_content(db, recipe_id)
            try:
                split_cache[recipe_id] = recipe_nutrition_split(
                    content, profile_id, llm_gateway=llm_gateway,
                    add_cooking_fat_g=DEFAULT_COOKING_FAT_G) if content else None
            except Exception:
                split_cache[recipe_id] = None
        return split_cache[recipe_id]

    for dp in daily_plans:
        try:
            day = date.fromisoformat(dp.date)
        except Exception:
            day = None
        if day is not None and day < today:
            continue  # don't rewrite portions of already-consumed days

        # Target del giorno (periodizzazione: più kcal nei giorni di allenamento)
        tk = day_target_kcal(targets, by_date, dp.date)
        if not tk:
            continue
        budget = max(tk - routine_kcal, 0.0)

        scalable = []           # (meal, fixed_kcal, carb_kcal)
        fixed_kcal = 0.0
        carb_kcal = 0.0
        for meal in dp.meals:
            if not meal.items:
                continue
            first = meal.items[0]
            if first.food_group in _DEVIATION_FG or not first.recipe_id:
                continue
            split = _meal_split(first.recipe_id)
            if not split:
                continue
            fx, sc = split
            scalable.append(meal)
            fixed_kcal += fx["kcal"]
            carb_kcal += sc["kcal"]

        if not scalable:
            continue

        # Scala SOLO i carboidrati per centrare il budget, lasciando intatte
        # proteine e verdure: carb_scale tale che fisse + carbo×s = budget.
        if carb_kcal <= 0:
            continue  # nessun carboidrato da regolare: niente da scalare
        scale = (budget - fixed_kcal) / carb_kcal
        if not allow_upscale:
            scale = min(scale, 1.0)
        scale = max(SCALE_MIN, min(SCALE_MAX, scale))
        for meal in scalable:
            meal.scale = round(scale, 3)

    return daily_plans
