# Plan My Dinner - Memoria di Progetto

## Stato analisi
- Analisi completa del repo eseguita il 2026-02-26
- File dettagliato: `project_analysis.md`
- Piano MVP: `mvp_plan.md`

## Stack tecnico
- Backend: FastAPI + SQLAlchemy + SQLite (`planmydinner_addon/`)
- Frontend: Vue 3 ESM (no build step) + Vanilla JS (`planmydinner_addon/frontend/`)
- LLM: Gateway astratto → OpenAI o Ollama (`planmydinner_addon/llm_gateway.py`)
- HA Integration: custom_components/planmydinner (adapter sopra le API)
- Container: Docker (Dockerfile + run.sh)

## Decision: Standalone-first
Il prodotto deve funzionare PRIMA senza HA. HA è un adapter/plus.
Il backend FastAPI già funziona standalone. La GUI Vue.js già esiste.
Non serve riscrivere: serve FINIRE e connettere correttamente.

## File chiave
- `planmydinner_addon/main.py` - Entry point FastAPI
- `planmydinner_addon/planner.py` - PlannerEngine (core logic)
- `planmydinner_addon/database.py` - ORM + modelli
- `planmydinner_addon/schemas.py` - Pydantic schemas
- `planmydinner_addon/llm_gateway.py` - LLM abstraction
- `planmydinner_addon/pdf_parser.py` - PDF parsing
- `planmydinner_addon/frontend/index.html` - App shell Vue 3
- `planmydinner_addon/frontend/import.js` - Import wizard
- `planmydinner_addon/api/_import.py` - Import endpoints
- `planmydinner_addon/api/planner.py` - Planner endpoints
- `planmydinner_addon/api/shopping_list.py` - Shopping list endpoints

## Preferenze utente
- Italian language preferred in UI and docs
- Standalone-first architecture (HA is plus, not core)
- Single-user, no multi-account
- 4 schermate principali: Dashboard, Import, Settimana, Lista Spesa

## Avanzamento MVP (Step 1 COMPLETATO - 2026-02-26)

### Step 1: Fix bug critici backend ✅
- [x] QUANTITY_TOLERANCE_PERCENT: 0.50 → 0.10 (planner.py:32)
- [x] _calculate_dosing(): implementata (somma qty A+B, aggiunge chiave "combined")
- [x] Shopping list: aggiunta esclusione pasti free-text override
- [x] _get_active_meal_plan(): rimossa finestra 7-giorni hardcoded, ora verifica daily_plans

### Step 2: Verifica flusso end-to-end senza UI ✅
- POST /seed → crea profili (persona_a Marco, persona_b Sara) + 12 ricette + piano settimanale
- POST /planner/generate-week → genera piano 7 giorni ✓
- GET /planner/weekly-plan → cache funziona ✓
- GET /shopping-list → lista per categoria ✓
- GET /shopping-list/export/csv → CSV funzionante ✓
- POST /planner/change-recipe → 3 opzioni ✓ (fix: default mood/cleanup erano "normal" invece di "" → filtrava tutto)
- POST /planner/apply-recipe-option → ✓

**Bug extra trovati e fixati in Step 2:**
- recipe_food_groups dict comprehension sovrascriveva ingredienti dello stesso food group (ora aggrega)
- tabula-py reso import opzionale (non blocca avvio server senza Java)
- change-recipe endpoint richiedeva piano per profilo B (ora usa dummy se mancante)
- mood/cleanup default "normal" → non matchava tag italiani "normale" → ora default ""
- max_time_minutes default 60 → troppo basso per alcune ricette → ora 120

### Step 3: Fix Frontend - Feedback stati ✅  (+ Step 5 dashboard)
- index.html: sistema toast globale (provide/inject), stili base (loading, error-box, empty-box, modal, btn)
- dashboard.js: riscritto — italiano, bottone "Genera settimana", empty-state, modale change-recipe funzionante
- today.js: fix markConsumed (recipeId era sempre null), inject toast, rimossi alert()
- shopping.js: inject toast, alert() → toast
- dashboard.css: restyling completo con nuove classi
### Step 4: Frontend - Lista Spesa funzionale ✅ (già completa in Step 2/3)
### Step 5: Frontend - Change Recipe UI ✅ (fatto in dashboard.js + today.js già aveva il modal)
### Step 6: Docker standalone verifica ✅
- README.md: aggiunta sezione "Avvio rapido standalone" (3 comandi + tabella variabili)
- docker-compose.standalone.yml e .env.example già pronti dalla sessione precedente

### Step 7: PDF Import fix ✅
- api/_import.py: /import/pdf ora estrae testo con pdfminer → passa all'LLM
- Logica LLM estratta in _parse_text_with_llm() condivisa tra /pdf e /text
- Fallback al parser regex se LLM non disponibile
- Messaggio errore suggerisce tab Testo se PDF non estraibile

### Step 8: Test & Polish UI ✅
- import.js: riscritto con inject toast, loading state, async/await
- Preview piano: tabella semplificata (4 colonne invece di 6), form più pulita
- style.css: stili dedicati per import view, tab-bar, preview giornaliero
