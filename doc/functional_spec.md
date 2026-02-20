# Functional Specification and UI Flows for Meal Planning System

This document outlines the functional requirements and user interface (UI) flows for the Home Assistant Meal Planning system. It details how users will interact with the system and what features will be available, aligning with the project's core objectives.

---

## 1. User Stories

*   **As a user, I want a robust Import Wizard** that, starting from PDF meal plans provided by my nutritionist, automatically analyzes and structures the dietary plans for both myself and my partner. This wizard should recognize quantities, food item alternatives, weekly rotation rules, and recommended cooking methods, while allowing me to review and confirm the extracted output.
*   **As a user, I want an intelligent automatic planner** that, based on the imported plans, generates new lunch and dinner recipes. This planner must ensure that portion sizes are correctly calculated for both profiles ("stesso piatto, dosi diverse") and that weekly nutritional rotations (e.g., max eggs/week, min legumes/week) are consistently respected.
*   **As a user, I want a clear and intuitive "Today" View** on my Home Assistant Lovelace dashboard (optimized for tablets). This view should feature prominent cards for lunch and dinner, displaying the proposed recipe, estimated preparation times, personalized portion sizes for each profile, and convenient buttons for viewing full recipe details, quickly changing the recipe, and tracking what I've actually eaten.
*   **As a user, I want a "CHANGE RECIPE!" button** that, when pressed, presents me with three intelligently generated alternative recipe candidates. These alternatives should be ranked based on nutritional plan adherence, ingredients currently in my pantry (including their expiration dates), seasonality, my current cooking mood, and my preference for kitchen cleanup effort.
*   **As a user, I want a consumption tracking system** that allows me to easily mark a proposed meal as "eaten" or, if I ate something different, to manually input what I actually consumed (either as free text or with structured ingredients). The system should leverage this real consumption data to influence future rotation calculations and to auto-learn new recipe candidates.
*   **As a user, I want manual management of my pantry**, enabling me to add, edit, or remove ingredients, specifying quantities, units, categories, and expiration dates. The recipe planner should prioritize recipes that utilize existing pantry ingredients, especially those nearing their expiration dates, to minimize food waste.
*   **As a user, I want an aggregated and smart weekly shopping list**, which automatically updates based on the planned recipes. This list should avoid including ingredients if a meal was tracked via free-text override without structured ingredient data.

## 2. UI Flows

### 2.1. Import Wizard (Web Page within Docker Add-on)

1.  **Trigger**: User activates `service.mealplan.import_pdf(person_id='A')` from Home Assistant.
2.  **Upload**: A web page opens (served by the Docker add-on) prompting the user to upload the PDF for Persona A.
3.  **Parsing & Pre-processing**: The system uses a pre-configured parsing template (for the nutritionist's specific layout) to extract data:
    *   Meal types (Pranzo, Cena, etc.), food items, quantities, units.
    *   "Alternative" boxes for specific items.
    *   Global rules: "Frequenze Settimanali" (e.g., max eggs/week), "Metodi Cottura Consigliati."
    *   "Idee/Piatti Esempio" are extracted but marked as suggestions, not constraints.
4.  **Review & Edit UI**: A tabular interface displays the extracted data for each day and meal.
    *   Each `PlannedItem` shows extracted name, quantity, unit.
    *   Units marked as `is_estimated_unit` (e.g., "bicchiere" converted to "ml") are visually highlighted, allowing the user to override the conversion.
    *   User can manually correct extracted `quantity`, `unit`, or assign/refine a `food_group` if the automatic recognition is ambiguous.
    *   User can review and confirm `RotationRule`s and `allowed_cooking_methods`.
5.  **Save**: User confirms. The system saves the `StructuredMealPlan` JSON for Persona A in the SQLite DB.
6.  **Repeat for Persona B**: The process is repeated for Persona B.
7.  **System Initialization**: Once both plans are saved, the HA integration triggers `mealplan.generate_week()` to populate the initial weekly plan and shopping list.

### 2.2. "Today" View (Home Assistant Lovelace Dashboard)

*   **Layout**: Optimized for tablet. Two main `Mushroom Template Card`s for "Pranzo" and "Cena".
*   **Content per Card**:
    *   **Recipe Name**: Prominently displayed.
    *   **Times**: `total_time_minutes` (e.g., "30 min").
    *   **Cleanup Score**: Icon/text representing `cleanup_score` (e.g., a dishwashing sponge icon with "Low Mess").
    *   **Portions**: Clear display of main ingredient portions for Persona A and Persona B (e.g., "Pasta: 120g (A), 90g (B)").
    *   **Buttons**:
        1.  **`Dettagli Ricetta`**: Opens a modal (`browser_mod` pop-up or custom card) displaying the full `Recipe` details (ingredients with A/B quantities, step-by-step procedure, notes, full tags).
        2.  **`CAMBIA RICETTA!`**: Triggers the "Change Recipe" flow.
        3.  **`SEGNA COME MANGIATO`**: A split button or a main button with a confirmation and an "Override" option:
            *   **Direct Click**: `mealplan.mark_consumed(meal='pranzo', day_offset=0)` confirms the proposed recipe was eaten.
            *   **"Ho mangiato altro..."**: Opens the "Override Consumo" modal.

### 2.3. "Change Recipe" Flow (Modal/Overlay)

1.  **Trigger**: User clicks `CAMBIA RICETTA!` on a meal card.
2.  **Parameter Input**: A compact modal appears, asking for current preferences:
    *   `mood` (dropdown: quick / normal / effort).
    *   `cleanup` (dropdown: low_mess / normal / high_mess).
    *   `max_time_minutes` (slider/input: e.g., 15/30/45/60+).
3.  **Service Call**: HA calls `service.mealplan.change_recipe(meal, mood, cleanup, max_time_minutes, day_offset=0)`.
4.  **Alternatives Display**: The modal updates to show three `ChangeRecipeOption` cards.
    *   Each option card includes: name, time, difficulty, `cleanup_score`, key ingredients, and `divergence_strategy` (if any).
5.  **Selection**: User selects one alternative by clicking a "Scegli" button on the chosen option.
6.  **Apply Change**: HA calls `service.mealplan.apply_recipe_option(option_id, meal, day_offset=0)`.
7.  **UI Update**: The "Today" view updates with the new recipe, and the `AggregatedShoppingList` sensor is automatically re-generated.

### 2.4. "Override Consumo" Modal

1.  **Trigger**: User selects "Ho mangiato altro..." from the `SEGNA COME MANGIATO` button.
2.  **Input Fields**:
    *   `Nome del piatto` (text input, e.g., "Torta salata peperoni e ricotta").
    *   `Ingredienti` (optional, expandable component allowing structured input: `name`, `quantity`, `unit` for multiple ingredients).
    *   `Note` (text area, optional).
3.  **Service Call**: HA calls `service.mealplan.override_consumed(meal, day_offset, free_text_name, optional_ingredients, notes)`.
4.  **Feedback**:
    *   If no structured ingredients were provided: A temporary message appears in the UI (e.g., a toast notification): *"Pasto registrato per le rotazioni. Non verrà aggiunto alla lista della spesa."*
    *   If structured ingredients were provided (or successfully inferred by LLM/system): A message indicating that a candidate recipe has been created.

### 2.5. "Week" View (Lovelace)

*   **Layout**: Grid or calendar-style view showing `pranzo` and `cena` for each day of the week. Each cell/card briefly shows the recipe name.
*   **Interactions**:
    *   Clicking a recipe name opens the full recipe details modal.
    *   Button: `RIGENERA SETTIMANA` (triggers `mealplan.generate_week()`).

### 2.6. "Shopping List" View (Lovelace)

*   **Content**: Displays `sensor.shopping_list_aggregated`, grouped by category.
*   **Interactions**:
    *   Each item has a checkbox (`custom:checklist-card` or similar).
    *   Button: `ESPORTA A HA SHOPPING LIST` (triggers HA native service).
    *   Button: `PULISCI LISTA` (resets checkboxes).

### 2.7. "Pantry" View (Lovelace)

*   **Content**: Displays a table of `PantryItem`s from `sensor.pantry_summary`, showing name, quantity, unit, category, and expiration date. Visually highlights items nearing expiration.
*   **Interactions**:
    *   Buttons: `AGGIUNGI ARTICOLO`, `MODIFICA`, `RIMUOVI`.
    *   (Optional) `STORICO CONSUMI` per vedere come gli item sono stati decrementati.

---

## 3. Modello Dati Completo e JSON Schema

La definizione completa e validata JSON Schema è contenuta nel file `doc/json_schemas.md`. Questo schema è la base per la consistenza dei dati tra tutti i componenti del sistema.

#### Riepilogo delle entità chiave definite nello schema:

*   **`UnitConversion`**: Regole per la conversione di unità di misura "soft".
*   **`RotationRule`**: Regole configurabili per le frequenze settimanali di food groups o item specifici.
*   **`PlannedItem`**: Singolo alimento/ingrediente come estratto dal PDF per un pasto specifico.
*   **`PlannedMeal`**: Un pasto completo (es. pranzo) composto da `PlannedItem`s.
*   **`DailyPlannedMeals`**: Raggruppa i `PlannedMeal`s per un giorno specifico.
*   **`StructuredMealPlan`**: L'intero piano settimanale per un profilo utente, inclusi regole di rotazione e metodi di cottura.
*   **`QuantityPerProfile`**: Dettaglio di quantità, unità ed equivalente in grammi per un singolo profilo.
*   **`RecipeIngredient`**: Ingrediente di una ricetta, con quantità separate per `persona_a` e `persona_b`.
*   **`ComposedDishContent`**: Struttura per piatti composti (es. torta salata) con i suoi `RecipeIngredient`s.
*   **`Recipe`**: La definizione completa di una ricetta, con ingredienti (strutturati per profilo), steps, tempi, difficoltà, e tag. Include `is_composed_dish` e `content` (che può essere una lista di `RecipeIngredient` o un `ComposedDishContent`).
*   **`CandidateRecipe`**: Una ricetta in stato di "bozza", generata da un `override_consumed`, con uno `status` (`draft_free_text`, `draft_structured`, `approved`) e `usage_count`.
*   **`OverrideConsumedDetails`**: Dettagli del pasto consumato tramite override.
*   **`ConsumedEntry`**: Registrazione di un pasto consumato, sia pianificato che tramite override. Cruciale per le rotazioni.
*   **`PantryItem`**: Ingrediente presente in dispensa, con quantità, scadenza, etc.
*   **`SeasonalityItem`**: Dati di stagionalità per un ingrediente specifico.
*   **`UserProfile`**: Profilo dell'utente con preferenze, allergie, attrezzature.
*   **`ShoppingListItem`**: Singolo articolo per la lista della spesa.
*   **`AggregatedShoppingList`**: La lista della spesa finale, raggruppata per categoria.

---

## 4. Algoritmo del Planner

Il cuore del sistema è il Planner/Ranking Engine che genera ricette basandosi su un insieme complesso di vincoli e criteri di punteggio.

### 4.1. Definizione Constraints

*   **Hard Constraints (Filtri booleani - DEVONO essere soddisfatti):**
    1.  **Corrispondenza Piano (`PlannedMeal`):** Per il pasto target, la ricetta candidata deve contenere `RecipeIngredient`s che mappano i `food_group` e le quantità (grammi equivalenti) dei `PlannedItem`s per entrambi i profili. La somma delle `grams_equiv` per ogni `food_group` nella ricetta deve rientrare nella tolleranza configurabile (default ±10%) della somma delle `grams_equiv` pianificate per quel gruppo per *entrambi i profili*.
    2.  **Allergie/Intolleranze/Esclusioni**: La ricetta non deve contenere ingredienti presenti nelle liste `allergies` o `excluded_foods` di *nessun profilo*. Se un ingrediente può essere sostituito (`ingredient_swap`) per un profilo specifico, la ricetta può rimanere se la sostituzione risolve il problema.
    3.  **Rotazioni Settimanali (Hard)**: Per ogni `RotationRule` con `is_hard_constraint: true`, il conteggio del `food_group_or_item` nella ricetta candidata, sommato ai consumi reali (`ConsumedEntry`) degli ultimi 6 giorni, non deve superare il `max_per_week`.
    4.  **Metodi di Cottura**: La ricetta deve usare solo `cooking_methods` presenti in `UserProfile.allowed_cooking_methods` e non deve usare quelli in `UserProfile.global_excluded_cooking_methods`.
    5.  **Parametri Utente (`change_recipe` call)**: La `total_time_minutes` della ricetta deve essere <= `max_time_minutes`. I `tags.mood` e `tags.cleanup` della ricetta devono essere compatibili con i `mood` e `cleanup` richiesti dall'utente.
    6.  **Attrezzatura (`UserProfile.equipment`)**: La ricetta deve essere realizzabile con l'attrezzatura (`equipment_tags`) disponibile per l'utente.
    7.  **Anti-Ripetizione**: La ricetta `id` non deve essere presente nelle `ConsumedEntry` o nel `StructuredMealPlan` (se già assegnata) degli ultimi `N` giorni (default 7).
    8.  **Alternative del Piano**: Se un `PlannedItem` ha `alternatives`, il motore cercherà prima un ingrediente esatto, poi un'alternativa se l'originale non è disponibile o desiderabile.

*   **Soft Constraints (Influenzano il ranking - non bloccano la ricetta):**
    *   **Utilizzo Dispensa**: Bonus per ingredienti presenti nella `Pantry`.
    *   **Ingredienti in Scadenza**: Bonus significativo per ingredienti della `Pantry` prossimi alla `expiration_date`.
    *   **Stagionalità**: Bonus per ingredienti di stagione (dalla tabella `SeasonalityItem`). Malus per fuori stagione.
    *   **Rotazioni Settimanali (Soft)**: Bonus per ricette che aiutano a raggiungere un `min_per_week` per un `food_group_or_item` o che rientrano in `RotationRule` con `is_hard_constraint: false`.
    *   **Preferenze `UserProfile`**: Bonus per ricette che rispecchiano le `preferences` (es. Vegetariano) anche se non sono hard constraints (per onnivori).

### 4.2. Algoritmo di Generazione/Ranking

1.  **Inizializzazione**:
    *   Carica `StructuredMealPlan` (A e B) per il giorno e pasto target.
    *   Carica `UserProfile` (A e B).
    *   Carica `ConsumedEntry` degli ultimi N giorni per A e B.
    *   Carica `PantryItem` e `SeasonalityItem`.
    *   Inizia con l'intero `Recipe` catalogo (incluse le `CandidateRecipe` con `status: 'approved'`).

2.  **Filtraggio Hard Constraints**:
    *   Per ogni ricetta nel catalogo:
        *   **Applica Hard Constraint #1 (Corrispondenza Piano):** Verifica che i `food_group` e le quantità degli `RecipeIngredient` della ricetta rientrino nella tolleranza dei `PlannedItem` del `StructuredMealPlan`. Se la ricetta è un `ComposedDish`, analizza i suoi `components`.
        *   **Applica Hard Constraint #2 (Allergie/Esclusioni):** Controlla gli `RecipeIngredient` contro le liste di `allergies` e `excluded_foods` di entrambi i profili. Se un conflitto esiste, tenta una `divergence_strategy` (`ingredient_swap`) se possibile. Se la divergenza non risolve o non è applicabile, scarta la ricetta.
        *   **Applica Hard Constraint #3 (Rotazioni Settimanali Hard):** Simula il consumo della ricetta e verifica se viola `max_per_week` per A o B, tenendo conto delle `ConsumedEntry` già registrate. Scarta se viola.
        *   **Applica Hard Constraint #4-8:** Controlla tutti gli altri hard constraints (`cooking_methods`, `max_time`, `mood`, `cleanup`, `equipment`, `anti-ripetizione`, `alternative_del_piano`). Scarta se violati.

3.  **Calcolo Dosi Specifiche e Strategie di Divergenza**:
    *   Per ogni ricetta che ha superato il filtraggio:
        *   **Garantisci "stesso piatto, dosi diverse"**: Genera le `quantities` per `persona_a` e `persona_b` per ogni `RecipeIngredient`. Questo è un processo di scaling basato sui `grams_equiv` dei `PlannedItem` e sui `UserProfile` (es. Persona A mangia più carboidrati, Persona B più proteine).
        *   **Conferma/Applica Strategia Divergenza**: Se il filtro ha suggerito una `ingredient_swap` o `side_dish`, applicala qui e registra i `divergence_details`. `separate_dishes` è l'ultima ratio, e verrà applicata solo se inevitabile. Se a questo punto una ricetta non riesce a soddisfare entrambi i profili anche con divergenze, viene scartata.

4.  **Scoring Soft Constraints**:
    *   Per ogni ricetta che ha superato i filtri e le divergenze, calcola il `Score` utilizzando la formula di scoring basata sui Soft Constraints e sui pesi configurati.

5.  **Selezione delle Alternative**:
    *   Ordina le ricette per `Score` decrescente.
    *   Seleziona le Top 3 ricette per `change_recipe()`.
    *   Seleziona la Top 1 per `generate_week()`.

---

## 5. Piano di Implementazione a Fasi

Questo piano divide il progetto in fasi gestibili, garantendo un valore incrementale ad ogni rilascio.

*   **Fase 0: Setup e Fondamenta (Pre-MVP)**
    *   **Obiettivo**: Preparare l'ambiente di sviluppo e le strutture dati di base.
    *   **Deliverables**:
        *   Repository GIT inizializzato.
        *   Ambiente di sviluppo Docker (con FastAPI/SQLite) e Home Assistant configurato.
        *   Struttura del database SQLite con tutte le tabelle create (anche se vuote).
        *   Popolamento DB con tabelle di `UnitConversion` e `SeasonalityItem` (dati per l'Italia).
        *   Boilerplate dell'integrazione HA custom e dell'add-on Docker.

*   **Fase 1: MVP - Il "Tracciatore di Consumi" Manuale**
    *   **Obiettivo**: Permettere all'utente di definire i profili, gestire manualmente la dispensa e tracciare ciò che viene mangiato (proposto o override).
    *   **Deliverables**:
        *   **Add-on Docker**:
            *   API e DB per `UserProfile` CRUD.
            *   API e DB per `PantryItem` CRUD (manuale).
            *   API e DB per `ConsumedEntry` (registrazione di `type: planned` e `type: override`).
            *   Implementazione del servizio `pantry.consume_meal_ingredients`.
        *   **Integrazione HA**:
            *   Servizi: `pantry.add_item`, `pantry.update_item`, `pantry.remove_item`, `mealplan.mark_consumed`, `mealplan.override_consumed`.
            *   Sensori: `sensor.pantry_summary`.
        *   **UI Lovelace**:
            *   Vista "Pantry" con CRUD base.
            *   Vista "Oggi" con card (vuote per ora) per Pranzo/Cena e i pulsanti "SEGNA COME MANGIATO" e "Ho mangiato altro..." con la relativa modale.
            *   Dashboard di configurazione per `UserProfile` (manuale).

*   **Fase 2: V1 - Il "Planner Intelligente" e l'Importazione PDF**
    *   **Obiettivo**: Automatizzare la pianificazione, implementare il robusto parsing PDF e il motore di suggerimento base.
    *   **Deliverables**:
        *   **Add-on Docker**:
            *   **PDF Parser (Completo)**: Implementazione del modulo completo con template specifici, riconoscimento sezioni, normalizzazione unità/alimenti.
            *   **Import Wizard UI (Web)**: Interfaccia web per l'importazione, revisione e conferma del `StructuredMealPlan`.
            *   **Catalogo Ricette**: Implementazione API e DB per `Recipe` (popolato inizialmente con un set base di 20-30 ricette o da importazione esterna).
            *   **Planner/Ranking Engine (Base)**: Implementazione completa del filtraggio Hard Constraints e del calcolo Dosi/Divergenze. Implementazione del Ranking Soft Constraints per: utilizzo dispensa, stagionalità, anti-ripetizione. Rotazioni Hard gestite.
            *   Servizi: `mealplan.import_pdf`, `mealplan.generate_week`, `mealplan.change_recipe`, `mealplan.apply_recipe_option`.
        *   **Integrazione HA**:
            *   Servizi per le nuove funzioni del planner.
            *   Sensori: `sensor.mealplan_today`, `sensor.mealplan_week`, `sensor.shopping_list_aggregated`.
        *   **UI Lovelace**:
            *   Completamento della Vista "Oggi" (visualizzazione ricette proposte).
            *   Implementazione della modale "Cambia Ricetta!" (con input parametri e 3 alternative).
            *   Implementazione della Vista "Settimana".
            *   Implementazione della Vista "Shopping List".

*   **Fase 3: V2 - L'Autoapprendimento e l'Intelligenza Aumentata**
    *   **Obiettivo**: Introdurre l'integrazione LLM, raffinare l'autoapprendimento e ottimizzare ulteriormente la user experience.
    *   **Deliverables**:
        *   **Add-on Docker**:
            *   **LLM Gateway**: Implementazione del modulo per l'interazione con LLM (Ollama/OpenAI), con configurazione e caching.
            *   **Autoapprendimento**: Logica per convertire `override_consumed` con ingredienti parziali o free-text in `CandidateRecipe` (`draft_structured`) tramite LLM/euristiche. Logica per promuovere `CandidateRecipe` ad `approved` dopo N usi o approvazione manuale.
            *   **Ranking Avanzato**: Ottimizzazione del `ExpirationScore` per ingredienti prossimi alla scadenza (priorità dinamica).
        *   **Integrazione HA**:
            *   Opzioni di configurazione LLM.
        *   **UI Lovelace**:
            *   Vista "Ricette Candidate" per la gestione (`approve`, `edit`, `delete`) delle ricette autoapprese.
            *   Feedback visivo migliorato nell'Import Wizard e nella modale "Cambia Ricetta!".
            *   Integrazione opzionale con la lista della spesa nativa di HA.

---

### 6. Esempi JSON

Questi esempi concreti illustrano i formati di dati utilizzati nel sistema.

#### a) Un giorno del `StructuredMealPlan` importato per `persona_a`

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

#### b) `ConsumedEntry` per `mark_consumed` e `override_consumed`

```json
// Consumo di un pasto pianificato (mark_consumed)
{
  "id": "cons_1_20260219_pranzo_A",
  "profile_id": "persona_a",
  "date": "2026-02-19",
  "meal_type": "pranzo",
  "type": "planned",
  "consumed_recipe_id": "recipe_riso_salmone_verdure_001"
}

// Consumo con override (override_consumed con ingredienti strutturati)
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

// Consumo con override (override_consumed solo free-text)
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

#### c) Una `CandidateRecipe` generata da `override_consumed` ("Torta salata peperoni e ricotta")

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

#### d) `change_recipe` con 3 opzioni (risposta all'integrazione HA)

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

#### e) Lista spesa aggregata (dal `sensor.shopping_list_aggregated`)

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