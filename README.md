# Plan My Dinner

Pianificatore di pasti settimanali con IA, pensato per chi segue il piano alimentare
di un nutrizionista: genera la settimana rispettando grammature e frequenze, calcola
kcal e macro di ogni pasto, tiene il diario di quello che mangi davvero e la
dispensa, e prepara la lista della spesa.
Funziona **standalone** (solo Docker) o come **Add-on + Integrazione per Home
Assistant**, e può ricevere gli obiettivi calorici da un'app di allenamento
([OpenFit](https://github.com/rikyru/mywahoo)).

## Funzionalità

### Piano
- **Importa il PDF del nutrizionista** — grammature, opzioni di carboidrati e
  proteine, frequenze settimanali, verdure libere.
- **Genera la settimana** — algoritmo con rotazione, limiti per categoria
  proteica, stagionalità, dispensa, storico; oppure **con AI** (per slot o
  settimana intera, OpenAI o Ollama). Modalità **"Dal mio storico"**: pesca dalle
  ricette che mangi davvero, seguendo le frequenze della nutrizionista.
- **Settimana** — frequenze del piano a colpo d'occhio, **drag & drop** dei pasti
  tra slot, cambio di carboidrato/proteina/verdura, "Cambia ricetta", **nuove
  idee AI** su più pasti selezionati, periodi di **vacanza**, scelta degli slot da
  generare.
- **Oggi** — pasti del giorno con navigazione tra i giorni, segna consumato /
  non mangiato / pasto libero, "segna tutta la giornata", striscia
  dell'**obiettivo energetico** del giorno.

### Nutrizione
- **kcal e macro** per ingrediente, ricetta e pasto: tabella di composizione
  locale, con fallback **stima LLM** in cache (anche con i modelli gpt-5.x).
- **Quote per pasto** coerenti con la giornata, con suggerimenti e indicazione di
  quale ingrediente fa sforare; **olio di cottura** stimato su pranzo e cena.
- **Bilanciamento ricette** — proteine rispetto al target, "Applica adattamento".
- **Scaling delle porzioni** verso un target kcal (taglia i carboidrati, tiene le
  proteine; in deficit le porzioni possono solo ridursi), anche **per giorno**
  (periodizzazione: più kcal nei giorni di allenamento).

### Diario
- **Routine** — colazione, spuntini e merende fissi, contati ogni giorno; si
  saltano o si registrano per giorno; **suggerimenti AI** anche **dalla dispensa**.
- **Merende extra** fuori dagli slot fissi.
- **Pasto da foto** (mensa) con modello vision, **pasto da descrizione** testuale,
  catalogo mensa riusabile.
- **Storico** — kcal e macro per giorno, medie **"a oggi"** calcolate sui soli
  pasti **mangiati davvero**, indicatore "X/Y pasti registrati".

### Spesa e dispensa
- **Lista della spesa** dai soli giorni generati, raggruppata **per reparto**,
  spunte persistenti per settimana, export CSV; aggiunge le **scorte sotto soglia**.
- **Dispensa** con **barcode** (Open Food Facts) e scansioni multiple, scadenze,
  soglia minima, **ricette anti-spreco** con quello che sta per scadere.

### Ricette
- Catalogo con **ricerca e filtri** (nome, ingrediente, tempo, difficoltà),
  **preferiti 👍 / 👎** ("non proporre più", usato dal planner), **import da URL**
  (schema JSON-LD + LLM), bulk import JSON, **Cook mode** passo-passo a schermo intero.

### Altro
- **Profili** (fino a due) con grammature e vincoli distinti.
- **PWA** installabile, versione dell'app nelle Impostazioni con avviso di aggiornamento.
- **API per integrazioni** (`/integration/*`): riepilogo per app esterne e
  ricezione degli obiettivi calorici.
- **Debug LLM**: trace di generazione e log delle chiamate all'IA.

---

## Architettura

```
planmydinner_addon/     ← Backend FastAPI + frontend Vue 3 (standalone o HA Add-on)
custom_components/      ← HA Custom Integration (sensori + servizi)
```

Il backend funziona in modo completamente autonomo. L'integrazione HA è un adapter
opzionale che espone sensori e servizi. La card Lovelace sta in un
[repo separato](https://github.com/rikyru/planmydinner-card).

---

## Avvio rapido — Standalone (Docker)

```bash
git clone https://github.com/rikyru/planmydinner.git
cd planmydinner
cp .env.example .env            # scegli ollama o openai e compila i valori
docker-compose -f docker-compose.standalone.yml up -d
open http://localhost:8000      # la UI è su /ui/
```

I dati sono persistiti nel volume Docker `planmydinner_data` (`/data`).

**Aggiornamento**: `git pull`, poi ricostruisci **e ricrea** il container
(`docker compose up -d --build --force-recreate <servizio>`): senza
`--force-recreate` compose può lasciare in esecuzione il container vecchio.

### Primo avvio — dati di esempio

```bash
curl -X POST http://localhost:8000/seed
```

Crea 2 profili (persona_a / persona_b), 28 ricette italiane e un piano di test.
Poi vai su **Settimana → Genera piano**.

### Sviluppo locale (senza Docker)

```bash
pip install -r planmydinner_addon/requirements.txt
uvicorn planmydinner_addon.main:app --reload
python -m pytest planmydinner_addon/tests     # i test PDF richiedono Java (tabula)
```

---

## Configurazione

| Variabile | Descrizione | Esempio |
|-----------|-------------|---------|
| `LLM_PROVIDER` | Provider LLM | `ollama` o `openai` |
| `LLM_MODEL` | Modello | `llama3`, `gpt-4o-mini`, `gpt-5.5` |
| `LLM_BASE_URL` | URL Ollama (solo provider=ollama) | `http://host.docker.internal:11434` |
| `LLM_API_KEY` | API key (solo provider=openai) | `sk-...` |
| `API_KEY` | Se impostata, l'API richiede `X-API-Key` (vedi sotto) | |
| `CORS_ORIGINS` | Origini ammesse per chiamate dal browser | `https://...` |
| `DATA_DIR` / `DATABASE_URL` | Cartella dati (DB, cache LLM) / URL del database | `/data` |

Provider, modello, temperatura e **modello vision** (per le foto dei pasti) si
possono anche cambiare dalle **Impostazioni** della UI.

### Ollama (locale, gratuito)

```bash
ollama pull llama3
# .env
LLM_PROVIDER=ollama
LLM_MODEL=llama3
LLM_BASE_URL=http://host.docker.internal:11434
```

### OpenAI

```bash
# .env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
```

> I modelli che accettano solo la temperatura di default (es. gpt-5.x) sono
> gestiti in automatico: la richiesta viene ripetuta senza `temperature`.

> Il sistema funziona anche **senza LLM**: usa l'algoritmo sul catalogo ricette.
> L'LLM serve per import PDF/URL, generazione AI, stima nutrizionale degli
> alimenti fuori tabella, foto e descrizioni dei pasti, suggerimenti.

---

## Home Assistant — Add-on

Per HA OS o HA Supervised:

1. **Impostazioni → Add-on Store** → menu tre puntini → **Repositories** → aggiungi
   `https://github.com/rikyru/planmydinner`
2. Installa "Plan My Dinner", imposta le variabili LLM nella tab **Configurazione**, avvia.

La Web UI è accessibile tramite **HA Ingress** o su `http://<ha-ip>:8000`.

### HA Core / Docker puro

HA Core non supporta gli Add-on: la UI non appare in sidebar. Usa il container
standalone (`http://<ip>:8000/ui/`); l'integrazione HACS funziona comunque.

```bash
docker build -t planmydinner-addon ./planmydinner_addon
docker run -d -p 8000:8000 -v /path/to/data:/data \
  -e LLM_PROVIDER=ollama -e LLM_BASE_URL=http://host.docker.internal:11434 \
  -e LLM_MODEL=llama3 --name planmydinner planmydinner-addon
```

---

## Home Assistant — Integrazione Custom (HACS)

1. HACS → **Integrazioni** → **Repository personalizzati** → aggiungi
   `https://github.com/rikyru/planmydinner` come **Integration**, installa e riavvia.
   (Oppure copia `custom_components/planmydinner/` nella configurazione di HA.)
2. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Plan My Dinner**,
   host e porta del backend.

| Sensore | Descrizione |
|---------|-------------|
| `sensor.plan_my_dinner_today` | Pasti del giorno (pranzo/cena) |
| `sensor.plan_my_dinner_week` | Piano settimanale riepilogativo |
| `sensor.plan_my_dinner_shopping` | Prodotti nella lista spesa |
| `sensor.plan_my_dinner_pantry` | Articoli in dispensa |
| `sensor.plan_my_dinner_pasti_da_registrare` | Pasti di oggi non ancora registrati |
| `sensor.plan_my_dinner_web_ui` | URL della Web UI |

| Servizio | Descrizione |
|---------|-------------|
| `planmydinner.generate_week` | Genera piano settimanale (algoritmo) |
| `planmydinner.generate_week_ai` | Genera piano con AI |
| `planmydinner.mark_consumed` | Segna un pasto come consumato |
| `planmydinner.add_pantry_item` / `remove_pantry_item` | Gestione dispensa |

### Promemoria "segna il pasto"

```yaml
automation:
  - alias: "Promemoria segna pasto"
    trigger:
      - { platform: time, at: "13:45:00" }
      - { platform: time, at: "20:45:00" }
    condition:
      - condition: template
        value_template: >
          {% set meal = 'pranzo' if now().hour < 15 else 'cena' %}
          {{ meal in state_attr('sensor.plan_my_dinner_pasti_da_registrare', 'unlogged') | default([]) }}
    action:
      - service: notify.mobile_app_TUO_TELEFONO
        data:
          title: "🍽️ Plan My Dinner"
          message: "Hai registrato il pasto? Tocca per farlo ora."
          data: { url: "https://dinner.esempio.it/ui/" }
```

---

## Lovelace Card

[github.com/rikyru/planmydinner-card](https://github.com/rikyru/planmydinner-card) —
pranzo e cena di oggi, strip settimanale, spesa e dispensa, pulsanti per generare il
piano e aprire la UI. Installazione via HACS (**Frontend → Custom repositories**,
tipo Lovelace) o manuale (`config/www/` + risorsa JavaScript Module).

```yaml
type: custom:planmydinner-card
title: "Piano Pasti"      # opzionale
show_week: true
show_shopping: true
show_actions: true
compact: false
```

---

## Profili

Fino a **due profili** (A e B) con grammature distinte per ingrediente: il piano è
generato per entrambi insieme, ogni ricetta mostra le dosi di ciascuno, e i vincoli
(es. "carne rossa max 1 volta/sett") sono indipendenti per profilo.

---

## Valori nutrizionali

Ogni ingrediente è valutato **per 100 g** (peso a crudo/secco per pasta, cereali e
legumi; peso cotto riconosciuto dal nome), in quest'ordine:

1. valori salvati sull'ingrediente (`source: manual`)
2. tabella di composizione locale (alimenti comuni italiani, `source: table`)
3. stima LLM con cache permanente su disco (`source: llm`)

Le risposte riportano `coverage` (quota di ingredienti risolti) e `sources`. Su
pranzo e cena si aggiunge una stima dell'olio di cottura. Se un alimento resta a
0 kcal, controlla i log: `docker logs <container> | grep "Error during LLM"`.

---

## API per integrazioni esterne

Superficie ufficiale per app esterne (es. una dashboard fitness).

### `GET /integration/summary`

```
GET /integration/summary?profile_id=aa&start_date=2026-07-06&end_date=2026-07-12
```

Payload versionato (`"version": 1`), sempre **200** (campi a 0/`null` senza dati):

- `adherence` — aderenza del periodo (pianificati, consumati, liberi, saltati)
- `days[]` — per giorno: pasti pianificati e registrati (`main_consumed`),
  `nutrition` (kcal + macro, `coverage`), `routine_kcal`, `extra_kcal`,
  `target_kcal` (periodizzato), `training_note`, `complete`, `future`
- `averages` — medie **"a oggi"**: solo giorni completi fino a oggi
- `targets` — obiettivi kcal/macro correnti

Parametri: `consumed_only=true` conta solo i pasti **registrati come mangiati**
(un pasto pianificato e non registrato non conta); `meal_detail=true` aggiunge il
dettaglio per pasto. Senza date usa la settimana corrente.

### `POST /integration/apply-targets?profile_id=…`

Riceve gli obiettivi da un'app esterna e riscala subito le porzioni del piano corrente:

```json
{"kcal": 1755, "protein_g": 119, "carbs_g": 201, "fat_g": 53,
 "allow_upscale": false,
 "daily": {"2026-10-23": {"kcal": 1995, "training_note": "Corpo libero 40′"}}}
```

`allow_upscale: false` (deficit) = le porzioni possono solo ridursi; `daily` =
target per singola data (periodizzazione, anche retroattiva per lo storico).

Altri endpoint: `GET /integration/plan-targets`, `GET /integration/today-status`
(pasti di oggi da registrare), `GET /integration/unlogged-meals`.

### Auth opzionale (`API_KEY`)

Di default l'API è aperta (LAN / rete Docker). Con `API_KEY` impostata ogni chiamata
richiede l'header `X-API-Key` (o `?api_key=`); la UI salva la chiave aprendo una
volta `/ui/?api_key=...`. Senza `API_KEY` non cambia nulla.

---

## Flusso d'uso tipico

1. **Importa** il PDF del nutrizionista: rivedi grammature, opzioni e frequenze, salva.
2. **Settimana → Genera piano** (algoritmo, AI o "Dal mio storico"), poi aggiusta con
   drag & drop, cambi di componente o nuove idee AI.
3. **Oggi**: segna i pasti (consumato, non mangiato, pasto libero, foto, descrizione),
   la routine e le merende extra.
4. **Spesa**: lista dai giorni generati, per reparto, con le scorte sotto soglia.
5. **Storico**: com'è andata davvero, sui pasti mangiati.

---

## Aggiungere ricette

- **Manuale** — **Ricette → + Aggiungi** (le ricette personali ricevono un boost nel planner).
- **Da URL** — **Ricette → Importa da URL** (pagine con schema ricetta JSON-LD, altrimenti LLM).
- **Bulk import (JSON)** — **Ricette → Bulk Import**:

```json
[
  {
    "name": "Pasta al tonno",
    "total_time_minutes": 20,
    "difficulty": "facile",
    "ingredients": [
      { "name": "Pasta di semola", "food_group": "carboidrati", "grams": 80 },
      { "name": "Tonno sott'olio", "food_group": "pesce", "grams": 70 },
      { "name": "Pomodorini", "food_group": "verdure", "grams": 100 }
    ],
    "mood": "veloce",
    "cooking_method": "tegame"
  }
]
```

Food group validi: `carboidrati`, `carne_bianca`, `carne_rossa`, `pesce`, `legumi`,
`latticini`, `proteina`, `verdure`, `grassi`.

---

## Struttura del progetto

```
planmydinner/
├── planmydinner_addon/
│   ├── main.py               # Entry point FastAPI, auth opzionale, client LLM
│   ├── planner.py            # PlannerEngine (generazione, rotazione, spesa)
│   ├── nutrition.py          # Valori nutrizionali (tabella, LLM, olio di cottura)
│   ├── scaling.py            # Porzioni verso il target kcal (anche per giorno)
│   ├── llm_gateway.py        # Astrazione LLM (OpenAI / Ollama) + cache
│   ├── barcode.py            # Open Food Facts
│   ├── pdf_parser.py         # Parsing PDF del nutrizionista
│   ├── database.py · schemas.py
│   ├── api/
│   │   ├── planner.py        # Generazione, settimana, aderenza, vacanze
│   │   ├── consumption.py    # Diario pasti, foto/descrizione, mensa
│   │   ├── routine.py        # Colazione/spuntini/merende fissi e merende extra
│   │   ├── integration.py    # API per app esterne (summary, apply-targets)
│   │   ├── recipes.py        # Ricette, import URL, preferiti, bilanciamento
│   │   ├── pantry.py         # Dispensa, barcode, scadenze, scorte
│   │   ├── shopping_list.py  # Spesa, spunte, CSV
│   │   ├── _import.py        # Import PDF/testo
│   │   ├── profiles.py · settings.py · seed.py
│   ├── frontend/             # Vue 3 (Oggi, Settimana, Spesa, Ricette, Storico,
│   │                         #  Dispensa, Importa, Profili, Impostazioni), PWA
│   └── tests/                # pytest
├── custom_components/planmydinner/   # HA Custom Integration
├── docker-compose.standalone.yml
├── docker-compose.yml                 # Con HA + Ollama
└── .env.example
```

---

## Requisiti

- Docker (standalone o HA addon) · Python 3.11+ per lo sviluppo
- Home Assistant 2024.1+ (solo per l'integrazione HA)
- LLM: Ollama locale o account OpenAI (opzionale ma consigliato)
- Java solo per i test del parser PDF

---

## Licenza

MIT
