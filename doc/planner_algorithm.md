# Planner Algorithm: Hard/Soft Constraints and Scoring

This document details the core algorithm used by the Planner & Ranking Engine within the Docker Add-on. It describes how recipes are filtered based on strict rules (hard constraints) and then ranked using a scoring system influenced by various criteria (soft constraints).

---

## 1. Core Principles

*   **"Stesso Piatto, Dosi Diverse"**: Priority is given to finding a single recipe that can be adapted for both `UserProfile`s with personalized quantities, even if it requires `ingredient_swap` or `side_dish` strategies.
*   **Hierarchical Filtering**: Hard constraints are applied first as strict filters, eliminating non-compliant recipes. Soft constraints then provide a scoring mechanism for the remaining valid recipes.
*   **Dynamic Context**: The algorithm considers the current `StructuredMealPlan` (for quantities, food groups), `UserProfile`s (for allergies, preferences, current mood/cleanup), `Pantry` (for available/expiring ingredients), `Seasonality` data, and `ConsumedEntry` (for past consumptions and rotation tracking).

## 2. Input to the Algorithm

The algorithm receives the following contextual information for a given `meal_type` and `date`:

*   `target_meal_plan_A`: `PlannedMeal` for Persona A for the specific meal/day.
*   `target_meal_plan_B`: `PlannedMeal` for Persona B for the specific meal/day.
*   `user_profile_A`: `UserProfile` for Persona A.
*   `user_profile_B`: `UserProfile` for Persona B.
*   `current_pantry`: List of `PantryItem`.
*   `consumed_entries_last_N_days`: List of `ConsumedEntry` for both profiles (e.g., last 7 days).
*   `seasonality_data`: List of `SeasonalityItem`.
*   `config`: System configuration including tolerance levels, N for anti-repetition, scoring weights.
*   `request_params`: Parameters from `change_recipe` call (e.g., `mood`, `cleanup`, `max_time_minutes`).

## 3. Algorithm Steps

### Step 1: Initial Recipe Set

*   Start with the entire catalog of available `Recipe`s and `CandidateRecipe`s with `status: 'approved'`.

### Step 2: Filtering by Hard Constraints (Elimination Phase)

For each `Recipe` in the initial set, apply the following checks. If any check fails, the recipe is discarded.

1.  **Meal Type Compatibility**: `Recipe.meal_type` must match the requested `meal_type` (e.g., "pranzo" or "cena").
2.  **Time Constraint**: `Recipe.total_time_minutes` must be <= `request_params.max_time_minutes`.
3.  **Mood/Cleanup Tags**:
    *   `Recipe.tags.mood` must include `request_params.mood`.
    *   `Recipe.tags.cleanup` must include `request_params.cleanup`.
    *   If no explicit `mood` or `cleanup` tag is present in the recipe, it can be considered "normal".
4.  **Cooking Methods**:
    *   All `Recipe.tags.cooking_methods` must be present in `UserProfile.allowed_cooking_methods` for both profiles.
    *   No `Recipe.tags.cooking_methods` can be present in `UserProfile.global_excluded_cooking_methods` for both profiles.
5.  **Allergies/Intolerances/Excluded Foods**:
    *   For each `RecipeIngredient` in the recipe's `content`:
        *   Check `RecipeIngredient.name` (and its synonyms) against `UserProfile.allergies` and `UserProfile.excluded_foods` for Persona A and Persona B.
        *   If a conflict is found:
            *   Attempt an `ingredient_swap` using internal recipe logic or `alternatives` from `PlannedItem`. If a valid swap resolves the conflict for the affected profile, mark this as `divergence_strategy: ingredient_swap`.
            *   If no `ingredient_swap` is possible, or if `UserProfile.preferences` (e.g., "vegetariano") causes a conflict, attempt a `side_dish` strategy (meaning one profile gets a different component). Mark `divergence_strategy: side_dish`.
            *   If no `ingredient_swap` or `side_dish` strategy can resolve the conflict for *both* profiles, discard the recipe.
6.  **Equipment Availability**: All `Recipe.tags.equipment` must be present in `UserProfile.equipment` for both profiles.
7.  **Nutritional Plan Adherence (Food Groups & Quantities)**:
    *   Aggregate `grams_equiv` for each `food_group` from `target_meal_plan_A.items` and `target_meal_plan_B.items`.
    *   Aggregate `grams_equiv` for each `food_group` from `Recipe.content` (using Persona A and B quantities).
    *   For each `food_group` present in the plan, the recipe's aggregated `grams_equiv` must be within the configurable tolerance (e.g., ±10%) of the plan's `grams_equiv`.
    *   If the recipe is a `ComposedDish`, iterate through its `components` to aggregate food groups.
    *   If any `PlannedItem` has `alternatives`, consider these during the matching process if the primary item from the recipe doesn't align.
8.  **Weekly Rotation Rules (Hard Constraints)**:
    *   For each `RotationRule` where `is_hard_constraint: true`:
        *   Calculate current consumption count for `RotationRule.food_group_or_item` based on `consumed_entries_last_N_days`.
        *   Add the estimated count from the current recipe.
        *   If `(current_count + recipe_count) > RotationRule.max_per_week` for either profile, discard the recipe.
9.  **Anti-Repetition**:
    *   Check `Recipe.id` against `consumed_entries_last_N_days` and `StructuredMealPlan` (for already assigned recipes). If the same `Recipe.id` has been consumed or is assigned within `N` days, discard it.
    *   (Optional but recommended) Check main ingredients or `ComposedDish.dish_name` for repetition within `N` days, discarding if a high similarity is found.

### Step 3: Dosing and Final Divergence Strategy (for remaining recipes)

For each recipe that successfully passed all Hard Constraints:

1.  **Calculate `QuantityPerProfile`**: Based on the `Recipe.content` (or `ComposedDish.components`) and the required `grams_equiv` for `food_group`s from the `target_meal_plan` for A and B, precisely scale all `RecipeIngredient.quantities` to reflect `persona_a` and `persona_b`'s needs. This is where "stesso piatto, dosi diverse" is fully realized.
2.  **Confirm Divergence Strategy**: Finalize the `divergence_strategy` (e.g., `none`, `ingredient_swap`, `side_dish`, `separate_dishes`) and `divergence_details` based on the successful adaptations made during filtering. `separate_dishes` should only be used if no other strategy was viable and the recipe almost perfectly matched the plan for one profile but was impossible for the other, allowing the planner to explicitly suggest two distinct dishes as a last resort.

### Step 4: Scoring by Soft Constraints (Ranking Phase)

For each recipe that passed all Hard Constraints and had its dosing calculated, assign a `Score`:

`RecipeScore = (w_pantry * PantryScore) + (w_expiration * ExpirationScore) + (w_seasonality * SeasonalityScore) - (w_repetition * RepetitionPenalty) + (w_rotations_soft * RotationScore)`

*   **`PantryScore` (0-1)**:
    *   Calculate `(count of recipe ingredients present in current_pantry) / (total unique ingredients in recipe)`.
    *   Higher if more ingredients are already available.
*   **`ExpirationScore` (0-1)**:
    *   For each `RecipeIngredient` present in `current_pantry`:
        *   Calculate `days_to_expiration` for the corresponding `PantryItem`.
        *   Map `days_to_expiration` to a score (e.g., 1 for <3 days, 0.7 for 3-7 days, 0.3 for 7-14 days, 0 for >14 days).
    *   Average scores for all matched pantry items.
    *   This component prioritizes using ingredients nearing expiration.
*   **`SeasonalityScore` (0-1)**:
    *   For each `RecipeIngredient`:
        *   Look up `RecipeIngredient.name` in `seasonality_data` for the `current_month`.
        *   Score 1 if in season, 0.5 if borderline, 0 if out of season.
    *   Average scores for all ingredients with seasonality data.
*   **`RepetitionPenalty` (0-1)**:
    *   Penalize recipes or main `food_group`s that have been consumed or planned recently but *outside* the hard constraint `N` days (e.g., mild penalty for something eaten 8-14 days ago).
*   **`RotationScore` (0-1)**:
    *   For each `RotationRule` where `is_hard_constraint: false` or `RotationRule.min_per_week` is set:
        *   If the current recipe helps fulfill `min_per_week` or balances soft rotation goals, add a bonus.
    *   This component helps balance nutritional variety beyond strict hard constraints.

### Step 5: Final Selection

1.  Sort all recipes by `RecipeScore` in descending order.
2.  For `mealplan.change_recipe`, return the top 3 recipes as `ChangeRecipeOption` objects.
3.  For `mealplan.generate_week`, return the top 1 recipe.

## 5. Ensuring "Stesso Piatto, Dosi Diverse"

This critical requirement is addressed throughout the algorithm:

*   **PDF Parsing**: Extracts quantities for A and B from the plan, even if they're different (implicitly, if the PDF specifies separate values).
*   **Hard Constraint #5 (Allergies/Exclusions)**: This is the first point where divergence is *forced*. If a recipe ingredient conflicts with one profile, `ingredient_swap` or `side_dish` strategies are attempted *before* discarding the recipe.
*   **Step 3 (Dosing & Final Divergence)**: This is where the magic happens. The algorithm precisely scales each ingredient to meet the distinct `grams_equiv` requirements of Persona A and Persona B derived from their respective `StructuredMealPlan`s. If, after all adaptations, a single "same dish" cannot be created that satisfies both profiles' hard constraints, only then is the recipe discarded. The `divergence_strategy` field in the final `Recipe` (or `ChangeRecipeOption`) clearly indicates how the recipe was adapted for both.
*   **`Recipe.content.quantities`**: The `Recipe` schema explicitly includes `persona_a` and `persona_b` quantities for *each ingredient*, ensuring that the UI can display and the shopping list can aggregate precise, personalized amounts.

## 6. Tracking Consumption and Auto-Learning

### `ConsumedEntry`
*   Every time a meal is `mark_consumed` (planned) or `override_consumed`, a `ConsumedEntry` is created for each profile.
*   This entry records `profile_id`, `date`, `meal_type`, `type` (`planned` or `override`), and the `consumed_recipe_id` (if `planned`) or `override_details` (if `override`).
*   These entries are crucial for calculating current `RotationRule` counts.

### `CandidateRecipe` Lifecycle
1.  **Creation**:
    *   If `override_consumed` is called with `override_details.ingredients` (even partial), a `CandidateRecipe` is created with `status: 'draft_structured'`.
    *   If `override_consumed` is called only with `override_details.free_text_name` (no structured ingredients), a `CandidateRecipe` is created with `status: 'draft_free_text'`.
    *   In both cases, `CandidateRecipe.origin_override_id` links it back to the `ConsumedEntry`.
2.  **LLM Enrichment (Optional)**: If the LLM Gateway is active and `status` is `draft_free_text`, the system can attempt to use the LLM to convert `free_text_name` and `notes` into a fully structured `Recipe` (ingredients, steps, tags), updating `status` to `draft_structured`.
3.  **Promotion to `approved`**:
    *   **Manual Approval**: User can manually approve a `CandidateRecipe` (via a dedicated UI) which changes its `status` to `approved`.
    *   **Automatic Promotion**: If a `CandidateRecipe` reaches `CandidateRecipe.usage_count` of `N` (e.g., 2 or 3) times (i.e., it was selected as an override by the user multiple times), its `status` is automatically changed to `approved`.
4.  **Usage in Planner**: Only `CandidateRecipe`s with `status: 'approved'` are considered by the Planner & Ranking Engine in Step 1.

### Impact on Shopping List Generation
*   **Planned/Approved Meals**: Ingredients from `Recipe`s assigned to the `StructuredMealPlan` (including `approved` `CandidateRecipe`s) directly contribute to the `AggregatedShoppingList`.
*   **Override Free-Text**: If `override_consumed` is performed with only `free_text_name` (meaning `override_details.ingredients` is empty/null), the associated meal **DOES NOT** contribute to the `AggregatedShoppingList`. The UI explicitly informs the user about this. This prevents adding ambiguous or unquantifiable items to the shopping list.
*   **Override Structured**: If `override_consumed` includes structured ingredients, the associated `CandidateRecipe` (`draft_structured` status) **DOES NOT** immediately contribute to the shopping list. It can only contribute if the user later approves it, and it becomes part of a future planned meal. This ensures the shopping list remains clean and reflects only confirmed future plans.
```