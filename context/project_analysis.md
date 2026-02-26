# Analisi Completa - Plan My Dinner (2026-02-26)

## STATO REALE DEL CODICE (fonte di verità: codice, non docs)

### Backend FastAPI - Route implementate

| Endpoint | Metodo | File | Stato |
|----------|--------|------|-------|
| /profiles/ | GET, POST | api/profiles.py | ✅ Implementato |
| /profiles/{id} | GET, PUT, DELETE | api/profiles.py | ✅ Implementato |
| /pantry/ | GET, POST, DELETE | api/pantry.py | ✅ Implementato |
| /consumed-entries/ | GET, POST | api/consumption.py | ✅ Implementato |
| /recipes/ | GET, POST, PUT, DELETE | api/recipes.py | ✅ Implementato |
| /import/pdf | POST | api/_import.py | ✅ Implementato |
| /import/text | POST | api/_import.py | ✅ Implementato |
| /import/save | POST | api/_import.py | ✅ Implementato |
| /planner/generate-week | POST | api/planner.py | ✅ Implementato |
| /planner/change-recipe | POST | api/planner.py | ✅ Implementato |
| /planner/apply-recipe-option | POST | api/planner.py | ✅ Implementato |
| /planner/plan | GET | api/planner.py | ✅ Implementato |
| /planner/weekly-plan | GET | api/planner.py | ✅ Implementato (cache + generate) |
| /shopping-list | GET | api/shopping_list.py | ✅ Implementato |
| /shopping-list/export/csv | GET | api/shopping_list.py | ✅ Implementato |
| /seed | POST | api/seed.py | ✅ Implementato |

### PlannerEngine - Metodi (planner.py)

| Metodo | Stato | Note |
|--------|-------|------|
| _get_user_profile() | ✅ | SQLAlchemy query |
| _get_active_meal_plan() | ✅ | Filtra per data con julianday |
| _get_consumed_entries() | ✅ | Ultimi N giorni |
| _get_pantry_items() | ✅ | Tutti |
| _get_seasonality_data() | ✅ | Dict by name |
| _get_all_recipes() | ✅ | Recipe + CandidateRecipe approved |
| _normalize_food_group() | ✅ | Singolarizza |
| _get_food_group_for_item() | ✅ | Regex keyword map |
| _filter_hard_constraints() | ✅ | 5 check: time, mood, allergie, grammage, rotazioni, anti-ripetizione |
| _calculate_dosing() | ⚠️ STUB | Ritorna ricetta senza modifiche (linea 221) |
| _score_soft_constraints() | ✅ | Pantry 40%, scadenza 30%, stagionalità 20%, ripetizione penalità |
| generate_weekly_plan() | ✅ | Loop 7 giorni × 2 pasti |
| suggest_recipes_for_meal() | ✅ | Filter → Score → Sort → Top 3 + LLM fallback |
| _generate_llm_recipe_suggestion() | ✅ | Chiama llm_gateway.generate_recipe_from_constraints() |
| apply_recipe_to_plan() | ✅ | Aggiorna GeneratedWeeklyPlan in DB |
| generate_shopping_list_for_week() | ✅ | Usa piano generato, sottrae pantry |

### Bug critici trovati

1. **QUANTITY_TOLERANCE_PERCENT = 0.50** (linea 32, planner.py)
   - Valore debug lasciato: dovrebbe essere 0.10
   - Con 50% di tolleranza quasi tutto passa i filtri grammage

2. **_calculate_dosing() è uno stub** (linea 220-221)
   - Ritorna la ricetta invariata, dosi non adattate al profilo

3. **Shopping list non esclude override free-text**
   - Doc dice di escludere ingredienti quando pasto tracciato come free-text
   - Il codice non lo fa

4. **Soft constraint scoring manca componente rotazioni**
   - Doc descrive 5 componenti (pantry, scadenza, stagionalità, ripetizione, rotazioni)
   - Implementati 4: manca il boost rotazioni soft

5. **_get_active_meal_plan: finestra 7 giorni hardcoded**
   - Cerca piani con start_date nel range di 7 giorni
   - Non gestisce piani mensili/bimestrali

### Frontend Vue.js - Componenti

| Componente | File | Stato |
|-----------|------|-------|
| App shell + nav | index.html | ✅ |
| Import wizard | import.js | ✅ Completo |
| Dashboard settimanale | dashboard.js | ✅ Struttura |
| Vista Oggi | today.js | ✅ Struttura |
| Lista spesa | shopping.js | ✅ Struttura |
| Dispensa | pantry.js | ✅ Struttura |
| Profili | profiles.js | ✅ Struttura |
| Planner | planner.js | ✅ Struttura |
| Ricette | recipes.js | ✅ Struttura |

**Mancanze UI**:
- Nessun feedback di stato job visibile (loading/error generico)
- Nessun export CSV dalla UI (endpoint esiste ma non collegato)
- Nessun "copia negli appunti" per lista spesa
- Dashboard non mostra stato "nessun piano generato" chiaramente
- Change recipe non ha UI per selezionare tra 3 opzioni

### Custom Components HA

- **__init__.py**: Setup + 8 servizi registrati ✅
- **api_client.py**: HTTP client verso add-on ✅
- **sensor.py**: Sensori esposti ✅
- **config_flow.py**: Configurazione UI ⚠️ (basico)

### Incoerenze Doc vs Codice

| Incoerenza | Gravità |
|-----------|---------|
| QUANTITY_TOLERANCE_PERCENT a 50% vs doc 10% | 🔴 Critica |
| _calculate_dosing stub (doc: adatta dosi per profilo) | 🔴 Critica |
| PDF templates: _load_parsing_templates() è placeholder | 🟡 Maggiore |
| LLM caching: doc lo descrive, non implementato | 🟡 Maggiore |
| CandidateRecipe auto-promotion (draft→approved): struttura OK, logica mancante | 🟡 Maggiore |
| Soft constraint manca rotazioni component | 🟡 Maggiore |
| Shopping list non esclude free-text override | 🟡 Maggiore |

### Completamento per area

| Area | % |
|------|---|
| DB/ORM | 100% |
| API scaffolding | 95% |
| Hard constraints | 85% (dosing stub) |
| Soft constraints | 75% (manca rotazioni) |
| LLM Gateway | 70% (manca generate_recipe_from_constraints?) |
| PDF Parser | 50% (template loading è placeholder) |
| Frontend struttura | 70% |
| Frontend UX (feedback, export) | 40% |
| HA Integration | 80% |
| Test | 10% |
