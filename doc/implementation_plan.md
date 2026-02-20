# Implementation Plan: Phased Approach (MVP -> v1 -> v2)

This document outlines the phased implementation plan for the Home Assistant Meal Planning System. This approach allows for incremental delivery of value, starting with a minimum viable product (MVP) and progressively adding more sophisticated features. Each phase has clear deliverables and builds upon the previous one.

---

## 1. Phase 0: Setup and Foundational Infrastructure

**Objective**: Prepare the development environment and establish the core architectural components.

*   **Deliverables**:
    *   **Version Control**: Initialize Git repository.
    *   **Environment Setup**:
        *   Docker environment configured for the Add-on (FastAPI, SQLite).
        *   Home Assistant development environment (for custom integration).
    *   **Database Schema**: SQLite database schema created with all necessary tables (though initially empty).
        *   `user_profiles`, `structured_meal_plans`, `recipes`, `candidate_recipes`, `consumed_entries`, `pantry_items`, `seasonality_items`, `unit_conversions`, `rotation_rules`.
    *   **Seed Data**:
        *   `unit_conversions` table populated with default metric/soft unit conversions.
        *   `seasonality_items` table populated with seasonality data for Italy.
    *   **Basic Boilerplate**:
        *   Home Assistant custom integration boilerplate (manifest, initial `__init__.py`).
        *   Docker Add-on boilerplate (FastAPI app structure, basic routes, DB connection).
*   **Success Criteria**: All development tools are installed, the basic project structure is in place, and the database schema is defined and applied.

## 2. Phase 1: MVP - The "Consumption Tracker"

**Objective**: Allow users to define profiles, manually manage their pantry, and accurately track what they've eaten (either planned or overridden). This phase provides a foundational data collection layer without complex planning.

*   **Deliverables**:
    *   **Add-on Docker**:
        *   **User Profiles API**: CRUD operations for `UserProfile`.
        *   **Pantry Management API**: CRUD operations for `PantryItem`.
        *   **Consumption Tracking API**:
            *   API endpoint for `mealplan.mark_consumed` (records `ConsumedEntry` of `type: planned`).
            *   API endpoint for `mealplan.override_consumed` (records `ConsumedEntry` of `type: override`).
            *   Logic to calculate current counts for `RotationRule`s based on `ConsumedEntry`.
            *   Implementation of `pantry.consume_meal_ingredients` service (manual decrement).
        *   **Basic Recipe Catalog**: API for `Recipe` retrieval (recipes are manually added to DB for testing).
        *   FastAPI Web Server operational.
    *   **Home Assistant Custom Integration**:
        *   **Services**: `mealplan.mark_consumed`, `mealplan.override_consumed`, `pantry.add_item`, `pantry.update_item`, `pantry.remove_item`, `pantry.consume_meal_ingredients`.
        *   **Sensors**: `sensor.pantry_summary` (simple count of items).
        *   Basic UI for configuring `UserProfile`s (via HA config flow or manual YAML).
    *   **UI Lovelace**:
        *   **"Today" View**: Card placeholders for Lunch/Dinner.
            *   `SEGNA COME MANGIATO` button with options: "Conferma pasto proposto" and "Ho mangiato altro..." (triggers override modal).
            *   "Override Consumo" modal implementation.
        *   **"Pantry" View**: Basic UI for `PantryItem` CRUD operations (table + add/edit form).
        *   **Visual Editor**: Implement a visual configuration editor for the card to simplify setup (e.g., entity selection).
*   **Success Criteria**: Users can configure their profiles, manually manage pantry items, and accurately record consumed meals (both planned and overridden) which are stored in the database. Rotation counts are correctly updated in the backend.

## 3. Phase 2: V1 - The "Intelligent Planner" and PDF Import

**Objective**: Introduce automated meal planning, robust PDF import, and the core recipe suggestion engine.

*   **Deliverables**:
    *   **Add-on Docker**:
        *   **PDF Parser & Import Wizard UI (Complete)**:
            *   Robust PDF parsing logic (text, tables, template-based).
            *   Data normalization (units, food groups).
            *   Web-based Import Wizard UI for review and confirmation of `StructuredMealPlan`.
            *   API for `mealplan.import_pdf`.
        *   **Recipe Catalog**: API for `Recipe` management (importing external recipes, manual entry).
        *   **Planner & Ranking Engine (Base)**:
            *   Full implementation of **Hard Constraints** filtering (all rules from `planner_algorithm.md`).
            *   Full implementation of **Dosing and Divergence Strategies** (`ingredient_swap`, `side_dish`).
            *   Initial implementation of **Soft Constraints** scoring for: Pantry usage, Seasonality, Anti-repetition (based on `ConsumedEntry`).
            *   API for `mealplan.generate_week` (generates an entire week's plan).
            *   API for `mealplan.change_recipe` (returns 3 `ChangeRecipeOption`s).
            *   API for `mealplan.apply_recipe_option`.
        *   **Shopping List Generator**: Aggregates ingredients for both profiles from the current `StructuredMealPlan`.
    *   **Home Assistant Custom Integration**:
        *   **Services**: `mealplan.import_pdf`, `mealplan.generate_week`, `mealplan.change_recipe`, `mealplan.apply_recipe_option`.
        *   **Sensors**: `sensor.mealplan_today` (now showing actual recipes), `sensor.mealplan_week` (full weekly plan), `sensor.shopping_list_aggregated`.
    *   **UI Lovelace**:
        *   **"Today" View**: Displays actual proposed recipes, doses A/B, time, cleanup score. `CAMBIA RICETTA!` button fully functional with parameter input and 3 alternatives display.
        *   **"Week" View**: Displays the full weekly plan with `RIGENERA SETTIMANA` button.
        *   **"Shopping List" View**: Displays aggregated list grouped by category.
*   **Success Criteria**: Users can import PDF plans, the system generates coherent meal plans respecting constraints, users can dynamically change recipes, and the shopping list accurately reflects the plan.

## 4. Phase 3: V2 - Auto-Learning and LLM Integration

**Objective**: Enhance the system with auto-learning capabilities from user overrides and integrate optional LLM functionality for recipe enrichment.

*   **Deliverables**:
    *   **Add-on Docker**:
        *   **LLM Gateway**: Implementation for selected LLM (Ollama/OpenAI), including caching and JSON Schema validation for LLM outputs.
        *   **Auto-Learning Logic**:
            *   If `override_consumed` with `draft_free_text` status `CandidateRecipe`, attempt LLM processing to convert to `draft_structured`.
            *   Logic to increment `CandidateRecipe.usage_count` when selected in `override_consumed` or `apply_recipe_option`.
            *   Logic to promote `CandidateRecipe` from `draft_structured` to `approved` based on `usage_count` (e.g., >= 2) or manual approval.
        *   **Planner & Ranking Engine (Refined)**:
            *   Incorporates `CandidateRecipe`s with `status: 'approved'` into the planning process.
            *   Refines `ExpirationScore` to be more granular (e.g., dynamic weight based on days to expiration).
            *   (Optional) LLM-driven recipe enrichment (generating `steps`, `description`, more tags).
    *   **Home Assistant Custom Integration**:
        *   Configuration options for LLM provider and API keys via HA config flow.
    *   **UI Lovelace**:
        *   **"Candidate Recipes" View**: UI for users to review, edit, approve, or delete `CandidateRecipe`s.
        *   Enhanced feedback for `override_consumed` (e.g., "Candidate recipe created!").
        *   (Optional) Integration with HA native shopping list (push/pull items).
*   **Success Criteria**: The system learns from user input, new recipes are automatically generated and approved, and LLM capabilities enhance recipe data.

---

## 5. Development Checklist (For this documentation task)

This section tracks the completion of the documentation files requested by the user.

- [X] `doc/functional_spec.md`: Functional Specification and UI Flows
- [X] `doc/architecture.md`: Architecture and Data Flow
- [X] `doc/planner_algorithm.md`: Planner Algorithm (Hard/Soft Constraints, Scoring)
- [X] `doc/implementation_plan.md`: Phased Implementation Plan (MVP, v1, v2)
- [X] `doc/json_schemas.md`: Complete JSON Schema Definition
- [X] `doc/examples.md`: Realistic JSON Examples
- [X] `doc/progress_checklist.md`: Document Creation Progress Checklist