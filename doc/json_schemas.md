# JSON Schemas for Meal Planning System

This document provides the complete and validated JSON Schema definition for the Home Assistant Meal Planning system. This schema defines the structure and types for all core data entities, ensuring data consistency and facilitating communication between the Home Assistant integration, the Docker add-on, and external services (like LLMs).

---

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Meal Planning System Schema",
  "definitions": {
    "UnitConversion": {
      "type": "object",
      "properties": {
        "unit": { "type": "string", "description": "The symbolic unit (e.g., 'bicchiere', 'cucchiaino')." },
        "grams_equivalent": { "type": "number", "description": "Equivalent in grams." },
        "ml_equivalent": { "type": "number", "description": "Equivalent in milliliters." }
      },
      "required": ["unit"]
    },
    "RotationRule": {
      "type": "object",
      "properties": {
        "food_group_or_item": { "type": "string", "description": "The food group or specific item for the rotation rule (e.g., 'uova', 'proteine_carne_rossa')." },
        "max_per_week": { "type": "integer", "description": "Maximum occurrences per week." },
        "min_per_week": { "type": "integer", "description": "Minimum occurrences per week." },
        "is_hard_constraint": { "type": "boolean", "default": true, "description": "If true, this rule is strictly enforced; otherwise, it influences ranking." }
      },
      "required": ["food_group_or_item"]
    },
    "PlannedItem": {
      "type": "object",
      "properties": {
        "item_name": { "type": "string", "description": "Name of the food item or ingredient as per the PDF (e.g., 'Riso integrale')." },
        "food_group": { "type": "string", "description": "Assigned food group (e.g., 'carboidrati', 'proteine_pesce')." },
        "quantity": { "type": "number", "description": "Numeric quantity from the PDF." },
        "unit": { "type": "string", "description": "Unit of measure from the PDF (e.g., 'g', 'fette', 'bicchiere')." },
        "is_estimated_unit": { "type": "boolean", "default": false, "description": "True if the unit conversion was based on an estimate (e.g., 'bicchiere' converted to 'ml')." },
        "alternatives": { "type": "array", "items": { "type": "string" }, "description": "Alternative items suggested in the PDF for this specific item." }
      },
      "required": ["item_name", "food_group", "quantity", "unit"]
    },
    "PlannedMeal": {
      "type": "object",
      "properties": {
        "meal_type": { "type": "string", "enum": ["pranzo", "cena"], "description": "Type of meal." },
        "items": { "type": "array", "items": { "$ref": "#/definitions/PlannedItem" }, "description": "List of planned food items for this meal." }
      },
      "required": ["meal_type", "items"]
    },
    "DailyPlannedMeals": {
      "type": "object",
      "properties": {
        "date": { "type": "string", "format": "date", "description": "Date of the planned day (YYYY-MM-DD)." },
        "meals": { "type": "array", "items": { "$ref": "#/definitions/PlannedMeal" }, "description": "List of planned meals for this day." }
      },
      "required": ["date", "meals"]
    },
    "StructuredMealPlan": {
      "type": "object",
      "properties": {
        "profile_id": { "type": "string", "description": "ID of the user profile this plan belongs to." },
        "start_date": { "type": "string", "format": "date", "description": "Start date of the meal plan (YYYY-MM-DD)." },
        "rotation_rules": { "type": "array", "items": { "$ref": "#/definitions/RotationRule" }, "description": "Specific rotation rules for this plan." },
        "allowed_cooking_methods": { "type": "array", "items": { "type": "string" }, "description": "List of preferred cooking methods for this plan." },
        "daily_plans": { "type": "array", "items": { "$ref": "#/definitions/DailyPlannedMeals" }, "description": "Daily breakdown of planned meals." }
      },
      "required": ["profile_id", "start_date", "rotation_rules", "daily_plans"]
    },
    "QuantityPerProfile": {
      "type": "object",
      "properties": {
        "qty": { "type": "number", "description": "Numeric quantity for the specific profile." },
        "unit": { "type": "string", "description": "Unit of measure for the specific profile." },
        "grams_equiv": { "type": "number", "description": "Equivalent in grams for the specific profile." }
      },
      "required": ["qty", "unit"]
    },
    "RecipeIngredient": {
      "type": "object",
      "properties": {
        "name": { "type": "string", "description": "Name of the ingredient." },
        "food_group": { "type": "string", "description": "Assigned food group." },
        "quantities": {
          "type": "object",
          "properties": {
            "persona_a": { "$ref": "#/definitions/QuantityPerProfile" },
            "persona_b": { "$ref": "#/definitions/QuantityPerProfile" }
          },
          "required": ["persona_a", "persona_b"],
          "description": "Quantities tailored for each user profile."
        }
      },
      "required": ["name", "food_group", "quantities"]
    },
    "ComposedDishContent": {
      "type": "object",
      "properties": {
        "dish_name": { "type": "string", "description": "Name of the composed dish." },
        "components": { "type": "array", "items": { "$ref": "#/definitions/RecipeIngredient" }, "description": "List of ingredients that make up the composed dish." }
      },
      "required": ["dish_name", "components"]
    },
    "Recipe": {
      "type": "object",
      "properties": {
        "id": { "type": "string", "description": "Unique ID for the recipe." },
        "name": { "type": "string", "description": "Name of the recipe." },
        "description": { "type": "string", "description": "Brief description of the recipe." },
        "is_composed_dish": { "type": "boolean", "default": false, "description": "True if the recipe represents a composed dish with components." },
        "content": {
          "oneOf": [
            { "type": "array", "items": { "$ref": "#/definitions/RecipeIngredient" } },
            { "$ref": "#/definitions/ComposedDishContent" }
          ],
          "description": "Either a list of direct ingredients or a composed dish structure."
        },
        "steps": { "type": "array", "items": { "type": "string" }, "description": "Step-by-step instructions." },
        "total_time_minutes": { "type": "integer", "description": "Total preparation and cooking time." },
        "difficulty": { "type": "string", "enum": ["facile", "media", "difficile"], "description": "Recipe difficulty level." },
        "tags": {
          "type": "object",
          "properties": {
            "mood": { "type": "array", "items": { "type": "string", "enum": ["quick", "normal", "effort"] }, "description": "Tags indicating cooking mood." },
            "cleanup": { "type": "array", "items": { "type": "string", "enum": ["low_mess", "normal", "high_mess"] }, "description": "Tags indicating cleanup effort." },
            "cooking_methods": { "type": "array", "items": { "type": "string" }, "description": "Primary cooking methods used." },
            "other": { "type": "array", "items": { "type": "string" }, "description": "Other descriptive tags (e.g., 'one-pan', 'meal-prep')." }
          }
        },
        "llm_generated_metadata": {
            "type": "object",
            "properties": {
                "source_prompt": { "type": "string" },
                "generated_at": { "type": "string", "format": "date-time" }
            },
            "description": "Metadata if the recipe was generated or enriched by an LLM."
        }
      },
      "required": ["id", "name", "content", "steps", "total_time_minutes", "difficulty"]
    },
    "CandidateRecipe": {
      "type": "object",
      "properties": {
        "id": { "type": "string", "description": "Unique ID for the candidate recipe." },
        "status": { "type": "string", "enum": ["draft_free_text", "draft_structured", "approved"], "description": "Current status of the candidate recipe." },
        "usage_count": { "type": "integer", "default": 0, "description": "Number of times this recipe has been manually overridden or selected." },
        "origin_override_id": { "type": "string", "description": "ID of the ConsumedEntry that originated this candidate recipe." },
        "recipe_data": { "$ref": "#/definitions/Recipe", "description": "The structured recipe data." }
      },
      "required": ["id", "status", "recipe_data"]
    },
    "OverrideConsumedDetails": {
      "type": "object",
      "properties": {
        "free_text_name": { "type": "string", "description": "Free text name of the dish eaten." },
        "ingredients": { "type": "array", "items": { "type": "object", "properties": {"name": {"type": "string"}, "qty": {"type": "number"}, "unit": {"type": "string"}}, "required": ["name", "qty", "unit"] } },
        "notes": { "type": "string", "description": "Additional notes about the consumed meal." }
      },
      "required": ["free_text_name"]
    },
    "ConsumedEntry": {
      "type": "object",
      "properties": {
        "id": { "type": "string", "description": "Unique ID for the consumed entry." },
        "profile_id": { "type": "string", "description": "ID of the profile that consumed the meal." },
        "date": { "type": "string", "format": "date", "description": "Date of consumption (YYYY-MM-DD)." },
        "meal_type": { "type": "string", "enum": ["pranzo", "cena"], "description": "Type of meal consumed." },
        "type": { "type": "string", "enum": ["planned", "override"], "description": "Whether it was a planned meal or an override." },
        "consumed_recipe_id": { "type": "string", "description": "ID of the Recipe consumed (if type='planned')." },
        "override_details": { "$ref": "#/definitions/OverrideConsumedDetails", "description": "Details if type='override'." }
      },
      "required": ["id", "profile_id", "date", "meal_type", "type"]
    },
    "PantryItem": {
      "type": "object",
      "properties": {
        "id": { "type": "string", "description": "Unique ID for the pantry item." },
        "name": { "type": "string", "description": "Name of the ingredient." },
        "quantity": { "type": "number" },
        "unit": { "type": "string" },
        "category": { "type": "string", "description": "Category of the ingredient (e.g., 'Verdura', 'Latticini')." },
        "expiration_date": { "type": "string", "format": "date", "description": "Expiration date (YYYY-MM-DD)." },
        "synonyms": { "type": "array", "items": { "type": "string" }, "description": "Alternative names for the ingredient." }
      },
      "required": ["id", "name", "quantity", "unit"]
    },
    "SeasonalityItem": {
      "type": "object",
      "properties": {
        "ingredient_name": { "type": "string", "description": "Name of the ingredient." },
        "months_in_season": { "type": "array", "items": { "type": "integer", "minimum": 1, "maximum": 12 }, "description": "Months (1-12) when the ingredient is in season in Italy." }
      },
      "required": ["ingredient_name", "months_in_season"]
    },
    "UserProfile": {
      "type": "object",
      "properties": {
        "id": { "type": "string" },
        "name": { "type": "string" },
        "allergies": { "type": "array", "items": { "type": "string" } },
        "excluded_foods": { "type": "array", "items": { "type": "string" } },
        "preferences": { "type": "array", "items": { "type": "string", "enum": ["onnivoro", "vegetariano", "vegano"] } },
        "max_cook_time_default": { "type": "integer" },
        "cleanup_tolerance": { "type": "string", "enum": ["low_mess", "normal", "high_mess"] },
        "equipment": { "type": "array", "items": { "type": "string" } }
      },
      "required": ["id", "name"]
    },
    "ShoppingListItem": {
      "type": "object",
      "properties": {
        "name": { "type": "string" },
        "quantity": { "type": "number" },
        "unit": { "type": "string" },
        "category": { "type": "string" },
        "notes": { "type": "string" }
      },
      "required": ["name", "quantity", "unit"]
    },
    "AggregatedShoppingList": {
      "type": "object",
      "properties": {
        "generated_at": { "type": "string", "format": "date-time" },
        "items_by_category": {
          "type": "object",
          "additionalProperties": {
            "type": "array",
            "items": { "$ref": "#/definitions/ShoppingListItem" }
          }
        }
      },
      "required": ["generated_at", "items_by_category"]
    }
  }
}
```