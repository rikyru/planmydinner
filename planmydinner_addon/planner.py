import logging
import uuid
import json
from datetime import date, timedelta
from typing import List, Dict, Any, Optional

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
        # No longer instance attributes here
        # self.QUANTITY_TOLERANCE_PERCENT = 0.10
        # self.ANTI_REPETITION_DAYS = 7

    def _get_user_profile(self, profile_id: str) -> Optional[schemas.UserProfile]:
        db_profile = self.db.query(UserProfile).filter(UserProfile.id == profile_id).first()
        if db_profile:
            return schemas.UserProfile.from_orm(db_profile)
        return None

    def _get_active_meal_plan(self, profile_id: str, current_date: date) -> Optional[schemas.StructuredMealPlan]:
        db_plan = self.db.query(StructuredMealPlan).filter(
            StructuredMealPlan.profile_id == profile_id,
            func.julianday(StructuredMealPlan.start_date) <= func.julianday(current_date.isoformat()),
            # Assuming plans are weekly and we take the latest
            func.julianday(StructuredMealPlan.start_date) + 7 > func.julianday(current_date.isoformat())
        ).order_by(StructuredMealPlan.start_date.desc()).first()
        if db_plan:
            return schemas.StructuredMealPlan.from_orm(db_plan)
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
        # Includes approved candidate recipes
        db_recipes = self.db.query(Recipe).all()
        db_candidate_recipes = self.db.query(CandidateRecipe).filter(CandidateRecipe.status == "approved").all()
        
        all_recipes = [schemas.Recipe.from_orm(rec) for rec in db_recipes]
        all_recipes.extend([schemas.Recipe(**cand.recipe_data.model_dump(), id=cand.id) for cand in db_candidate_recipes])
        return all_recipes

    def _get_food_group_for_item(self, item_name: str) -> str:
        """
        Determines food group for a given item name.
        """
        item_lower = item_name.lower()
        
        vegetables = [
            "verdure", "insalata", "pomodoro", "cetriolo", "carota", "peperone", 
            "cipolla", "aglio", "melanzana", "zucchina", "spinaci", "broccoli", 
            "cavolfiore", "finocchi", "sedano", "asparagi", "funghi", "radicchio",
            "barbabietola", "zucca"
        ]

        if "pasta" in item_lower or "riso" in item_lower or "pane" in item_lower or "patate" in item_lower:
            return "carboidrati"
        
        if "pollo" in item_lower or "tacchino" in item_lower or "manzo" in item_lower or "maiale" in item_lower or \
           "pesce" in item_lower or "salmone" in item_lower or "tonno" in item_lower or "uova" in item_lower or \
           "lenticchie" in item_lower or "ceci" in item_lower or "fagioli" in item_lower or "legumi" in item_lower or "tofu" in item_lower:
            return "proteine"
            
        if "olio" in item_lower or "burro" in item_lower or "frutta secca" in item_lower or "noci" in item_lower or "mandorle" in item_lower:
            return "grassi"
            
        if "mela" in item_lower or "banana" in item_lower or "arancia" in item_lower or "fragole" in item_lower or "frutta" in item_lower:
            return "frutta"
            
        if any(veg in item_lower for veg in vegetables):
            return "verdure"
            
        return "altro"

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
        """
        Applies hard constraints to a single recipe, including weekly rotation rules.
        """
        _LOGGER.debug(f"Filtering recipe: {recipe.id}")

        # --- Time, Mood, Cleanup Constraints ---
        if recipe.total_time_minutes > request_params.get("max_time_minutes", 9999) or \
           (request_params.get("mood") and request_params["mood"] not in recipe.tags.get("mood", [])) or \
           (request_params.get("cleanup") and request_params["cleanup"] not in recipe.tags.get("cleanup", [])):
            return False, None, None

        # --- Allergies/Excluded Foods ---
        recipe_ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content
        for rec_ing in recipe_ingredients:
            ing_name = rec_ing.name.lower()
            if ing_name in [item.lower() for item in profile_A.allergies + profile_A.excluded_foods] or \
               ing_name in [item.lower() for item in profile_B.allergies + profile_B.excluded_foods]:
                _LOGGER.debug(f"Recipe {recipe.id} has unresolvable allergy/exclusion conflicts.")
                return False, None, None

        # --- Nutritional Plan Adherence ---
        # This check is now correctly handling items with planned_qty > 0
        planned_food_groups_A = {item.food_group: item.quantity for item in target_meal_plan_A.items if item.quantity > 0}
        planned_food_groups_B = {item.food_group: item.quantity for item in target_meal_plan_B.items if item.quantity > 0}
        
        recipe_food_groups_A = {rec_ing.food_group: rec_ing.quantities["persona_a"].grams_equiv for rec_ing in recipe_ingredients if rec_ing.quantities["persona_a"].grams_equiv is not None}
        recipe_food_groups_B = {rec_ing.food_group: rec_ing.quantities["persona_b"].grams_equiv for rec_ing in recipe_ingredients if rec_ing.quantities["persona_b"].grams_equiv is not None}

        for fg, planned_qty in planned_food_groups_A.items():
            recipe_qty = recipe_food_groups_A.get(fg, 0)
            if not (planned_qty * (1 - self.QUANTITY_TOLERANCE_PERCENT) <= recipe_qty <= planned_qty * (1 + self.QUANTITY_TOLERANCE_PERCENT)):
                return False, None, None
        
        for fg, planned_qty in planned_food_groups_B.items():
            recipe_qty = recipe_food_groups_B.get(fg, 0)
            if not (planned_qty * (1 - self.QUANTITY_TOLERANCE_PERCENT) <= recipe_qty <= planned_qty * (1 + self.QUANTITY_TOLERANCE_PERCENT)):
                return False, None, None

        # --- Weekly Rotation Rules (Hard Constraints) ---
        all_consumed = consumed_entries_A + consumed_entries_B
        rotation_rules = self.db.query(RotationRule).filter(RotationRule.is_hard_constraint == True).all()
        
        consumption_counts = {}
        for entry in all_consumed:
            if entry.consumed_recipe_id:
                consumed_recipe = self.db.query(Recipe).filter(Recipe.id == entry.consumed_recipe_id).first()
                if consumed_recipe:
                    ingredients = consumed_recipe.content.components if consumed_recipe.is_composed_dish else consumed_recipe.content
                    for ing in ingredients:
                        consumption_counts[ing.food_group] = consumption_counts.get(ing.food_group, 0) + 1
                        consumption_counts[ing.name.lower()] = consumption_counts.get(ing.name.lower(), 0) + 1
            elif entry.override_details and entry.override_details.ingredients:
                for ing in entry.override_details.ingredients:
                    food_group = self._get_food_group_for_item(ing.name)
                    consumption_counts[food_group] = consumption_counts.get(food_group, 0) + 1
                    consumption_counts[ing.name.lower()] = consumption_counts.get(ing.name.lower(), 0) + 1
            elif entry.override_details and entry.override_details.free_text_name:
                food_group = self._get_food_group_for_item(entry.override_details.free_text_name)
                consumption_counts[food_group] = consumption_counts.get(food_group, 0) + 1
                consumption_counts[entry.override_details.free_text_name.lower()] = consumption_counts.get(entry.override_details.free_text_name.lower(), 0) + 1
        
        for rule in rotation_rules:
            if rule.max_per_week is not None:
                count = consumption_counts.get(rule.food_group_or_item.lower(), 0)
                if count >= rule.max_per_week:
                    # Check if the current recipe contains this food group/item
                    for rec_ing in recipe_ingredients:
                        if rec_ing.food_group == rule.food_group_or_item.lower() or rec_ing.name.lower() == rule.food_group_or_item.lower():
                            _LOGGER.debug(f"Recipe {recipe.id} failed hard rotation rule for '{rule.food_group_or_item}'. Count: {count}, Max: {rule.max_per_week}")
                            return False, None, None

        # --- Anti-Repetition (Hard) ---
        recent_recipe_ids = {e.consumed_recipe_id for e in all_consumed if e.consumed_recipe_id}
        if recipe.id in recent_recipe_ids:
            _LOGGER.debug(f"Recipe {recipe.id} failed anti-repetition.")
            return False, None, None

        return True, "none", ""

    def _calculate_dosing(self, recipe: schemas.Recipe, profile_A: schemas.UserProfile, profile_B: schemas.UserProfile) -> schemas.Recipe:
        """
        Calculates precise dosing for each ingredient for Persona A and Persona B.
        For MVP, this assumes pre-calculated 'quantities' in the recipe.
        """
        # In V1, this would dynamically scale based on plan quantities and profile needs.
        # For now, we return the recipe as is, assuming its 'content' already holds A/B quantities.
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
        """
        Calculates a score for the recipe based on soft constraints.
        Higher score means better fit.
        """
        score = 0.0

        recipe_ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content

        # --- Pantry Score ---
        ingredients_in_pantry = 0
        for rec_ing in recipe_ingredients:
            if any(pi.name.lower() == rec_ing.name.lower() for pi in pantry_items):
                ingredients_in_pantry += 1
        
        if len(recipe_ingredients) > 0:
            pantry_score = ingredients_in_pantry / len(recipe_ingredients)
            score += pantry_score * 0.4 # Weight for pantry usage

        # --- Expiration Score ---
        expiration_bonus = 0.0
        max_bonus_days = 14 # Max days before expiration to start giving bonus
        for rec_ing in recipe_ingredients:
            for pi in pantry_items:
                if pi.name.lower() == rec_ing.name.lower() and pi.expiration_date:
                    days_to_expire = (date.fromisoformat(pi.expiration_date) - current_date).days
                    if 0 < days_to_expire <= max_bonus_days:
                        expiration_bonus += ((max_bonus_days - days_to_expire) / max_bonus_days) * 0.5
        score += expiration_bonus * 0.3 # Weight for expiration

        # --- Seasonality Score ---
        seasonality_bonus = 0.0
        current_month = current_date.month
        for rec_ing in recipe_ingredients:
            season_item = seasonality_data.get(rec_ing.name.lower())
            if season_item and current_month in season_item.months_in_season:
                seasonality_bonus += 0.1
            
        score += seasonality_bonus * 0.2 # Weight for seasonality

        # --- Soft Anti-Repetition Score ---
        repetition_penalty = 0.0
        all_consumed = consumed_entries_A + consumed_entries_B
        recent_ingredients = set()
        for entry in all_consumed:
            if entry.consumed_recipe_id:
                consumed_recipe = self.db.query(Recipe).filter(Recipe.id == entry.consumed_recipe_id).first()
                if consumed_recipe:
                    ingredients = consumed_recipe.content.components if consumed_recipe.is_composed_dish else consumed_recipe.content
                    for ing in ingredients:
                        recent_ingredients.add(ing.name.lower())
            elif entry.override_details and entry.override_details.ingredients:
                for ing in entry.override_details.ingredients:
                    recent_ingredients.add(ing.name.lower())

        for rec_ing in recipe_ingredients:
            if rec_ing.name.lower() in recent_ingredients:
                repetition_penalty += 0.1 # Penalize for each repeated ingredient
        
        score -= repetition_penalty

        return score

    def generate_weekly_plan(self, profile_id_A: str, profile_id_B: str, start_date: date) -> List[schemas.DailyPlannedMeals]:
        """
        Generates a full weekly meal plan for both profiles.
        """
        
        weekly_plan_A_raw = self._get_active_meal_plan(profile_id_A, start_date)
        weekly_plan_B_raw = self._get_active_meal_plan(profile_id_B, start_date)

        if not weekly_plan_A_raw or not weekly_plan_B_raw:
            _LOGGER.error("Could not find active meal plans for one or both profiles.")
            return []

        # Parse daily_plans from string to Pydantic models
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

                best_recipe = self._find_best_recipe(
                    meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date
                )

                if best_recipe:
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

    def _find_best_recipe(self, meal_plan_A, meal_plan_B, profile_id_A, profile_id_B, current_date):
        
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
                consumed_entries_A, consumed_entries_B, {},
                current_date
            )
            
            if is_valid:
                valid_recipes.append({
                    "recipe": recipe,
                    "divergence_strategy": divergence_strategy,
                    "divergence_details": divergence_details
                })
        
        for recipe_info in valid_recipes:
            recipe = recipe_info["recipe"]
            
            # Calculate dosing (MVP: assume pre-calculated in recipe)
            dosed_recipe = self._calculate_dosing(recipe, profile_A, profile_B)
            
            score = self._score_soft_constraints(dosed_recipe, pantry_items, seasonality_data, current_date, consumed_entries_A, consumed_entries_B)
            recipe_info["score"] = score
        
        if not valid_recipes:
            return None

        valid_recipes.sort(key=lambda x: x["score"], reverse=True)
        
        return valid_recipes[0]["recipe"]

    def suggest_recipes_for_meal(
        self,
        profile_id_A: str,
        profile_id_B: str,
        meal_type: str,
        current_date: date,
        request_params: Dict[str, Any] # mood, cleanup, max_time_minutes
    ) -> List[schemas.ChangeRecipeOption]:
        """
        Suggests 3 alternative recipes for a specific meal, filtered and ranked.
        """
        profile_A = self._get_user_profile(profile_id_A)
        profile_B = self._get_user_profile(profile_id_B)
        if not profile_A or not profile_B:
            _LOGGER.error(f"User profiles not found for {profile_id_A} or {profile_id_B}.")
            raise HTTPException(status_code=404, detail="One or both profiles not found.")

        plan_A = self._get_active_meal_plan(profile_id_A, current_date)
        plan_B = self._get_active_meal_plan(profile_id_B, current_date)

        if not plan_A or not plan_B:
            _LOGGER.error(f"Could not find active meal plan for one or both profiles on {current_date.isoformat()}.")
            return []

        # Find the daily plan for the current date
        daily_plan_A = next((dp for dp in plan_A.daily_plans if date.fromisoformat(dp.date) == current_date), None)
        daily_plan_B = next((dp for dp in plan_B.daily_plans if date.fromisoformat(dp.date) == current_date), None)

        if not daily_plan_A or not daily_plan_B:
            _LOGGER.error(f"Could not find daily plan for one or both profiles on {current_date.isoformat()}.")
            return []
            
        # Find the target meal within the daily plan
        target_meal_plan_A = next((m for m in daily_plan_A.meals if m.meal_type == meal_type), None)
        target_meal_plan_B = next((m for m in daily_plan_B.meals if m.meal_type == meal_type), None)

        if not target_meal_plan_A or not target_meal_plan_B:
            _LOGGER.error(f"Could not find meal type '{meal_type}' for one or both profiles on {current_date.isoformat()}.")
            return []


        all_recipes = self._get_all_recipes()
        pantry_items = self._get_pantry_items()
        seasonality_data = self._get_seasonality_data()
        consumed_entries_A = self._get_consumed_entries(profile_id_A, current_date, self.ANTI_REPETITION_DAYS)
        consumed_entries_B = self._get_consumed_entries(profile_id_B, current_date, self.ANTI_REPETITION_DAYS)

        candidate_options: List[schemas.ChangeRecipeOption] = []
        filtered_recipes = []

        for recipe in all_recipes:
            is_valid, divergence_strategy, divergence_details = self._filter_hard_constraints(
                recipe, target_meal_plan_A, target_meal_plan_B,
                profile_A, profile_B,
                consumed_entries_A, consumed_entries_B, request_params,
                current_date # Pass current_date to hard constraints
            )
            
            if is_valid:
                # Calculate dosing (MVP: assume pre-calculated in recipe)
                dosed_recipe = self._calculate_dosing(recipe, profile_A, profile_B)
                score = self._score_soft_constraints(dosed_recipe, pantry_items, seasonality_data, current_date, consumed_entries_A, consumed_entries_B)
                
                filtered_recipes.append({
                    "recipe": dosed_recipe,
                    "score": score,
                    "divergence_strategy": divergence_strategy,
                    "divergence_details": divergence_details
                })
        
        # Sort by score and take top 3
        filtered_recipes.sort(key=lambda x: x["score"], reverse=True)
        
        for rec_info in filtered_recipes[:3]:
            # Simplify content to key ingredients for ChangeRecipeOption
            recipe_content_list = rec_info["recipe"].content.components if rec_info["recipe"].is_composed_dish else rec_info["recipe"].content
            key_ingredients = [item.name for item in recipe_content_list if item.name][0:2] # Top 2 ingredients

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
        """
        Applies a chosen recipe to the meal plan for a specific date and meal type.
        For MVP, this is a placeholder. In V1, it would update the StructuredMealPlan in DB.
        """
        _LOGGER.warning("apply_recipe_to_plan is a placeholder for MVP.")
        return True

    def generate_shopping_list_for_week(self, profile_id_A: str, profile_id_B: str, start_date: date) -> schemas.AggregatedShoppingList:
        """
        Generates a shopping list for the week starting from start_date.
        """
        weekly_plan = self.generate_weekly_plan(profile_id_A, profile_id_B, start_date)
        pantry_items = self._get_pantry_items()
        
        required_items: Dict[str, Dict[str, Any]] = {}

        for day in weekly_plan:
            for meal in day.meals:
                # In a real implementation, you would fetch the recipe from the DB
                # For now, we'll assume the recipe is in the meal.items
                if not meal.items:
                    continue
                
                recipe_name = meal.items[0].item_name
                recipe = next((r for r in self._get_all_recipes() if r.name == recipe_name), None)

                if not recipe:
                    continue

                recipe_ingredients = recipe.content.components if recipe.is_composed_dish else recipe.content
                for ingredient in recipe_ingredients:
                    
                    qty_A = ingredient.quantities["persona_a"].grams_equiv
                    qty_B = ingredient.quantities["persona_b"].grams_equiv
                    total_qty = qty_A + qty_B

                    if ingredient.name in required_items:
                        required_items[ingredient.name]["quantity"] += total_qty
                    else:
                        required_items[ingredient.name] = {
                            "name": ingredient.name,
                            "quantity": total_qty,
                            "unit": "g", # All quantities are in grams
                            "category": ingredient.food_group,
                        }
        
        shopping_list_items: List[schemas.ShoppingListItem] = []
        for item_name, item_data in required_items.items():
            pantry_item = next((p for p in pantry_items if p.name.lower() == item_name.lower()), None)
            if pantry_item:
                if pantry_item.quantity < item_data["quantity"]:
                    shopping_list_items.append(schemas.ShoppingListItem(
                        name=item_data["name"],
                        quantity=item_data["quantity"] - pantry_item.quantity,
                        unit=item_data["unit"],
                        category=item_data["category"],
                    ))
            else:
                shopping_list_items.append(schemas.ShoppingListItem(**item_data))
        
        # Group by category
        items_by_category: Dict[str, List[schemas.ShoppingListItem]] = {}
        for item in shopping_list_items:
            if item.category not in items_by_category:
                items_by_category[item.category] = []
            items_by_category[item.category].append(item)

        return schemas.AggregatedShoppingList(
            generated_at=date.today().isoformat(),
            items_by_category=items_by_category
        )