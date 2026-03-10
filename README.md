# Plan My Dinner

Pianificatore di pasti settimanali con IA, pensato per chi segue un piano alimentare di un nutrizionista.
Funziona **standalone** (solo Docker, nessun Home Assistant necessario) o come **Add-on + Integrazione per Home Assistant**.

## Funzionalità

- **Importa il PDF del nutrizionista** — estrae grammature, opzioni di carboidrati e proteine, frequenze settimanali
- **Genera il piano settimanale** — algoritmo con regole di rotazione, limiti per categoria proteica, stagionalità
- **Genera con AI** — modalità "per slot" o "settimana completa" via LLM (OpenAI o Ollama)
- **Vista Oggi** — pranzo e cena del giorno, pulsante "Cambia ricetta", segna come consumato
- **Catalogo ricette** — aggiunta manuale o bulk import JSON, badge "Personale" con boost di priorità
- **Lista della spesa** — generata dal piano settimanale, esportabile in CSV
- **Dispensa** — gestione ingredienti in casa, integrata nel calcolo della spesa
- **Profili** — supporto a due profili (A e B) con grammature distinte, vincoli editabili dalla UI
- **Cache LLM** — risparmia chiamate API riusando risposte identiche

---

## Architettura

```
planmydinner_addon/     ← Backend FastAPI + Vue 3 (standalone o HA Add-on)
custom_components/      ← HA Custom Integration (sensori + servizi)
www/                    ← Lovelace custom card (planmydinner-card.js)
```

Il backend funziona in modo completamente autonomo. L'integrazione HA è un adapter opzionale che espone sensori e servizi.

---

## Avvio rapido — Standalone (Docker)

```bash
# 1. Clona il repo
git clone https://github.com/rikyru/planmydinner.git
cd planmydinner

# 2. Configura il provider LLM
cp .env.example .env
# Modifica .env: scegli ollama o openai e inserisci i tuoi valori

# 3. Avvia
docker-compose -f docker-compose.standalone.yml up -d

# 4. Apri il browser
open http://localhost:8000
```

I dati sono persistiti nel volume Docker `planmydinner_data`.

### Primo avvio — carica dati di esempio

```bash
curl -X POST http://localhost:8000/seed
```

Crea 2 profili (persona_a / persona_b), 28 ricette italiane e un piano di test.
Poi vai su **Settimana → Genera piano** per vedere il pianificatore in azione.

### Sviluppo locale (senza Docker)

```bash
pip install -r planmydinner_addon/requirements.txt
uvicorn planmydinner_addon.main:app --reload
# App disponibile su http://localhost:8000
```

---

## Configurazione LLM

Copia `.env.example` in `.env` e compila:

| Variabile | Descrizione | Esempio |
|-----------|-------------|---------|
| `LLM_PROVIDER` | Provider LLM | `ollama` o `openai` |
| `LLM_MODEL` | Modello da usare | `llama3`, `gpt-4o-mini` |
| `LLM_BASE_URL` | URL Ollama (solo se provider=ollama) | `http://host.docker.internal:11434` |
| `LLM_API_KEY` | API key (solo se provider=openai) | `sk-...` |

### Ollama (locale, gratuito)

```bash
# Installa Ollama: https://ollama.ai
ollama pull llama3

# Nel .env:
LLM_PROVIDER=ollama
LLM_MODEL=llama3
LLM_BASE_URL=http://host.docker.internal:11434
```

### OpenAI

```bash
# Nel .env:
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
```

> Il sistema funziona anche **senza LLM** configurato: usa solo l'algoritmo basato sul catalogo ricette.
> L'LLM serve per: import PDF, generazione ricette nuove, classificazione alimenti.

---

## Home Assistant — Add-on

Per HA OS o HA Supervised con il Supervisor:

1. Vai su **Impostazioni → Add-on Store**
2. Menu tre puntini → **Repositories** → aggiungi `https://github.com/rikyru/planmydinner`
3. Cerca "Plan My Dinner" e installa
4. Nella tab **Configurazione** imposta le variabili LLM (come sopra)
5. Avvia l'add-on e verifica i log

La Web UI è accessibile tramite **HA Ingress** (sidebar di HA, senza aprire porte extra) o direttamente su `http://<ha-ip>:8000`.

### HA Core / Docker puro

> **Nota**: HA Core (container Docker) non supporta il sistema Add-on/Supervisor. La Web UI **non appare in sidebar HA**. Usa il container standalone e accedi direttamente su `http://<ip>:8000/ui/`. L'integrazione HACS (sensori) funziona comunque.

Se usi HA Core in Docker, usa `docker-compose.yml` come riferimento e adattalo al tuo setup:

```bash
# Build immagine
docker build -t planmydinner-addon ./planmydinner_addon

# Avvia (adatta i path)
docker run -d \
  -p 8000:8000 \
  -v /path/to/data:/data \
  -e LLM_PROVIDER=ollama \
  -e LLM_BASE_URL=http://host.docker.internal:11434 \
  -e LLM_MODEL=llama3 \
  --name planmydinner \
  planmydinner-addon
```

---

## Home Assistant — Integrazione Custom (HACS)

L'integrazione espone sensori e servizi HA per controllare Plan My Dinner da automazioni e dashboard.

### Installazione via HACS

1. Apri HACS → **Integrazioni** → menu tre puntini → **Repository personalizzati**
2. Aggiungi `https://github.com/rikyru/planmydinner` come **Integration**
3. Installa "Plan My Dinner" e riavvia HA

### Installazione manuale

Copia `custom_components/planmydinner/` nella directory `custom_components/` della tua configurazione HA, poi riavvia.

### Configurazione

Vai su **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Plan My Dinner**.
Inserisci host e porta del backend (es. `localhost` porta `8000`).

### Sensori esposti

| Sensore | Descrizione |
|---------|-------------|
| `sensor.plan_my_dinner_today` | Pasti del giorno (pranzo/cena) |
| `sensor.plan_my_dinner_week` | Piano settimanale riepilogativo |
| `sensor.plan_my_dinner_shopping` | Conteggio prodotti nella lista spesa |
| `sensor.plan_my_dinner_pantry` | Conteggio articoli in dispensa |
| `sensor.plan_my_dinner_web_ui` | URL della Web UI |

### Servizi disponibili

| Servizio | Descrizione |
|---------|-------------|
| `planmydinner.generate_week` | Genera piano settimanale (algoritmo) |
| `planmydinner.generate_week_ai` | Genera piano con AI |
| `planmydinner.mark_consumed` | Segna un pasto come consumato |
| `planmydinner.add_pantry_item` | Aggiunge un articolo alla dispensa |
| `planmydinner.remove_pantry_item` | Rimuove un articolo dalla dispensa |

---

## Lovelace Card

La card `planmydinner-card` mostra pranzo e cena di oggi, il conteggio prodotti della spesa e un link alla Web UI.

### Installazione

1. Copia `www/planmydinner-card.js` nella directory `www/` della tua configurazione HA
2. Vai su **Impostazioni → Dashboard → Risorse** e aggiungi:
   - URL: `/local/planmydinner-card.js`
   - Tipo: **JavaScript Module**
3. Riavvia HA o ricarica la dashboard

### Uso in Lovelace YAML

```yaml
type: custom:planmydinner-card
title: Pasti di oggi
```

---

## Profili

Plan My Dinner supporta fino a **due profili** (Persona A e Persona B) con grammature distinte per ogni ingrediente. Utile per coppie o famiglie con piani alimentari diversi.

- **Profilo A**: piano nutrizionale principale (es. chi segue la dieta del nutrizionista)
- **Profilo B**: secondo profilo opzionale con proprie grammature (es. partner con fabbisogno diverso)
- Il piano settimanale viene generato tenendo conto di entrambi i profili contemporaneamente
- Ogni ricetta può avere grammature separate per A e B: il pianificatore mostra i valori corretti per ciascuno
- Vai su **Profili** per creare/modificare i profili e i loro vincoli (categorie proteiche, limiti settimanali)
- I vincoli (es. "carne rossa max 1 volta/sett") sono configurabili indipendentemente per profilo

---

## Funzionalità avanzate

### Vista Settimana — azioni sul pasto

Cliccando su un pasto nella vista settimanale si apre un popup con:

- **↕ Cambia carboidrato** — sostituisce il carboidrato con un'altra opzione del piano, scalando i grammi
- **↕ Cambia proteina** — sostituisce la proteina mantenendo il target proteico
- **↕ Cambia verdura** — swap verdura con equivalente calorico
- **↺ Cambia ricetta** — propone 3 ricette alternative dal catalogo
- **✨ ExtraFantasy** — chiede all'IA una ricetta nuova generata al momento, coerente con i vincoli del piano
- **📋 Vedi ricetta** — mostra ingredienti e nome completo della ricetta generata
- **Non mangiato** (pasti passati) — registra che il pasto non è stato consumato
- **Pasto libero** (pasti passati) — registra un pasto fuori piano

### ExtraFantasy

Genera una ricetta completamente nuova tramite LLM per quello slot specifico, rispettando:
- Categoria proteica richiesta da quel giorno (es. "tocca il pesce")
- Grammature del piano nutrizionale
- Stagionalità e ingredienti in dispensa

La ricetta viene mostrata subito in un modal con nome e ingredienti.

### Pasti liberi e aderenza

Nel piano nutrizionale puoi specificare un numero di **pasti liberi** a settimana (`free_meal_quota`). Il widget aderenza nella vista Oggi mostra quanti ne hai usati e quanti ne rimangono.

### Debug LLM (sviluppatori)

Con almeno 2 profili configurati, appare il bottone **🐛 Debug** in sidebar. Mostra:
- **Trace generazione**: per ogni slot del piano, quali candidati erano disponibili, i filtri applicati e il punteggio finale
- **Log LLM**: le ultime 50 chiamate all'IA con prompt completo e risposta grezza, espandibili

---

## Flusso d'uso tipico

### 1. Importa il piano del nutrizionista

Vai su **Importa** nella Web UI:
- Carica il PDF del nutrizionista (supporta piani strutturati con grammature)
- L'IA estrae grammature, opzioni proteiche/carboidrati, frequenze settimanali
- Rivedi e correggi i valori prima di salvare
- Il piano viene salvato con le ricette trovate nel catalogo

### 2. Genera il piano settimanale

Vai su **Settimana → Genera piano**.

Il pianificatore usa:
- Frequenze settimanali (es. carne bianca 2/sett, legumi 3-5/sett)
- Regole di rotazione (no stesso ingrediente due giorni di fila)
- Dispensa disponibile
- Stagionalità
- Storico consumo (evita ripetizioni recenti)

### 3. Giorno per giorno

Vai su **Oggi**:
- Vedi pranzo e cena del giorno
- "Cambia ricetta" propone 3 alternative
- "Ho mangiato altro" registra un pasto libero
- Segna come consumato al termine del pasto

### 4. Lista della spesa

Vai su **Lista spesa**: la lista è generata automaticamente dal piano settimanale, raggruppata per categoria, esportabile in CSV.

---

## Aggiungere ricette

### Manuale (dalla Web UI)

Vai su **Ricette → + Aggiungi**. Compila nome, ingredienti con grammature, metodo di cottura.
Le ricette aggiunte manualmente ricevono un boost nel pianificatore.

### Bulk import (JSON)

Vai su **Ricette → Bulk Import**. Incolla un array JSON:

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

Food group validi: `carboidrati`, `carne_bianca`, `carne_rossa`, `pesce`, `legumi`, `latticini`, `proteina`, `verdure`, `grassi`.

---

## Struttura del progetto

```
planmydinner/
├── planmydinner_addon/
│   ├── main.py               # Entry point FastAPI
│   ├── planner.py            # PlannerEngine (logica principale)
│   ├── database.py           # ORM SQLAlchemy + SQLite
│   ├── schemas.py            # Pydantic schemas
│   ├── llm_gateway.py        # Astrazione LLM (OpenAI / Ollama) + cache
│   ├── pdf_parser.py         # Parsing PDF con pdfminer
│   ├── api/
│   │   ├── planner.py        # Endpoint pianificatore
│   │   ├── recipes.py        # CRUD ricette + bulk import
│   │   ├── _import.py        # Import PDF/testo
│   │   ├── shopping_list.py  # Lista spesa
│   │   ├── pantry.py         # Dispensa
│   │   ├── profiles.py       # Profili utente
│   │   └── settings.py       # Impostazioni + cache LLM
│   └── frontend/
│       ├── index.html        # App shell Vue 3
│       ├── today.js          # Vista Oggi
│       ├── planner.js        # Vista Settimana
│       ├── recipes.js        # Catalogo ricette
│       ├── import.js         # Import wizard
│       ├── profiles.js       # Profili + vincoli
│       ├── shopping.js       # Lista spesa
│       └── settings.js       # Impostazioni
├── custom_components/
│   └── planmydinner/         # HA Custom Integration
├── www/
│   └── planmydinner-card.js  # Lovelace card
├── docker-compose.standalone.yml
├── docker-compose.yml        # Con HA + Ollama
└── .env.example
```

---

## Requisiti

- Docker (per uso standalone o HA addon)
- Python 3.11+ (per sviluppo locale)
- Home Assistant 2024.1+ (solo per l'integrazione HA)
- LLM: Ollama locale o account OpenAI (opzionale ma consigliato)

---

## Licenza

MIT
