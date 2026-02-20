# Implementation & Testing Checklist

This document tracks the step-by-step implementation and testing of the Meal Planning System, following the phased approach defined in `doc/implementation_plan.md`.

---

## Phase 1: MVP - The "Consumption Tracker"

**Objective**: Allow users to define profiles, manually manage their pantry, and accurately track what they've eaten (either planned or overridden).

### 1.1: Project Scaffolding & Basic Setup

-   [X] **Task**: Create directory structure for the Home Assistant custom component (`custom_components/planmydinner`).
    -   [X] Create `__init__.py` (empty).
    -   [X] Create `manifest.json` with basic info (domain, name, version, dependencies).
    -   [X] Create `const.py` to define constants (domain, platforms).
-   [X] **Task**: Create directory structure for the Docker Add-on (`planmydinner_addon`).
    -   [X] Create `main.py` with a basic FastAPI "Hello World" app.
    -   [X] Create `requirements.txt` with initial dependencies (`fastapi`, `uvicorn`, `sqlalchemy`).
    -   [X] Create `Dockerfile` for the add-on.
    -   [X] Create `config.json` for add-on configuration.
    -   [X] Create `run.sh` script to start the FastAPI server.
-   [X] **Test**: Manually build and run the add-on to verify it starts correctly.

### 1.2: Database and User Profile API

-   [X] **Task**: Implement DB setup logic in the add-on (`planmydinner_addon/database.py`).
    -   [X] Define SQLAlchemy models for `UserProfile` and `PantryItem` based on `json_schemas.md`.
    -   [X] Create logic to initialize the SQLite database.
-   [X] **Task**: Implement `UserProfile` CRUD API endpoints in the add-on.
    -   [X] `POST /profiles`: Create a new user profile.
    -   [X] `GET /profiles/{profile_id}`: Retrieve a user profile.
    -   [X] `PUT /profiles/{profile_id}`: Update a user profile.
    -   [X] `DELETE /profiles/{profile_id}`: Delete a user profile.
-   [X] **Test**: Write unit tests (`pytest`) for the `UserProfile` API endpoints.
    -   [X] `tests/test_profiles.py`: Test creation, retrieval, update, and deletion of profiles, checking for correct data and status codes.

### 1.3: Pantry Management API

-   [X] **Task**: Implement `PantryItem` CRUD API endpoints in the add-on.
    -   [X] `POST /pantry/items`: Add an item to the pantry.
    *   [X] `GET /pantry/items`: Retrieve all pantry items.
    -   [X] `PUT /pantry/items/{item_id}`: Update a pantry item.
    -   [X] `DELETE /pantry/items/{item_id}`: Remove an item.
-   [X] **Task**: Implement logic to consume ingredients from pantry upon meal consumption (triggered by consumption API).
-   [X] **Test**: Write unit tests (`pytest`) for the `PantryItem` API endpoints.
    -   [X] `tests/test_pantry.py`: Test CRUD operations for pantry items.

### 1.4: Consumption Tracking API

-   [X] **Task**: Implement DB model for `ConsumedEntry`.
-   [X] **Task**: Implement `ConsumedEntry` API endpoints in the add-on.
    -   [X] `POST /consumed-entries/mark-planned`: Endpoint for `mealplan.mark_consumed`.
    -   [X] `POST /consumed-entries/override`: Endpoint for `mealplan.override_consumed`.
    -   [X] `GET /consumed-entries/`: Retrieve consumed entries for a date range.
-   [X] **Test**: Write unit tests (`pytest`) for `ConsumedEntry` endpoints.
    -   [X] `tests/test_consumption.py`: Test creation of both `planned` and `override` entries.

### 1.5: Home Assistant Integration (MVP)

-   [X] **Task**: Implement basic HA integration setup (`async_setup`, `async_setup_entry`).
-   [X] **Task**: Implement `pantry.add_item` service (and others will be added later).
-   [X] **Task**: Implement `mealplan.mark_consumed` and `mealplan.override_consumed` services.
-   [X] **Task**: Implement `sensor.pantry_summary` to display the count of items in the pantry.
-   [X] **Test**: Manual testing in a Home Assistant development environment.
    -   [X] Verify Planner services work.
    -   [X] Check sensor data updates.

---

## Phase 2: V1 - The "Intelligent Planner"

**Objective**: Automatizzare la pianificazione, implementare il robusto parsing PDF e il motore di suggerimento base.

### 2.1: Recipe Catalog Management

-   [X] **Task**: Implement DB models for `Recipe`, `CandidateRecipe`, `RotationRule`, `SeasonalityItem`, `UnitConversion` based on `json_schemas.md`.
    -   [X] Define SQLAlchemy models in `planmydinner_addon/database.py`.
-   [X] **Task**: Implement `Recipe` CRUD API endpoints in the add-on (`planmydinner_addon/api/recipes.py`).
    -   [X] `POST /recipes`: Create a new recipe.
    -   [X] `GET /recipes/{recipe_id}`: Retrieve a recipe.
    -   [X] `GET /recipes`: Retrieve all recipes.
    -   [X] `PUT /recipes/{recipe_id}`: Update a recipe.
    -   [X] `DELETE /recipes/{recipe_id}`: Delete a recipe.
-   [X] **Test**: Write unit tests (`pytest`) for the `Recipe` API endpoints.
    -   [X] `tests/test_recipes.py`: Test CRUD operations for recipes.

### 2.2: Structured Meal Plan & PDF Parser

-   [X] **Task**: Implement DB model for `StructuredMealPlan` (`planmydinner_addon/database.py`).
-   [X] **Task**: Implement Pydantic schemas for `StructuredMealPlan` (`schemas.py`).
-   [X] **Task**: Implement PDF parsing logic (`planmydinner_addon/pdf_parser.py`).
    -   [X] Use `pdfminer.six` and `tabula-py` (add to `requirements.txt`).
    -   [X] Logic for template-based extraction (regex, keyword matching).
    -   [X] Data normalization (unit conversions, food group assignment).
-   [X] **Task**: Implement Import Wizard API endpoint (`planmydinner_addon/api/import.py`).
    -   [X] `POST /import/pdf`: Endpoint to upload and process PDF.
-   [X] **Test**: Write unit tests (`pytest`) for the PDF parser logic (mocking PDF input).
    -   [X] `tests/test_pdf_parser.py`: Test extraction, normalization, and structuring.

### 2.3: Planner & Ranking Engine

-   [X] **Task**: Implement the Planner logic (`planmydinner_addon/planner.py`).
    -   [X] Function for filtering recipes based on Hard Constraints.
    -   [X] Function for calculating dosing and divergence strategies.
    -   [X] Function for scoring recipes based on Soft Constraints.
-   [X] **Task**: Implement Planner API endpoints (`planmydinner_addon/api/planner.py`).
    -   [X] `POST /planner/generate-week`: Generate a full week's plan.
    -   [X] `POST /planner/change-recipe`: Suggest 3 alternative recipes.
-   [X] **Test**: Write unit tests (`pytest`) for the Planner logic (mocking recipes, pantry, etc.).
    -   [X] `tests/test_planner.py`: Test filtering, dosing, scoring, and ranking.

### 2.4: Home Assistant Integration (V1)

-   [X] **Task**: Implement API client methods for new Planner endpoints (`api_client.py`).
-   [X] **Task**: Implement HA services for `mealplan.generate_week`, `mealplan.change_recipe`, `mealplan.apply_recipe_option`.
-   [X] **Task**: Implement HA sensors for `mealplan_today`, `mealplan_week`, `shopping_list_aggregated`.
-   [X] **Test**: Manual testing in Home Assistant development environment.
    -   [X] Verify Planner services work.
    -   [X] Check sensor data updates.

---

---

## Phase 4: V1 - Lovelace UI Development

**Objective**: Create interactive Lovelace custom cards for Plan My Dinner functionalities.

### 4.1: Basic Custom Card Setup

-   [X] **Task**: Create a custom card directory (`www/community/planmydinner-card`).
-   [X] **Task**: Create `planmydinner-card.js` with a minimal `lit-element` custom card.
-   [X] **Test**: Verify the card loads and displays a static message on a Lovelace dashboard.
-   [X] **Doc**: Update documentation on how to load and use the custom card.

### 4.2: "Today View" Card Implementation

-   [X] **Task**: Implement UI with "Pranzo" and "Cena" sections based on entity attributes.
-   [X] **Task**: Add buttons to call `mark_consumed` and `override_consumed` services.
-   [ ] **Test**: Verify the new UI displays meal attributes and buttons call HA services correctly.

### 4.3: Visual Card Editor

-   [ ] **Task**: Implement `static getConfigElement()` and `static getStubConfig()` to enable the visual editor.
-   [ ] **Task**: Create the editor UI element to allow configuring the card's entity via a form.
-   [ ] **Test**: Verify the visual editor appears and correctly saves the card configuration.

---

## Phase 3: V2 - Auto-Learning & LLM (Checklist TBD)

-   [ ] LLM Gateway
-   [ ] Auto-Learning Logic
-   [ ] Candidate Recipe Management
-   [ ] UI View (Candidate Recipes)
