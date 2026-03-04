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

# Plan My Dinner — Project Memory

## Ultima sessione (2026-03-03) — Cambio verdura + target verdure + popup settimanale

### Feature: Cambio verdura (componente)
- `get_component_alternatives(component='veg')` in `planner.py`: swap verdura mantenendo prot+carbo
- Scala grammi in modo equivalente (insalata mista 80g/porzione → melanzane 200g/porzione)
- Usa `_VEG_PORTION_GRAMS` dict + `_VEG_DEFAULT_PORTION_GRAMS=150.0` come costanti di classe
- today.js: aggiunto bottone `↕ Verdura` accanto a `↕ Carbo` e `↕ Proteina`

### Feature: Target verdure nel profilo
- `PlanRules.veg_target` (JSON): `{"min_grams": 150, "portion_grams": {"insalata mista": 80, ...}}`
- `database.py`: nuova colonna `veg_target JSON` + migrazione automatica in `create_db_and_tables()`
- `schemas.py`: `veg_target: Optional[Dict[str, Any]] = None` aggiunto a `PlanRules`
- `api/planner.py`: `PlanRulesUpdate` aggiornato; GET `/rules` include `veg_target`; `GET /planner/veg-portions` restituisce tabella default
- `planner.py`: `_veg_portions_in_recipe()` + soft penalty (-0.2) se ricetta < min_portions in `suggest_recipes_for_meal`
- profiles.js: sezione view+edit per veg_target con tabella equivalenze editabile

### Feature: Popup pasto nella vista settimanale
- planner.js: click su `week-meal` apre modal pasto con 2 viste:
  1. Vista principale: nome pasto + [↕ Carbo] [↕ Proteina] [↕ Verdura] [↺ Cambia ricetta]
  2. Vista alternative: lista opzioni con ← Indietro
- Usa stessa API: `POST /planner/change-component` + `POST /planner/apply-recipe-option`
- Il bottone ↺ usa `.stop` per non propagare il click al week-meal

### Migrazione DB (importante)
- Aggiunta in `database.py.create_db_and_tables()` per ALTER TABLE automatico
- Pattern: loop su `[(table, col, type)]` con try/except per colonne già esistenti

## Sessione precedente (2026-03-03) — Fix fingerprint + LLM debug + bulk pantry

### Root cause "stesso pollo ogni giorno"
- Docker usa OpenAI GPT-4o-mini (env: `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini`)
- `_load_recent_plan_recipe_ids` (days_back=14) escludeva le 5 ricette carne_bianca usate la settimana precedente
- Con solo 8 ricette carne_bianca totali e 5 per settimana → solo 3 rimanenti, di cui 1 fallisce hard_constraint (patate 180g) e 2 hanno stesso fingerprint (pure-pollo) → 1 slot da catalogo poi tutto LLM
- LLM generava sempre "Pollo con Couscous" perché il piano ha couscous come carb default

### Fix 1 — 6 nuove ricette carne_bianca in seed.py (totale 48 ricette, 14 carne_bianca)
- `seed_comp_pollo_couscous`: pollo + couscous (fp: {couscous, pollo})
- `seed_comp_tacchino_pasta`: tacchino + pasta (fp: {tacchino, pasta})
- `seed_comp_tacchino_riso`: tacchino + riso (fp: {tacchino, riso})
- `seed_comp_tacchino_farro`: tacchino + farro (fp: {tacchino, farro})
- `seed_comp_tacchino_couscous`: tacchino + couscous (fp: {couscous, tacchino})
- `seed_comp_pollo_patate`: pollo + patate 80g (fp: {patate, pollo}) — patate 80g passa hard constraint (vs 180g che falliva)

### Fix 2 — LLM fingerprint bypass in suggest_recipes_for_meal
- Prima: LLM generava recipe anche se il suo fingerprint era già in `excluded_fingerprints`
- Ora: dopo get_llm_suggestion, carica il recipe da DB, calcola fingerprint, se in excluded → fallback catalog
- Anche: aggiunge `[combo già usata: X + Y]` nella used_recipe_names passata all'LLM

### Fix 3 — Fingerprint tracking per ricette LLM in _generate_from_plan_rules
- Bug: `selected_recipe_obj = next((r for r in _get_all_recipes() if r.id == ...), None)` tornava None per ricette LLM (status=draft_structured, non approved)
- Fix: aggiunto fallback `db.query(CandidateRecipe).filter(...id == recipe_id).first()` in entrambe le occorrenze
- Stessa fix anche in suggest_recipes_for_meal (sessione precedente)

### Feature — LLM call log
- `_LLM_CALL_LOG: list = []` e `_LLM_CALL_LOG_MAX = 50` in planner.py a livello modulo
- Ogni chiamata LLM logga: timestamp, meal_type, target_protein_category, carb/protein_target, avoid_count, prompt, raw_response, parsed_name, status
- `GET /planner/llm-log?last=N` restituisce le ultime N chiamate (più recente prima)
- Import in api/planner.py: `from ..planner import PlannerEngine, _LLM_CALL_LOG, _LLM_CALL_LOG_MAX`

### Feature — Bulk pantry upsert
- `POST /pantry/items/bulk` in api/pantry.py
- Body: `List[PantryItemCreate]` — upsert case-insensitive per nome
- Ritorna `{"created": N, "updated": M, "total": N+M}`

### Risultato piano generato (2026-03-09)
- Proteine diverse: lenticchie, uova, ceci, salmone, fagioli, tonno, pollo, manzo — nessun ripetuto
- LLM log: 3 chiamate uova, 2 con stesso fingerprint → fingerprint check fallback a catalogo (uova_camicia)

### Docker rebuild necessario dopo ogni modifica planner.py/seed.py
- `docker-compose -f docker-compose.standalone.yml build --no-cache && docker-compose -f docker-compose.standalone.yml up -d`
- Docker env: `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini`, `LLM_API_KEY=...`

## Sessione precedente (2026-03-02) — Debug + 3 fix generazione

### Fix 1 — Profile ID mismatch (recipe quantity keys)
- `_get_qty_for_profile(quantities, profile_id, positional_fallback)` staticmethod
- Fallback chain: profile_id → "persona_a"/"persona_b"
- Updated `_filter_hard_constraints` + `_calculate_dosing` to use it

### Fix 3 — Cross-week anti-repetition
- `_load_recent_plan_recipe_ids(profile_id_A, before_date, days_back=14)` — reads past GeneratedWeeklyPlan JSON
- Both `_generate_from_plan_rules` and `generate_weekly_plan` pre-populate `used_recipe_ids` from this method

### Fix 2 — LLM enriched generation when catalog insufficient
- `_extract_user_preferences()` → `{"proteins": [...top6], "carbs": [...top4]}` from recipe catalog
- `_build_llm_prompt` now accepts `target_protein_category`, `user_preferences`, `used_recipe_names`
- `_generate_llm_recipe_suggestion` forwards these params through
- `suggest_recipes_for_meal` tracks `target_category_unmet = True` when no catalog recipe matches target protein
- LLM triggered if `not candidate_options OR target_category_unmet`; result prepended to catalog candidates
- `prompt.txt` has `{{target_protein_note}}`, `{{user_pref_note}}`, `{{avoid_note}}` placeholders

### Fix per varietà settimana (2026-03-03)
- **`QUANTITY_TOLERANCE_PERCENT = 0.40`** — portato da 0.10 a 0.40 perché seed recipes hanno 150g proteina ma PlanRules targets sono 120g (gap 25%)
- **`_filter_hard_constraints` inverted**: ora itera sugli ingredienti della RICETTA (non del piano) → ricette pure-proteina o puro-carbo passano anche quando il piano richiede entrambi
- **Seed data**: 14 piatti composti aggiunti (proteina+carbo) per ogni categoria: pollo×4, pesce×4, legumi×2, carne_rossa×2, uova×2 → totale 42 ricette
- **`_recipe_fingerprint(recipe)`** staticmethod: frozenset dei nomi di ingredienti in gruppi proteina+carbo
- **`excluded_fingerprints: set`**: nuovo parametro in `suggest_recipes_for_meal`; usato in entrambi i path di generazione per evitare display name identici anche con recipe_id diversi
- **Risultato**: piano settimanale con 7 proteine diverse, nessun pasto ripetuto, verdure variate

### Debug endpoint
- `GET /planner/debug-generate?profile_id_A=&start_date=` → full 14-slot trace (dry-run)
- `schemas.py` PlanRules fields made Optional (were failing when DB columns NULL)
- Server port: varia (usa porta libera, default 8000)

## Sessione precedente (2026-02-27) — Quality + UX (A-G)
- **A**: `_parse_text_with_llm` prompt addendum: fixed quantities repetition + rotation_rules extraction
- **B**: Monotony fix — `_get_main_protein_item(recipe_id)`, `_get_main_protein_item_from_recipe(recipe)`, `protein_item_counts`+`recent_protein_items` tracked in both generation paths; soft-filter (≥2/week) + scoring penalty (-0.3) in `suggest_recipes_for_meal`
- **C**: `_pantry_matches(rec_name, pantry_items)` staticmethod — token-overlap instead of exact name match
- **D**: `_make_display_name` fallback = `_VEG_CATALOG[hash(protein_name)%len]` — never shows generic "Verdure"
- **E**: `POST /planner/set-custom-meal` + `CustomMealBody`; approved CandidateRecipe with `tags={"manual":["true"],...}`; manual tag = +0.5 scoring boost
- **F**: `POST /planner/free-meal` + `DELETE /planner/free-meal`; free slot: `food_group="free_meal"`, `recipe_id=None`
- **G**: `GET /planner/adherence?profile_id_A=&start_date=&days=` — returns planned_slots/free_meals/in_plan_consumed/adherence_score/start_date/end_date
- **today.js**: full rewrite — adherence strip at top, free meal badge+prompt+cancel, custom meal modal, `loadAdherence()` called after all state changes; `isFree(meal)` helper

## Precedente sessione (2026-02-27) — PlanRules + Flexible Planner
- **PlanRules DB table**: `plan_rules` (id, profile_id, imported_at, carb_target, protein_target, carb_options, protein_options, frequency_targets) — all JSON columns
- **_derive_plan_rules()** in `api/_import.py`: averages grams from daily_plans, extracts options, maps rotation_rules → frequency_targets with defaults
- **/import/save** now upserts PlanRules after saving StructuredMealPlan
- **generate_weekly_plan** branches: if PlanRules found → `_generate_from_plan_rules`; else legacy StructuredMealPlan path
- **_build_protein_sequence(freq_targets, n_slots=14)**: greedy "most needed" algo, deterministic, same-day pranzo≠cena
- **_rules_to_planned_meal(rules, meal_type, target_cat)**: builds PlannedMeal from gram targets
- **suggest_recipes_for_meal** new param `target_protein_category`: soft preference
- **GET /planner/rules** returns `plan_rules` field (nullable) with full targets
- **profiles.js**: PlanRules gram targets table + enhanced frequency table

## Precedente sessione (2026-02-27) — Feature batch
- **Rolling week**: GeneratedWeeklyPlan keyed by exact start_date; `apply_recipe_to_plan` cerca per date-range; `/planner/plan-for-date` endpoint; `today.js` usa plan-for-date
- **Shopping list**: usa `recipe_id` da PlannedItem (no name-search), per-profile qty embed in notes; date picker in shopping.js
- **Regole piano**: `/planner/rules` endpoint + pannello in profiles.js (frequenze + grammi target)
- **Display names deterministici**: `_make_display_name()` in planner.py → "Proteina con Carbo (e Verdure)"
- **Vincolo proteina pranzo/cena**: `_PROTEIN_CATEGORY_MAP`, `_get_main_protein_category()`, `excluded_protein_category` param in suggest_recipes_for_meal
- **Cambia solo carbo/proteina**: `/planner/change-component`, `get_component_alternatives()`, pulsanti ↕ Carbo/Proteina in today.js
- **Week view**: planner.js → WeekView con date picker rolling; index.html usa WeekView

## Precedente sessione (2026-02-27) — MVP completato:
- Step 6: README.md aggiornato con sezione "Avvio rapido standalone" (3 comandi)
- Step 7: `/import/pdf` ora estrae testo con pdfminer e lo passa all'LLM (stessa logica di /import/text). Fallback regex se LLM non disponibile. Risolve il bug "solo 1 giorno" del parser regex.
- Step 8: import.js riscritto — inject toast, loading state, async/await, stili dedicati in style.css
Da riprendere: test end-to-end reale, fix eventuali bug post-deploy Docker.

## Contesto completo
→ Vedi `memory/context.md` per dettaglio completo (metodi, endpoint, convenzioni, next steps, setup)

## Architecture
- **Backend**: FastAPI (`planmydinner_addon/`) + SQLAlchemy SQLite
- **Frontend**: Vue3 CDN (no build step) served as static from `/ui`
- **HA integration**: `custom_components/planmydinner/` — DO NOT TOUCH

## Key Files
| File | Purpose |
|------|---------|
| `planmydinner_addon/main.py` | App entry, routers, lifespan |
| `planmydinner_addon/database.py` | SQLAlchemy models |
| `planmydinner_addon/schemas.py` | Pydantic schemas |
| `planmydinner_addon/planner.py` | PlannerEngine + get_week_start() |
| `planmydinner_addon/api/planner.py` | Planner endpoints + cache logic |
| `planmydinner_addon/api/seed.py` | POST /seed/recipes (48 Italian recipes, 14 carne_bianca) |
| `planmydinner_addon/frontend/today.js` | Vista "Oggi" (default page) |
| `planmydinner_addon/frontend/shopping.js` | Lista Spesa |

## DB Models (database.py)
- `UserProfile`, `PantryItem`, `ConsumedEntry`, `Recipe`, `CandidateRecipe`
- `StructuredMealPlan` — imported meal plan for a profile (from PDF/text)
- `GeneratedWeeklyPlan` — cached AI-generated weekly plan (profile_id_A, profile_id_B, week_start_date)

## Dual-Profile Convention
- Default profile IDs: `persona_a` / `persona_b`
- Seed recipes use these as quantity keys
- `_filter_hard_constraints` now uses `profile_A.id` / `profile_B.id` (not hardcoded)

## API Key Endpoints
- `GET /` → redirect to `/ui`
- `GET /planner/weekly-plan?profile_id_A=&profile_id_B=&start_date=` → cached plan
- `POST /planner/generate-week` → force-regenerate and save
- `POST /planner/apply-recipe-option` → update GeneratedWeeklyPlan in DB
- `GET /shopping-list/export/csv` → CSV download
- `POST /seed/recipes` → 201 {"created": N, "skipped": M}
- `POST /import/text` → parse text plan via LLM

## Docker
- `docker-compose.standalone.yml` — no HA dependency
- `DATA_DIR` env var controls DB path (`/data/database.db` in Docker)

## Nav Pages (index.html)
oggi (default) → dashboard → importa → lista spesa → dispensa → profili

## Patterns
- `get_week_start(d: date) -> date` in planner.py
- SQLAlchemy JSON column updates require full reassignment (copy.deepcopy)
- LLM calls: use `llm_gateway._client.chat.completions.create` (openai) or `llm_gateway._client.chat` (ollama)
