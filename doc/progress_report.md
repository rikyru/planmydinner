# Documentazione sullo Stato Avanzamento Lavori

Questa documentazione riassume il lavoro svolto e le funzionalità implementate finora, comprese le sfide incontrate e le relative soluzioni.

## Obiettivo Iniziale del Progetto
L'obiettivo è stato quello di implementare una nuova dashboard elegante con una vista settimanale del piano pasti. Questo piano doveva essere generato utilizzando un Large Language Model (LLM) basato sulle informazioni nutrizionali estratte da un PDF caricato dall'utente. L'utente avrebbe dovuto avere la possibilità di richiedere ricette alternative tramite l'LLM.

## Lavoro Svolto e Funzionalità Implementate

### 1. Nuova Dashboard e API del Piano Settimanale
*   **Frontend:**
    *   Creata una nuova componente Vue.js (`dashboard.js`) per visualizzare il piano settimanale.
    *   Aggiunti stili CSS (`dashboard.css`) per la dashboard.
    *   `index.html` è stato modificato per includere la dashboard come pagina predefinita, con un link di navigazione dedicato.
    *   La dashboard ora recupera dinamicamente i profili utente e mostra un messaggio informativo se non ci sono almeno due profili per la pianificazione.
*   **Backend:**
    *   Aggiunto un nuovo endpoint API `GET /planner/weekly-plan` (`planmydinner_addon/api/planner.py`) per recuperare il piano settimanale.

### 2. Miglioramenti al Planner Engine (Backend)
*   **Resilienza del Piano Settimanale:** La funzione `generate_weekly_plan` in `planmydinner_addon/planner.py` è stata resa più robusta. Ora gestisce il caso in cui solo uno dei due profili ha un piano pasti attivo, procedendo con la generazione basata sul piano disponibile e creando un piano "dummy" per il profilo mancante.
*   **Generazione Ricette basata su LLM (Fallback):**
    *   La funzione `suggest_recipes_for_meal` in `planmydinner_addon/planner.py` ora include una logica di fallback: se non trova ricette esistenti nel database che soddisfano i vincoli del piano, chiama l'LLM per generare una nuova ricetta su misura.
    *   La nuova ricetta generata dall'LLM viene salvata come `CandidateRecipe` nel database e restituita alla dashboard.

### 3. Integrazione e Ottimizzazione LLM
*   **LLMGateway:** Aggiunta una nuova funzione `generate_recipe_from_constraints` in `planmydinner_addon/llm_gateway.py`. Questa funzione è responsabile di costruire un prompt dettagliato per l'LLM, includendo tutti i vincoli (profili utente, dosi alimentari target, allergie, alimenti in scadenza, ecc.), e di richiedere all'LLM la generazione di una ricetta strutturata in formato JSON.

## Problemi Incontrati e Soluzioni

### A. Problema: `500 Internal Server Error` durante l'upload PDF
*   **Causa:** Un bug nella funzione `_parse_meal_section` in `pdf_parser.py` richiamava erroneamente `self.unit_converter.get_food_group_for_item` invece di `self.get_food_group_for_item`, causando un `AttributeError`.
*   **Soluzione:** Corretta la chiamata al metodo a `self.get_food_group_for_item`.

### B. Problema: Dashboard vuota dopo il riavvio iniziale (Nessun Piano)
*   **Causa:** Il pianificatore non trovava piani pasti attivi. Questo era dovuto a:
    1.  Gli ID dei profili utente erano hardcoded nel frontend e non corrispondevano a quelli reali nel database.
    2.  L'utente non aveva cliccato il pulsante "Save" dopo l'upload del PDF, quindi nessun `StructuredMealPlan` era stato salvato.
*   **Soluzione:**
    1.  Modificata la dashboard per recuperare dinamicamente i profili e usare i primi due disponibili.
    2.  Fornite istruzioni chiare all'utente per cliccare "Save" dopo l'importazione PDF.

### C. Problema: Dashboard vuota anche con piani salvati e ricette di esempio
*   **Causa:**
    1.  Il `PlannerEngine` era troppo rigido e richiedeva piani attivi per *entrambi* i profili, fallendo se uno era mancante.
    2.  Le ricette di esempio aggiunte non soddisfacevano i vincoli di quantità del PDF caricato dall'utente, anche con una tolleranza del 10%.
*   **Soluzione:**
    1.  Modificata la funzione `generate_weekly_plan` in `planner.py` per gestire un `profile_id_B` opzionale e creare un piano "dummy" se mancante.
    2.  Aumentata temporaneamente la `QUANTITY_TOLERANCE_PERCENT` a 50% per il debug, dimostrando che il matching di quantità era il problema.

### D. Problema: Errori di Validazione dello Schema `RecipeCreate` dall'LLM
*   **Causa:** L'LLM non stava generando il JSON della ricetta in un formato perfettamente conforme allo schema `RecipeCreate`, omettendo campi (`total_time_minutes`, `steps`) o usando tipi/valori errati (`difficulty` come int o stringa con capitalizzazione errata).
*   **Soluzione:** I prompt in `llm_gateway.py` sono stati resi estremamente espliciti riguardo ai campi richiesti, ai loro tipi di dato e ai valori accettati (es. `difficulty` deve essere una stringa minuscola tra opzioni specifiche). È stato anche aggiunto un esempio JSON completo al prompt per guidare l'LLM.

## Stato Attuale
L'applicazione è ora configurata per:
*   Visualizzare una dashboard con un piano settimanale.
*   Generare ricette dinamicamente tramite LLM se non ne trova di adatte nel database, rispettando i vincoli del PDF.
*   Gestire in modo più resiliente scenari con profili utente incompleti.

Il prossimo passo è verificare che la generazione LLM funzioni correttamente con l'ultimo fix, e poi implementare la funzionalità del pulsante "Change" e l'integrazione con la ricerca web.
