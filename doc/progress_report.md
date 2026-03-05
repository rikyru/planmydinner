# Stato Avanzamento Lavori — Plan My Dinner

Ultimo aggiornamento: **Marzo 2026**

---

## Panoramica

Il progetto è passato dalla fase MVP iniziale a un prodotto standalone completo e funzionale. L'approccio **standalone-first** è stato confermato: il backend FastAPI funziona in autonomia, la GUI Vue 3 è servita direttamente da FastAPI, e Home Assistant è trattato come adapter/plus (non prerequisito).

---

## Funzionalità implementate (stato attuale)

### Core Backend

| Feature | Stato | Note |
|---|---|---|
| FastAPI + SQLAlchemy + SQLite | ✅ | Stabile, 9 router montati |
| Docker standalone | ✅ | `Dockerfile` + `run.sh` + `.env.example` |
| LLM Gateway (OpenAI / Ollama) | ✅ | Astratto, configurabile da UI |
| LLM Caching (memoria + disco) | ✅ | `llm_cache.json` in `DATA_DIR` |
| Import PDF via pdfminer + LLM | ✅ | Prompt deterministico, fallback regex |
| Import testo libero via LLM | ✅ | Stessa pipeline di import PDF |
| Import debug endpoint | ✅ | `POST /import/pdf-debug` per diagnostica |

### Profili e Vincoli

| Feature | Stato | Note |
|---|---|---|
| CRUD profili utente | ✅ | Allergie, esclusioni, preferenze |
| Import PlanRules da PDF | ✅ | `carb_target`, `protein_target`, `frequency_targets`, `meal_slots` |
| Edit vincoli manuale (UI) | ✅ | Form in schermata Profili |
| `PUT /planner/rules/{profile_id}` | ✅ | Aggiornamento granulare dei vincoli |

### Planner Engine

| Feature | Stato | Note |
|---|---|---|
| Generazione piano 7 giorni | ✅ | Path PlanRules + path legacy StructuredMealPlan |
| Hard constraints (allergie, tempi, mood) | ✅ | Filtro esplicito |
| Soft scoring (pantry, stagionalità, rotazione) | ✅ | +random jitter per varietà |
| Sequenza proteica `_build_protein_sequence` | ✅ | Greedy deficit-first |
| Rotazione proteica settimanale | ✅ | `protein_cat_counts`, `protein_cat_limits` |
| `used_recipe_ids` (no ripetizioni) | ✅ | Hard-exclude per tutta la settimana |
| Boost ricette manuali (+1.5) | ✅ | Ricette aggiunte dall'utente preferite |
| Boost CandidateRecipe approvate (+1.0) | ✅ | Ricette già mangiate e apprezzate |
| LLM fallback (slot vuoti) | ✅ | Genera `CandidateRecipe` se pool esaurito |
| Auto-promozione CandidateRecipe | ✅ | Dopo 2 usi → `status=approved` |
| Pasto personalizzato (custom meal) | ✅ | Con campo `veg_grams` configurabile |
| Pasto libero (free meal) | ✅ | Titolo + note, nessuna ricetta |

### Ricette

| Feature | Stato | Note |
|---|---|---|
| CRUD ricette | ✅ | Con validazione schema |
| Ricette seed (28) | ✅ | Variate: pollo, pesce, carne rossa, legumi, cereali |
| Bulk import JSON | ✅ | `POST /recipes/bulk` con normalizzazione difficulty EN→IT |
| Elimina tutte le ricette | ✅ | `DELETE /recipes/all` |
| Auto-tag `manual=["true"]` | ✅ | Tutte le ricette create/importate dall'utente |
| Robustezza ricette invalide | ✅ | `GET /recipes/` e `_get_all_recipes()` skippano errori |

### Lista Spesa e Dispensa

| Feature | Stato | Note |
|---|---|---|
| Lista spesa aggregata | ✅ | Da piano settimanale generato |
| Export CSV | ✅ | Download diretto dal frontend |
| CRUD dispensa (pantry) | ✅ | Con date di scadenza |

### Frontend (Vue 3 ESM, no build)

| Schermata | Stato | Note |
|---|---|---|
| Oggi | ✅ | Pranzo/cena, change recipe, segna mangiato, pasto custom/libero |
| Settimana | ✅ | Grid 7 giorni, datepicker, rigenera, change recipe |
| Importa | ✅ | Upload PDF + testo, review interattiva, salva |
| Lista Spesa | ✅ | Aggregata, export CSV |
| Dispensa | ✅ | CRUD ingredienti |
| Profili | ✅ | CRUD profili + edit vincoli piano |
| Ricette | ✅ | Catalogo, add/edit, bulk import, elimina tutte |
| Impostazioni | ✅ | LLM config, regole custom, **gestione cache LLM** |

### Impostazioni LLM

| Feature | Stato | Note |
|---|---|---|
| Configurazione provider/modello/chiave | ✅ | Persistita in DB, reinizializzazione live |
| Regole custom (iniettate nei prompt) | ✅ | Una per riga, stile culinario, preferenze |
| Cache statistiche + clear | ✅ | `GET/DELETE /settings/llm-cache` + UI |

---

## Cosa rimane da fare

### Home Assistant Integration
- [ ] Sensori essenziali (`mealplan_today`, `shopping_count`)
- [ ] Lovelace card minimale (today view)
- [ ] HACS packaging (`manifest.json`, `hacs.json`)
- [ ] Test integrazione con HA reale

### Qualità e Manutenzione
- [ ] Test coverage (~10% attuale, target ~40%)
- [ ] Rivedere e limare il flusso import PDF (parsing edge cases)
- [ ] Documentazione API (FastAPI Swagger già disponibile a `/docs`)

---

## Architettura attuale (semplificata)

```
Browser → GET /ui → StaticFiles (Vue 3 ESM)
Browser → REST API → FastAPI routers
FastAPI → SQLite (via SQLAlchemy)
FastAPI → LLMGateway → OpenAI / Ollama
LLMGateway → llm_cache.json (cache disco)
FastAPI → PDFParser (pdfminer + LLM)
```

### File chiave
| File | Descrizione |
|---|---|
| `planmydinner_addon/main.py` | Entry point FastAPI, lifespan, router mount |
| `planmydinner_addon/planner.py` | PlannerEngine (~1800 righe) |
| `planmydinner_addon/llm_gateway.py` | LLM abstraction + caching |
| `planmydinner_addon/pdf_parser.py` | Parser PDF regex + LLM |
| `planmydinner_addon/api/_import.py` | Import PDF/testo, save plan, derive rules |
| `planmydinner_addon/api/planner.py` | Endpoints planner (generate, change, custom) |
| `planmydinner_addon/api/recipes.py` | CRUD ricette + bulk import |
| `planmydinner_addon/api/settings.py` | LLM config + cache management |
| `planmydinner_addon/frontend/` | Vue 3 ESM, 8 componenti |
