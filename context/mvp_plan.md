# Piano MVP Standalone - Plan My Dinner

## Architettura "Standalone-first" MINIMA

### Cosa tenere (già funziona)
- FastAPI backend + SQLite → già standalone, già deployabile con `uvicorn`
- PlannerEngine → già usabile, solo bug da fixare
- LLMGateway → già astratto su OpenAI/Ollama
- Vue.js frontend → già servito da FastAPI come static files
- Tutti i CRUD endpoint
- Import wizard UI (import.js)

### Cosa modificare
- QUANTITY_TOLERANCE_PERCENT: 0.50 → 0.10
- _calculate_dosing(): implementare logica reale (o rimuovere per MVP)
- Shopping list: aggiungere esclusione free-text override
- Frontend: aggiungere feedback stati job, export CSV, copia appunti
- main.py: aggiungere CORS corretto per standalone

### Cosa eliminare per MVP
- Nessuna dipendenza HA per il flusso principale (già così)
- Template PDF avanzati (troppo complessi, usare LLM text import)

### Cosa non fare (fuori MVP)
- Multi-user
- Auto-promotion CandidateRecipe
- LLM caching
- Lovelace cards avanzate

---

## Piano MVP Standalone - 8 Step

### Step 1: Fix bug critici backend
**Obiettivo**: Backend stabile e corretto
**Azioni**:
- Fix QUANTITY_TOLERANCE_PERCENT → 0.10 in planner.py:32
- Implementare _calculate_dosing() (anche semplice: somma qty A + B)
- Aggiungere esclusione free-text override in generate_shopping_list_for_week()
- Aggiungere rotazioni soft nella _score_soft_constraints()
**Criteri di verifica**: POST /planner/generate-week restituisce piano con ricette filtrate correttamente

### Step 2: Verifica flusso end-to-end senza UI
**Obiettivo**: Flusso completo funzionante via curl/API
**Azioni**:
- Creare profilo → importare piano → generare settimana → ottenere shopping list
- Documentare qualsiasi 500 error
- Aggiungere seed con dati di test realistici (api/seed.py)
**Criteri di verifica**: curl sequence completa senza errori, piano con 7 giorni × 2 pasti

### Step 3: Fix Frontend - Feedback stati
**Obiettivo**: Nessuna pagina morta o dead-end
**Azioni**:
- Aggiungere loading spinner su tutte le chiamate API
- Mostrare errore leggibile (non solo console.error)
- Dashboard: mostrare messaggio chiaro se nessun piano generato
- Today view: CTA "Genera piano" se non esiste piano per oggi
**Criteri di verifica**: Ogni schermata ha uno stato empty, loading e error visibili

### Step 4: Frontend - Lista Spesa funzionale
**Obiettivo**: Lista spesa completa e esportabile
**Azioni**:
- Collegare bottone "Esporta CSV" all'endpoint /shopping-list/export/csv
- Aggiungere "Copia negli appunti" per lista spesa
- Shopping list: mostrare categorie collassabili
- Checkbox per spuntare items
**Criteri di verifica**: Utente può generare lista, copiarla o scaricarla in 2 click

### Step 5: Frontend - Change Recipe UI
**Obiettivo**: Flusso "cambia ricetta" utilizzabile
**Azioni**:
- Dashboard: pulsante "Cambia" su ogni ricetta del piano
- Modale/pannello con 3 alternative (da /planner/change-recipe)
- Conferma selezione → chiama /planner/apply-recipe-option
- Aggiornamento piano senza reload completo
**Criteri di verifica**: Utente può cambiare una ricetta in 3 click

### Step 6: Docker standalone verifica
**Obiettivo**: Deployabile con docker-compose
**Azioni**:
- Verificare docker-compose.standalone.yml funzionante
- Aggiungere .env.example con variabili LLM
- Verificare volume persistente per SQLite
- Documentare come avviare standalone (README sezione)
**Criteri di verifica**: `docker-compose -f docker-compose.standalone.yml up` e app funziona

### Step 7: PDF Import fix
**Obiettivo**: Import PDF funzionante (almeno per testi semplici)
**Azioni**:
- Testare PDFParser con PDF reale
- Se template loading fallisce, usare LLM text extraction come fallback
- Import wizard: mostrare preview chiaro prima di salvare
- Gestire errori PDF gracefully (mostrare tasto "prova come testo")
**Criteri di verifica**: Upload PDF → preview piano → salva → piano disponibile

### Step 8: Test & Polish UI
**Obiettivo**: App pronta per uso quotidiano reale
**Azioni**:
- Navigazione: verifica 2-click su ogni azione principale
- Mobile-friendly (viewport, touch targets)
- Aggiungere toast notifications per successo/errore
- Rimuovere pagine incomplete o nasconderle
**Criteri di verifica**: Flusso completo (import → settimana → spesa) da mobile in < 5 minuti

---

## Piano HA come Plus - 4 Step (dopo MVP)

### HA Step 1: Verificare adapter esistente
- Testare custom_components/planmydinner con HA reale
- Verificare config_flow funzionante (URL add-on)
- Verificare che tutti i servizi chiamino le API corrette

### HA Step 2: Sensori essenziali
- sensor.planmydinner_today: ricetta di oggi (pranzo + cena)
- sensor.planmydinner_shopping: conteggio items spesa
- Usare questi in automation HA (es. "annuncia ricetta di stasera")

### HA Step 3: Lovelace card minimale
- Card "Oggi" che mostra pranzo/cena (legge dal sensore)
- Bottone "Cambia ricetta" → chiama servizio HA
- Non duplicare tutta la GUI

### HA Step 4: HACS packaging
- Aggiornare hacs.json
- Documentazione installazione
- Test con HACS

---

## 8 Issue GitHub Prioritarie

### Issue #1: [BUG] QUANTITY_TOLERANCE_PERCENT al 50% blocca il filtro grammage
**Priorità**: P0 - Critica
**Labels**: bug, planner
**Descrizione**: `QUANTITY_TOLERANCE_PERCENT = 0.50` in `planner.py:32` è stato aumentato per debug e mai ripristinato. Con 50% di tolleranza il filtro grammage è inutile: quasi ogni ricetta passa il filtro indipendentemente dalle quantità del piano alimentare.
**Acceptance criteria**:
- QUANTITY_TOLERANCE_PERCENT = 0.10 (10%, valore da spec)
- Aggiungere test che verifichi che una ricetta fuori range venga scartata

### Issue #2: [BUG] _calculate_dosing() è uno stub che non fa nulla
**Priorità**: P0 - Critica
**Labels**: bug, planner
**Descrizione**: `PlannerEngine._calculate_dosing()` (planner.py:220-221) ritorna la ricetta invariata. Le dosi non vengono mai adattate per i profili A e B (es. somma delle porzioni). Il piano generato mostra sempre le quantità per profilo singolo.
**Acceptance criteria**:
- Per MVP: sommare le quantità di profilo_A + profilo_B per ogni ingrediente
- Nessuna ricetta con qty=0 per entrambi i profili

### Issue #3: [FEAT] Frontend: stati loading/error espliciti su tutte le schermate
**Priorità**: P1 - Alta
**Labels**: frontend, ux
**Descrizione**: Le schermate Vue.js (dashboard, shopping, today) non mostrano stati intermedi. Una chiamata API lenta o fallita lascia la pagina vuota senza feedback.
**Acceptance criteria**:
- Spinner/scheletro durante caricamento
- Messaggio errore leggibile (con testo dell'errore API)
- Stato "vuoto" con CTA (es. "Nessun piano - Genera ora")

### Issue #4: [FEAT] Lista spesa: export CSV e copia appunti dalla UI
**Priorità**: P1 - Alta
**Labels**: frontend, feature
**Descrizione**: L'endpoint `/shopping-list/export/csv` esiste ma non è collegato alla UI. Il componente `shopping.js` non ha bottoni di export.
**Acceptance criteria**:
- Bottone "Scarica CSV" → download diretto
- Bottone "Copia appunti" → testo formattato negli appunti
- Funziona su mobile

### Issue #5: [FEAT] Change Recipe: UI per selezionare tra 3 alternative
**Priorità**: P1 - Alta
**Labels**: frontend, feature
**Descrizione**: L'endpoint `/planner/change-recipe` ritorna 3 opzioni ma non c'è UI per mostrarle e selezionarne una. Il bottone "Cambia" sulla dashboard non esiste.
**Acceptance criteria**:
- Ogni ricetta nel piano ha bottone/icona "Cambia"
- Pannello/modale mostra 3 alternative con nome, tempo, ingredienti chiave
- Selezione → chiama /planner/apply-recipe-option → piano aggiornato

### Issue #6: [BUG] Shopping list non esclude ingredienti da override free-text
**Priorità**: P2 - Media
**Labels**: bug, planner
**Descrizione**: Quando un pasto è tracciato via override free-text (es. "pizza al ristorante"), `generate_shopping_list_for_week()` non esclude quel pasto dalla lista spesa. Risultato: si comprano ingredienti per pasti già mangiati fuori.
**Acceptance criteria**:
- Pasti con ConsumedEntry.type="override" e free_text_name non contribuiscono alla shopping list
- Test con override tracciato per un giorno della settimana

### Issue #7: [FEAT] Seed dati realistici per testing
**Priorità**: P2 - Media
**Labels**: devex, testing
**Descrizione**: Il seeder esistente (api/seed.py) non è documentato e probabilmente non crea dati sufficienti per testare il flusso completo (profili → piano alimentare → ricette → generazione settimana).
**Acceptance criteria**:
- `POST /seed` crea: 2 profili, 1 piano alimentare per 4 settimane, 10+ ricette realistiche
- Dopo il seed: GET /planner/weekly-plan restituisce piano completo
- Documentato in README come "Quick start"

### Issue #8: [INFRA] docker-compose.standalone.yml verificato e documentato
**Priorità**: P2 - Media
**Labels**: infra, docs
**Descrizione**: Esiste `docker-compose.standalone.yml` ma non è testato né documentato. Non c'è .env.example con le variabili necessarie per LLM.
**Acceptance criteria**:
- `docker-compose -f docker-compose.standalone.yml up` porta l'app funzionante su localhost:8123
- .env.example con OPENAI_API_KEY, OLLAMA_BASE_URL, ecc.
- README: sezione "Avvio rapido standalone" con 3 comandi
