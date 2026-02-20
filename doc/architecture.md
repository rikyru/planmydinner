# Architecture and Data Flow for Meal Planning System

This document details the overall architecture of the Home Assistant Meal Planning system, outlining its core components, their responsibilities, and how data flows between them. The design emphasizes modularity, scalability, and integration with Home Assistant.

---

## 1. System Overview

The Meal Planning System is composed of two primary parts:

1.  **Home Assistant Custom Integration (Python)**: Acts as the bridge between the user interface (Lovelace) and the core logic running in the Docker Add-on. It exposes sensors for displaying data and services for triggering actions.
2.  **Home Assistant Docker Add-on (FastAPI/SQLite)**: Contains the bulk of the business logic, including PDF parsing, recipe planning, pantry management, and interaction with external services like LLMs. It runs in an isolated Docker container, providing a robust and flexible environment.

## 2. Component Diagram

```mermaid
graph TD
    subgraph Home Assistant (Lovelace UI)
        UI[User Interface - Lovelace]
    end

    subgraph Home Assistant Core
        HA_Core[HA Core]
    end

    subgraph Home Assistant Custom Integration (Python)
        HA_Integration[Custom Integration]
        direction LR
        HA_Integration -- Sensors --> HA_Core
        HA_Core -- Services --> HA_Integration
    end

    subgraph Home Assistant Docker Add-on (FastAPI, SQLite)
        Addon_API[FastAPI Web Server / API Gateway]
        Addon_DB[SQLite Database]
        Addon_PDF[PDF Parser & Import Wizard UI]
        Addon_Planner[Planner & Ranking Engine]
        Addon_Pantry[Pantry Management Module]
        Addon_Seasonality[Seasonality Module]
        Addon_RecipeCatalog[Recipe Catalog Module]
        Addon_LLM[LLM Gateway (Optional)]

        Addon_API -- Reads/Writes --> Addon_DB
        Addon_API -- Calls --> Addon_PDF
        Addon_API -- Calls --> Addon_Planner
        Addon_API -- Calls --> Addon_Pantry
        Addon_Planner -- Uses --> Addon_DB
        Addon_Planner -- Uses --> Addon_Pantry
        Addon_Planner -- Uses --> Addon_Seasonality
        Addon_Planner -- Uses --> Addon_RecipeCatalog
        Addon_Planner -- Optional --> Addon_LLM
        Addon_Pantry -- Uses --> Addon_DB
        Addon_RecipeCatalog -- Uses --> Addon_DB
        Addon_LLM -- Calls --> External_LLM[External LLM Service (Ollama/OpenAI)]
    end

    UI -- Renders/Interacts --> HA_Core
    HA_Core -- Communicates --> HA_Integration
    HA_Integration -- HTTP/REST --> Addon_API

    Addon_API -- Serves HTML/JS --> UI_Wizard[Import Wizard UI (Browser)]
    UI -- Initiates Wizard --> UI_Wizard
```

## 3. Component Responsibilities

### 3.1. Home Assistant Custom Integration (Python)

*   **Configuration**: Manages configuration entries for add-on URL, API keys, default settings, and LLM configuration.
*   **Sensor Exposure**: Exposes system state (e.g., `sensor.mealplan_today`, `sensor.shopping_list_aggregated`, `sensor.pantry_summary`) to Lovelace UI.
*   **Service Exposure**: Exposes callable services (e.g., `mealplan.change_recipe`, `mealplan.mark_consumed`, `pantry.add_item`) to Lovelace UI and Home Assistant automations.
*   **API Client**: Acts as an HTTP client to communicate with the Docker Add-on's FastAPI API.
*   **Authentication**: Handles secure authentication/authorization with the Docker Add-on.

### 3.2. Home Assistant Docker Add-on

This add-on runs a FastAPI web server and manages a SQLite database.

*   **FastAPI Web Server / API Gateway**:
    *   Exposes a RESTful API for all functionalities (PDF parsing, planning, pantry, etc.) to the HA Custom Integration.
    *   Serves the HTML/JavaScript for the interactive PDF Import Wizard UI.
    *   Handles request validation and data serialization/deserialization (using Pydantic for JSON Schema adherence).
*   **SQLite Database**:
    *   Persistent storage for all structured data:
        *   `UserProfile` (preferences, allergies, equipment)
        *   `StructuredMealPlan` (the parsed and confirmed meal plans for each user)
        *   `Recipe` (the catalog of available recipes)
        *   `CandidateRecipe` (recipes learned from user overrides)
        *   `ConsumedEntry` (tracking of actual meal consumption)
        *   `PantryItem` (current pantry contents)
        *   `SeasonalityItem` (lookup table for ingredient seasonality)
        *   `UnitConversion` (lookup table for unit conversions)
        *   `RotationRule` (user-defined rotation rules)
*   **PDF Parser & Import Wizard UI**:
    *   **Parser Logic**: Utilizes libraries like `pdfminer.six` and `tabula-py` for robust text and table extraction. Employs pre-defined templates (e.g., regex patterns, keywords) specific to the nutritionist's PDF layout for accurate data extraction.
    *   **Data Normalization**: Cleans, validates, and normalizes extracted data (e.g., standardizing units, mapping food items to `food_group`).
    *   **Wizard UI**: A web-based interactive interface (HTML/JS/Vue/React served by FastAPI) allowing users to review, correct, and confirm the parsed data before saving it as `StructuredMealPlan`.
*   **Planner & Ranking Engine**:
    *   **Core Logic**: Implements the complex algorithm for filtering and scoring recipes based on Hard and Soft Constraints.
    *   **Dosing & Divergence**: Calculates precise `QuantityPerProfile` for each recipe ingredient and manages `ingredient_swap`, `side_dish`, or `separate_dishes` strategies if profiles conflict.
    *   **Rotation Tracking**: Utilizes `ConsumedEntry` to track past consumption and enforce `RotationRule`s.
    *   **Shopping List Generation**: Aggregates ingredients from planned meals for both profiles, consolidates quantities, and categorizes them.
*   **Pantry Management Module**:
    *   Provides CRUD operations for `PantryItem`.
    *   Interacts with the Planner to provide data on available and expiring ingredients.
*   **Seasonality Module**:
    *   Provides lookup functionality against `SeasonalityItem` data.
    *   Used by the Planner for scoring.
*   **Recipe Catalog Module**:
    *   Manages the `Recipe` and `CandidateRecipe` entities in the database.
    *   Provides search and retrieval capabilities for the Planner.
*   **LLM Gateway (Optional)**:
    *   Provides a standardized interface for interacting with various Large Language Models (e.g., Ollama, OpenAI).
    *   **Use Cases**: Transforming free-text overrides into structured `Recipe` data, generating detailed `steps` for recipes, or enriching metadata (`tags`).
    *   Includes caching mechanisms to reduce latency and API costs.

## 4. Data Flow

1.  **User Interaction (Lovelace)**: User interacts with the Lovelace UI, viewing sensors (e.g., `sensor.mealplan_today`) or triggering services (e.g., `mealplan.change_recipe`).
2.  **HA Integration Call**: Home Assistant routes service calls from Lovelace/automations to the custom integration.
3.  **API Call to Add-on**: The custom integration makes HTTP/REST API calls to the FastAPI server within the Docker Add-on.
4.  **Add-on Processing**:
    *   The FastAPI server receives the request, validates it, and dispatches it to the relevant internal module (PDF Parser, Planner, Pantry, etc.).
    *   These modules interact with the SQLite database to read and write `UserProfile`, `StructuredMealPlan`, `Recipe`, `PantryItem`, `ConsumedEntry`, etc.
    *   The Planner module might query `SeasonalityItem` and optionally interact with the `LLM Gateway`.
    *   The `LLM Gateway` forwards requests to external LLM services if configured, receiving structured JSON responses.
5.  **Add-on Response**: The FastAPI server returns a structured JSON response to the HA Custom Integration.
6.  **HA State Update**: The HA Custom Integration processes the response, updates internal state, and pushes new data to Home Assistant sensors.
7.  **Lovelace UI Update**: Home Assistant updates the Lovelace UI to reflect the new sensor states, providing real-time feedback to the user.
8.  **Import Wizard Specific Flow**: When `mealplan.import_pdf` is called, the HA Integration opens a browser window pointing to a URL served by the Add-on's FastAPI server. The user directly interacts with this web UI for PDF upload, review, and confirmation, which then communicates directly with the Add-on's internal PDF Parser and database.
```