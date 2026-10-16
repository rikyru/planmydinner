"""Adattamento giorno per giorno del piano "dal mio storico".

Le ricette scelte dallo storico restano quelle che mangi davvero, ma ogni pasto
riceve le SUE porzioni (``PlannedItem.portions``) per quel giorno:

- la proteina alla grammatura indicata dalla nutrizionista per quell'alimento;
- il carboidrato partendo dalla grammatura della nutrizionista e regolato per
  centrare la quota kcal del giorno (obiettivo − colazione/spuntini, ÷ 2 pasti,
  con la periodizzazione degli allenamenti);
- il condimento esplicito ridotto se i grassi sforano.

La ricetta di catalogo non viene modificata.
"""
import logging
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from .nutrition import (NUTRITION_KEYS, _DRY_CEREALS, _match_table_key, compute_recipe_nutrition,
                        is_cooked_weight, plan_portions)
from .scaling import _latest_rules, _recipe_content, day_target_kcal

_LOGGER = logging.getLogger(__name__)

MAIN_MEALS = ("pranzo", "cena")
_MEAT_FISH = ("carne_bianca", "carne_rossa", "pesce", "pollo")


def routine_totals(db: Session, profile_id: str, llm_gateway: Any = None) -> Dict[str, float]:
    """kcal e macro dei pasti fissi assunti ogni giorno (colazione/spuntini)."""
    from .api.routine import get_routine_meals
    tot = {k: 0.0 for k in NUTRITION_KEYS}
    for meal in get_routine_meals(db, profile_id).values():
        if not meal["default_on"]:
            continue
        try:
            n = compute_recipe_nutrition(meal["content"], profile_id, llm_gateway=llm_gateway)
        except Exception:
            n = None
        for k in NUTRITION_KEYS:
            tot[k] += (n or {}).get(k, 0.0)
    return tot


def meal_quota(targets: Optional[Dict[str, Any]], by_date: Optional[Dict[str, Any]], iso: str,
               routine: Dict[str, float]) -> Dict[str, float]:
    """Quota di un pasto principale: (obiettivo del giorno − pasti fissi) ÷ 2."""
    quota: Dict[str, float] = {}
    tk = day_target_kcal(targets, by_date, iso)
    if tk:
        quota["kcal"] = max(tk - routine.get("kcal", 0), 0) / len(MAIN_MEALS)
    for k in ("protein_g", "carbs_g", "fat_g"):
        v = (targets or {}).get(k)
        if v:
            quota[k] = max(float(v) - routine.get(k, 0), 0) / len(MAIN_MEALS)
    return quota


def _same_food(a: str, b: str) -> bool:
    from .planner import PlannerEngine
    if PlannerEngine._rotation_key(a) == PlannerEngine._rotation_key(b):
        return True
    ka, kb = _match_table_key(a.lower()), _match_table_key(b.lower())
    return bool(ka and ka == kb)


def nutritionist_portion_lookup(rules: Any, meal_type: str):
    """Funzione (kind, part) → (nome, grammi) con le grammature del piano della
    nutrizionista per quel pasto: prima l'alimento esatto fra le opzioni, poi il
    target generico (proteine per carne/pesce, carboidrati per i cereali secchi)."""
    def _options(field):
        opts = (getattr(rules, field, None) or {}).get(meal_type) or []
        return [(o.get("name"), float(o.get("quantity") or 0)) for o in opts
                if isinstance(o, dict) and o.get("name") and o.get("quantity")]

    prot_opts, carb_opts = _options("protein_options"), _options("carb_options")
    prot_t = (getattr(rules, "protein_target", None) or {}).get(meal_type)
    carb_t = (getattr(rules, "carb_target", None) or {}).get(meal_type)

    def lookup(kind: str, part: Dict[str, Any]) -> Optional[Tuple[str, float]]:
        name = part["name"]
        for opt_name, grams in (prot_opts if kind == "protein" else carb_opts):
            if _same_food(name, opt_name):
                return opt_name, grams
        if kind == "protein" and prot_t and part["food_group"] in _MEAT_FISH:
            return name, float(prot_t)
        if kind == "carb" and carb_t and part.get("key") in _DRY_CEREALS and not is_cooked_weight(name):
            return name, float(carb_t)
        return None
    return lookup


def adapt_plan_portions(db: Session, profile_id: str, daily_plans: List[Any],
                        llm_gateway: Any = None, today: Optional[date] = None,
                        skip: Optional[Set[Tuple[str, str]]] = None) -> int:
    """Imposta ``portions`` e ``adapt_note`` sui pasti di ricetta dai giorni da
    oggi in poi (``skip`` = slot già registrati da non toccare). Ritorna quanti
    pasti sono stati adattati."""
    rules = _latest_rules(db, profile_id)
    if rules is None:
        return 0
    today = today or date.today()
    skip = skip or set()
    routine = routine_totals(db, profile_id, llm_gateway)
    targets = rules.nutrition_targets or None
    by_date = rules.nutrition_targets_by_date or None
    lookups = {mt: nutritionist_portion_lookup(rules, mt) for mt in MAIN_MEALS}
    adapted = 0
    for dp in daily_plans:
        try:
            if date.fromisoformat(dp.date) < today:
                continue
        except ValueError:
            continue
        quota = meal_quota(targets, by_date, dp.date, routine)
        for meal in dp.meals:
            if (dp.date, meal.meal_type) in skip or not meal.items:
                continue
            item = meal.items[0]
            if not item.recipe_id or item.food_group != "recipe":
                continue
            content = _recipe_content(db, item.recipe_id)
            if not content:
                continue
            try:
                res = plan_portions(content, profile_id, quota or None,
                                    portion_for=lookups.get(meal.meal_type),
                                    llm_gateway=llm_gateway)
            except Exception:
                _LOGGER.exception(f"[adatta] porzioni fallite per {item.recipe_id}")
                res = None
            if not res:
                continue
            item.portions = res["portions"] or None
            note = []
            if quota.get("kcal"):
                note.append(f"quota {round(quota['kcal'])} kcal")
            item.adapt_note = note + res["notes"]
            meal.scale = 1.0
            adapted += 1
    return adapted
