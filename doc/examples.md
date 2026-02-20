# JSON Examples for Meal Planning System

This document provides realistic JSON examples for key data structures and API responses within the Home Assistant Meal Planning System. These examples illustrate the data formats defined in `doc/json_schemas.md` and are consistent with the functional specifications.

---

## 1. Structured Meal Plan for One Day (Persona A)

This example shows how a single day's plan for Persona A, as a `DailyPlannedMeals` object, would look after being imported and structured. It includes `PlannedItem`s with their `food_group` and potential `alternatives` as derived from the PDF.

```json
{
  "profile_id": "persona_a",
  "start_date": "2026-02-19",
  "rotation_rules": [
    { "food_group_or_item": "proteine_uova", "max_per_week": 2, "is_hard_constraint": true },
    { "food_group_or_item": "proteine_carne_rossa", "max_per_week": 1, "is_hard_constraint": true },
    { "food_group_or_item": "legumi", "min_per_week": 3, "is_hard_constraint": false }
  ],
  "allowed_cooking_methods": ["vapore", "tegame", "forno"],
  "daily_plans": [
    {
      "date": "2026-02-19",
      "meals": [
        {
          "meal_type": "pranzo",
          "items": [
            { "item_name": "Riso integrale", "food_group": "carboidrati", "quantity": 80, "unit": "g", "alternatives": ["pasta integrale", "farro"] },
            { "item_name": "Salmone", "food_group": "proteine_pesce", "quantity": 150, "unit": "g", "alternatives": ["merluzzo", "orata"] },
            { "item_name": "Olio Extra Vergine Oliva", "food_group": "grassi", "quantity": 10, "unit": "ml", "is_estimated_unit": false, "alternatives": [] },
            { "item_name": "Verdure miste", "food_group": "verdure", "quantity": 1, "unit": "piatto", "is_estimated_unit": true, "alternatives": [] }
          ]
        },
        {
          "meal_type": "cena",
          "items": [
            { "item_name": "Zuppa di legumi", "food_group": "legumi", "quantity": 300, "unit": "ml", "alternatives": ["passato di verdure"] },
            { "item_name": "Pane integrale", "food_group": "carboidrati", "quantity": 50, "unit": "g", "alternatives": ["gallette di riso"] },
            { "item_name": "Frutta", "food_group": "frutta", "quantity": 1, "unit": "porzione", "is_estimated_unit": true, "alternatives": [] }
          ]
        }
      ]
    }
  ]
}
```

## 2. Consumed Entries (`ConsumedEntry`)

Examples of how meals are recorded when marked as consumed, either as planned or through an override.

### a) Consumed a planned meal (`mark_consumed`)

```json
{
  "id": "cons_1_20260219_pranzo_A",
  "profile_id": "persona_a",
  "date": "2026-02-19",
  "meal_type": "pranzo",
  "type": "planned",
  "consumed_recipe_id": "recipe_riso_salmone_verdure_001"
}
```

### b) Consumed an override meal with structured ingredients (`override_consumed`)

```json
{
  "id": "cons_2_20260220_cena_A",
  "profile_id": "persona_a",
  "date": "2026-02-20",
  "meal_type": "cena",
  "type": "override",
  "override_details": {
    "free_text_name": "Torta salata peperoni e ricotta",
    "ingredients": [
      { "name": "pasta sfoglia", "qty": 1, "unit": "rotolo" },
      { "name": "peperoni", "qty": 200, "unit": "g" },
      { "name": "ricotta", "qty": 150, "unit": "g" }
    ],
    "notes": "Fatta con la sfoglia pronta"
  }
}
```

### c) Consumed an override meal with only free-text (`override_consumed`)

```json
{
  "id": "cons_3_20260221_pranzo_B",
  "profile_id": "persona_b",
  "date": "2026-02-21",
  "meal_type": "pranzo",
  "type": "override",
  "override_details": {
    "free_text_name": "Panino al bar",
    "notes": "Ero di fretta"
  }
}
```

## 3. Candidate Recipe (`CandidateRecipe`)

An example of a candidate recipe, created from an override, in a `draft_structured` state.

```json
{
  "id": "cand_rec_TS_001",
  "status": "draft_structured",
  "usage_count": 1,
  "origin_override_id": "cons_2_20260220_cena_A",
  "recipe_data": {
    "id": "cand_rec_TS_001",
    "name": "Torta Salata Peperoni e Ricotta",
    "description": "Una torta salata vegetariana versatile, perfetta per una cena veloce o un picnic.",
    "is_composed_dish": true,
    "content": {
      "dish_name": "Torta Salata",
      "components": [
        { "name": "pasta sfoglia", "food_group": "carboidrati", "quantities": { "persona_a": { "qty": 1, "unit": "rotolo", "grams_equiv": 230 }, "persona_b": { "qty": 1, "unit": "rotolo", "grams_equiv": 230 } } },
        { "name": "peperoni", "food_group": "verdure", "quantities": { "persona_a": { "qty": 200, "unit": "g", "grams_equiv": 200 }, "persona_b": { "qty": 200, "unit": "g", "grams_equiv": 200 } } },
        { "name": "ricotta", "food_group": "proteine_formaggio", "quantities": { "persona_a": { "qty": 150, "unit": "g", "grams_equiv": 150 }, "persona_b": { "qty": 150, "unit": "g", "grams_equiv": 150 } } },
        { "name": "uova", "food_group": "proteine_uova", "quantities": { "persona_a": { "qty": 2, "unit": "pz", "grams_equiv": 100 }, "persona_b": { "qty": 2, "unit": "pz", "grams_equiv": 100 } } },
        { "name": "parmigiano grattugiato", "food_group": "grassi", "quantities": { "persona_a": { "qty": 30, "unit": "g", "grams_equiv": 30 }, "persona_b": { "qty": 30, "unit": "g", "grams_equiv": 30 } } }
      ]
    },
    "steps": [
      "Stendere la pasta sfoglia in una teglia da forno.",
      "In una ciotola, mescolare ricotta, uova, peperoni (precedentemente cotti e tagliati), parmigiano, sale e pepe.",
      "Versare il composto sulla pasta sfoglia.",
      "Infornare in forno preriscaldato a 180°C per circa 30-35 minuti, o fino a doratura."
    ],
    "total_time_minutes": 45,
    "difficulty": "facile",
    "tags": {
      "mood": ["normal"],
      "cleanup": ["low_mess"],
      "cooking_methods": ["forno"],
      "other": ["vegetariano"]
    },
    "llm_generated_metadata": {
      "source_prompt": "Torta salata peperoni e ricotta",
      "generated_at": "2026-02-20T20:30:00Z"
    }
  }
}
```

## 4. `change_recipe` Response (3 Options)

This example shows the JSON response from the Docker Add-on when `mealplan.change_recipe` is called. It provides three alternative recipe options.

```json
[
  {
    "option_id": "opt_CR_001",
    "recipe_id": "recipe_lenticchie_curry_010",
    "name": "Curry di Lenticchie Rosse (Low Mess)",
    "total_time_minutes": 30,
    "difficulty": "facile",
    "cleanup_score": "low_mess",
    "key_ingredients": ["lenticchie rosse", "latte di cocco", "spinaci"],
    "divergence_strategy": "none"
  },
  {
    "option_id": "opt_CR_002",
    "recipe_id": "recipe_pollo_verdure_forno_011",
    "name": "Pollo e Verdure al Forno (per A con Tempeh)",
    "total_time_minutes": 45,
    "difficulty": "media",
    "cleanup_score": "normal",
    "key_ingredients": ["petto di pollo", "patate", "carote", "broccoli"],
    "divergence_strategy": "ingredient_swap",
    "divergence_details": "Tempeh per Persona A (vegetariana) invece di pollo"
  },
  {
    "option_id": "opt_CR_003",
    "recipe_id": "recipe_pesce_vapore_pure_patate_012",
    "name": "Filetto di Pesce al Vapore con Purè di Patate",
    "total_time_minutes": 25,
    "difficulty": "facile",
    "cleanup_score": "normal",
    "key_ingredients": ["filetto di merluzzo", "patate", "latte"],
    "divergence_strategy": "none"
  }
]
```

## 5. Aggregated Shopping List (`AggregatedShoppingList`)

This example shows a shopping list, aggregated for both profiles' planned meals and grouped by category.

```json
{
  "generated_at": "2026-02-22T09:00:00Z",
  "items_by_category": {
    "Verdure": [
      { "name": "Asparagi", "quantity": 500, "unit": "g", "notes": "" },
      { "name": "Patate", "quantity": 1.2, "unit": "kg", "notes": "" },
      { "name": "Spinaci freschi", "quantity": 200, "unit": "g", "notes": "" },
      { "name": "Carote", "quantity": 400, "unit": "g", "notes": "" },
      { "name": "Zucca", "quantity": 800, "unit": "g", "notes": "" }
    ],
    "Carne": [
      { "name": "Petto di pollo", "quantity": 300, "unit": "g", "notes": "Solo per Persona B" }
    ],
    "Pesce": [
      { "name": "Filetto di merluzzo", "quantity": 300, "unit": "g", "notes": "" }
    ],
    "Legumi": [
      { "name": "Lenticchie rosse secche", "quantity": 250, "unit": "g", "notes": "" }
    ],
    "Latticini e Uova": [
      { "name": "Latte di cocco", "quantity": 400, "unit": "ml", "notes": "Lattina" },
      { "name": "Latte fresco", "quantity": 500, "unit": "ml", "notes": "" }
    ],
    "Dispensa": [
      { "name": "Olio Extra Vergine Oliva", "quantity": 20, "unit": "ml", "notes": "" },
      { "name": "Sale", "quantity": 1, "unit": "conf", "notes": "" },
      { "name": "Pepe nero", "quantity": 1, "unit": "conf", "notes": "" }
    ],
    "Alternative Vegetali": [
      { "name": "Tempeh", "quantity": 200, "unit": "g", "notes": "Solo per Persona A" }
    ]
  }
}
```