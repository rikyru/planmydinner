import logging
import uuid
import json
from datetime import date, timedelta
from typing import List, Dict, Any, Optional
import re

from sqlalchemy.orm import Session
from sqlalchemy import func

from . import schemas
from .database import (
    UserProfile, StructuredMealPlan, Recipe, CandidateRecipe,
    PantryItem, ConsumedEntry, RotationRule, SeasonalityItem, UnitConversion
)

_LOGGER = logging.getLogger(__name__)

class PlannerEngine:
    """
    Core logic for filtering, dosing, and ranking recipes based on meal plans, profiles,
    pantry, seasonality, and consumption history.
    """
    QUANTITY_TOLERANCE_PERCENT = 0.10 # +/- 10%
    ANTI_REPETITION_DAYS = 7 # Defined as a class variable

    def __init__(self, db: Session):
        self.db = db

    def _get_user_profile(self, profile_id: str) -> Optional[schemas.UserProfile]:
        db_profile = self.db.query(UserProfile).filter(UserProfile.id == profile_id).first()
        if db_profile:
            return schemas.UserProfile.from_orm(db_profile)
        return None

    def _get_active_meal_plan(self, profile_id: str, current_date: date) -> Optional[schemas.StructuredMealPlan]:
        _LOGGER.debug(f"Searching for active meal plan for profile {profile_id} on date {current_date.isoformat()}")
        db_plan = self.db.query(StructuredMealPlan).filter(
            StructuredMealPlan.profile_id == profile_id,
            StructuredMealPlan.start_date <= current_date.isoformat(),
            func.julianday(StructuredMealPlan.start_date) + 7 > func.julianday(current_date.isoformat())
        ).order_by(StructuredMealPlan.start_date.desc()).first()
        if db_plan:
            _LOGGER.debug(f"Found active meal plan: {db_plan.id} starting on {db_plan.start_date}")
            return schemas.StructuredMealPlan.from_orm(db_plan)
        _LOGGER.debug(f"No active meal plan found for profile {profile_id}")
        return None

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
        
        all_recipes = [schemas.Recipe.from_orm(rec) for rec in db_recipes]
        all_recipes.extend([schemas.Recipe(**cand.recipe_data.model_dump(), id=cand.id) for cand in db_candidate_recipes])
        return all_recipes

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
            "carne_rossa": [r"\bmanzo\b", r"\bbistecca\b", r"\bcarne trita\b", r"\bsalsiccia\b"],
            "pollo": [r"\bpollo\b", r"\bpetti di pollo\b"],
            "legumi": [r"\bceci\b", r"\blenticchie\b", r"\bfagioli\b"],
            "pesce": [r"\bpesce\b", r"\bsalmone\b", r"\btonno\b", r"\bmerluzzo\b"],
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
               ing_name in [item.lower() for item in profile_B.allergies + profile_B.excluded_foods]:
                _LOGGER.debug(f"Recipe {recipe.id} has unresolvable allergy/exclusion conflicts.")
                return False, None, None

        planned_food_groups_A = {self._normalize_food_group(item.food_group): item.quantity for item in target_meal_plan_A.items if item.quantity > 0}
        _LOGGER.debug(f"Target grammages for profile A from meal plan: {planned_food_groups_A}")
        planned_food_groups_B = {self._normalize_food_group(item.food_group): item.quantity for item in target_meal_plan_B.items if item.quantity > 0}
        _LOGGER.debug(f"Target grammages for profile B from meal plan: {planned_food_groups_B}")
        
        recipe_food_groups_A = {self._normalize_food_group(rec_ing.food_group): rec_ing.quantities["persona_a"].grams_equiv for rec_ing in recipe_ingredients if rec_ing.quantities["persona_a"].grams_equiv is not None}
        recipe_food_groups_B = {self._normalize_food_group(rec_ing.food_group): rec_ing.quantities["persona_b"].grams_equiv for rec_ing in recipe_ingredients if rec_ing.quantities["persona_b"].grams_equiv is not None}

        for fg, planned_qty in planned_food_groups_A.items():
            recipe_qty = recipe_food_groups_A.get(fg, 0)
            if not (planned_qty * (1 - self.QUANTITY_TOLERANCE_PERCENT) <= recipe_qty <= planned_qty * (1 + self.QUANTITY_TOLERANCE_PERCENT)):
                return False, None, None
        
        for fg, planned_qty in planned_food_groups_B.items():
            recipe_qty = recipe_food_groups_B.get(fg, 0)
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
                        consumption_counts[food_group] = consumption_counts.get(food_group, 0) + 1
                        consumption_counts[ing.name.lower()] = consumption_counts.get(ing.name.lower(), 0) + 1
            elif entry.override_details and entry.override_details.ingredients:
                for ing in entry.override_details.ingredients:
                    food_group = self._get_food_group_for_item(ing.name)
                    if food_group:
                        normalized_food_group = self._normalize_food_group(food_group)
                        consumption_counts[normalized_food_group] = consumption_counts.get(normalized_food_group, 0) + 1
                        consumption_counts[ing.name.lower()] = consumption_counts.get(ing.name.lower(), 0) + 1
            elif entry.override_details and entry.override_details.free_text_name:
                food_group = self._get_food_group_for_item(entry.override_details.free_text_name)
                if food_group:
                    normalized_food_group = self._normalize_food_group(food_group)
                    consumption_counts[normalized_food_group] = consumption_counts.get(normalized_food_group, 0) + 1
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
                        # A rule can apply to a food group OR a specific ingredient name
                        if self._normalize_food_group(rec_ing.food_group) == normalized_rule_fg or rec_ing.name.lower() == normalized_rule_fg:
                            _LOGGER.debug(f"!!! Rotation rule triggered for recipe {recipe.id} on '{rule.food_group_or_item}' with ing '{rec_ing.name}'. Current count: {count}, Max: {rule.max_per_week}")
                            return False, None, None
        
        recent_recipe_ids = {e.consumed_recipe_id for e in all_consumed if e.consumed_recipe_id}
        if recipe.id in recent_recipe_ids:
            _LOGGER.debug(f"Recipe {recipe.id} failed anti-repetition.")
            return False, None, None

        return True, "none", ""

    def _calculate_dosing(self, recipe: schemas.Recipe, profile_A: schemas.UserProfile, profile_B: schemas.UserProfile) -> schemas.Recipe:
        return recipe

    def _score_soft_constraints(
        self,
        recipe: schemas.Recipe,
        pantry_items: List[schemas.PantryItem],
        seasonality_data: Dict[str, schemas.SeasonalityItem],
        current_date: date,
        consumed_entries_A: List[schemas.ConsumedEntry],
        consumed_entries_B: List[schemas.ConsumedEntry]
    ) -> float:
        score = 0.0

        recipe_ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content

        ingredients_in_pantry = 0
        for rec_ing in recipe_ingredients:
            if any(pi.name.lower() == rec_ing.name.lower() for pi in pantry_items):
                ingredients_in_pantry += 1
        
        if len(recipe_ingredients) > 0:
            pantry_score = ingredients_in_pantry / len(recipe_ingredients)
            score += pantry_score * 0.4

        expiration_bonus = 0.0
        max_bonus_days = 14
        for rec_ing in recipe_ingredients:
            for pi in pantry_items:
                if pi.name.lower() == rec_ing.name.lower() and pi.expiration_date:
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

        return score

    def generate_weekly_plan(self, profile_id_A: str, profile_id_B: str, start_date: date) -> List[schemas.DailyPlannedMeals]:
        
        weekly_plan_A_raw = self._get_active_meal_plan(profile_id_A, start_date)
        weekly_plan_B_raw = self._get_active_meal_plan(profile_id_B, start_date)

        if not weekly_plan_A_raw or not weekly_plan_B_raw:
            _LOGGER.error(f"Could not find active meal plans for {profile_id_A} or {profile_id_B} on {start_date.isoformat()}.")
            return []

        weekly_plan_A = schemas.StructuredMealPlan(
            **weekly_plan_A_raw.model_dump(exclude={"daily_plans"}),
            daily_plans=[schemas.DailyPlannedMeals.model_validate(dp) for dp in weekly_plan_A_raw.daily_plans]
        )
        weekly_plan_B = schemas.StructuredMealPlan(
            **weekly_plan_B_raw.model_dump(exclude={"daily_plans"}),
            daily_plans=[schemas.DailyPlannedMeals.model_validate(dp) for dp in weekly_plan_B_raw.daily_plans]
        )


        generated_plan: List[schemas.DailyPlannedMeals] = []
        for i in range(7):
            current_date = start_date + timedelta(days=i)
            
            daily_plan_A = next((d for d in weekly_plan_A.daily_plans if date.fromisoformat(d.date) == current_date), None)
            daily_plan_B = next((d for d in weekly_plan_B.daily_plans if date.fromisoformat(d.date) == current_date), None)

            if not daily_plan_A or not daily_plan_B:
                continue

            generated_day = schemas.DailyPlannedMeals(date=current_date.isoformat(), meals=[])
            
            for meal_type in ["pranzo", "cena"]:
                meal_plan_A = next((m for m in daily_plan_A.meals if m.meal_type == meal_type), None)
                meal_plan_B = next((m for m in daily_plan_B.meals if m.meal_type == meal_type), None)

                if not meal_plan_A or not meal_plan_B:
                    continue

                best_recipes = self.suggest_recipes_for_meal(
                    meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, {}
                )

                if best_recipes:
                    best_recipe = best_recipes[0] # Take the first best recipe
                    generated_day.meals.append(schemas.PlannedMeal(
                        meal_type=meal_type,
                        items=[schemas.PlannedItem(
                            item_name=best_recipe.name,
                            food_group="recipe", # Placeholder
                            quantity=1,
                            unit="recipe"
                        )]
                    ))

            generated_plan.append(generated_day)

        return generated_plan

    def suggest_recipes_for_meal(self, meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date, request_params):
        
        profile_A = self._get_user_profile(profile_id_A)
        profile_B = self._get_user_profile(profile_id_B)
        if not profile_A or not profile_B:
            _LOGGER.error(f"User profiles not found for {profile_id_A} or {profile_id_B}.")
            return None

        all_recipes = self._get_all_recipes()
        pantry_items = self._get_pantry_items()
        seasonality_data = self._get_seasonality_data()
        consumed_entries_A = self._get_consumed_entries(profile_id_A, current_date, self.ANTI_REPETITION_DAYS)
        consumed_entries_B = self._get_consumed_entries(profile_id_B, current_date, self.ANTI_REPETITION_DAYS)

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
        _LOGGER.debug(f"Valid recipes after hard constraints: {[r['recipe'].name for r in valid_recipes]}")
        
        filtered_recipes = []
        for recipe_info in valid_recipes:
            recipe = recipe_info["recipe"]
            
            dosed_recipe = self._calculate_dosing(recipe, profile_A, profile_B)
            score = self._score_soft_constraints(dosed_recipe, pantry_items, seasonality_data, current_date, consumed_entries_A, consumed_entries_B)
                
            filtered_recipes.append({
                "recipe": dosed_recipe,
                "score": score,
                "divergence_strategy": recipe_info["divergence_strategy"],
                "divergence_details": recipe_info["divergence_details"]
            })
        _LOGGER.debug(f"Filtered recipes after scoring: {[r['recipe'].name for r in filtered_recipes]}")
        
        filtered_recipes.sort(key=lambda x: x["score"], reverse=True)
        
        candidate_options = []
        for rec_info in filtered_recipes[:3]:
            recipe_content_list = rec_info["recipe"].content.components if rec_info["recipe"].is_composed_dish else rec_info["recipe"].content
            key_ingredients = [item.name for item in recipe_content_list if item.name][0:2]

            cleanup_score = rec_info["recipe"].tags.get("cleanup", ["normal"])[0] if rec_info["recipe"].tags and "cleanup" in rec_info["recipe"].tags else "normal"

            candidate_options.append(schemas.ChangeRecipeOption(
                option_id=str(uuid.uuid4()),
                recipe_id=rec_info["recipe"].id,
                name=rec_info["recipe"].name,
                total_time_minutes=rec_info["recipe"].total_time_minutes,
                difficulty=rec_info["recipe"].difficulty,
                cleanup_score=cleanup_score,
                key_ingredients=key_ingredients,
                divergence_strategy=rec_info["divergence_strategy"] if rec_info["divergence_strategy"] else "none",
                divergence_details=rec_info["divergence_details"]
            ))

        return candidate_options

    def apply_recipe_to_plan(
        self,
        profile_id_A: str,
        profile_id_B: str,
        meal_type: str,
        current_date: date,
        recipe_id: str
    ) -> bool:
        _LOGGER.warning("apply_recipe_to_plan is a placeholder for MVP.")
        return True

    def generate_shopping_list_for_week(self, profile_id_A: str, profile_id_B: str, start_date: date) -> schemas.AggregatedShoppingList:
        weekly_plan = self.generate_weekly_plan(profile_id_A, profile_id_B, start_date)
        pantry_items = self._get_pantry_items()
        
        required_items: Dict[str, Dict[str, Any]] = {}

        for day in weekly_plan:
            for meal in day.meals:
                if not meal.items:
                    continue
                
                recipe_name = meal.items[0].item_name
                recipe = next((r for r in self._get_all_recipes() if r.name == recipe_name), None)

                if not recipe:
                    continue

                recipe_ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content
                for ingredient in recipe_ingredients:
                    
                    qty_A = ingredient.quantities.get("persona_a").grams_equiv or 0
                    qty_B = ingredient.quantities.get("persona_b").grams_equiv or 0
                    total_qty = qty_A + qty_B

                    is_free_vegetable = total_qty == 0 and self._normalize_food_group(ingredient.food_group) == "verdura"
                    
                    shopping_qty = 200 if is_free_vegetable else total_qty
                    note = "Quantità stimata" if is_free_vegetable else None

                    if shopping_qty == 0:
                        continue

                    if ingredient.name in required_items:
                        required_items[ingredient.name]["quantity"] += shopping_qty
                        if note and not required_items[ingredient.name].get("notes"):
                             required_items[ingredient.name]["notes"] = note
                    else:
                        item_data = {
                            "name": ingredient.name,
                            "quantity": shopping_qty,
                            "unit": "g",
                            "category": self._normalize_food_group(ingredient.food_group),
                        }
                        if note:
                            item_data["notes"] = note
                        required_items[ingredient.name] = item_data
        
        shopping_list_items: List[schemas.ShoppingListItem] = []
        for item_name, item_data in required_items.items():
            pantry_item = next((p for p in pantry_items if p.name.lower() == item_name.lower()), None)
            
            notes = item_data.pop("notes", None)

            if pantry_item:
                if pantry_item.quantity < item_data["quantity"]:
                    shopping_list_items.append(schemas.ShoppingListItem(
                        name=item_data["name"],
                        quantity=item_data["quantity"] - pantry_item.quantity,
                        unit=item_data["unit"],
                        category=item_data["category"],
                        notes=notes
                    ))
            else:
                shopping_list_items.append(schemas.ShoppingListItem(**item_data, notes=notes))
        
        items_by_category: Dict[str, List[schemas.ShoppingListItem]] = {}
        for item in shopping_list_items:
            if item.category not in items_by_category:
                items_by_category[item.category] = []
            items_by_category[item.category].append(item)

        return schemas.AggregatedShoppingList(
            generated_at=date.today().isoformat(),
            items_by_category=items_by_category
        )
