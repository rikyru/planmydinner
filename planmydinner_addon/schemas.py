from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict, Any
from datetime import date

# Pydantic models for UserProfile (already defined)
class UserProfileBase(BaseModel):
    name: str
    allergies: Optional[List[str]] = []
    excluded_foods: Optional[List[str]] = []
    preferences: Optional[List[str]] = []
    max_cook_time_default: Optional[int] = None
    cleanup_tolerance: Optional[str] = None
    equipment: Optional[List[str]] = []

class UserProfileCreate(UserProfileBase):
    id: str

class UserProfile(UserProfileBase):
    id: str
    class Config:
        from_attributes = True

# Pydantic models for PantryItem (already defined)
class PantryItemBase(BaseModel):
    name: str
    quantity: float
    unit: str
    category: Optional[str] = None
    expiration_date: Optional[str] = None
    synonyms: Optional[List[str]] = []

class PantryItemCreate(PantryItemBase):
    pass

class PantryItem(PantryItemBase):
    id: str
    class Config:
        from_attributes = True

# Pydantic models for ConsumedEntry (already defined)
class OverrideIngredient(BaseModel):
    name: str
    qty: float
    unit: str

class OverrideConsumedDetails(BaseModel):
    free_text_name: str
    ingredients: Optional[List[OverrideIngredient]] = None
    notes: Optional[str] = None

class ConsumedEntryBase(BaseModel):
    profile_id: str
    date: str
    meal_type: str
    type: str
    consumed_recipe_id: Optional[str] = None
    override_details: Optional[OverrideConsumedDetails] = None

class ConsumedEntryCreate(ConsumedEntryBase):
    pass

class ConsumedEntry(ConsumedEntryBase):
    id: str
    class Config:
        from_attributes = True

# Pydantic models for UnitConversion
class UnitConversionBase(BaseModel):
    unit: str
    grams_equivalent: Optional[float] = None
    ml_equivalent: Optional[float] = None

class UnitConversion(UnitConversionBase):
    class Config:
        from_attributes = True

# Pydantic models for RotationRule
class RotationRuleBase(BaseModel):
    profile_id: Optional[str] = None # Can be global if None
    food_group_or_item: str
    max_per_week: Optional[int] = None
    min_per_week: Optional[int] = None
    is_hard_constraint: bool = True

class RotationRuleCreate(RotationRuleBase):
    id: Optional[str] = None # ID can be provided or generated

class RotationRule(RotationRuleBase):
    id: str
    class Config:
        from_attributes = True

# Pydantic models for SeasonalityItem
class SeasonalityItemBase(BaseModel):
    ingredient_name: str
    months_in_season: List[int]

class SeasonalityItem(SeasonalityItemBase):
    class Config:
        from_attributes = True

# Pydantic models for Meal Planning Core
class PlannedItem(BaseModel):
    item_name: str
    food_group: str
    quantity: float
    unit: str
    is_estimated_unit: bool = False
    alternatives: List['PlannedItem'] = []
    shopping_list_quantity: Optional[float] = None

PlannedItem.model_rebuild()

class PlannedMeal(BaseModel):
    meal_type: str = Field(..., pattern="^(pranzo|cena)$")
    items: List[PlannedItem]

class DailyPlannedMeals(BaseModel):
    date: str
    meals: List[PlannedMeal]

class StructuredMealPlanBase(BaseModel):
    profile_id: str
    start_date: str
    rotation_rules: Optional[List[RotationRuleCreate]] = [] # Using Create to allow optional ID
    allowed_cooking_methods: Optional[List[str]] = []
    daily_plans: List[DailyPlannedMeals]

class StructuredMealPlanCreate(StructuredMealPlanBase):
    id: Optional[str] = None # ID can be provided or generated

class StructuredMealPlan(StructuredMealPlanBase):
    id: str
    class Config:
        from_attributes = True

# Pydantic models for Recipe Core
class QuantityPerProfile(BaseModel):
    qty: float
    unit: str
    grams_equiv: Optional[float] = None # Equivalent in grams

class RecipeIngredient(BaseModel):
    name: str
    food_group: str
    quantities: Dict[str, QuantityPerProfile] = Field(..., description="Keys are profile_ids (e.g., 'persona_a', 'persona_b')")

class ComposedDishContent(BaseModel):
    dish_name: str
    components: List[RecipeIngredient]

class RecipeBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_composed_dish: bool = False
    content: Union[List[RecipeIngredient], ComposedDishContent] # This field contains the actual ingredients/components
    steps: List[str]
    total_time_minutes: int
    difficulty: str = Field(..., pattern="^(facile|media|difficile|sconosciuto)$")
    tags: Optional[Dict[str, List[str]]] = None # mood, cleanup, cooking_methods, other

class RecipeCreate(RecipeBase):
    id: Optional[str] = None # ID can be provided or generated

class Recipe(RecipeBase):
    id: str
    llm_generated_metadata: Optional[Dict[str, Any]] = None # Metadata if LLM generated/enriched
    class Config:
        from_attributes = True

# Pydantic models for CandidateRecipe
class CandidateRecipeBase(BaseModel):
    status: str = Field(..., pattern="^(draft_free_text|draft_structured|approved)$")
    usage_count: int = 0
    origin_override_id: Optional[str] = None
    recipe_data: RecipeCreate # Store the full recipe data

class CandidateRecipeCreate(CandidateRecipeBase):
    id: Optional[str] = None # ID can be provided or generated

class CandidateRecipe(CandidateRecipeBase):
    id: str
    class Config:
        from_attributes = True

# Pydantic models for API Responses (e.g., ChangeRecipeOption)
class ChangeRecipeOption(BaseModel):
    option_id: str
    recipe_id: str
    name: str
    total_time_minutes: int
    difficulty: str
    cleanup_score: str
    key_ingredients: List[str]
    divergence_strategy: str
    divergence_details: Optional[str] = None

class ShoppingListItem(BaseModel):
    name: str
    quantity: float
    unit: str
    category: str
    notes: Optional[str] = None

class AggregatedShoppingList(BaseModel):
    generated_at: date
    items_by_category: Dict[str, List[ShoppingListItem]]


class GeneratedWeeklyPlan(BaseModel):
    id: str
    profile_id_A: str
    profile_id_B: Optional[str] = None
    week_start_date: str
    generated_at: str
    daily_plans: List[DailyPlannedMeals]

    class Config:
        from_attributes = True