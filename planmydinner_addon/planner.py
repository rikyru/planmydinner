import logging
import os
import uuid
import json
import random
from datetime import date, timedelta
from typing import List, Dict, Any, Optional
import re

from sqlalchemy.orm import Session
from sqlalchemy import func

from . import schemas
from .database import (
    UserProfile, StructuredMealPlan, Recipe, CandidateRecipe,
    PantryItem, ConsumedEntry, RotationRule, SeasonalityItem, UnitConversion,
    GeneratedWeeklyPlan, PlanRules
)
from .llm_gateway import LLMGateway

_LOGGER = logging.getLogger(__name__)

# In-memory ring buffer of the last 50 LLM calls — accessible via GET /planner/llm-log
_LLM_CALL_LOG: list = []
_LLM_CALL_LOG_MAX = 50


def get_week_start(d: date) -> date:
    """Returns the Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


class PlannerEngine:
    """
    Core logic for filtering, dosing, and ranking recipes based on meal plans, profiles,
    pantry, seasonality, and consumption history.
    """
    QUANTITY_TOLERANCE_PERCENT = 0.40 # +/- 40% — covers real-world portion variation (es. 150g vs 120g target)
    ANTI_REPETITION_DAYS = 7 # Defined as a class variable

    def __init__(self, db: Session, llm_gateway: Optional[LLMGateway] = None):
        self.db = db
        self.llm_gateway = llm_gateway

    def _get_user_profile(self, profile_id: str) -> Optional[schemas.UserProfile]:
        db_profile = self.db.query(UserProfile).filter(UserProfile.id == profile_id).first()
        if db_profile:
            return schemas.UserProfile.from_orm(db_profile)
        return None

    def _get_active_meal_plan(self, profile_id: str, current_date: date) -> Optional[schemas.StructuredMealPlan]:
        _LOGGER.debug(f"Searching for active meal plan for profile {profile_id} on date {current_date.isoformat()}")
        # Prendi tutti i piani con start_date <= current_date, ordinati dal più recente.
        # La finestra 7-days era hardcoded e non funzionava per piani mensili/bimestrali.
        # Verifichiamo in Python se current_date è coperta dalle daily_plans del piano.
        db_plans = self.db.query(StructuredMealPlan).filter(
            StructuredMealPlan.profile_id == profile_id,
            StructuredMealPlan.start_date <= current_date.isoformat(),
        ).order_by(StructuredMealPlan.start_date.desc()).all()

        for db_plan in db_plans:
            plan = schemas.StructuredMealPlan.from_orm(db_plan)
            plan_dates = {dp.date for dp in plan.daily_plans}
            if current_date.isoformat() in plan_dates:
                _LOGGER.debug(f"Found active meal plan: {db_plan.id} starting on {db_plan.start_date}")
                return plan

        _LOGGER.debug(f"No active meal plan found for profile {profile_id}")
        return None

    def _get_latest_meal_plan(self, profile_id: str) -> Optional[schemas.StructuredMealPlan]:
        """Returns the most recently imported meal plan for a profile, regardless of specific dates.
        Used so that future-date generation works by mapping day-of-week from the plan."""
        db_plan = self.db.query(StructuredMealPlan).filter(
            StructuredMealPlan.profile_id == profile_id,
        ).order_by(StructuredMealPlan.start_date.desc()).first()
        if db_plan:
            return schemas.StructuredMealPlan.from_orm(db_plan)
        return None

    def _get_latest_plan_rules(self, profile_id: str) -> Optional[schemas.PlanRules]:
        """Returns the most recently imported PlanRules for a profile, or None."""
        db_rules = self.db.query(PlanRules).filter(
            PlanRules.profile_id == profile_id
        ).order_by(PlanRules.imported_at.desc()).first()
        return schemas.PlanRules.from_orm(db_rules) if db_rules else None

    def _get_consumed_entries(self, profile_id: str, end_date: date, days_back: int) -> List[schemas.ConsumedEntry]:
        start_date = end_date - timedelta(days=days_back)
        db_entries = self.db.query(ConsumedEntry).filter(
            ConsumedEntry.profile_id == profile_id,
            func.julianday(ConsumedEntry.date) >= func.julianday(start_date.isoformat()),
            func.julianday(ConsumedEntry.date) <= func.julianday(end_date.isoformat())
        ).all()
        return [schemas.ConsumedEntry.from_orm(entry) for entry in db_entries]

    def _get_pantry_items(self) -> List[schemas.PantryItem]:
        db_items = self.db.query(PantryItem).all()
        return [schemas.PantryItem.from_orm(item) for item in db_items]

    def _get_seasonality_data(self) -> Dict[str, schemas.SeasonalityItem]:
        db_items = self.db.query(SeasonalityItem).all()
        return {item.ingredient_name.lower(): schemas.SeasonalityItem.from_orm(item) for item in db_items}

    def _get_all_recipes(self) -> List[schemas.Recipe]:
        db_recipes = self.db.query(Recipe).all()
        db_candidate_recipes = self.db.query(CandidateRecipe).filter(CandidateRecipe.status == "approved").all()

        all_recipes = []
        for rec in db_recipes:
            try:
                all_recipes.append(schemas.Recipe.from_orm(rec))
            except Exception as e:
                _LOGGER.warning(f"Recipe {rec.id} non valida, saltata: {e}")
        for cand in db_candidate_recipes:
            data = cand.recipe_data if isinstance(cand.recipe_data, dict) else cand.recipe_data.model_dump()
            try:
                rec = schemas.Recipe(**data, id=cand.id)
                rec._is_candidate = True
                all_recipes.append(rec)
            except Exception as e:
                _LOGGER.warning(f"CandidateRecipe {cand.id} non valida, saltata: {e}")
        for rec in all_recipes:
            self._normalize_recipe_protein_groups(rec)
        return all_recipes

    def _normalize_recipe_protein_groups(self, rec: schemas.Recipe) -> None:
        """Sostituisce in-memory i food_group proteici generici ("proteina") con la
        categoria dedotta dal nome dell'ingrediente (es. "vitellone" → carne_rossa).

        Senza questa normalizzazione le ricette generiche sfuggono ai limiti di
        categoria settimanali, al narrowing sul target e all'esclusione same-day.
        Non tocca il DB: vale solo per la selezione del planner.
        """
        try:
            ingredients = rec.content.components if rec.is_composed_dish else rec.content
            for ing in ingredients:
                fg = (ing.food_group or "").lower()
                if fg in ("proteina", "proteine"):
                    inferred = self._infer_protein_fg(ing.name, fg)
                    if inferred not in ("proteina", "proteine"):
                        ing.food_group = inferred
        except Exception:
            pass  # ricette con content anomalo: lascia i food_group originali

    def _normalize_food_group(self, food_group: str) -> str:
        """Normalizes food group names to a singular, consistent format."""
        if not food_group:
            return "altro"
        food_group_lower = food_group.lower()
        if food_group_lower.endswith('i'):
            return food_group_lower[:-1]
        return food_group_lower

    def _get_food_group_for_item(self, item_name: str) -> Optional[str]:
        """
        Determines food group for a given item name using a high-confidence keyword whitelist.
        """
        item_lower = item_name.lower()
        _LOGGER.debug(f"Attempting to get food group for item: '{item_name}'")

        keyword_map = {
            "carne_rossa": [r"\bmanzo\b", r"\bbistecca\b", r"\bcarne trita\b", r"\bsalsiccia\b",
                            r"\bvitellone\b", r"\bbovino\b", r"\bagnello\b", r"\bcinghiale\b", r"\bmaiale\b"],
            "carne_bianca": [r"\bpollo\b", r"\bpetto di pollo\b", r"\bpetti di pollo\b",
                             r"\btacchino\b", r"\bsovracoscio\b",
                             r"\bprosciutto cotto\b", r"\bprosciutto crudo\b"],
            "legumi": [r"\bceci\b", r"\blenticchie\b", r"\bfagioli\b", r"\bpiselli\b", r"\bfave\b"],
            "pesce": [r"\bpesce\b", r"\bsalmone\b", r"\btonno\b", r"\bmerluzzo\b",
                      r"\borata\b", r"\bspigola\b", r"\bsgombro\b"],
            "carboidrato": [r"\bpasta\b", r"\briso\b", r"\bpane\b", r"\bpatate\b"],
            "verdura": [
                r"\bverdura\b", r"\binsalata\b", r"\bpomodoro\b", r"\bcetriolo\b", r"\bcarota\b", r"\bpeperone\b",
                r"\bcipolla\b", r"\baglio\b", r"\bmelanzana\b", r"\bzucchina\b", r"\bspinaci\b", r"\bbroccoli\b",
                r"\bcavolfiore\b", r"\bfinocchio\b", r"\bsedano\b", r"\basparagi\b", r"\bfungo\b", r"\bradicchio\b",
                r"\bbarbabietola\b", r"\bzucca\b"
            ],
            "grasso": [r"\bolio\b", r"\bburro\b", r"\bfrutta secca\b", r"\bnoci\b", r"\bmandorle\b"],
            "frutta": [r"\bmela\b", r"\bbanana\b", r"\barancia\b", r"\bfragola\b", r"\bfrutta\b"],
            "proteina": [r"\buova\b", r"\btofu\b"],
            "latticini": [r"\bmozzarella\b", r"\bricotta\b", r"\bcrescenza\b", r"\bgrana\b",
                          r"\bparmigiano\b", r"\bformaggio\b", r"\bfiocchi di latte\b",
                          r"\bstracchino\b", r"\bscamorza\b", r"\bpecorino\b", r"\bemmental\b"],
        }

        for group, keywords in keyword_map.items():
            for keyword_regex in keywords:
                if re.search(keyword_regex, item_lower):
                    _LOGGER.debug(f"Matched '{item_name}' with keyword '{keyword_regex}' to group '{group}'")
                    return group
            
        _LOGGER.debug(f"No food group found for item: '{item_name}'")
        return None

    def _filter_hard_constraints(
        self,
        recipe: schemas.Recipe,
        target_meal_plan_A: schemas.PlannedMeal,
        target_meal_plan_B: schemas.PlannedMeal,
        profile_A: schemas.UserProfile,
        profile_B: schemas.UserProfile,
        consumed_entries_A: List[schemas.ConsumedEntry],
        consumed_entries_B: List[schemas.ConsumedEntry],
        request_params: Dict[str, Any],
        current_date: date
    ) -> (bool, Optional[str], Optional[str]):
        _LOGGER.debug(f"Filtering recipe: {recipe.id}")

        if recipe.total_time_minutes > request_params.get("max_time_minutes", 9999) or \
           (request_params.get("mood") and request_params["mood"] not in recipe.tags.get("mood", [])) or \
           (request_params.get("cleanup") and request_params["cleanup"] not in recipe.tags.get("cleanup", [])):
            return False, None, None

        recipe_ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content
        for rec_ing in recipe_ingredients:
            ing_name = rec_ing.name.lower()
            if ing_name in [item.lower() for item in profile_A.allergies + profile_A.excluded_foods] or \
               (profile_B and ing_name in [item.lower() for item in profile_B.allergies + profile_B.excluded_foods]):
                _LOGGER.debug(f"Recipe {recipe.id} has unresolvable allergy/exclusion conflicts.")
                return False, None, None

        planned_food_groups_A = {self._normalize_food_group(item.food_group): item.quantity for item in target_meal_plan_A.items if item.quantity > 0}
        _LOGGER.debug(f"Target grammages for profile A from meal plan: {planned_food_groups_A}")
        planned_food_groups_B = {self._normalize_food_group(item.food_group): item.quantity for item in target_meal_plan_B.items if item.quantity > 0}
        _LOGGER.debug(f"Target grammages for profile B from meal plan: {planned_food_groups_B}")
        
        recipe_food_groups_A: Dict[str, float] = {}
        recipe_food_groups_B: Dict[str, float] = {}
        recipe_has_profile_A_quantities = False
        recipe_has_profile_B_quantities = False
        for rec_ing in recipe_ingredients:
            fg = self._normalize_food_group(rec_ing.food_group)
            qty_a = self._get_qty_for_profile(rec_ing.quantities, profile_A.id, "persona_a")
            # Quantità 0 = ingrediente non previsto per questo profilo (es. ricette
            # dual-profile con proteine alternative): non deve pesare nel check tolleranza.
            if qty_a and qty_a.grams_equiv:
                recipe_food_groups_A[fg] = recipe_food_groups_A.get(fg, 0) + qty_a.grams_equiv
                recipe_has_profile_A_quantities = True
            if profile_B:
                qty_b = self._get_qty_for_profile(rec_ing.quantities, profile_B.id, "persona_b")
                if qty_b and qty_b.grams_equiv:
                    recipe_food_groups_B[fg] = recipe_food_groups_B.get(fg, 0) + qty_b.grams_equiv
                    recipe_has_profile_B_quantities = True

        # Controlla grammage solo se la ricetta ha quantità per il profilo corrente.
        # Itera sugli ingredienti della RICETTA, non sul piano: una ricetta con solo pollo
        # (senza carbo) può passare il check anche se il piano richiede anche 80g carbo.
        # Vengono scartate solo ricette con un ingrediente FUORI TOLLERANZA rispetto al piano.
        if recipe_has_profile_A_quantities:
            for fg, recipe_qty in recipe_food_groups_A.items():
                planned_qty = planned_food_groups_A.get(fg)
                if planned_qty is None:
                    continue  # la ricetta ha un gruppo non richiesto dal piano — OK
                if not (planned_qty * (1 - self.QUANTITY_TOLERANCE_PERCENT) <= recipe_qty <= planned_qty * (1 + self.QUANTITY_TOLERANCE_PERCENT)):
                    return False, None, None

        if profile_B and recipe_has_profile_B_quantities:
            for fg, recipe_qty in recipe_food_groups_B.items():
                planned_qty = planned_food_groups_B.get(fg)
                if planned_qty is None:
                    continue
                if not (planned_qty * (1 - self.QUANTITY_TOLERANCE_PERCENT) <= recipe_qty <= planned_qty * (1 + self.QUANTITY_TOLERANCE_PERCENT)):
                    return False, None, None

        all_consumed = consumed_entries_A + consumed_entries_B
        rotation_rules = self.db.query(RotationRule).filter(RotationRule.is_hard_constraint == True).all()
        
        consumption_counts = {}
        for entry in all_consumed:
            if entry.consumed_recipe_id:
                consumed_recipe = self.db.query(Recipe).filter(Recipe.id == entry.consumed_recipe_id).first()
                if consumed_recipe:
                    ingredients = consumed_recipe.content.components if consumed_recipe.is_composed_dish else consumed_recipe.content
                    for ing in ingredients:
                        food_group = self._normalize_food_group(ing.food_group)
                        # Canonicalize: pollo → carne_bianca so rotation rules on carne_bianca fire correctly
                        cat = self._PROTEIN_CATEGORY_MAP.get(food_group, food_group)
                        consumption_counts[cat] = consumption_counts.get(cat, 0) + 1
                        consumption_counts[ing.name.lower()] = consumption_counts.get(ing.name.lower(), 0) + 1
            elif entry.override_details and entry.override_details.ingredients:
                for ing in entry.override_details.ingredients:
                    food_group = self._get_food_group_for_item(ing.name)
                    if food_group:
                        normalized_food_group = self._normalize_food_group(food_group)
                        cat = self._PROTEIN_CATEGORY_MAP.get(normalized_food_group, normalized_food_group)
                        consumption_counts[cat] = consumption_counts.get(cat, 0) + 1
                        consumption_counts[ing.name.lower()] = consumption_counts.get(ing.name.lower(), 0) + 1
            elif entry.override_details and entry.override_details.free_text_name:
                food_group = self._get_food_group_for_item(entry.override_details.free_text_name)
                if food_group:
                    normalized_food_group = self._normalize_food_group(food_group)
                    cat = self._PROTEIN_CATEGORY_MAP.get(normalized_food_group, normalized_food_group)
                    consumption_counts[cat] = consumption_counts.get(cat, 0) + 1
                    consumption_counts[entry.override_details.free_text_name.lower()] = consumption_counts.get(entry.override_details.free_text_name.lower(), 0) + 1
        
        _LOGGER.debug(f"Consumption counts: {consumption_counts}")
        for rule in rotation_rules:
            normalized_rule_fg = self._normalize_food_group(rule.food_group_or_item)
            _LOGGER.debug(f"Checking rule: '{normalized_rule_fg}', max: {rule.max_per_week}")
            if rule.max_per_week is not None:
                count = consumption_counts.get(normalized_rule_fg, 0)
                _LOGGER.debug(f"Count for '{normalized_rule_fg}' is {count}")
                if count >= rule.max_per_week:
                    _LOGGER.debug(f"Count for '{normalized_rule_fg}' ({count}) meets or exceeds max ({rule.max_per_week})")
                    for rec_ing in recipe_ingredients:
                        # A rule can apply to a food group OR a specific ingredient name.
                        # Resolve both sides through _PROTEIN_CATEGORY_MAP so that
                        # "pollo" (food_group) and "carne_bianca" (rule) are treated as equal.
                        rec_fg = self._normalize_food_group(rec_ing.food_group)
                        rec_fg_cat = self._PROTEIN_CATEGORY_MAP.get(rec_fg, rec_fg)
                        rule_fg_cat = self._PROTEIN_CATEGORY_MAP.get(normalized_rule_fg, normalized_rule_fg)
                        if rec_fg == normalized_rule_fg or rec_fg_cat == rule_fg_cat or rec_ing.name.lower() == normalized_rule_fg:
                            _LOGGER.debug(f"!!! Rotation rule triggered for recipe {recipe.id} on '{rule.food_group_or_item}' with ing '{rec_ing.name}'. Current count: {count}, Max: {rule.max_per_week}")
                            return False, None, None
        
        recent_recipe_ids = {e.consumed_recipe_id for e in all_consumed if e.consumed_recipe_id}
        if recipe.id in recent_recipe_ids:
            _LOGGER.debug(f"Recipe {recipe.id} failed anti-repetition.")
            return False, None, None

        return True, "none", ""

    def _calculate_dosing(self, recipe: schemas.Recipe, profile_A: schemas.UserProfile, profile_B: schemas.UserProfile) -> schemas.Recipe:
        """
        Crea una copia della ricetta con quantità combinate (profilo A + profilo B).
        Aggiunge una chiave "combined" in quantities per ogni ingrediente.
        """
        import copy
        dosed = copy.deepcopy(recipe)
        ingredients = dosed.content.components if dosed.is_composed_dish else dosed.content
        for ing in ingredients:
            qty_a = self._get_qty_for_profile(ing.quantities, profile_A.id, "persona_a")
            qty_b = self._get_qty_for_profile(ing.quantities, profile_B.id, "persona_b") if profile_B else None
            if qty_a is not None and qty_b is not None:
                combined_grams = (qty_a.grams_equiv or 0) + (qty_b.grams_equiv or 0)
                combined_qty = qty_a.qty + qty_b.qty
                ing.quantities["combined"] = schemas.QuantityPerProfile(
                    qty=combined_qty,
                    unit=qty_a.unit,
                    grams_equiv=combined_grams
                )
            elif qty_a is not None:
                ing.quantities["combined"] = copy.deepcopy(qty_a)
        return dosed

    def _score_soft_constraints(
        self,
        recipe: schemas.Recipe,
        pantry_items: List[schemas.PantryItem],
        seasonality_data: Dict[str, schemas.SeasonalityItem],
        current_date: date,
        consumed_entries_A: List[schemas.ConsumedEntry],
        consumed_entries_B: List[schemas.ConsumedEntry],
        recent_protein_items: Optional[List[str]] = None,
        protein_cat_counts: Optional[Dict[str, int]] = None,
        protein_cat_limits: Optional[Dict[str, int]] = None,
        day_slot: int = 0,
    ) -> float:
        score = 0.0

        recipe_ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content

        # Step C: token-overlap pantry matching instead of exact name
        ingredients_in_pantry = 0
        for rec_ing in recipe_ingredients:
            if self._pantry_matches(rec_ing.name, pantry_items):
                ingredients_in_pantry += 1

        if len(recipe_ingredients) > 0:
            pantry_score = ingredients_in_pantry / len(recipe_ingredients)
            score += pantry_score * 0.4

        expiration_bonus = 0.0
        max_bonus_days = 14
        for rec_ing in recipe_ingredients:
            for pi in pantry_items:
                if self._pantry_matches(rec_ing.name, [pi]) and pi.expiration_date:
                    days_to_expire = (date.fromisoformat(pi.expiration_date) - current_date).days
                    if 0 < days_to_expire <= max_bonus_days:
                        expiration_bonus += ((max_bonus_days - days_to_expire) / max_bonus_days) * 0.5
        score += expiration_bonus * 0.3

        seasonality_bonus = 0.0
        current_month = current_date.month
        for rec_ing in recipe_ingredients:
            season_item = seasonality_data.get(rec_ing.name.lower())
            if season_item and current_month in season_item.months_in_season:
                seasonality_bonus += 0.1
            
        score += seasonality_bonus * 0.2

        repetition_penalty = 0.0
        all_consumed = consumed_entries_A + consumed_entries_B
        recent_food_groups = set()
        recent_ingredients = set()

        for entry in all_consumed:
            if entry.consumed_recipe_id:
                consumed_recipe = self.db.query(Recipe).filter(Recipe.id == entry.consumed_recipe_id).first()
                if consumed_recipe:
                    ingredients = consumed_recipe.content.components if consumed_recipe.is_composed_dish else consumed_recipe.content
                    for ing in ingredients:
                        recent_food_groups.add(self._normalize_food_group(ing.food_group))
                        recent_ingredients.add(ing.name.lower())
            elif entry.override_details and entry.override_details.ingredients:
                for ing in entry.override_details.ingredients:
                    recent_ingredients.add(ing.name.lower())
                    fg = self._get_food_group_for_item(ing.name)
                    if fg:
                        recent_food_groups.add(fg)

        for rec_ing in recipe_ingredients:
            if rec_ing.name.lower() in recent_ingredients:
                repetition_penalty += 0.1
            if self._normalize_food_group(rec_ing.food_group) in recent_food_groups:
                repetition_penalty += 0.05

        score -= repetition_penalty

        # Step B (Tier 2): 48h avoidance penalty for recently used protein items
        if recent_protein_items:
            item = self._get_main_protein_item_from_recipe(recipe)
            if item and item in recent_protein_items[-2:]:
                score -= 0.3

        # Rotation deficit boost: promuove attivamente categorie proteiche in deficit
        # rispetto alla quota attesa a questo punto della settimana (14 slot totali)
        if protein_cat_counts is not None and protein_cat_limits:
            recipe_cat = self._recipe_protein_cat(recipe)
            if recipe_cat and recipe_cat in protein_cat_limits:
                max_for_week = protein_cat_limits[recipe_cat]
                actual = protein_cat_counts.get(recipe_cat, 0)
                expected_so_far = max_for_week * (day_slot / 14.0)
                deficit = expected_so_far - actual
                if deficit > 0:
                    score += min(deficit * 0.2, 0.4)

        # Boost ricette aggiunte manualmente dall'utente: vuol dire che gli piacciono
        recipe_tags = recipe.tags or {}
        if recipe_tags.get("manual"):
            score += 1.5

        # Boost CandidateRecipe approvate: l'utente le ha mangiate e apprezzate
        if getattr(recipe, "_is_candidate", False):
            score += 1.0

        # Piccolo jitter casuale per rompere i pareggi e garantire varietà
        score += random.uniform(-0.05, 0.05)

        return score

    def _rules_to_planned_meal(
        self,
        rules: schemas.PlanRules,
        meal_type: str,
        target_cat: Optional[str],
    ) -> schemas.PlannedMeal:
        """
        Builds a PlannedMeal from PlanRules gram targets.
        target_cat: protein category (carne_bianca, carne_rossa, pesce, legumi, uova) or None.
        """
        # Map protein category → food_group (use canonical name directly)
        _cat_to_fg = {
            "carne_bianca": "carne_bianca",
            "carne_rossa":  "carne_rossa",
            "pesce":        "pesce",
            "legumi":       "legumi",
            "uova":         "uova",
            "proteina":     "proteina",
            "formaggio":    "latticini",
            "latticini":    "latticini",
        }
        carb_g = float((rules.carb_target or {}).get(meal_type, 80))
        protein_g = float((rules.protein_target or {}).get(meal_type, 120))

        protein_fg = _cat_to_fg.get(target_cat, "proteina") if target_cat else "proteina"

        # Use first option from rules as item_name (handles both str and {name,quantity,...} formats)
        def _opt_name(opt):
            return opt["name"] if isinstance(opt, dict) else opt

        carb_options = (rules.carb_options or {}).get(meal_type, ["pasta"])
        protein_options = (rules.protein_options or {}).get(meal_type, ["pollo"])
        carb_name = _opt_name(carb_options[0]) if carb_options else "pasta"

        # Proteina coerente con la categoria target dello slot: cerca fra le opzioni
        # del piano quella della categoria giusta; se il piano non ne prevede,
        # usa l'ingrediente di default della categoria (es. target "uova" → "uova",
        # non la prima opzione qualsiasi, che sarebbe quasi sempre pollo).
        protein_name = None
        if target_cat:
            for opt in protein_options:
                opt_name = _opt_name(opt)
                opt_cat = self._PROTEIN_CATEGORY_MAP.get(self._infer_protein_fg(opt_name))
                if opt_cat == target_cat:
                    protein_name = opt_name
                    break
            if protein_name is None:
                protein_name = self._CATEGORY_DEFAULT_ITEMS.get(target_cat)
        if protein_name is None:
            protein_name = _opt_name(protein_options[0]) if protein_options else "pollo"

        items = [
            schemas.PlannedItem(
                item_name=carb_name,
                food_group="carboidrati",
                quantity=carb_g,
                unit="g",
            ),
            schemas.PlannedItem(
                item_name=protein_name,
                food_group=protein_fg,
                quantity=protein_g,
                unit="g",
            ),
        ]
        return schemas.PlannedMeal(meal_type=meal_type, items=items)

    @staticmethod
    def _build_protein_sequence(frequency_targets: Dict[str, Any], n_slots: int = 14) -> List[Optional[str]]:
        """
        Greedy 'most needed' algorithm to fill n_slots with protein categories.
        n_slots = 14 = 7 days × 2 meals (pranzo then cena).
        Returns a list where each entry is a protein category str or None.
        Deterministic: no randomness, sorted iteration.
        """
        # Build state per category
        state: Dict[str, Dict[str, Any]] = {}
        for cat, tgt in sorted(frequency_targets.items()):
            state[cat] = {
                "min": int(tgt.get("min", 0)),
                "max": int(tgt.get("max", 7)),
                "hard_max": tgt.get("hard_max"),
                "count": 0,
            }

        sequence: List[Optional[str]] = []
        n_days = n_slots // 2

        for day in range(n_days):
            day_cats: List[Optional[str]] = []
            for meal_idx, meal_type in enumerate(["pranzo", "cena"]):
                exclude_cat = day_cats[0] if (meal_idx == 1 and day_cats) else None

                def _score(cat: str) -> tuple:
                    s = state[cat]
                    hard_max = s["hard_max"]
                    effective_max = hard_max if hard_max is not None else s["max"]
                    if s["count"] >= effective_max:
                        return (-999, 0)  # exhausted
                    remaining_slots = n_slots - len(sequence) - meal_idx
                    # Priority: deficit from min first, then remaining room
                    deficit = max(0, s["min"] - s["count"])
                    room = effective_max - s["count"]
                    return (deficit, room)

                # Pick category with highest score, excluding same-day cat
                candidates = [c for c in sorted(state.keys()) if c != exclude_cat]
                best = max(candidates, key=_score, default=None)

                # Check if best is still valid (not exhausted)
                if best:
                    s = state[best]
                    hard_max = s["hard_max"]
                    effective_max = hard_max if hard_max is not None else s["max"]
                    if s["count"] >= effective_max:
                        best = None

                if best:
                    state[best]["count"] += 1
                day_cats.append(best)

            sequence.extend(day_cats)

        return sequence

    def _pre_generate_catalog(
        self,
        rules: schemas.PlanRules,
        profile_id_A: str,
        profile_id_B: str,
    ) -> None:
        """
        Pre-generates approved catalog recipes from PlanRules when the Recipe catalog is empty.
        Iterates over every protein_option × top-3 carb_options from the imported PDF,
        calls the LLM once per combo, and saves each result as status='approved' so that
        _get_all_recipes() can pick them up immediately for the weekly plan generation.
        """
        if not self.llm_gateway:
            _LOGGER.warning("[pre-generate] No LLM gateway — skipping catalog pre-generation")
            return

        profile_A = self._get_user_profile(profile_id_A)
        profile_B = self._get_user_profile(profile_id_B)
        if not profile_A:
            _LOGGER.error(f"[pre-generate] Profile {profile_id_A} not found")
            return
        if not profile_B:
            profile_B = schemas.UserProfile(id=profile_id_B, name="Dummy")

        # Mappa nome ingrediente → food_group canonico (keyword list condivisa di classe,
        # così la categoria è coerente con limiti di rotazione e narrowing sul target).
        def _name_to_food_group(name: str) -> str:
            return self._infer_protein_fg(name)

        def _opt_name(opt) -> str:
            return opt["name"] if isinstance(opt, dict) else str(opt)

        def _opt_grams(opt) -> float:
            if isinstance(opt, dict):
                return float(opt.get("quantity") or 0)
            return 0.0

        protein_opts = (
            (rules.protein_options or {}).get("pranzo")
            or (rules.protein_options or {}).get("cena")
            or []
        )
        carb_opts = (
            (rules.carb_options or {}).get("pranzo")
            or (rules.carb_options or {}).get("cena")
            or []
        )

        if not protein_opts or not carb_opts:
            _LOGGER.warning("[pre-generate] PlanRules has no protein_options or carb_options — cannot pre-generate")
            return

        default_protein_g = float((rules.protein_target or {}).get("pranzo", 120))
        default_carb_g = float((rules.carb_target or {}).get("pranzo", 80))

        # Build combos ensuring coverage across protein CATEGORIES (not just first 20 proteins).
        # Strategy: group protein_opts by food_group category, then interleave so that each
        # category gets at least MIN_PER_CAT combos before any category gets more.
        MIN_PER_CAT = 2   # minimum recipes per distinct protein category
        MAX_RECIPES = 30  # total cap (was 20 — raised to allow diverse categories)

        from collections import defaultdict as _dd
        cat_to_opts: dict = _dd(list)
        for popt in protein_opts:
            p_name = _opt_name(popt)
            cat = _name_to_food_group(p_name)
            cat_to_opts[cat].append(popt)

        # Round-robin: fill MIN_PER_CAT per category first, then top-up
        interleaved = []
        for _round in range(MIN_PER_CAT):
            for cat_opts in cat_to_opts.values():
                if _round < len(cat_opts):
                    interleaved.append(cat_opts[_round])
        # Fill remaining slots with any protein not yet covered
        seen = set(id(o) for o in interleaved)
        for popt in protein_opts:
            if id(popt) not in seen:
                interleaved.append(popt)
                seen.add(id(popt))

        combos = []
        carb_top = carb_opts[:3]
        for popt in interleaved:
            p_name = _opt_name(popt)
            p_grams = _opt_grams(popt) or default_protein_g
            for copt in carb_top:
                c_name = _opt_name(copt)
                c_grams = _opt_grams(copt) or default_carb_g
                combos.append((p_name, p_grams, c_name, c_grams))
        combos = combos[:MAX_RECIPES]

        _LOGGER.info(f"[pre-generate] Starting: {len(combos)} recipes from PlanRules via LLM...")
        generated_names: List[str] = []

        for p_name, p_grams, c_name, c_grams in combos:
            meal_plan_A = schemas.PlannedMeal(
                meal_type="pranzo",
                items=[
                    schemas.PlannedItem(
                        item_name=p_name,
                        food_group="proteina",
                        quantity=p_grams,
                        unit="g",
                    ),
                    schemas.PlannedItem(
                        item_name=c_name,
                        food_group="carboidrati",
                        quantity=c_grams,
                        unit="g",
                    ),
                ],
            )
            meal_plan_B = schemas.PlannedMeal(meal_type="pranzo", items=[])

            result = self._generate_llm_recipe_suggestion(
                meal_plan_A, meal_plan_B, profile_A, profile_B,
                pantry_items=[], consumed_entries_A=[], consumed_entries_B=[],
                used_recipe_names=list(generated_names),
            )

            if result:
                # Promote from draft_structured → approved so _get_all_recipes() finds it
                cand = self.db.query(CandidateRecipe).filter(CandidateRecipe.id == result.recipe_id).first()
                if cand:
                    cand.status = "approved"
                    # Fix protein food_group: LLM always saves "proteina" but we know the real category.
                    # Without this, protein_cat_limits (e.g. carne_rossa:1) would never apply to these recipes.
                    correct_fg = _name_to_food_group(p_name)
                    if correct_fg != "proteina":
                        import copy as _copy
                        from sqlalchemy.orm.attributes import flag_modified
                        updated_content = _copy.deepcopy(cand.recipe_data.get("content", []))
                        for ing in updated_content:
                            if isinstance(ing, dict) and ing.get("food_group") == "proteina":
                                ing["food_group"] = correct_fg
                                break
                        cand.recipe_data = {**cand.recipe_data, "content": updated_content}
                        flag_modified(cand, "recipe_data")
                    self.db.commit()
                    generated_names.append(result.name)
                    _LOGGER.info(f"[pre-generate] Approved: '{result.name}' ({p_name}/{correct_fg} + {c_name})")

        _LOGGER.info(f"[pre-generate] Done: {len(generated_names)}/{len(combos)} recipes approved")

    def _ensure_category_coverage(
        self,
        rules: schemas.PlanRules,
        profile_id_A: str,
        profile_id_B: str,
    ) -> None:
        """
        Garantisce almeno una ricetta in catalogo per ogni categoria proteica
        richiesta dalle frequency_targets con min > 0 (es. uova 2/sett, formaggio 2/sett).

        Senza copertura, gli slot con quei target finiscono nei fallback e vengono
        riempiti con qualsiasi proteina (tipicamente pollo). Prova prima l'LLM;
        se non disponibile o fallisce, crea una ricetta-template deterministica
        (carboidrato del piano + proteina di default + verdure), così i minimi
        sono soddisfacibili anche a LLM spento.
        """
        freq = rules.frequency_targets or {}
        wanted = [
            cat for cat, tgt in freq.items()
            if (tgt or {}).get("min", 0) and cat in self._CATEGORY_DEFAULT_ITEMS
        ]
        if not wanted:
            return

        profile_A = self._get_user_profile(profile_id_A)
        profile_B = self._get_user_profile(profile_id_B)
        if not profile_A:
            _LOGGER.warning(f"[category-coverage] Profilo {profile_id_A} non trovato, salto")
            return
        if not profile_B:
            profile_B = schemas.UserProfile(id=profile_id_B, name="Dummy")

        # Quante ricette DISTINTE servirebbero per categoria: quante volte la
        # categoria compare nella sequenza proteica settimanale (cap 4).
        # Conta solo le ricette REALMENTE SELEZIONABILI: complete (proteina+carbo)
        # e che passano i vincoli di grammatura del piano — una ricetta con il
        # carbo fuori tolleranza non coprirà mai i suoi slot.
        sequence = self._build_protein_sequence(freq)
        all_recipes = self._get_all_recipes()
        empty_meal = schemas.PlannedMeal(meal_type="pranzo", items=[])

        deficits = {}
        for cat in wanted:
            needed = min(sequence.count(cat), 4)
            if needed <= 0:
                continue
            target_meal = self._rules_to_planned_meal(rules, "pranzo", cat)
            selectable = 0
            for r in all_recipes:
                if self._recipe_protein_cat(r) != cat or not self._get_main_carb_item_from_recipe(r):
                    continue
                try:
                    ok, _, _ = self._filter_hard_constraints(
                        r, target_meal, empty_meal, profile_A, profile_B, [], [], {}, date.today()
                    )
                except Exception:
                    ok = False
                if ok:
                    selectable += 1
            if selectable < needed:
                deficits[cat] = needed - selectable
        if not deficits:
            return
        missing = list(deficits.keys())
        _LOGGER.info(f"[category-coverage] Ricette selezionabili mancanti per categoria: {deficits}")

        def _opt_name(opt):
            return opt["name"] if isinstance(opt, dict) else str(opt)

        carb_opts = (
            (rules.carb_options or {}).get("pranzo")
            or (rules.carb_options or {}).get("cena")
            or ["pasta"]
        )
        carb_g = float((rules.carb_target or {}).get("pranzo", 80))
        protein_g = float((rules.protein_target or {}).get("pranzo", 120))
        _cat_to_fg = {"uova": "uova", "formaggio": "latticini"}

        def _q(g):
            return {"qty": float(g), "unit": "g", "grams_equiv": float(g)}

        # Opzioni proteiche del PDF raggruppate per categoria: i template usano gli
        # alimenti reali del piano (es. ceci/borlotti/cannellini/lenticchie), non
        # sempre lo stesso ingrediente di default.
        all_protein_opts = (
            ((rules.protein_options or {}).get("pranzo") or [])
            + ((rules.protein_options or {}).get("cena") or [])
        )
        opts_by_cat: Dict[str, List[str]] = {}
        for opt in all_protein_opts:
            opt_name = _opt_name(opt)
            opt_cat = self._PROTEIN_CATEGORY_MAP.get(self._infer_protein_fg(opt_name))
            if opt_cat and opt_name not in opts_by_cat.setdefault(opt_cat, []):
                opts_by_cat[opt_cat].append(opt_name)

        for idx, cat in enumerate(missing):
            # Colma il deficit: ricette distinte finché la categoria può coprire
            # i suoi slot nella sequenza settimanale senza ripetersi.
            n_target = deficits[cat]
            created = 0

            # 1) Tentativo LLM: fino a n_target ricette creative DISTINTE per la categoria
            # (una sola ricetta riusata per tutti gli slot della categoria = settimana monotona)
            if self.llm_gateway:
                llm_names: List[str] = []
                for _attempt in range(n_target):
                    meal_plan_A = self._rules_to_planned_meal(rules, "pranzo", target_cat=cat)
                    meal_plan_B = schemas.PlannedMeal(meal_type="pranzo", items=[])
                    result = self._generate_llm_recipe_suggestion(
                        meal_plan_A, meal_plan_B, profile_A, profile_B,
                        pantry_items=[], consumed_entries_A=[], consumed_entries_B=[],
                        used_recipe_names=list(llm_names),
                    )
                    if not result:
                        break
                    cand = self.db.query(CandidateRecipe).filter(CandidateRecipe.id == result.recipe_id).first()
                    if not cand:
                        break
                    cand.status = "approved"
                    correct_fg = _cat_to_fg.get(cat, cat)
                    import copy as _copy
                    from sqlalchemy.orm.attributes import flag_modified
                    updated_content = _copy.deepcopy(cand.recipe_data.get("content", []))
                    for ing in updated_content:
                        if isinstance(ing, dict) and (ing.get("food_group") or "").lower() in ("proteina", "proteine"):
                            ing["food_group"] = correct_fg
                            break
                    cand.recipe_data = {**cand.recipe_data, "content": updated_content}
                    flag_modified(cand, "recipe_data")
                    self.db.commit()
                    created += 1
                    llm_names.append(result.name)
                    _LOGGER.info(f"[category-coverage] LLM: '{result.name}' per categoria '{cat}'")

            # 2) Fallback deterministico: ricette-template (funziona anche senza LLM)
            cat_proteins = opts_by_cat.get(cat) or [self._CATEGORY_DEFAULT_ITEMS[cat]]
            j = 0
            while created < n_target:
                protein_name = cat_proteins[j % len(cat_proteins)]
                carb_name = _opt_name(carb_opts[(idx + j) % len(carb_opts)])
                fg = _cat_to_fg.get(cat, cat)

                content = [
                    {"name": carb_name, "food_group": "carboidrati",
                     "quantities": {profile_A.id: _q(carb_g), profile_B.id: _q(carb_g)}},
                    {"name": protein_name, "food_group": fg,
                     "quantities": {profile_A.id: _q(protein_g), profile_B.id: _q(protein_g)}},
                    {"name": "verdure", "food_group": "verdure",
                     "quantities": {profile_A.id: _q(150), profile_B.id: _q(150)}},
                ]
                recipe_data = {
                    "name": self._make_display_name(content),
                    "description": f"Ricetta base generata automaticamente per coprire la categoria '{cat}'.",
                    "is_composed_dish": False,
                    "content": content,
                    "steps": [],
                    "total_time_minutes": 25,
                    "difficulty": "facile",
                    "tags": {"mood": ["normale"], "cooking_methods": ["tegame"],
                             "cleanup": ["facile"], "auto_template": ["true"]},
                }
                self.db.add(CandidateRecipe(id=str(uuid.uuid4()), status="approved", recipe_data=recipe_data))
                self.db.commit()
                _LOGGER.info(f"[category-coverage] Template: '{recipe_data['name']}' per categoria '{cat}'")
                created += 1
                j += 1

    def _get_recipe_name_and_tags(self, recipe_id: str):
        """Returns (name, tags) from Recipe or CandidateRecipe by ID."""
        rec = self.db.query(Recipe).filter(Recipe.id == recipe_id).first()
        if rec:
            return rec.name, rec.tags or {}
        cand = self.db.query(CandidateRecipe).filter(CandidateRecipe.id == recipe_id).first()
        if cand:
            data = cand.recipe_data if isinstance(cand.recipe_data, dict) else {}
            return data.get("name"), data.get("tags") or {}
        return None, {}

    def _slot_display_name(self, recipe_id: str, content_raw: list, specific_veg: Optional[str]) -> str:
        """
        Nome mostrato nello slot del piano. Preferisce il nome proprio della ricetta
        quando è descrittivo (manuale o LLM, >= 4 parole): prima veniva sempre
        appiattito in '<Proteina> con <Carbo>', rendendo la settimana monotona alla
        vista anche con ricette diverse. Template e nomi corti usano il nome
        costruito, che include la verdura a rotazione.
        """
        name, tags = self._get_recipe_name_and_tags(recipe_id)
        name = (name or "").strip()
        is_template = "true" in ((tags or {}).get("auto_template") or [])
        if name and not is_template and len(name.split()) >= 4:
            return name
        if content_raw:
            return self._make_display_name(content_raw, specific_veg)
        return name or "Pasto"

    _CARB_GROUPS = {"carboidrati", "carboidrato"}

    def _get_main_carb_item(self, recipe_id: str) -> Optional[str]:
        """Nome (lowercase) del carboidrato principale della ricetta, per ID."""
        ingredients, _ = self._get_recipe_content(recipe_id)
        for ing in ingredients:
            fg = (ing.get("food_group") if isinstance(ing, dict) else ing.food_group or "").lower()
            if fg in self._CARB_GROUPS:
                return ((ing.get("name") if isinstance(ing, dict) else ing.name) or "").lower()
        return None

    def _get_main_carb_item_from_recipe(self, recipe: "schemas.Recipe") -> Optional[str]:
        """Nome (lowercase) del carboidrato principale da una Recipe già caricata."""
        ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content
        for ing in ingredients:
            if (ing.food_group or "").lower() in self._CARB_GROUPS:
                return (ing.name or "").lower()
        return None

    def _generate_from_plan_rules(
        self,
        rules: schemas.PlanRules,
        profile_id_A: str,
        profile_id_B: Optional[str],
        start_date: date,
        fantasy_mode: bool = False,
    ) -> List[schemas.DailyPlannedMeals]:
        """
        New generation path when PlanRules are available.
        Builds protein sequence from frequency_targets, then suggests recipes slot-by-slot.
        """
        # Auto-populate catalog from PlanRules constraints if too sparse
        if len(self._get_all_recipes()) < 5:
            _LOGGER.info("[PlanRules] Catalog too sparse — pre-generating recipes from PDF constraints via LLM")
            self._pre_generate_catalog(rules, profile_id_A, profile_id_B or "persona_b")

        # Garantisci che ogni categoria richiesta dal piano abbia almeno una ricetta
        self._ensure_category_coverage(rules, profile_id_A, profile_id_B or "persona_b")

        protein_sequence = self._build_protein_sequence(rules.frequency_targets)
        _LOGGER.info(f"[PlanRules] protein_sequence={protein_sequence}")

        # Build protein category weekly limits for the variety filter in suggest_recipes_for_meal
        protein_cat_limits: Dict[str, int] = {}
        for cat, tgt in rules.frequency_targets.items():
            hard_max = tgt.get("hard_max")
            effective_max = hard_max if hard_max is not None else tgt.get("max", 7)
            protein_cat_limits[cat] = int(effective_max)
        # Conservative defaults for categories not in frequency_targets, to prevent
        # a single protein type from filling all unconstrained slots (e.g. uova every day).
        protein_cat_limits.setdefault("carne_bianca", 3)
        protein_cat_limits.setdefault("carne_rossa", 2)
        protein_cat_limits.setdefault("pesce", 4)
        protein_cat_limits.setdefault("legumi", 4)
        protein_cat_limits.setdefault("proteina", 4)  # generiche/tofu: max 4 slots / week
        protein_cat_limits.setdefault("uova", 3)      # uova: max 3 slots / week
        protein_cat_limits.setdefault("formaggio", 2)  # latticini: max 2 slots / week

        protein_cat_counts: Dict[str, int] = {}
        protein_item_counts: Dict[str, int] = {}
        recent_protein_items: List[str] = []
        carb_item_counts: Dict[str, int] = {}
        recent_carb_items: List[str] = []
        # Pre-popola con le ricette della settimana precedente per evitare ripetizioni cross-week
        used_recipe_ids: set = self._load_recent_plan_recipe_ids(profile_id_A, start_date)
        used_fingerprints: set = set()
        used_vegs: List[str] = []
        recently_selected: List[str] = []  # ordered list for recent-ID buffer in fallback 2
        day_slot = 0
        generated_plan: List[schemas.DailyPlannedMeals] = []

        for i in range(7):
            current_date = start_date + timedelta(days=i)
            generated_day = schemas.DailyPlannedMeals(date=current_date.isoformat(), meals=[])
            pranzo_protein_category: Optional[str] = None

            for meal_idx, meal_type in enumerate(["pranzo", "cena"]):
                seq_idx = i * 2 + meal_idx
                target_cat = protein_sequence[seq_idx] if seq_idx < len(protein_sequence) else None

                meal_plan_A = self._rules_to_planned_meal(rules, meal_type, target_cat)
                meal_plan_B = schemas.PlannedMeal(meal_type=meal_type, items=[])

                excluded_protein = pranzo_protein_category if meal_type == "cena" else None

                _common_kwargs = dict(
                    excluded_protein_category=excluded_protein,
                    protein_cat_counts=protein_cat_counts,
                    protein_cat_limits=protein_cat_limits,
                    target_protein_category=target_cat,
                    protein_item_counts=protein_item_counts,
                    recent_protein_items=recent_protein_items,
                    carb_item_counts=carb_item_counts,
                    recent_carb_items=recent_carb_items,
                    day_slot=day_slot,
                    use_llm_fill=fantasy_mode,
                )
                best_recipes = self.suggest_recipes_for_meal(
                    meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, {},
                    excluded_recipe_ids=used_recipe_ids,
                    excluded_fingerprints=used_fingerprints,
                    allow_llm=fantasy_mode,          # ExtraFantasy: LLM proattivo su ogni slot
                    strict_target_protein=True,       # se categoria assente in DB → forza fallback
                    **_common_kwargs,
                )
                # Fallback 1: rilassa il vincolo fingerprint
                if not best_recipes:
                    _LOGGER.info(f"[fallback1] {current_date} {meal_type}: rilasso fingerprint")
                    best_recipes = self.suggest_recipes_for_meal(
                        meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, {},
                        excluded_recipe_ids=used_recipe_ids,
                        excluded_fingerprints=set(),
                        allow_llm=fantasy_mode,
                        strict_target_protein=True,
                        **_common_kwargs,
                    )
                # Fallback 2: rilassa recipe_ids + LLM sempre ammesso (genera categoria mancante),
                # ma mantiene i fingerprint per non ripetere pasti identici nella settimana
                if not best_recipes:
                    _LOGGER.info(f"[fallback2] {current_date} {meal_type}: rilasso recipe_ids, LLM ammesso")
                    recent_ids = set(recently_selected[-2:]) if recently_selected else set()
                    best_recipes = self.suggest_recipes_for_meal(
                        meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, {},
                        excluded_recipe_ids=recent_ids,
                        excluded_fingerprints=used_fingerprints,
                        allow_llm=True,
                        strict_target_protein=False,  # usa DB se LLM non disponibile
                        **_common_kwargs,
                    )
                # Fallback 3 (ultima spiaggia): rilassa anche i fingerprint — meglio un
                # pasto ripetuto che uno slot vuoto
                if not best_recipes:
                    _LOGGER.info(f"[fallback3] {current_date} {meal_type}: rilasso anche i fingerprint")
                    recent_ids = set(recently_selected[-2:]) if recently_selected else set()
                    best_recipes = self.suggest_recipes_for_meal(
                        meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, {},
                        excluded_recipe_ids=recent_ids,
                        excluded_fingerprints=set(),
                        allow_llm=True,
                        strict_target_protein=False,
                        **_common_kwargs,
                    )

                if best_recipes:
                    best_recipe = best_recipes[0]
                    ingredients, _ = self._get_recipe_content(best_recipe.recipe_id)
                    content_raw = [
                        {"name": ing.name, "food_group": ing.food_group}
                        if not isinstance(ing, dict) else ing
                        for ing in ingredients
                    ]

                    cooking = self._get_cooking_method(best_recipe.recipe_id)
                    specific_veg = self._pick_vegetable(day_slot, cooking, used_vegs)
                    used_vegs.append(specific_veg)
                    day_slot += 1

                    display_name = self._slot_display_name(best_recipe.recipe_id, content_raw, specific_veg)

                    generated_day.meals.append(schemas.PlannedMeal(
                        meal_type=meal_type,
                        items=[schemas.PlannedItem(
                            item_name=display_name,
                            food_group="recipe",
                            quantity=1,
                            unit="recipe",
                            recipe_id=best_recipe.recipe_id,
                        )]
                    ))

                    used_recipe_ids.add(best_recipe.recipe_id)
                    recently_selected.append(best_recipe.recipe_id)

                    # Rotazione carboidrati: traccia il carbo usato per la varietà settimanale
                    carb_item = self._get_main_carb_item(best_recipe.recipe_id)
                    if carb_item:
                        carb_item_counts[carb_item] = carb_item_counts.get(carb_item, 0) + 1
                        recent_carb_items.append(carb_item)

                    # Track fingerprint to prevent visually identical meals
                    selected_recipe_obj = next(
                        (r for r in self._get_all_recipes() if r.id == best_recipe.recipe_id), None
                    )
                    if selected_recipe_obj:
                        used_fingerprints.add(self._recipe_fingerprint(selected_recipe_obj))
                    else:
                        # LLM-generated recipes are saved as draft_structured (not approved),
                        # so _get_all_recipes() won't find them. Query directly by ID.
                        from .database import CandidateRecipe as _CR2
                        _llm_cand = self.db.query(_CR2).filter(_CR2.id == best_recipe.recipe_id).first()
                        if _llm_cand is not None and _llm_cand.recipe_data is not None:
                            _content2 = _llm_cand.recipe_data.get("content", [])
                            _fg2 = PlannerEngine._FINGERPRINT_GROUPS
                            _fp2 = frozenset(
                                ing["name"].lower().strip()
                                for ing in _content2
                                if isinstance(ing, dict)
                                and (ing.get("food_group") or "").lower() in _fg2
                                and ing.get("name")
                            )
                            if _fp2:
                                used_fingerprints.add(_fp2)

                    cat = self._get_main_protein_category(best_recipe.recipe_id)
                    if cat:
                        protein_cat_counts[cat] = protein_cat_counts.get(cat, 0) + 1

                    # Step B: track protein item for monotony avoidance
                    item = self._get_main_protein_item(best_recipe.recipe_id)
                    if item:
                        protein_item_counts[item] = protein_item_counts.get(item, 0) + 1
                        recent_protein_items.append(item)
                        if len(recent_protein_items) > 3:
                            recent_protein_items.pop(0)

                    if meal_type == "pranzo":
                        pranzo_protein_category = cat

            generated_plan.append(generated_day)

        return generated_plan

    def _generate_full_week_with_llm(
        self,
        rules: schemas.PlanRules,
        profile_id_A: str,
        profile_id_B: str,
        start_date: date,
    ) -> List[schemas.DailyPlannedMeals]:
        """
        Genera l'intero piano settimanale con UNA SOLA chiamata LLM.
        Il LLM riceve le regole nutrizionali e restituisce 7 giorni × 2 pasti.
        """
        if not self.llm_gateway:
            _LOGGER.error("[full_week_llm] LLM gateway non disponibile.")
            return []

        rules_dict = {
            "carb_target": rules.carb_target or {"pranzo": 80, "cena": 60},
            "protein_target": rules.protein_target or {"pranzo": 150, "cena": 120},
            "frequency_targets": rules.frequency_targets or {},
        }
        custom_rules = getattr(self.llm_gateway, "custom_rules", "") or ""

        _LOGGER.info("[full_week_llm] Chiamata LLM singola per piano settimanale...")
        raw = self.llm_gateway.generate_full_week_plan_json(
            rules_dict=rules_dict,
            profile_id_A=profile_id_A,
            profile_id_B=profile_id_B,
            start_date=start_date.isoformat(),
            custom_rules=custom_rules,
            use_cache=False,  # ogni generazione deve essere fresca e varia
        )
        if not raw:
            _LOGGER.error("[full_week_llm] LLM ha restituito None.")
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            _LOGGER.error(f"[full_week_llm] JSON non valido: {e}. Raw: {raw[:500]}")
            return []

        daily_plans_raw = data.get("daily_plans", [])
        result: List[schemas.DailyPlannedMeals] = []

        for day_data in daily_plans_raw:
            day_date = day_data.get("date", "")
            meals_out: List[schemas.PlannedMeal] = []

            for meal_data in day_data.get("meals", []):
                meal_type = meal_data.get("meal_type", "pranzo")
                recipe_name = meal_data.get("recipe_name", "Pasto LLM")
                difficulty = meal_data.get("difficulty", "facile")
                total_time = meal_data.get("total_time_minutes", 30)

                # Build a CandidateRecipe from LLM output and save it
                ingredients_raw = meal_data.get("ingredients", [])
                content: List[schemas.RecipeIngredient] = []
                for ing in ingredients_raw:
                    g_a = ing.get(f"grams_{profile_id_A}", ing.get("grams", 100))
                    g_b = ing.get(f"grams_{profile_id_B}", ing.get("grams", 100))
                    content.append(schemas.RecipeIngredient(
                        name=ing.get("name", "ingrediente"),
                        food_group=ing.get("food_group", "altro"),
                        quantities={
                            profile_id_A: schemas.QuantityPerProfile(qty=g_a, unit="g", grams_equiv=g_a),
                            profile_id_B: schemas.QuantityPerProfile(qty=g_b, unit="g", grams_equiv=g_b),
                        }
                    ))

                recipe_data = schemas.RecipeCreate(
                    name=recipe_name,
                    content=content,
                    steps=[],
                    total_time_minutes=int(total_time),
                    difficulty=difficulty if difficulty in ("facile", "media", "difficile", "sconosciuto") else "facile",
                    tags={"mood": ["normale"], "cleanup": ["facile"], "manual": ["true"]},
                )

                # Save as CandidateRecipe (draft_structured) in DB
                candidate = CandidateRecipe(
                    id=str(uuid.uuid4()),
                    status="draft_structured",
                    usage_count=1,
                    recipe_data=recipe_data.model_dump(),
                )
                try:
                    self.db.add(candidate)
                    self.db.commit()
                    self.db.refresh(candidate)
                except Exception as e:
                    _LOGGER.warning(f"[full_week_llm] Impossibile salvare CandidateRecipe: {e}")
                    self.db.rollback()

                # Build planned items from ingredients
                items = [
                    schemas.PlannedItem(
                        item_name=ing.name,
                        food_group=ing.food_group,
                        quantity=ing.quantities.get(profile_id_A, schemas.QuantityPerProfile(qty=0, unit="g")).qty,
                        unit="g",
                        recipe_id=candidate.id,
                    )
                    for ing in content
                ]
                meals_out.append(schemas.PlannedMeal(meal_type=meal_type, items=items))

            if day_date and meals_out:
                result.append(schemas.DailyPlannedMeals(date=day_date, meals=meals_out))

        _LOGGER.info(f"[full_week_llm] Piano generato: {len(result)} giorni.")
        return result

    def generate_weekly_plan(self, profile_id_A: str, profile_id_B: Optional[str], start_date: date, fantasy_mode: bool = False, ai_mode: Optional[str] = None) -> List[schemas.DailyPlannedMeals]:
        """
        ai_mode override: "off" | "per_slot" | "full_week" | None.
        Se None, usa il valore salvato in AppSettings.
        """
        # New path: if PlanRules exist, use rule-based generation (no fixed weekly schedule)
        plan_rules = self._get_latest_plan_rules(profile_id_A)
        if plan_rules:
            effective_mode = ai_mode  # may be None (algorithmic) or "per_slot"/"full_week"

            if effective_mode == "full_week":
                _LOGGER.info(f"[generate_weekly_plan] AI full_week per '{profile_id_A}'")
                return self._generate_full_week_with_llm(
                    plan_rules, profile_id_A, profile_id_B or "persona_b", start_date
                )

            use_llm_fill = (effective_mode == "per_slot") or fantasy_mode
            _LOGGER.info(f"[generate_weekly_plan] PlanRules path per '{profile_id_A}' (fantasy={fantasy_mode}, ai_mode={effective_mode})")
            return self._generate_from_plan_rules(plan_rules, profile_id_A, profile_id_B, start_date, fantasy_mode=use_llm_fill)

        # Legacy path: use StructuredMealPlan (day-of-week mapping)
        # Use the most recent imported plan (any date), so future start_dates work fine.
        # Day mapping is done by weekday (Mon→Mon, Tue→Tue, ...) instead of exact date.
        weekly_plan_A_raw = self._get_latest_meal_plan(profile_id_A)
        if not weekly_plan_A_raw:
            _LOGGER.error(f"Could not find any meal plan for the primary profile {profile_id_A}.")
            return []

        weekly_plan_B_raw = None
        if profile_id_B:
            weekly_plan_B_raw = self._get_latest_meal_plan(profile_id_B)

        # If profile B was specified but no plan was found, create a dummy plan to allow generation to continue
        if profile_id_B and not weekly_plan_B_raw:
            _LOGGER.warning(f"No active plan found for profile '{profile_id_B}'. Proceeding with a single-profile plan.")
            weekly_plan_B_raw = schemas.StructuredMealPlan(
                id="dummy_plan",
                profile_id=profile_id_B,
                start_date=start_date.isoformat(),
                rotation_rules=[],
                allowed_cooking_methods=[],
                daily_plans=[schemas.DailyPlannedMeals(
                    date=(start_date + timedelta(days=i)).isoformat(),
                    meals=[
                        schemas.PlannedMeal(meal_type="pranzo", items=[]),
                        schemas.PlannedMeal(meal_type="cena", items=[])
                    ]
                ) for i in range(7)]
            )
        # If profile B wasn't specified at all, create a similar dummy plan
        elif not profile_id_B:
             _LOGGER.warning("No profile B specified. Proceeding with single profile plan.")
             weekly_plan_B_raw = weekly_plan_A_raw # Just mirror profile A for now

        if not weekly_plan_B_raw:
             _LOGGER.error(f"Could not find or create a plan for Profile B. Aborting.")
             return []

        weekly_plan_A = schemas.StructuredMealPlan(
            **weekly_plan_A_raw.model_dump(exclude={"daily_plans"}),
            daily_plans=[schemas.DailyPlannedMeals.model_validate(dp) for dp in weekly_plan_A_raw.daily_plans]
        )
        weekly_plan_B = schemas.StructuredMealPlan(
            **weekly_plan_B_raw.model_dump(exclude={"daily_plans"}),
            daily_plans=[schemas.DailyPlannedMeals.model_validate(dp) for dp in weekly_plan_B_raw.daily_plans]
        )


        # Protein category limits (from rotation rules + defaults) and weekly counts
        protein_cat_limits = self._build_protein_limits(weekly_plan_A_raw.rotation_rules)
        protein_cat_counts: Dict[str, int] = {}
        protein_item_counts: Dict[str, int] = {}
        recent_protein_items: List[str] = []
        # Vegetable rotation across the week (no repeated veg in back-to-back slots)
        used_vegs: List[str] = []
        day_slot = 0

        generated_plan: List[schemas.DailyPlannedMeals] = []
        # Pre-popola con le ricette della settimana precedente per evitare ripetizioni cross-week
        used_recipe_ids: set = self._load_recent_plan_recipe_ids(profile_id_A, start_date)
        used_fingerprints: set = set()
        for i in range(7):
            current_date = start_date + timedelta(days=i)

            # Match by day-of-week so plans cover any rolling week, not just original dates
            daily_plan_A = next((d for d in weekly_plan_A.daily_plans if date.fromisoformat(d.date).weekday() == current_date.weekday()), None)
            daily_plan_B = next((d for d in weekly_plan_B.daily_plans if date.fromisoformat(d.date).weekday() == current_date.weekday()), None)

            if not daily_plan_A:
                continue
            if not daily_plan_B:
                daily_plan_B = schemas.DailyPlannedMeals(date=current_date.isoformat(), meals=[])

            generated_day = schemas.DailyPlannedMeals(date=current_date.isoformat(), meals=[])

            # Track pranzo protein category to enforce no-same-protein at cena
            pranzo_protein_category: Optional[str] = None

            for meal_type in ["pranzo", "cena"]:
                meal_plan_A = next((m for m in daily_plan_A.meals if m.meal_type == meal_type), None)
                meal_plan_B = next((m for m in daily_plan_B.meals if m.meal_type == meal_type), None)

                if not meal_plan_A:
                    continue
                if not meal_plan_B:
                    meal_plan_B = schemas.PlannedMeal(meal_type=meal_type, items=[])

                # For cena, exclude the protein category already used at pranzo
                excluded_protein = pranzo_protein_category if meal_type == "cena" else None

                _legacy_kwargs = dict(
                    excluded_protein_category=excluded_protein,
                    protein_cat_counts=protein_cat_counts,
                    protein_cat_limits=protein_cat_limits,
                    protein_item_counts=protein_item_counts,
                    recent_protein_items=recent_protein_items,
                    day_slot=day_slot,
                )
                best_recipes = self.suggest_recipes_for_meal(
                    meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, {},
                    excluded_recipe_ids=used_recipe_ids,
                    excluded_fingerprints=used_fingerprints,
                    **_legacy_kwargs,
                )
                if not best_recipes:
                    best_recipes = self.suggest_recipes_for_meal(
                        meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, {},
                        excluded_recipe_ids=used_recipe_ids,
                        excluded_fingerprints=set(),
                        **_legacy_kwargs,
                    )
                if not best_recipes:
                    best_recipes = self.suggest_recipes_for_meal(
                        meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, {},
                        excluded_recipe_ids=set(),
                        excluded_fingerprints=set(),
                        **_legacy_kwargs,
                    )

                if best_recipes:
                    best_recipe = best_recipes[0]

                    # Build display name from recipe content
                    ingredients, _ = self._get_recipe_content(best_recipe.recipe_id)
                    content_raw = [
                        {"name": ing.name, "food_group": ing.food_group}
                        if not isinstance(ing, dict) else ing
                        for ing in ingredients
                    ]

                    # Pick a specific vegetable for this slot (rotation across week)
                    cooking = self._get_cooking_method(best_recipe.recipe_id)
                    specific_veg = self._pick_vegetable(day_slot, cooking, used_vegs)
                    used_vegs.append(specific_veg)
                    day_slot += 1

                    display_name = self._make_display_name(content_raw, specific_veg) if content_raw else best_recipe.name

                    generated_day.meals.append(schemas.PlannedMeal(
                        meal_type=meal_type,
                        items=[schemas.PlannedItem(
                            item_name=display_name,
                            food_group="recipe",
                            quantity=1,
                            unit="recipe",
                            recipe_id=best_recipe.recipe_id,
                        )]
                    ))

                    # Track used recipes (hard-exclude from remaining slots)
                    used_recipe_ids.add(best_recipe.recipe_id)

                    # Track fingerprint to prevent visually identical meals
                    selected_recipe_obj = next(
                        (r for r in self._get_all_recipes() if r.id == best_recipe.recipe_id), None
                    )
                    if selected_recipe_obj:
                        used_fingerprints.add(self._recipe_fingerprint(selected_recipe_obj))
                    else:
                        # LLM-generated recipes are saved as draft_structured (not approved),
                        # so _get_all_recipes() won't find them. Query directly by ID.
                        from .database import CandidateRecipe as _CR2
                        _llm_cand = self.db.query(_CR2).filter(_CR2.id == best_recipe.recipe_id).first()
                        if _llm_cand is not None and _llm_cand.recipe_data is not None:
                            _content2 = _llm_cand.recipe_data.get("content", [])
                            _fg2 = PlannerEngine._FINGERPRINT_GROUPS
                            _fp2 = frozenset(
                                ing["name"].lower().strip()
                                for ing in _content2
                                if isinstance(ing, dict)
                                and (ing.get("food_group") or "").lower() in _fg2
                                and ing.get("name")
                            )
                            if _fp2:
                                used_fingerprints.add(_fp2)

                    # Track protein category for weekly variety
                    cat = self._get_main_protein_category(best_recipe.recipe_id)
                    if cat:
                        protein_cat_counts[cat] = protein_cat_counts.get(cat, 0) + 1

                    # Step B: track protein item for monotony avoidance
                    item = self._get_main_protein_item(best_recipe.recipe_id)
                    if item:
                        protein_item_counts[item] = protein_item_counts.get(item, 0) + 1
                        recent_protein_items.append(item)
                        if len(recent_protein_items) > 3:
                            recent_protein_items.pop(0)

                    # Track protein for the same-day pranzo/cena constraint
                    if meal_type == "pranzo":
                        pranzo_protein_category = cat

            generated_plan.append(generated_day)

        return generated_plan

    # Gruppi alimentari che contano come proteine
    _PROTEIN_GROUPS = {"proteina", "proteine", "pollo", "carne_bianca", "pesce", "carne_rossa", "legumi", "uova", "latticini", "formaggio"}

    # Mappa food_group → categoria proteica canonica.
    # "pollo" è il food_group legacy nelle ricette esistenti; "carne_bianca" è il nome
    # canonico usato in frequency_targets, protein_sequence e protein_cat_counts.
    # Entrambi mappano a "carne_bianca" così i confronti funzionano in entrambe le direzioni.
    _PROTEIN_CATEGORY_MAP = {
        "pollo":        "carne_bianca",
        "carne_bianca": "carne_bianca",
        "carne_rossa":  "carne_rossa",
        "pesce":        "pesce",
        "legumi":       "legumi",
        "proteina":     "proteina",
        "proteine":     "proteina",
        "uova":         "uova",
        "latticini":    "formaggio",
        "formaggio":    "formaggio",
    }

    # Keyword → food_group canonico per l'ingrediente proteico, in ordine di
    # specificità (chiave più specifica prima). Usata per normalizzare i
    # food_group generici ("proteina") che altrimenti sfuggono a limiti di
    # categoria, narrowing sul target ed esclusione same-day.
    _FG_KEYWORDS = [
        ("petto di pollo", "carne_bianca"), ("sovracoscio", "carne_bianca"),
        ("prosciutto cotto", "carne_bianca"), ("prosciutto crudo", "carne_bianca"),
        ("fesa di tacchino", "carne_bianca"), ("tacchino", "carne_bianca"), ("pollo", "carne_bianca"),
        ("vitellone", "carne_rossa"), ("vitello", "carne_rossa"), ("manzo", "carne_rossa"),
        ("bovino", "carne_rossa"), ("maiale", "carne_rossa"), ("agnello", "carne_rossa"),
        ("cinghiale", "carne_rossa"), ("bresaola", "carne_rossa"),
        ("salmone", "pesce"), ("tonno", "pesce"), ("merluzzo", "pesce"), ("orata", "pesce"),
        ("spigola", "pesce"), ("branzino", "pesce"), ("sgombro", "pesce"),
        ("gamber", "pesce"), ("pesce", "pesce"),
        # uova di pesce (bottarga & co.) PRIMA della keyword generica "uova"
        ("uova di cefalo", "pesce"), ("uova di muggine", "pesce"),
        ("uova di lompo", "pesce"), ("bottarga", "pesce"),
        ("ceci", "legumi"), ("fagioli", "legumi"), ("lenticchie", "legumi"),
        ("piselli", "legumi"), ("fave", "legumi"), ("soia", "legumi"),
        ("uova", "uova"), ("uovo", "uova"), ("albume", "uova"), ("frittata", "uova"),
        ("mozzarella", "latticini"), ("ricotta", "latticini"), ("crescenza", "latticini"),
        ("grana", "latticini"), ("parmigiano", "latticini"), ("fiocchi di latte", "latticini"),
        ("stracchino", "latticini"), ("scamorza", "latticini"), ("pecorino", "latticini"),
        ("feta", "latticini"), ("formagg", "latticini"),
    ]

    # Ingrediente proteico di default per categoria: usato quando una categoria
    # richiesta dal piano non ha né opzioni nel PDF né ricette in catalogo.
    _CATEGORY_DEFAULT_ITEMS = {
        "uova":         "uova",
        "formaggio":    "mozzarella",
        "carne_bianca": "petto di pollo",
        "carne_rossa":  "vitellone magro",
        "pesce":        "merluzzo",
        "legumi":       "ceci",
    }

    @classmethod
    def _infer_protein_fg(cls, name: str, food_group: Optional[str] = None) -> str:
        """Risolve il food_group proteico di un ingrediente.

        Se il food_group è già specifico lo restituisce com'è; se è generico
        ("proteina"/"proteine") lo deduce dal nome via _FG_KEYWORDS.
        """
        fg = (food_group or "").lower()
        if fg and fg not in ("proteina", "proteine"):
            return fg
        n = (name or "").lower()
        for kw, mapped in cls._FG_KEYWORDS:
            if kw in n:
                return mapped
        return fg or "proteina"

    # Catalogo verdure specifiche con metodi cottura compatibili.
    # "griglia" è inclusa perché molte ricette LLM usano quel cooking_method.
    _VEG_CATALOG = [
        {"name": "zucchine",      "methods": ["tegame", "forno", "vapore", "griglia"]},
        {"name": "spinaci",       "methods": ["tegame", "vapore"]},
        {"name": "broccoli",      "methods": ["forno", "vapore", "tegame"]},
        {"name": "carote",        "methods": ["forno", "vapore", "tegame"]},
        {"name": "peperoni",      "methods": ["forno", "tegame", "griglia"]},
        {"name": "melanzane",     "methods": ["forno", "tegame", "griglia"]},
        {"name": "fagiolini",     "methods": ["vapore", "tegame"]},
        {"name": "cavolfiore",    "methods": ["forno", "vapore"]},
        {"name": "finocchi",      "methods": ["forno", "tegame"]},
        {"name": "asparagi",      "methods": ["vapore", "forno", "griglia"]},
        {"name": "pomodori",      "methods": ["forno", "tegame", "griglia"]},
        {"name": "insalata mista","methods": []},  # compatibile con tutto (crudo/griglia/ecc.)
        {"name": "bietole",       "methods": ["tegame", "vapore"]},
        {"name": "piselli",       "methods": ["tegame", "vapore"]},
        {"name": "radicchio",     "methods": ["griglia", "tegame", "crudo"]},
        {"name": "cetrioli",      "methods": ["crudo"]},
    ]
    # Nomi generici da sostituire con verdure specifiche
    _VEG_GENERIC_NAMES = {"verdure", "verdura", "verdura mista", "verdure miste", "contorno"}

    # Grammi per porzione standard di ciascuna verdura (per le equivalenze nutrizionali)
    _VEG_PORTION_GRAMS: Dict[str, float] = {
        "zucchine":      150.0,
        "spinaci":       100.0,
        "broccoli":      150.0,
        "carote":        120.0,
        "peperoni":      150.0,
        "melanzane":     200.0,
        "fagiolini":     120.0,
        "cavolfiore":    150.0,
        "finocchi":      150.0,
        "asparagi":      100.0,
        "pomodori":      120.0,
        "insalata mista": 80.0,
        "bietole":       120.0,
        "piselli":       100.0,
    }
    _VEG_DEFAULT_PORTION_GRAMS: float = 150.0

    @staticmethod
    def _make_display_name(content: list, specific_veg: Optional[str] = None) -> str:
        """
        Builds a human-readable meal name from ingredient content.
        Format: "<Proteina> con <Carbo>" or "<Proteina> con <Carbo> e <Verdura>"
        specific_veg overrides the generic "Verdure" label with the actual vegetable name.
        Falls back to the first ingredient name if structure is unexpected.
        """
        protein_name = None
        carb_name = None
        has_veg = False

        protein_groups = {"proteina", "proteine", "pollo", "carne_bianca", "pesce", "carne_rossa",
                          "legumi", "uova", "latticini", "formaggio"}
        carb_groups = {"carboidrati", "carboidrato"}

        for ing in content:
            fg = (ing.get("food_group") if isinstance(ing, dict) else ing.food_group or "").lower()
            name = (ing.get("name") if isinstance(ing, dict) else ing.name or "").title()
            if not protein_name and fg in protein_groups:
                protein_name = name
            elif not carb_name and fg in carb_groups:
                carb_name = name
            elif fg == "verdure":
                has_veg = True

        if protein_name and carb_name:
            base = f"{protein_name} con {carb_name}"
            if specific_veg:
                return f"{base} e {specific_veg.title()}"
            if has_veg:
                # Step D: never show generic "Verdure" — pick deterministic fallback from catalog
                fallback = PlannerEngine._VEG_CATALOG[
                    abs(hash(protein_name or "")) % len(PlannerEngine._VEG_CATALOG)
                ]["name"]
                return f"{base} e {fallback.title()}"
            return base
        if protein_name:
            return protein_name
        if carb_name:
            return carb_name
        # Last resort: first ingredient
        if content:
            first = content[0]
            return (first.get("name") if isinstance(first, dict) else first.name or "Pasto").title()
        return "Pasto"

    @staticmethod
    def _veg_portions_in_recipe(
        content, veg_portion_overrides: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Calcola il numero di porzioni di verdure presenti in una ricetta.
        La dimensione di una porzione varia per verdura (es. 80g insalata, 200g melanzane).
        veg_portion_overrides: sovrascrive i valori di default per singola verdura.
        """
        total = 0.0
        for ing in content:
            fg = (ing.get("food_group") if isinstance(ing, dict) else ing.food_group or "").lower()
            if fg != "verdure":
                continue
            name = (ing.get("name") if isinstance(ing, dict) else ing.name or "").lower().strip()
            qty_raw = ing.get("quantities") if isinstance(ing, dict) else getattr(ing, "quantities", {})
            # Get grams from any profile key
            grams = 0.0
            if isinstance(qty_raw, dict):
                for v in qty_raw.values():
                    if isinstance(v, dict):
                        grams = float(v.get("grams_equiv") or v.get("qty") or 0)
                    elif hasattr(v, "grams_equiv"):
                        grams = float(v.grams_equiv or v.qty or 0)
                    if grams > 0:
                        break
            portion_size = (
                (veg_portion_overrides or {}).get(name)
                or PlannerEngine._VEG_PORTION_GRAMS.get(name)
                or PlannerEngine._VEG_DEFAULT_PORTION_GRAMS
            )
            total += grams / portion_size
        return total

    _FINGERPRINT_GROUPS = {
        "proteina", "proteine", "pollo", "carne_bianca", "pesce", "carne_rossa",
        "legumi", "uova", "latticini", "formaggio", "carboidrati", "carboidrato",
    }

    @staticmethod
    def _recipe_fingerprint(recipe: "schemas.Recipe") -> frozenset:
        """
        Calcola un fingerprint basato sugli ingredienti proteici e glucidici principali.
        Due ricette con lo stesso fingerprint avranno lo stesso aspetto visivo (stesso display name).
        Usato per evitare pasti identici nella stessa settimana anche se con recipe_id diversi.
        """
        ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content
        key_names = frozenset(
            ing.name.lower().strip()
            for ing in ingredients
            if (ing.food_group or "").lower() in PlannerEngine._FINGERPRINT_GROUPS
            and ing.name
        )
        return key_names

    def _get_main_protein_category(self, recipe_id: str) -> Optional[str]:
        """Returns the protein category of the main protein ingredient in a recipe.

        I food_group generici ("proteina") vengono risolti dal nome dell'ingrediente,
        così i conteggi settimanali per categoria sono corretti anche per ricette
        salvate senza categoria specifica.
        """
        ingredients, _ = self._get_recipe_content(recipe_id)
        for ing in ingredients:
            name = ing.get("name") if isinstance(ing, dict) else ing.name
            fg = (ing.get("food_group") if isinstance(ing, dict) else ing.food_group or "").lower()
            if fg in ("proteina", "proteine"):
                fg = self._infer_protein_fg(name, fg)
            cat = self._PROTEIN_CATEGORY_MAP.get(fg)
            if cat:
                return cat
        return None

    def _recipe_protein_cat(self, recipe: "schemas.Recipe") -> Optional[str]:
        """Returns protein category from an already-loaded Recipe object (no DB query)."""
        ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content
        for ing in ingredients:
            fg = (ing.food_group or "").lower()
            cat = self._PROTEIN_CATEGORY_MAP.get(fg)
            if cat:
                return cat
        return None

    def _get_main_protein_item(self, recipe_id: str) -> Optional[str]:
        """Returns the name (lowercase) of the main protein ingredient, looked up by recipe_id."""
        ingredients, _ = self._get_recipe_content(recipe_id)
        for ing in ingredients:
            fg = (ing.get("food_group") if isinstance(ing, dict) else ing.food_group or "").lower()
            if fg in self._PROTEIN_GROUPS:
                return (ing.get("name") if isinstance(ing, dict) else ing.name or "").lower()
        return None

    def _get_main_protein_item_from_recipe(self, recipe: "schemas.Recipe") -> Optional[str]:
        """Returns the name (lowercase) of the main protein ingredient from an already-loaded Recipe."""
        ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content
        for ing in ingredients:
            fg = (ing.food_group or "").lower()
            if fg in self._PROTEIN_GROUPS:
                return (ing.name or "").lower()
        return None

    def _load_recent_plan_recipe_ids(self, profile_id_A: str, before_date: date, days_back: int = 14) -> set:
        """
        Restituisce i recipe_id usati nei piani generati nelle ultime `days_back` giorni
        prima di `before_date`. Usato per pre-popolare used_recipe_ids in modo che
        la nuova settimana non ripeta le ricette della settimana precedente anche senza
        ConsumedEntry esplicite.
        """
        cutoff = (before_date - timedelta(days=days_back)).isoformat()
        plans = self.db.query(GeneratedWeeklyPlan).filter(
            GeneratedWeeklyPlan.profile_id_A == profile_id_A,
            GeneratedWeeklyPlan.week_start_date < before_date.isoformat(),
            GeneratedWeeklyPlan.week_start_date >= cutoff,
        ).order_by(GeneratedWeeklyPlan.week_start_date.desc()).all()

        ids: set = set()
        for plan in plans:
            for dp in (plan.daily_plans or []):
                for meal in dp.get("meals", []):
                    for item in meal.get("items", []):
                        if item.get("recipe_id") and item.get("food_group") == "recipe":
                            ids.add(item["recipe_id"])
        if ids:
            _LOGGER.info(
                f"[anti-rep] Pre-caricati {len(ids)} recipe_id dai piani recenti "
                f"({before_date - timedelta(days=days_back)} → {before_date})"
            )
        return ids

    @staticmethod
    def _get_qty_for_profile(quantities: dict, profile_id: str, positional_fallback: str):
        """
        Cerca le quantità prima con il profile_id reale, poi con la chiave posizionale
        (es. 'persona_a'/'persona_b' usata dalle ricette seed).
        Questo permette di usare ricette seed con qualsiasi nome di profilo.
        """
        return quantities.get(profile_id) or quantities.get(positional_fallback)

    @staticmethod
    def _pantry_matches(rec_name: str, pantry_items) -> bool:
        """Token-overlap match: ingredient name matches pantry item if any word overlaps."""
        tokens = set(rec_name.lower().split())
        return any(tokens & set(pi.name.lower().split()) for pi in pantry_items)

    # Recognised short method names. Anything else is treated as free-text and parsed.
    _KNOWN_METHODS = {"tegame", "forno", "vapore", "griglia", "crudo", "bollitura", "microonde"}

    def _get_cooking_method(self, recipe_id: str) -> str:
        """Returns the primary cooking method (short name) of a recipe.
        If the stored value is a full sentence (LLM sometimes writes the step text there),
        we extract a recognised keyword from it; fallback to 'tegame'."""
        def _parse(raw: str) -> str:
            raw = (raw or "").lower()
            for kw in ("griglia", "forno", "vapore", "crudo", "bollitura"):
                if kw in raw:
                    return kw
            return "tegame"

        def _from_methods(methods: list) -> str:
            if not methods:
                return "tegame"
            first = methods[0].lower().strip()
            if first in self._KNOWN_METHODS:
                return first
            return _parse(first)  # stored value is free text

        db_recipe = self.db.query(Recipe).filter(Recipe.id == recipe_id).first()
        if db_recipe:
            return _from_methods((db_recipe.tags or {}).get("cooking_methods", []))
        candidate = self.db.query(CandidateRecipe).filter(CandidateRecipe.id == recipe_id).first()
        if candidate:
            data = candidate.recipe_data if isinstance(candidate.recipe_data, dict) else candidate.recipe_data.model_dump()
            return _from_methods(data.get("tags", {}).get("cooking_methods", []))
        return "tegame"

    @staticmethod
    def _pick_vegetable(day_slot: int, cooking_method: str, used_vegs: List[str]) -> str:
        """Deterministically pick a specific vegetable, rotating and avoiding recent repeats.
        Prefers vegetables compatible with the meal's cooking method."""
        method = (cooking_method or "tegame").lower()
        # Compatible = method in veg's list OR veg has no restriction (empty list)
        compatible = [v for v in PlannerEngine._VEG_CATALOG
                      if not v["methods"] or method in v["methods"]]
        if not compatible:
            compatible = PlannerEngine._VEG_CATALOG

        # Avoid last 3 used vegetables
        recent = set(used_vegs[-3:]) if used_vegs else set()
        candidates = [v for v in compatible if v["name"] not in recent]
        if not candidates:
            candidates = compatible  # all recent → allow repeats

        return candidates[day_slot % len(candidates)]["name"]

    @staticmethod
    def _build_protein_limits(rotation_rules) -> Dict[str, int]:
        """Build protein category weekly max limits from plan rotation rules + hardcoded defaults.
        Returns {category: max_per_week}."""
        defaults: Dict[str, int] = {
            "carne_bianca": 2,
            "carne_rossa":  1,
            "pesce":        3,
            "legumi":       5,
            "proteina":     4,
        }
        limits = dict(defaults)
        _fg_to_cat = {
            "pollo": "carne_bianca", "carne_bianca": "carne_bianca",
            "carne_rossa": "carne_rossa",
            "pesce": "pesce",
            "legumi": "legumi",
            "proteina": "proteina", "proteine": "proteina", "uova": "proteina",
        }
        for rule in (rotation_rules or []):
            fg = (rule.food_group_or_item if hasattr(rule, "food_group_or_item")
                  else rule.get("food_group_or_item", "")).lower()
            cat = _fg_to_cat.get(fg)
            max_pw = (rule.max_per_week if hasattr(rule, "max_per_week")
                      else rule.get("max_per_week"))
            if cat and max_pw is not None:
                limits[cat] = max_pw
        return limits

    def _extract_user_preferences(self) -> Dict[str, List[str]]:
        """
        Scansiona il catalogo ricette (Recipe + CandidateRecipe approved) per inferire
        le preferenze proteiche e glucidiche dell'utente. Restituisce:
          {"proteins": [...], "carbs": [...]}
        Usato per arricchire il prompt LLM con contesto reale.
        """
        protein_counts: Dict[str, int] = {}
        carb_counts: Dict[str, int] = {}

        all_recipes = self._get_all_recipes()
        for recipe in all_recipes:
            ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content
            for ing in ingredients:
                fg = (ing.food_group or "").lower()
                name = (ing.name or "").strip()
                if not name:
                    continue
                if fg in self._PROTEIN_GROUPS:
                    protein_counts[name] = protein_counts.get(name, 0) + 1
                elif "carbo" in fg:
                    carb_counts[name] = carb_counts.get(name, 0) + 1

        top_proteins = [k for k, _ in sorted(protein_counts.items(), key=lambda x: -x[1])[:6]]
        top_carbs = [k for k, _ in sorted(carb_counts.items(), key=lambda x: -x[1])[:4]]
        return {"proteins": top_proteins, "carbs": top_carbs}

    def _load_prompt_template(self) -> str:
        """Carica il template del prompt da file, con fallback inline."""
        prompt_path = os.path.join(os.path.dirname(__file__), "prompt.txt")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            _LOGGER.warning(f"prompt.txt non trovato in {prompt_path}, uso fallback.")
            return (
                "Sei un assistente nutrizionale. Genera un pasto per {{meal_type}} "
                "con {{carb_target}}g di carboidrati ({{carb_options}}) e "
                "{{protein_target}}g di proteine ({{protein_options}}). "
                "Restituisci SOLO JSON: "
                '{"meal_name":"...","components":{"protein":{"name":"...","grams":0},'
                '"carb":{"name":"...","grams":0},"vegetables":[]},'
                '"cooking_method":"...","notes":"..."}'
            )

    # Nomi generici che non devono essere passati al LLM come opzioni concreti.
    # Mappati a una lista di alimenti concreti di fallback.
    _GENERIC_NAME_MAP: Dict[str, List[str]] = {
        "carboidrati":  ["pasta", "riso", "pane comune"],
        "carboidrato":  ["pasta", "riso", "pane comune"],
        "proteine":     ["pollo", "pesce", "uova"],
        "proteina":     ["pollo", "pesce", "uova"],
        "legumi":       ["lenticchie", "ceci", "fagioli"],
        "verdure":      ["verdura mista"],
        "verdura":      ["verdura mista"],
        "grassi":       ["olio d'oliva"],
        "grasso":       ["olio d'oliva"],
        "frutta":       ["mela", "banana"],
        "pesce":        ["salmone", "tonno", "merluzzo"],  # "pesce" è semi-generico
    }

    def _resolve_concrete_options(self, items: list, role: str) -> List[str]:
        """
        Dato un elenco di PlannedItem, restituisce i nomi concreti degli alimenti.
        Se item_name è vuoto o generico (uguale al food_group), usa il mapping di fallback.
        """
        result = []
        for it in items:
            name = (it.item_name or "").strip().lower()
            fg   = (it.food_group or "").strip().lower()
            if not name or name == fg or name in self._GENERIC_NAME_MAP:
                fallback = self._GENERIC_NAME_MAP.get(name or fg, self._GENERIC_NAME_MAP.get(fg, []))
                if fallback:
                    _LOGGER.warning(
                        f"[{role}] item_name '{it.item_name}' è generico per food_group '{it.food_group}'. "
                        f"Uso fallback: {fallback}"
                    )
                    result.extend(fallback)
                else:
                    _LOGGER.warning(
                        f"[{role}] item_name '{it.item_name}' generico e nessun fallback trovato. Ignorato."
                    )
            else:
                result.append(it.item_name)
        return result

    def _build_llm_prompt(
        self,
        meal_plan_A: schemas.PlannedMeal,
        meal_plan_B: schemas.PlannedMeal,
        profile_A: schemas.UserProfile,
        target_protein_category: Optional[str] = None,
        user_preferences: Optional[Dict[str, List[str]]] = None,
        used_recipe_names: Optional[List[str]] = None,
    ) -> tuple:
        """
        Riempie il template del prompt con i dati reali del piano.
        Ritorna: (prompt_str, carb_target, protein_target, carb_options_list, protein_options_list)
        """
        carb_items    = [it for it in meal_plan_A.items if "carbo" in it.food_group.lower()]
        protein_items = [it for it in meal_plan_A.items
                         if any(pg in it.food_group.lower() for pg in self._PROTEIN_GROUPS)]

        carb_target    = int(sum(it.quantity for it in carb_items) or 80)
        protein_target = int(sum(it.quantity for it in protein_items) or 120)

        carb_options_list    = self._resolve_concrete_options(carb_items, "carb")
        protein_options_list = self._resolve_concrete_options(protein_items, "protein")

        # Fallback se ancora vuoti
        if not carb_options_list:
            carb_options_list = ["pasta", "riso", "pane comune"]
        if not protein_options_list:
            protein_options_list = ["pollo", "pesce", "uova"]

        _LOGGER.info(
            f"[build_llm_prompt] meal_type={meal_plan_A.meal_type} | "
            f"carb_items={[it.item_name for it in carb_items]} carb_target={carb_target}g | "
            f"protein_items={[it.item_name for it in protein_items]} protein_target={protein_target}g | "
            f"carb_options={carb_options_list} protein_options={protein_options_list} | "
            f"target_protein_category={target_protein_category}"
        )

        exclusions = list(set((profile_A.allergies or []) + (profile_A.excluded_foods or [])))

        # Build optional context notes
        if target_protein_category:
            target_note = (
                f"\nCATEGORIA PROTEICA RICHIESTA: {target_protein_category}\n"
                f"Il pasto DEVE usare una proteina di categoria '{target_protein_category}'. Non è opzionale.\n"
            )
        else:
            target_note = ""

        if user_preferences and (user_preferences.get("proteins") or user_preferences.get("carbs")):
            prots = ", ".join(user_preferences.get("proteins", []))
            carbs_pref = ", ".join(user_preferences.get("carbs", []))
            pref_note = (
                f"\nPREFERENZE UTENTE (ingredienti più usati nelle ricette salvate):\n"
                f"- Proteine preferite: {prots}\n"
                f"- Carboidrati preferiti: {carbs_pref}\n"
                f"Prediligi questi ingredienti se compatibili con i target.\n"
            )
        else:
            pref_note = ""

        if used_recipe_names:
            avoid_note = (
                f"\nRICETTE DA NON RIPETERE (già usate di recente): {', '.join(used_recipe_names[:10])}\n"
                f"Genera un pasto DIVERSO e ORIGINALE rispetto a questi.\n"
            )
        else:
            avoid_note = ""

        # Inject custom rules from settings if present
        custom_rules = getattr(self.llm_gateway, 'custom_rules', '') if self.llm_gateway else ''
        if custom_rules and custom_rules.strip():
            custom_rules_block = f"\nREGOLE AGGIUNTIVE UTENTE:\n{custom_rules.strip()}\n"
        else:
            custom_rules_block = ""

        template = self._load_prompt_template()
        prompt = (
            template
            .replace("{{meal_type}}", meal_plan_A.meal_type)
            .replace("{{carb_target}}", str(carb_target))
            .replace("{{carb_options}}", ", ".join(carb_options_list))
            .replace("{{protein_target}}", str(protein_target))
            .replace("{{protein_options}}", ", ".join(protein_options_list))
            .replace("{{base_recipe_json}}", "nessuna")
            .replace("{{target_protein_note}}", target_note)
            .replace("{{user_pref_note}}", pref_note)
            .replace("{{avoid_note}}", avoid_note)
            .replace("{{custom_rules}}", custom_rules_block)
        )

        if exclusions:
            prompt += f"\n\nINGREDIENTI VIETATI (allergie/esclusioni): {', '.join(exclusions)}. Non includerli MAI."

        return prompt, carb_target, protein_target, carb_options_list, protein_options_list

    def _parse_llm_recipe_response(
        self,
        raw: str,
        profile_A: schemas.UserProfile,
        profile_B: schemas.UserProfile,
        meal_type: str,
    ) -> Optional[dict]:
        """
        Converte il JSON del nuovo formato prompt in un dict compatibile con RecipeCreate.
        Formato atteso: {meal_name, components:{protein, carb, vegetables}, cooking_method, notes}
        """
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            _LOGGER.error(f"LLM non ha restituito JSON valido. Raw: {raw[:300]}")
            return None

        try:
            result = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            _LOGGER.error(f"JSON non parsabile: {e}. Raw: {raw[:300]}")
            return None

        components = result.get("components", {})
        protein    = components.get("protein", {})
        carb       = components.get("carb", {})
        vegetables = components.get("vegetables", [])

        def _make_ing(name: str, grams: float, food_group: str) -> dict:
            grams = float(grams) if grams else 0.0
            return {
                "name": name,
                "food_group": food_group,
                "quantities": {
                    profile_A.id: {"qty": grams, "unit": "g", "grams_equiv": grams},
                    profile_B.id: {"qty": grams, "unit": "g", "grams_equiv": grams},
                },
            }

        content = []
        if protein.get("name") and protein.get("grams"):
            content.append(_make_ing(protein["name"], protein["grams"], "proteina"))
        if carb.get("name") and carb.get("grams"):
            content.append(_make_ing(carb["name"], carb["grams"], "carboidrati"))
        for veg in vegetables:
            if veg.get("name") and veg.get("grams"):
                content.append(_make_ing(veg["name"], veg["grams"], "verdure"))

        cooking = result.get("cooking_method", "tegame")
        return {
            "name": result.get("meal_name", "Pasto AI"),
            "description": result.get("notes", ""),
            "is_composed_dish": False,
            "content": content,
            "steps": [],
            "total_time_minutes": 30,
            "difficulty": "facile",
            "tags": {
                "cooking_methods": [cooking],
                "mood": ["normale"],
                "cleanup": ["facile"],
            },
        }

    def _enforce_fallbacks(
        self,
        recipe_data: dict,
        carb_target: int,
        protein_target: int,
        carb_options: List[str],
        protein_options: List[str],
        profile_A: schemas.UserProfile,
        profile_B: schemas.UserProfile,
    ) -> dict:
        """
        Garantisce SEMPRE esattamente 1 carboidrato e 1 proteina con grammature target esatte.

        Logica deterministica:
        - Se l'ingrediente esiste: corregge le grammature al valore target (ignora quelle del LLM).
        - Se ce ne sono più d'uno per gruppo: mantiene solo il primo, scarta gli altri.
        - Se manca: aggiunge un fallback con grammatura target.

        Il LLM decide nomi e metodo cottura. Il codice impone sempre le grammature del piano.
        """
        import copy
        result = copy.deepcopy(recipe_data)
        content = result["content"]
        cooking = (result["tags"]["cooking_methods"] or ["tegame"])[0]

        def _set_grams(ing: dict, grams: float):
            """Sovrascrive le grammature per tutti i profili."""
            for pid in ing["quantities"]:
                ing["quantities"][pid] = {"qty": float(grams), "unit": "g", "grams_equiv": float(grams)}

        def _make_fallback_ing(name: str, grams: int, food_group: str) -> dict:
            return {
                "name": name,
                "food_group": food_group,
                "quantities": {
                    profile_A.id: {"qty": float(grams), "unit": "g", "grams_equiv": float(grams)},
                    profile_B.id: {"qty": float(grams), "unit": "g", "grams_equiv": float(grams)},
                },
            }

        carbs    = [i for i in content if i["food_group"] == "carboidrati"]
        proteins = [i for i in content if i["food_group"] == "proteina"]
        others   = [i for i in content if i["food_group"] not in ("carboidrati", "proteina")]

        # --- CARBOIDRATI ---
        if carbs:
            if len(carbs) > 1:
                _LOGGER.warning(
                    f"[enforce] {len(carbs)} carboidrati trovati → mantenuto solo il primo: '{carbs[0]['name']}'"
                )
            chosen = carbs[0]
            old_g = list(chosen["quantities"].values())[0].get("grams_equiv", 0) if chosen["quantities"] else 0
            _set_grams(chosen, carb_target)
            if abs(old_g - carb_target) > 0.5:
                _LOGGER.warning(
                    f"[enforce] Carbo '{chosen['name']}': LLM={old_g}g → corretto a {carb_target}g"
                )
            new_carbs = [chosen]
        elif carb_target > 0:
            if cooking == "forno" and "patate" in carb_options:
                carb_name = "patate"
            elif carb_options:
                carb_name = carb_options[0]
            else:
                carb_name = "pane comune"
            new_carbs = [_make_fallback_ing(carb_name, carb_target, "carboidrati")]
            _LOGGER.warning(f"[enforce] Carboidrato mancante → aggiunto '{carb_name}' {carb_target}g")
        else:
            new_carbs = []

        # --- PROTEINE ---
        if proteins:
            if len(proteins) > 1:
                _LOGGER.warning(
                    f"[enforce] {len(proteins)} proteine trovate → mantenuta solo la prima: '{proteins[0]['name']}'"
                )
            chosen = proteins[0]
            old_g = list(chosen["quantities"].values())[0].get("grams_equiv", 0) if chosen["quantities"] else 0
            _set_grams(chosen, protein_target)
            if abs(old_g - protein_target) > 0.5:
                _LOGGER.warning(
                    f"[enforce] Proteina '{chosen['name']}': LLM={old_g}g → corretta a {protein_target}g"
                )
            new_proteins = [chosen]
        elif protein_target > 0:
            protein_name = protein_options[0] if protein_options else "pollo"
            new_proteins = [_make_fallback_ing(protein_name, protein_target, "proteina")]
            _LOGGER.warning(f"[enforce] Proteina mancante → aggiunta '{protein_name}' {protein_target}g")
        else:
            new_proteins = []

        result["content"] = new_carbs + new_proteins + others
        return result

    def _validate_meal_targets(
        self,
        recipe_data: dict,
        carb_target: int,
        protein_target: int,
        tolerance: float = 1.0,
    ) -> bool:
        """
        Verifica che le grammature di carbo e proteina rispettino i target con tolleranza ±1g.
        Usa il primo profilo trovato per leggere i grams_equiv.
        """
        content = recipe_data.get("content", [])
        actual_carb    = 0.0
        actual_protein = 0.0

        for ing in content:
            fg = ing.get("food_group", "")
            # Leggi grams_equiv dal primo profilo disponibile
            for qty in ing.get("quantities", {}).values():
                grams = qty.get("grams_equiv", 0) or 0
                if fg == "carboidrati":
                    actual_carb += float(grams)
                elif fg == "proteina":
                    actual_protein += float(grams)
                break  # un solo profilo è sufficiente per il totale

        carb_ok    = abs(actual_carb - carb_target) <= tolerance
        protein_ok = abs(actual_protein - protein_target) <= tolerance

        if not carb_ok:
            _LOGGER.error(
                f"[validate] Carbo: attuale={actual_carb}g, target={carb_target}g "
                f"(delta={abs(actual_carb - carb_target):.1f}g > ±{tolerance}g)"
            )
        if not protein_ok:
            _LOGGER.error(
                f"[validate] Proteina: attuale={actual_protein}g, target={protein_target}g "
                f"(delta={abs(actual_protein - protein_target):.1f}g > ±{tolerance}g)"
            )

        return carb_ok and protein_ok

    def _generate_llm_recipe_suggestion(
        self,
        meal_plan_A: schemas.PlannedMeal,
        meal_plan_B: schemas.PlannedMeal,
        profile_A: schemas.UserProfile,
        profile_B: schemas.UserProfile,
        pantry_items: List[schemas.PantryItem],
        consumed_entries_A: List[schemas.ConsumedEntry],
        consumed_entries_B: List[schemas.ConsumedEntry],
        target_protein_category: Optional[str] = None,
        user_preferences: Optional[Dict[str, List[str]]] = None,
        used_recipe_names: Optional[List[str]] = None,
    ) -> Optional[schemas.ChangeRecipeOption]:
        """
        Flusso completo:
        1. Costruzione prompt con target reali e opzioni concrete
        2. Chiamata LLM via gateway
        3. Parsing JSON → recipe_data
        4. Enforcement fallback (carbo/proteina mancanti)
        5. Validazione grammature (±1g)
        6. Salvataggio CandidateRecipe solo se conforme
        """
        if not self.llm_gateway:
            _LOGGER.warning("LLM Gateway non disponibile, impossibile generare ricetta.")
            return None

        _LOGGER.info(
            f"Avvio generazione LLM (target_protein_category={target_protein_category}, "
            f"avoid={len(used_recipe_names or [])} ricette)..."
        )

        from datetime import datetime as _dt

        # 1. Prompt
        prompt, carb_target, protein_target, carb_options, protein_options = (
            self._build_llm_prompt(
                meal_plan_A, meal_plan_B, profile_A,
                target_protein_category=target_protein_category,
                user_preferences=user_preferences,
                used_recipe_names=used_recipe_names,
            )
        )

        # Build a log entry for this LLM call
        log_entry = {
            "timestamp": _dt.now().isoformat(timespec="seconds"),
            "meal_type": meal_plan_A.meal_type,
            "target_protein_category": target_protein_category,
            "carb_target_g": carb_target,
            "protein_target_g": protein_target,
            "avoid_count": len(used_recipe_names or []),
            "prompt": prompt,
            "raw_response": None,
            "parsed_name": None,
            "status": "pending",
        }
        _LLM_CALL_LOG.append(log_entry)
        if len(_LLM_CALL_LOG) > _LLM_CALL_LOG_MAX:
            _LLM_CALL_LOG.pop(0)

        # 2. Chiamata LLM (via gateway, senza accedere a _client)
        raw = self.llm_gateway.generate_structured_meal(prompt)
        log_entry["raw_response"] = raw
        if not raw:
            _LOGGER.error("LLM non ha restituito nulla.")
            log_entry["status"] = "no_response"
            return None

        # 3. Parsing
        recipe_data = self._parse_llm_recipe_response(raw, profile_A, profile_B, meal_plan_A.meal_type)
        if not recipe_data:
            log_entry["status"] = "parse_error"
            return None

        log_entry["parsed_name"] = recipe_data.get("name")

        # 4. Enforcement fallback lato codice
        recipe_data = self._enforce_fallbacks(
            recipe_data, carb_target, protein_target,
            carb_options, protein_options, profile_A, profile_B,
        )

        # 5. Validazione grammature
        if not self._validate_meal_targets(recipe_data, carb_target, protein_target):
            _LOGGER.error(
                f"[LLM] Ricetta '{recipe_data.get('name')}' scartata: grammature non conformi ai target."
            )
            log_entry["status"] = "validation_failed"
            return None

        # 6. Salvataggio
        try:
            candidate_id = str(uuid.uuid4())
            db_candidate = CandidateRecipe(
                id=candidate_id,
                status="draft_structured",
                recipe_data=recipe_data,
            )
            self.db.add(db_candidate)
            self.db.commit()
            _LOGGER.info(f"[LLM] CandidateRecipe salvata: {candidate_id} → '{recipe_data['name']}'")
            log_entry["status"] = "ok"
            log_entry["candidate_id"] = candidate_id

            cooking = (recipe_data["tags"]["cooking_methods"] or ["tegame"])[0]
            key_ingredients = [ing["name"] for ing in recipe_data["content"][:2]]
            # Task 4: build deterministic display name
            display_name = self._make_display_name(recipe_data["content"])

            return schemas.ChangeRecipeOption(
                option_id=str(uuid.uuid4()),
                recipe_id=candidate_id,
                name=display_name,
                total_time_minutes=recipe_data["total_time_minutes"],
                difficulty=recipe_data["difficulty"],
                cleanup_score="facile",
                key_ingredients=key_ingredients,
                divergence_strategy="llm_generated",
                divergence_details=recipe_data.get("description", ""),
            )
        except Exception as e:
            _LOGGER.error(f"Errore nel salvataggio della ricetta AI: {e}")
            log_entry["status"] = "save_error"
            self.db.rollback()
            return None

    def suggest_recipes_for_meal(self, meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, request_params,
                                 excluded_protein_category: Optional[str] = None,
                                 excluded_recipe_ids: Optional[set] = None,
                                 excluded_fingerprints: Optional[set] = None,
                                 protein_cat_counts: Optional[Dict[str, int]] = None,
                                 protein_cat_limits: Optional[Dict[str, int]] = None,
                                 target_protein_category: Optional[str] = None,
                                 protein_item_counts: Optional[Dict[str, int]] = None,
                                 recent_protein_items: Optional[List[str]] = None,
                                 carb_item_counts: Optional[Dict[str, int]] = None,
                                 recent_carb_items: Optional[List[str]] = None,
                                 day_slot: int = 0,
                                 _debug_log: Optional[dict] = None,
                                 target_count: int = 3,
                                 use_llm_fill: bool = False,
                                 allow_llm: bool = True,
                                 strict_target_protein: bool = False):
        
        profile_A = self._get_user_profile(profile_id_A)
        profile_B = self._get_user_profile(profile_id_B)
        
        # We can proceed even if profile_B is a dummy profile and not found in DB
        if not profile_A:
            _LOGGER.error(f"User profile not found for {profile_id_A}.")
            return None
        if not profile_B:
             _LOGGER.warning(f"User profile not found for {profile_id_B}, will use a dummy profile.")
             profile_B = schemas.UserProfile(id=profile_id_B, name="Dummy")


        all_recipes = self._get_all_recipes()
        pantry_items = self._get_pantry_items()
        seasonality_data = self._get_seasonality_data()
        consumed_entries_A = self._get_consumed_entries(profile_id_A, current_date, self.ANTI_REPETITION_DAYS)

        consumed_entries_B = []
        if profile_id_B:
            consumed_entries_B = self._get_consumed_entries(profile_id_B, current_date, self.ANTI_REPETITION_DAYS)

        if _debug_log is not None:
            _debug_log["n_total_recipes"] = len(all_recipes)
            _debug_log["hard_constraint_pass"] = []
            _debug_log["hard_constraint_fail"] = []
            _debug_log["protein_limit_filtered"] = []
            _debug_log["used_ids_filtered"] = []
            _debug_log["protein_cat_excluded"] = []
            _debug_log["target_protein_narrowed"] = []
            _debug_log["protein_item_filtered"] = []
            _debug_log["scored_recipes"] = []
            _debug_log["n_final_candidates"] = 0
            _debug_log["consumed_entries_count"] = len(consumed_entries_A) + len(consumed_entries_B)

        valid_recipes = []
        for recipe in all_recipes:
            is_valid, divergence_strategy, divergence_details = self._filter_hard_constraints(
                recipe, meal_plan_A, meal_plan_B,
                profile_A, profile_B,
                consumed_entries_A, consumed_entries_B, request_params,
                current_date
            )

            if is_valid:
                valid_recipes.append({
                    "recipe": recipe,
                    "divergence_strategy": divergence_strategy,
                    "divergence_details": divergence_details
                })
                if _debug_log is not None:
                    _debug_log["hard_constraint_pass"].append(recipe.name)
            else:
                if _debug_log is not None:
                    _debug_log["hard_constraint_fail"].append(recipe.name)
        _LOGGER.debug(f"Valid recipes after hard constraints: {[r['recipe'].name for r in valid_recipes]}")

        # Hard stop: protein category at weekly max (variety constraint)
        if protein_cat_counts is not None and protein_cat_limits:
            before = len(valid_recipes)
            def _under_protein_limit(recipe: schemas.Recipe) -> bool:
                cat = self._recipe_protein_cat(recipe)
                return cat is None or protein_cat_counts.get(cat, 0) < protein_cat_limits.get(cat, 999)
            excluded_by_limit = [r["recipe"].name for r in valid_recipes if not _under_protein_limit(r["recipe"])]
            valid_recipes = [r for r in valid_recipes if _under_protein_limit(r["recipe"])]
            if _debug_log is not None:
                _debug_log["protein_limit_filtered"] = excluded_by_limit
            _LOGGER.info(
                f"[protein-limits] Excluded {before - len(valid_recipes)} recipe(s) "
                f"over weekly limit. Counts={protein_cat_counts}, Limits={protein_cat_limits}"
            )

        # Exclude recipes already used in this generation run (hard filter, avoids repeats)
        if excluded_recipe_ids:
            before = len(valid_recipes)
            excluded_by_ids = [r["recipe"].name for r in valid_recipes if r["recipe"].id in excluded_recipe_ids]
            valid_recipes = [r for r in valid_recipes if r["recipe"].id not in excluded_recipe_ids]
            if _debug_log is not None:
                _debug_log["used_ids_filtered"] = excluded_by_ids
            _LOGGER.info(
                f"[excluded-ids] Excluded {before - len(valid_recipes)} already-used recipe(s)"
            )

        # Exclude recipes whose ingredient fingerprint already appeared this week (prevents
        # visually identical meals even with different recipe IDs)
        if excluded_fingerprints:
            before = len(valid_recipes)
            valid_recipes = [
                r for r in valid_recipes
                if self._recipe_fingerprint(r["recipe"]) not in excluded_fingerprints
            ]
            _LOGGER.info(
                f"[fingerprint-filter] Excluded {before - len(valid_recipes)} recipe(s) with duplicate ingredient fingerprint"
            )

        # Task 5: exclude recipes whose main protein matches the same-day pranzo protein
        if excluded_protein_category:
            before = len(valid_recipes)
            def _cat_of(r):
                return self._PROTEIN_CATEGORY_MAP.get(
                    self._normalize_food_group(
                        next(
                            (ing.food_group for ing in (
                                r["recipe"].content.components if r["recipe"].is_composed_dish else r["recipe"].content
                            ) if ing.food_group.lower() in self._PROTEIN_CATEGORY_MAP),
                            ""
                        )
                    ), None
                )
            if _debug_log is not None:
                _debug_log["protein_cat_excluded"] = [
                    r["recipe"].name for r in valid_recipes if _cat_of(r) == excluded_protein_category
                ]
            valid_recipes = [r for r in valid_recipes if _cat_of(r) != excluded_protein_category]
            _LOGGER.info(
                f"[protein-constraint] Excluded {before - len(valid_recipes)} recipe(s) "
                f"with protein category '{excluded_protein_category}'"
            )

        # Soft preference: if target_protein_category given, prefer matching recipes; fall back to all
        target_category_unmet = False
        if target_protein_category:
            preferred = [r for r in valid_recipes if self._recipe_protein_cat(r["recipe"]) == target_protein_category]
            if preferred:
                if _debug_log is not None:
                    _debug_log["target_protein_narrowed"] = [
                        r["recipe"].name for r in valid_recipes if r["recipe"].name not in {p["recipe"].name for p in preferred}
                    ]
                _LOGGER.info(
                    f"[target-protein] Narrowed {len(valid_recipes)} → {len(preferred)} "
                    f"recipe(s) matching '{target_protein_category}'"
                )
                valid_recipes = preferred
            else:
                target_category_unmet = True
                if strict_target_protein:
                    _LOGGER.info(
                        f"[target-protein] strict=True, nessuna ricetta DB per '{target_protein_category}' → lista vuota (forza fallback LLM)"
                    )
                    return []
                _LOGGER.info(
                    f"[target-protein] No recipes match '{target_protein_category}', keeping all {len(valid_recipes)}. "
                    f"Will trigger LLM if catalog candidates insufficient."
                )

        # Step B Tier 1: max 2/week per specific protein item (soft filter, keeps variety)
        if protein_item_counts:
            over_limit = {k for k, v in protein_item_counts.items() if v >= 2}
            preferred = [
                r for r in valid_recipes
                if (self._get_main_protein_item_from_recipe(r["recipe"]) or "") not in over_limit
            ]
            if preferred:
                if _debug_log is not None:
                    _debug_log["protein_item_filtered"] = [
                        r["recipe"].name for r in valid_recipes if r["recipe"].name not in {p["recipe"].name for p in preferred}
                    ]
                valid_recipes = preferred
                _LOGGER.info(
                    f"[protein-item-filter] Narrowed to {len(preferred)} recipe(s) "
                    f"excluding items used ≥2 times: {over_limit}"
                )

        # Varietà carboidrati (soft): evita lo stesso carbo per >= 3 slot a settimana
        # e nello slot immediatamente precedente. Si applica solo se restano alternative.
        if carb_item_counts is not None or recent_carb_items:
            over_carbs = {k for k, v in (carb_item_counts or {}).items() if v >= 3}
            over_carbs |= set((recent_carb_items or [])[-1:])
            if over_carbs:
                preferred = [
                    r for r in valid_recipes
                    if (self._get_main_carb_item_from_recipe(r["recipe"]) or "") not in over_carbs
                ]
                if preferred:
                    valid_recipes = preferred
                    _LOGGER.info(
                        f"[carb-variety] Narrowed to {len(preferred)} recipe(s) excluding carbs: {over_carbs}"
                    )

        # Soft filter: prefer balanced meals (protein + carb)
        # If composed (protein+carb) recipes exist in pool → keep only those.
        # If none exist BUT we still have ID exclusions → return empty to force fallback 2,
        #   where ID restrictions are lifted and composed options reappear.
        # If none exist AND no ID restrictions (already fallback 2) → accept whatever is left.
        _prot_norm = {"proteina", "proteine", "pollo", "carne_bianca", "pesce", "carne_rossa",
                      "legum", "uova", "uov", "latticini", "latticin", "formaggio"}
        _carb_norm = {"carboidrat", "carboidrato"}

        def _is_composed(recipe):
            ings = recipe.content.components if recipe.is_composed_dish else recipe.content
            fgs = {self._normalize_food_group(getattr(i, "food_group", "")) for i in ings}
            return bool(fgs & _prot_norm) and bool(fgs & _carb_norm)

        composed_only = [r for r in valid_recipes if _is_composed(r["recipe"])]
        if composed_only:
            valid_recipes = composed_only
            _LOGGER.info(f"[composed-filter] Narrowed to {len(composed_only)} balanced (protein+carb) recipe(s)")
        elif excluded_recipe_ids:
            # No composed in current filtered pool, but we have ID exclusions.
            # Return empty to trigger fallback 2 (which relaxes ID exclusions → composed reappear).
            _LOGGER.info("[composed-filter] No balanced recipes in pool (all ID-excluded); returning empty to force fallback")
            valid_recipes = []

        # Load veg_target from PlanRules for the soft constraint
        _veg_min_grams: float = 0.0
        _veg_portion_overrides: Optional[Dict[str, float]] = None
        _plan_rules_veg = self.db.query(PlanRules).filter(PlanRules.profile_id == profile_id_A).first()
        if _plan_rules_veg and _plan_rules_veg.veg_target:
            _veg_min_grams = float(_plan_rules_veg.veg_target.get("min_grams") or 0)
            _veg_portion_overrides = _plan_rules_veg.veg_target.get("portion_grams") or None

        filtered_recipes = []
        for recipe_info in valid_recipes:
            recipe = recipe_info["recipe"]

            dosed_recipe = self._calculate_dosing(recipe, profile_A, profile_B)
            score = self._score_soft_constraints(
                dosed_recipe, pantry_items, seasonality_data, current_date,
                consumed_entries_A, consumed_entries_B, recent_protein_items,
                protein_cat_counts=protein_cat_counts,
                protein_cat_limits=protein_cat_limits,
                day_slot=day_slot,
            )

            # Soft constraint: verdure minime (da veg_target in PlanRules)
            if _veg_min_grams > 0:
                _rc = getattr(dosed_recipe.content, "components", None) or dosed_recipe.content
                portions = self._veg_portions_in_recipe(_rc, _veg_portion_overrides)
                min_portions = _veg_min_grams / PlannerEngine._VEG_DEFAULT_PORTION_GRAMS
                if portions < min_portions:
                    score -= 0.2

            # Bonus for composed meals (protein + carb) — prefer balanced over pure-carb/pure-protein
            _ings = getattr(dosed_recipe.content, "components", None) or dosed_recipe.content
            _fgs = {self._normalize_food_group(getattr(i, "food_group", "")) for i in _ings}
            _prot_fgs = {"proteina", "proteine", "pollo", "carne_bianca", "pesce", "carne_rossa", "legum", "latticini", "formaggio"}
            _carb_fgs = {"carboidrat", "carboidrato"}
            if _fgs & _prot_fgs and _fgs & _carb_fgs:
                score += 0.5

            filtered_recipes.append({
                "recipe": dosed_recipe,
                "score": score,
                "divergence_strategy": recipe_info["divergence_strategy"],
                "divergence_details": recipe_info["divergence_details"]
            })
        _LOGGER.debug(f"Filtered recipes after scoring: {[r['recipe'].name for r in filtered_recipes]}")

        filtered_recipes.sort(key=lambda x: x["score"], reverse=True)

        if _debug_log is not None:
            _debug_log["scored_recipes"] = [
                {"name": r["recipe"].name, "id": r["recipe"].id, "score": round(r["score"], 4)}
                for r in filtered_recipes
            ]
            _debug_log["n_final_candidates"] = len(filtered_recipes)
        
        candidate_options = []
        for rec_info in filtered_recipes[:target_count]:
            recipe_content_list = rec_info["recipe"].content.components if rec_info["recipe"].is_composed_dish else rec_info["recipe"].content
            key_ingredients = [item.name for item in recipe_content_list if item.name][0:2]

            cleanup_score = rec_info["recipe"].tags.get("cleanup", ["normal"])[0] if rec_info["recipe"].tags and "cleanup" in rec_info["recipe"].tags else "normal"

            # Task 4: deterministic display name from content
            content_raw = [{"name": i.name, "food_group": i.food_group} for i in recipe_content_list]
            display_name = self._make_display_name(content_raw) if content_raw else rec_info["recipe"].name

            candidate_options.append(schemas.ChangeRecipeOption(
                option_id=str(uuid.uuid4()),
                recipe_id=rec_info["recipe"].id,
                name=display_name,
                total_time_minutes=rec_info["recipe"].total_time_minutes,
                difficulty=rec_info["recipe"].difficulty,
                cleanup_score=cleanup_score,
                key_ingredients=key_ingredients,
                divergence_strategy=rec_info["divergence_strategy"] if rec_info["divergence_strategy"] else "none",
                divergence_details=rec_info["divergence_details"]
            ))

        # Trigger LLM if: no candidates, OR target protein unmet, OR fill mode (always in fantasy, or catalog insufficient)
        need_llm = allow_llm and (
            not candidate_options
            or target_category_unmet
            or use_llm_fill  # fantasy_mode: always call LLM to prepend creative option
        )

        if need_llm:
            needed = (target_count - len(candidate_options)) if use_llm_fill else 1
            needed = max(needed, 1)
            reason = (
                "no candidates" if not candidate_options
                else f"target category '{target_protein_category}' unmet" if target_category_unmet
                else f"fill mode: {len(candidate_options)}/{target_count} from catalog"
            )
            _LOGGER.info(f"[LLM trigger] Reason: {reason}, needed={needed}")

            # Build avoid list from recently used recipe IDs
            recipe_name_by_id = {r.id: r.name for r in all_recipes}
            base_avoid = [
                recipe_name_by_id[rid] for rid in (excluded_recipe_ids or set())
                if rid in recipe_name_by_id
            ]
            if excluded_fingerprints:
                for fp in excluded_fingerprints:
                    combo = " + ".join(sorted(fp))
                    if combo not in base_avoid:
                        base_avoid.append(f"[combo già usata: {combo}]")

            prefs = self._extract_user_preferences()
            llm_options: List[schemas.ChangeRecipeOption] = []

            for _llm_i in range(min(needed, 3)):  # max 3 LLM calls
                avoid_for_call = base_avoid + [opt.name for opt in llm_options]
                llm_suggestion = self._generate_llm_recipe_suggestion(
                    meal_plan_A, meal_plan_B, profile_A, profile_B,
                    pantry_items, consumed_entries_A, consumed_entries_B,
                    target_protein_category=target_protein_category,
                    user_preferences=prefs,
                    used_recipe_names=avoid_for_call,
                )
                if not llm_suggestion:
                    break

                # Fingerprint duplicate check
                skip = False
                if excluded_fingerprints:
                    from .database import CandidateRecipe as _CR
                    llm_cand = self.db.query(_CR).filter(_CR.id == llm_suggestion.recipe_id).first()
                    if llm_cand is not None and llm_cand.recipe_data is not None:
                        _content = llm_cand.recipe_data.get("content", [])
                        _fg = PlannerEngine._FINGERPRINT_GROUPS
                        llm_fp = frozenset(
                            ing["name"].lower().strip()
                            for ing in _content
                            if isinstance(ing, dict)
                            and (ing.get("food_group") or "").lower() in _fg
                            and ing.get("name")
                        )
                        if llm_fp in excluded_fingerprints:
                            _LOGGER.warning(f"[LLM fingerprint duplicate] Skipping LLM suggestion #{_llm_i+1}")
                            skip = True
                if not skip:
                    llm_options.append(llm_suggestion)

            # Merge: LLM first when ExtraFantasy mode or target category unmet; catalog first otherwise
            if not candidate_options:
                return llm_options[:target_count]
            if use_llm_fill or target_category_unmet:
                return (llm_options + candidate_options)[:target_count]
            return (candidate_options + llm_options)[:target_count]

        return candidate_options

    def debug_generate_weekly_plan(
        self,
        profile_id_A: str,
        profile_id_B: Optional[str],
        start_date: date,
    ) -> List[dict]:
        """
        Dry-run generation that returns a detailed trace (one dict per slot) without
        saving anything to the DB.  Used by GET /planner/debug-generate.
        Each slot dict contains:
            date, meal_type, target_protein_category, excluded_protein_category,
            protein_cat_counts_before, used_recipe_ids_before,
            consumed_entries_count,
            n_total_recipes, hard_constraint_pass, hard_constraint_fail,
            protein_limit_filtered, used_ids_filtered, protein_cat_excluded,
            target_protein_narrowed, protein_item_filtered,
            scored_recipes, n_final_candidates,
            selected_name, selected_id
        """
        plan_rules = self._get_latest_plan_rules(profile_id_A)

        if plan_rules and plan_rules.frequency_targets:
            protein_sequence = self._build_protein_sequence(plan_rules.frequency_targets)
            protein_cat_limits: Dict[str, int] = {}
            for cat, tgt in plan_rules.frequency_targets.items():
                hard_max = tgt.get("hard_max")
                protein_cat_limits[cat] = int(hard_max if hard_max is not None else tgt.get("max", 7))
            protein_cat_limits.setdefault("carne_bianca", 3)
        else:
            protein_sequence = [None] * 14
            # Legacy path: try to load StructuredMealPlan for limits
            raw_plan = self._get_latest_meal_plan(profile_id_A)
            protein_cat_limits = self._build_protein_limits(raw_plan.rotation_rules if raw_plan else [])

        protein_cat_counts: Dict[str, int] = {}
        protein_item_counts: Dict[str, int] = {}
        recent_protein_items: List[str] = []
        used_recipe_ids: set = set()
        day_slot = 0
        trace: List[dict] = []

        for i in range(7):
            current_date = start_date + timedelta(days=i)
            pranzo_protein_category: Optional[str] = None

            for meal_idx, meal_type in enumerate(["pranzo", "cena"]):
                seq_idx = i * 2 + meal_idx
                target_cat = protein_sequence[seq_idx] if seq_idx < len(protein_sequence) else None
                excluded_protein = pranzo_protein_category if meal_type == "cena" else None

                # Build meal plan for this slot
                if plan_rules:
                    meal_plan_A = self._rules_to_planned_meal(plan_rules, meal_type, target_cat)
                    meal_plan_B = schemas.PlannedMeal(meal_type=meal_type, items=[])
                else:
                    raw_plan = self._get_latest_meal_plan(profile_id_A)
                    if not raw_plan:
                        trace.append({
                            "date": current_date.isoformat(),
                            "meal_type": meal_type,
                            "error": "No StructuredMealPlan found for profile_A",
                        })
                        day_slot += 1
                        continue
                    daily_plan = next(
                        (d for d in raw_plan.daily_plans
                         if date.fromisoformat(d.date).weekday() == current_date.weekday()),
                        None
                    )
                    if not daily_plan:
                        trace.append({
                            "date": current_date.isoformat(),
                            "meal_type": meal_type,
                            "error": "No daily_plan matching weekday",
                        })
                        day_slot += 1
                        continue
                    meal_plan_A = next((m for m in daily_plan.meals if m.meal_type == meal_type), None)
                    if not meal_plan_A:
                        trace.append({
                            "date": current_date.isoformat(),
                            "meal_type": meal_type,
                            "error": f"No '{meal_type}' entry in daily_plan",
                        })
                        day_slot += 1
                        continue
                    meal_plan_B = schemas.PlannedMeal(meal_type=meal_type, items=[])

                debug_log: dict = {
                    "date": current_date.isoformat(),
                    "meal_type": meal_type,
                    "target_protein_category": target_cat,
                    "excluded_protein_category": excluded_protein,
                    "protein_cat_counts_before": dict(protein_cat_counts),
                    "protein_cat_limits": dict(protein_cat_limits),
                    "used_recipe_ids_before": list(used_recipe_ids),
                    "recent_protein_items": list(recent_protein_items),
                }

                results = self.suggest_recipes_for_meal(
                    meal_plan_A, meal_plan_B,
                    profile_id_A, profile_id_B,
                    current_date, {},
                    excluded_protein_category=excluded_protein,
                    excluded_recipe_ids=set(used_recipe_ids),  # copy so mutations don't leak
                    protein_cat_counts=dict(protein_cat_counts),
                    protein_cat_limits=protein_cat_limits,
                    target_protein_category=target_cat,
                    protein_item_counts=dict(protein_item_counts),
                    recent_protein_items=list(recent_protein_items),
                    day_slot=day_slot,
                    _debug_log=debug_log,
                )

                if results:
                    selected = results[0]
                    debug_log["selected_name"] = selected.name
                    debug_log["selected_id"] = selected.recipe_id
                    # Advance state exactly like the real generation
                    used_recipe_ids.add(selected.recipe_id)
                    cat = self._get_main_protein_category(selected.recipe_id)
                    if cat:
                        protein_cat_counts[cat] = protein_cat_counts.get(cat, 0) + 1
                    item = self._get_main_protein_item(selected.recipe_id)
                    if item:
                        protein_item_counts[item] = protein_item_counts.get(item, 0) + 1
                        recent_protein_items.append(item)
                        if len(recent_protein_items) > 3:
                            recent_protein_items.pop(0)
                    if meal_type == "pranzo":
                        pranzo_protein_category = cat
                else:
                    debug_log["selected_name"] = None
                    debug_log["selected_id"] = None

                day_slot += 1
                trace.append(debug_log)

        return trace

    def get_component_alternatives(
        self,
        recipe_id: str,
        component: str,  # 'carb', 'protein', or 'veg'
        meal_plan_A: schemas.PlannedMeal,
        profile_A: schemas.UserProfile,
        profile_B: schemas.UserProfile,
    ) -> List[schemas.ChangeRecipeOption]:
        """
        Returns CandidateRecipe options where only the specified component
        (carb/protein/veg) is swapped from the current recipe.
        """
        current_ingredients, _ = self._get_recipe_content(recipe_id)
        if not current_ingredients:
            return []

        # Convert any Pydantic RecipeIngredient objects to plain dicts
        def _ing_to_dict(ing) -> dict:
            if isinstance(ing, dict):
                return ing
            d = ing.model_dump()
            d["quantities"] = {
                k: (v.model_dump() if hasattr(v, "model_dump") else v)
                for k, v in d["quantities"].items()
            }
            return d

        def _make_qty(grams: float) -> dict:
            return {"qty": float(grams), "unit": "g", "grams_equiv": float(grams)}

        # ── VEG swap ──────────────────────────────────────────────────────────
        if component == "veg":
            kept_ingredients = [
                _ing_to_dict(ing) for ing in current_ingredients
                if (ing.get("food_group") if isinstance(ing, dict) else ing.food_group or "").lower() != "verdure"
            ]
            # Current veg grams (any profile) for equivalence scaling
            current_veg_grams: float = 150.0
            for ing in current_ingredients:
                fg = (ing.get("food_group") if isinstance(ing, dict) else ing.food_group or "").lower()
                if fg == "verdure":
                    qty_raw = ing.get("quantities") if isinstance(ing, dict) else {}
                    for v in qty_raw.values():
                        g = float(v.get("grams_equiv") or v.get("qty") or 0) if isinstance(v, dict) else 0.0
                        if g > 0:
                            current_veg_grams = g
                            break
                    break
            current_veg_name = ""
            for ing in current_ingredients:
                fg = (ing.get("food_group") if isinstance(ing, dict) else ing.food_group or "").lower()
                if fg == "verdure":
                    current_veg_name = (ing.get("name") if isinstance(ing, dict) else ing.name or "").lower()
                    break

            # Load per-profile veg overrides if available
            plan_rules_veg = self.db.query(PlanRules).filter(PlanRules.profile_id == profile_A.id).first()
            portion_overrides: Dict[str, float] = {}
            if plan_rules_veg and plan_rules_veg.veg_target:
                portion_overrides = plan_rules_veg.veg_target.get("portion_grams") or {}

            options = []
            for veg in self._VEG_CATALOG:
                veg_name = veg["name"]
                if veg_name == current_veg_name:
                    continue
                # Scale grams: keep the same number of portions (current_grams / current_portion_size * new_portion_size)
                cur_portion = portion_overrides.get(current_veg_name) or self._VEG_PORTION_GRAMS.get(current_veg_name, self._VEG_DEFAULT_PORTION_GRAMS)
                new_portion = portion_overrides.get(veg_name) or self._VEG_PORTION_GRAMS.get(veg_name, self._VEG_DEFAULT_PORTION_GRAMS)
                scaled_grams = round((current_veg_grams / cur_portion) * new_portion)
                new_ing = {
                    "name": veg_name,
                    "food_group": "verdure",
                    "quantities": {
                        profile_A.id: _make_qty(scaled_grams),
                        profile_B.id: _make_qty(scaled_grams),
                    },
                }
                new_content = list(kept_ingredients) + [new_ing]
                display = self._make_display_name(new_content, specific_veg=veg_name)
                new_recipe_data = {
                    "name": display,
                    "description": f"Variante con {veg_name} al posto della verdura.",
                    "is_composed_dish": False,
                    "content": new_content,
                    "steps": [],
                    "total_time_minutes": 20,
                    "difficulty": "facile",
                    "tags": {"cooking_methods": veg["methods"] or ["tegame"], "mood": ["normale"], "cleanup": ["facile"]},
                }
                try:
                    candidate_id = str(uuid.uuid4())
                    db_candidate = CandidateRecipe(id=candidate_id, status="draft_structured", recipe_data=new_recipe_data)
                    self.db.add(db_candidate)
                    self.db.commit()
                    options.append(schemas.ChangeRecipeOption(
                        option_id=str(uuid.uuid4()),
                        recipe_id=candidate_id,
                        name=display,
                        total_time_minutes=20,
                        difficulty="facile",
                        cleanup_score="facile",
                        key_ingredients=[veg_name],
                        divergence_strategy="swap_veg",
                        divergence_details=f"Verdura cambiata: {veg_name} ({scaled_grams}g)",
                    ))
                except Exception as e:
                    _LOGGER.error(f"Errore creazione CandidateRecipe per verdura '{veg_name}': {e}")
                    self.db.rollback()
            return options

        # ── CARB / PROTEIN swap ───────────────────────────────────────────────
        fg_map = {
            "carb":    ["carboidrati", "carboidrato"],
            "protein": ["proteina", "proteine", "pollo", "pesce", "carne_rossa", "legumi"],
        }
        target_fgs = fg_map.get(component, [])

        # Get current non-target ingredients (keep them as-is, as plain dicts)
        kept_ingredients = [
            _ing_to_dict(ing) for ing in current_ingredients
            if (ing.get("food_group") if isinstance(ing, dict) else ing.food_group or "").lower() not in target_fgs
        ]

        # Get target grams from meal plan
        target_qty = 0
        for item in meal_plan_A.items:
            if item.food_group.lower() in target_fgs:
                target_qty = item.quantity
                break

        # Build list of alternative names from the meal plan items for that component
        alternatives = [item.item_name for item in meal_plan_A.items if item.food_group.lower() in target_fgs and item.item_name]
        # Add plan-agnostic options
        if component == "carb":
            alternatives += ["pasta", "riso", "pane comune", "patate", "couscous"]
        else:
            alternatives += ["pollo", "pesce", "uova", "legumi", "tofu"]

        # Deduplicate, exclude current ingredient names
        current_names = {(ing.get("name") if isinstance(ing, dict) else ing.name or "").lower() for ing in current_ingredients if (ing.get("food_group") if isinstance(ing, dict) else ing.food_group or "").lower() in target_fgs}
        alternatives = list(dict.fromkeys(a for a in alternatives if a.lower() not in current_names))[:4]

        if not alternatives:
            return []

        options = []
        for alt_name in alternatives:
            food_group = "carboidrati" if component == "carb" else "proteina"
            new_ing = {
                "name": alt_name,
                "food_group": food_group,
                "quantities": {
                    profile_A.id: _make_qty(target_qty),
                    profile_B.id: _make_qty(target_qty),
                },
            }
            new_content = list(kept_ingredients) + [new_ing]
            display = self._make_display_name(new_content)
            new_recipe_data = {
                "name": display,
                "description": f"Variante con {alt_name} al posto del {component}.",
                "is_composed_dish": False,
                "content": new_content,
                "steps": [],
                "total_time_minutes": 20,
                "difficulty": "facile",
                "tags": {"cooking_methods": ["tegame"], "mood": ["normale"], "cleanup": ["facile"]},
            }
            try:
                candidate_id = str(uuid.uuid4())
                db_candidate = CandidateRecipe(id=candidate_id, status="draft_structured", recipe_data=new_recipe_data)
                self.db.add(db_candidate)
                self.db.commit()
                options.append(schemas.ChangeRecipeOption(
                    option_id=str(uuid.uuid4()),
                    recipe_id=candidate_id,
                    name=display,
                    total_time_minutes=20,
                    difficulty="facile",
                    cleanup_score="facile",
                    key_ingredients=[alt_name],
                    divergence_strategy=f"swap_{component}",
                    divergence_details=f"Solo {component} cambiato: {alt_name} ({target_qty}g)",
                ))
            except Exception as e:
                _LOGGER.error(f"Errore creazione CandidateRecipe per variante '{alt_name}': {e}")
                self.db.rollback()

        return options

    def apply_recipe_to_plan(
        self,
        profile_id_A: str,
        profile_id_B: str,
        meal_type: str,
        current_date: date,
        recipe_id: str
    ) -> bool:
        import copy
        # Find the plan whose 7-day window covers current_date (rolling, no Monday-snapping)
        all_plans = self.db.query(GeneratedWeeklyPlan).filter(
            GeneratedWeeklyPlan.profile_id_A == profile_id_A,
        ).all()
        plan = None
        for p in all_plans:
            plan_start = date.fromisoformat(p.week_start_date)
            if plan_start <= current_date <= plan_start + timedelta(days=6):
                plan = p
                break
        if not plan:
            _LOGGER.warning(f"No GeneratedWeeklyPlan found for {profile_id_A} week {week_start.isoformat()}")
            return False
        recipe = self.db.query(Recipe).filter(Recipe.id == recipe_id).first()
        if recipe:
            recipe_name = recipe.name
        else:
            # Ricerca in CandidateRecipe (ricette generate dall'LLM non ancora approvate)
            candidate = self.db.query(CandidateRecipe).filter(CandidateRecipe.id == recipe_id).first()
            if candidate:
                recipe_name = candidate.recipe_data.get("name", "Ricetta AI") if isinstance(candidate.recipe_data, dict) else getattr(candidate.recipe_data, "name", "Ricetta AI")
                _LOGGER.info(f"Recipe {recipe_id} found in CandidateRecipe: {recipe_name}")
                # Incrementa usage_count e auto-promuove se soglia raggiunta
                candidate.usage_count = (candidate.usage_count or 0) + 1
                if candidate.usage_count >= 2 and candidate.status == "draft_structured":
                    candidate.status = "approved"
                    _LOGGER.info(f"CandidateRecipe {recipe_id} auto-promossa ad 'approved' (usage_count={candidate.usage_count})")
                self.db.add(candidate)
            else:
                _LOGGER.warning(f"Recipe {recipe_id} not found in Recipe or CandidateRecipe.")
                return False
        updated = copy.deepcopy(plan.daily_plans)
        for day in updated:
            if day["date"] == current_date.isoformat():
                for meal in day["meals"]:
                    if meal["meal_type"] == meal_type:
                        meal["items"] = [{"item_name": recipe_name, "food_group": "recipe",
                                          "quantity": 1, "unit": "recipe",
                                          "is_estimated_unit": False, "alternatives": [],
                                          "recipe_id": recipe_id}]
        plan.daily_plans = updated
        self.db.add(plan)
        self.db.commit()
        return True

    def _get_recipe_content(self, recipe_id: str):
        """Returns (ingredients_list, is_composed) from Recipe or CandidateRecipe by ID."""
        db_recipe = self.db.query(Recipe).filter(Recipe.id == recipe_id).first()
        if db_recipe:
            rec = schemas.Recipe.from_orm(db_recipe)
            if rec.is_composed_dish:
                return rec.content.components, True
            return rec.content, False

        candidate = self.db.query(CandidateRecipe).filter(CandidateRecipe.id == recipe_id).first()
        if candidate:
            data = candidate.recipe_data if isinstance(candidate.recipe_data, dict) else candidate.recipe_data.model_dump()
            content_raw = data.get("content", [])
            ingredients = [schemas.RecipeIngredient(**i) if isinstance(i, dict) else i for i in content_raw]
            return ingredients, False

        return [], False

    def generate_shopping_list_for_week(self, profile_id_A: str, profile_id_B: str, start_date: date, exclude_consumed: bool = False) -> schemas.AggregatedShoppingList:
        # Find plan by exact start_date (rolling, no Monday-snapping)
        cached = self.db.query(GeneratedWeeklyPlan).filter(
            GeneratedWeeklyPlan.profile_id_A == profile_id_A,
            GeneratedWeeklyPlan.week_start_date == start_date.isoformat()
        ).first()
        if cached:
            weekly_plan = [schemas.DailyPlannedMeals.model_validate(dp) for dp in cached.daily_plans]
        else:
            weekly_plan = self.generate_weekly_plan(profile_id_A, profile_id_B, start_date)
        pantry_items = self._get_pantry_items()

        # Raccogli pasti da escludere dalla spesa:
        # - override free-text (mangiati fuori) sempre esclusi
        # - pasti consumati dal piano (type="recipe") esclusi se exclude_consumed=True
        override_meals: set = set()
        end_date = start_date + timedelta(days=6)
        all_consumed_for_week = self._get_consumed_entries(profile_id_A, end_date, 7)
        if profile_id_B:
            all_consumed_for_week += self._get_consumed_entries(profile_id_B, end_date, 7)
        for entry in all_consumed_for_week:
            if entry.type == "override" and entry.override_details and entry.override_details.free_text_name:
                override_meals.add((entry.date, entry.meal_type))
            elif exclude_consumed and entry.type == "recipe":
                override_meals.add((entry.date, entry.meal_type))

        # item_key → {name, qty_A, qty_B, unit, category, notes}
        required_items: Dict[str, Dict[str, Any]] = {}

        for day in weekly_plan:
            for meal in day.meals:
                if not meal.items:
                    continue
                if (day.date, meal.meal_type) in override_meals:
                    continue

                planned_item = meal.items[0]
                recipe_id = planned_item.recipe_id
                if not recipe_id:
                    continue

                ingredients, _ = self._get_recipe_content(recipe_id)

                for ingredient in ingredients:
                    qty_data_A = ingredient.quantities.get(profile_id_A)
                    qty_data_B = ingredient.quantities.get(profile_id_B) if profile_id_B else None
                    qty_A = float(qty_data_A.grams_equiv or qty_data_A.qty) if qty_data_A else 0.0
                    qty_B = float(qty_data_B.grams_equiv or qty_data_B.qty) if qty_data_B else 0.0
                    total_qty = qty_A + qty_B

                    is_free_vegetable = total_qty == 0 and self._normalize_food_group(ingredient.food_group) == "verdura"
                    shopping_qty = 200.0 if is_free_vegetable else total_qty
                    note = "Quantità stimata" if is_free_vegetable else None

                    if shopping_qty == 0:
                        continue

                    key = ingredient.name.lower()
                    if key in required_items:
                        required_items[key]["qty_A"] += qty_A
                        required_items[key]["qty_B"] += qty_B
                        required_items[key]["quantity"] += shopping_qty
                        if note and not required_items[key].get("notes"):
                            required_items[key]["notes"] = note
                    else:
                        required_items[key] = {
                            "name": ingredient.name,
                            "qty_A": qty_A,
                            "qty_B": qty_B,
                            "quantity": shopping_qty,
                            "unit": "g",
                            "category": self._normalize_food_group(ingredient.food_group),
                            "notes": note,
                        }
        
        shopping_list_items: List[schemas.ShoppingListItem] = []
        for key, item_data in required_items.items():
            pantry_item = next((p for p in pantry_items if p.name.lower() == key), None)
            notes = item_data.get("notes")
            needed_qty = item_data["quantity"]

            if pantry_item and pantry_item.quantity >= needed_qty:
                continue  # fully covered by pantry
            if pantry_item:
                needed_qty = needed_qty - pantry_item.quantity

            # Embed per-profile quantities in notes for UI display
            qty_A = round(item_data["qty_A"])
            qty_B = round(item_data["qty_B"])
            profile_note = f"A:{qty_A}g B:{qty_B}g" if qty_B > 0 else f"A:{qty_A}g"
            combined_notes = f"{profile_note}" + (f" — {notes}" if notes else "")

            shopping_list_items.append(schemas.ShoppingListItem(
                name=item_data["name"],
                quantity=round(needed_qty),
                unit=item_data["unit"],
                category=item_data["category"],
                notes=combined_notes,
            ))

        items_by_category: Dict[str, List[schemas.ShoppingListItem]] = {}
        for item in shopping_list_items:
            cat = item.category or "altro"
            if cat not in items_by_category:
                items_by_category[cat] = []
            items_by_category[cat].append(item)

        return schemas.AggregatedShoppingList(
            generated_at=date.today().isoformat(),
            items_by_category=items_by_category
        )
