# Plan My Dinner - Meal Planning System for Home Assistant

This project is a comprehensive meal planning system for Home Assistant, designed to automate and simplify meal planning, recipe generation, and shopping list management. It consists of a Home Assistant custom integration and a powerful backend Docker Add-on.

## Features

*   **Intelligent Meal Planner**: Automatically generates new lunch and dinner recipes based on user profiles, dietary restrictions, and meal plans.
*   **PDF Import Wizard**: Imports and structures meal plans from your nutritionist's PDF, allowing for review and editing.
*   **Dynamic Recipe Suggestions**: Get alternative recipe suggestions based on your pantry inventory, seasonality, and cooking preferences.
*   **Consumption Tracking**: Easily track what you've eaten, whether it's a planned meal or something else.
*   **Auto-Learning & LLM Integration**: Automatically learns new recipes from your free-text "override" entries using LLMs (e.g., Ollama, OpenAI).
*   **Pantry Management**: Keep track of your pantry inventory, with a focus on using ingredients before they expire.
*   **Aggregated Shopping List**: Automatically generates a weekly shopping list based on your planned meals.
*   **Lovelace UI**: A rich set of Lovelace cards for a seamless experience within Home Assistant, including a "Today" view, weekly plan, pantry management, and more.

## Architecture

The system is built on a modular architecture:

1.  **Home Assistant Custom Integration (`custom_components/planmydinner`)**: This integration provides the frontend interface within Home Assistant. It exposes sensors for displaying meal plans, shopping lists, and pantry items, as well as services for interacting with the backend.

2.  **Docker Add-on (`planmydinner_addon`)**: This is the backend of the system, running as a separate Docker Add-on within Home Assistant. It's built with FastAPI and includes:
    *   A robust API for managing user profiles, recipes, pantry, and more.
    *   The intelligent Planner and Ranking Engine.
    *   The PDF parsing and Import Wizard functionality.
    *   A SQLite database for storing all data.
    *   An LLM Gateway for interacting with Large Language Models.
    *   A Vue.js frontend for the Import Wizard and other web-based UI.

This decoupled architecture ensures that the intensive processing of the backend does not impact the performance of your Home Assistant instance.

## Setup and Installation

### Prerequisites

*   Home Assistant with Supervisor (for running add-ons).
*   Docker installed on your Home Assistant machine.
*   Access to the Home Assistant configuration directory.

### 1. Home Assistant Custom Integration

1.  Copy the `custom_components/planmydinner` directory into the `custom_components` directory of your Home Assistant configuration.
2.  Restart Home Assistant.
3.  Go to **Configuration** > **Devices & Services** and click **Add Integration**.
4.  Search for "Plan My Dinner" and follow the on-screen instructions to add the integration.

### 2. Docker Add-on

1.  **Copy the Add-on**: Copy the entire `planmydinner_addon` directory to the `/addons` directory of your Home Assistant installation. If the `/addons` directory does not exist, you will need to create it.
2.  **Install the Add-on**:
    *   Go to **Settings** > **Add-ons** in your Home Assistant UI.
    *   Click on the **Add-on Store** button in the bottom right.
    *   In the top-right menu (three dots), click **Check for updates**.
    *   Your "Plan My Dinner" add-on should appear under the "Local add-ons" section.
    *   Click on the add-on and then click **Install**.
3.  **Configure the Add-on**:
    *   Once installed, go to the "Configuration" tab of the add-on.
    *   Set up the necessary environment variables for the LLM Gateway:
        *   `LLM_PROVIDER`: The LLM provider to use (e.g., `ollama` or `openai`). Defaults to `ollama`.
        *   `LLM_API_KEY`: Your API key for the LLM provider (if applicable).
        *   `LLM_BASE_URL`: The base URL for the LLM provider's API (e.g., `http://localhost:11434` for Ollama).
        *   `LLM_MODEL`: The specific LLM model to use (e.g., `llama3`).
    *   Save the configuration.
4.  **Start the Add-on**:
    *   Go back to the "Info" tab of the add-on and click **Start**.
    *   Check the "Logs" tab to ensure the add-on starts up correctly.

### 3. Lovelace UI

1.  **Add Cards to Lovelace**: Add the custom cards from the `lovelace_cards` directory to your Lovelace dashboard as needed. You can use the visual editor for the "Today View" card to configure the entities.
2.  **Example Lovelace Cards**:
    *   `planmydinner-card`: The main "Today" view card.
    *   `planmydinner-pantry-card`: For managing your pantry.
    *   `planmydinner-recipe-card`: For viewing and managing recipes.
    *   `planmydinner-week-card`: For viewing your weekly meal plan.
    *   `planmydinner-shopping-list-card`: For viewing and managing your shopping list.

## Usage

1.  **Import Your Meal Plan**:
    *   Trigger the `service: planmydinner.import_pdf` service from Home Assistant's Developer Tools. This will open the Import Wizard UI.
    *   Upload your nutritionist's PDF meal plan.
    *   Review and edit the extracted plan in the web UI.
    *   Save the plan.

2.  **Generate Your Weekly Plan**:
    *   Trigger the `service: planmydinner.generate_week` service. This will generate a full week's meal plan based on your imported structured plans.

3.  **View and Interact with Your Plan**:
    *   Use the "Today" view card to see your daily meals.
    *   Use the "Change Recipe" button to get alternative suggestions.
    *   Mark meals as consumed using the buttons on the "Today" view card.

4.  **Manage Your Pantry and Shopping List**:
    *   Use the Pantry and Shopping List cards to manually manage your inventory and shopping needs. The shopping list will automatically update based on your weekly plan.
