# Plan My Dinner - Memoria di Progetto

## Stato analisi
- Analisi completa del repo eseguita il 2026-02-26
- File dettagliato: `project_analysis.md`
- Prossimo step: MVP Standalone (vedere `mvp_plan.md`)

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
