# Analisi dei Costi per l'Utilizzo di API LLM a Pagamento

Questo documento analizza i potenziali costi derivanti dall'utilizzo di un servizio LLM a pagamento (come OpenAI) al posto di una soluzione locale (Ollama) per il progetto Plan My Dinner.

## Introduzione

L'utilizzo di un modello LLM in locale su un server domestico, specialmente uno già carico di servizi come Plex, NAS, e torrent, può causare rallentamenti e instabilità. Una soluzione eccellente è "esternalizzare" questo carico di lavoro a un'API a pagamento, che offre performance superiori e non impatta minimamente sul tuo hardware.

## Come Funziona il Prezzo delle API LLM

La maggior parte dei provider, come OpenAI, utilizza un modello di prezzo basato su **token**.

*   **Cos'è un Token?**: Un token è una porzione di parola. In media, 100 token corrispondono a circa 75 parole.
*   **Costo di Input e Output**: Il costo viene calcolato separatamente per i token che invii all'API (l'**input**, cioè il nostro prompt) e per i token che ricevi come risposta (l'**output**, cioè la ricetta JSON generata).

## Stima dei Costi per Plan My Dinner

In questo progetto, l'unica interazione con l'LLM avviene quando si registra un pasto con la funzione "Ho mangiato altro..." e si inserisce solo il nome del piatto (es. "Pasta al ragù"), senza fornire una lista strutturata di ingredienti.

Vediamo una stima dei token per una singola chiamata, usando come esempio il modello `gpt-3.5-turbo` di OpenAI (uno dei più economici ed efficienti).

#### 1. Token di Input (Prompt)

Il prompt che inviamo all'API è composto da:
*   **System Message**: Un lungo testo di istruzioni che dice all'LLM come comportarsi e quale formato JSON produrre.
*   **User Message**: Il nome del piatto che hai inserito (es. "Torta salata con zucchine e gamberetti").

**Stima**:
*   System Message: ~200 token
*   User Message (medio): ~10 token
*   **Totale Input: ~210 token**

#### 2. Token di Output (Risposta)

L'LLM deve rispondere con un oggetto JSON che rappresenta la ricetta strutturata (`schemas.RecipeCreate`).

**Stima**:
*   Una ricetta JSON con 4-5 ingredienti, steps, e altri campi: **~300-400 token**

#### 3. Calcolo del Costo per Singolo Utilizzo

Prendiamo i prezzi di `gpt-3.5-turbo` (i prezzi possono variare, controlla sempre il sito ufficiale di OpenAI):
*   Input: ~$0.0005 per 1,000 token
*   Output: ~$0.0015 per 1,000 token

**Costo per un singolo "override"**:
*   Costo Input: (210 / 1000) * $0.0005 = $0.000105
*   Costo Output: (400 / 1000) * $0.0015 = $0.000600
*   **Totale per override: ~$0.000705**

Questo significa che ogni volta che usi la funzione di override con solo testo, il costo è di circa **sette centesimi di un centesimo di dollaro**.

#### 4. Scenari di Costo Mensile

| Numero di Override al Mese | Costo Mensile Stimato (USD) | Costo Mensile Stimato (EUR, ~0.92) |
| -------------------------- | --------------------------- | ------------------------------------ |
| 50                         | $0.035                      | ~€0.03                             |
| **100**                    | **$0.07**                   | **~€0.06**                           |
| 500                        | $0.35                       | ~€0.32                             |

**Conclusione sulla stima**: I costi per questo specifico caso d'uso sono **estremamente bassi**. Anche con un uso intensivo della funzione di override, il costo mensile sarebbe di pochi centesimi.

## Come Passare a OpenAI

1.  **Crea un Account e Ottieni una API Key**:
    *   Vai su [platform.openai.com](https://platform.openai.com/).
    *   Crea un account e aggiungi un metodo di pagamento.
    *   Vai nella sezione "API Keys" e crea una nuova chiave segreta. Copiala e tienila al sicuro.

2.  **Configura l'Add-on o il Docker Compose**:
    *   Modifica la configurazione del tuo `planmydinner-addon`. Se usi `docker-compose.yml`, modificalo così:
        ```yaml
        planmydinner-addon:
          # ...
          environment:
            - LLM_PROVIDER=openai
            - LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxx # Incolla la tua chiave API di OpenAI qui
            - LLM_MODEL=gpt-3.5-turbo
          # ...
        ```
    *   Riavvia il container.

## Pro e Contro: OpenAI vs. Ollama Locale

| Aspetto       | Ollama Locale (sul Mac Mini/Telefono)                               | API a Pagamento (OpenAI)                                           |
| ------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------ |
| **Costo**     | **Gratuito** (costo hardware ed elettricità a parte)                | **Pagamento a consumo**, ma molto basso per questo progetto        |
| **Performance** | **Lenta**, specialmente su hardware non recente.                  | **Molto veloce** e non impatta minimamente sul tuo server.         |
| **Privacy**   | **Massima**. Tutti i dati rimangono sulla tua rete locale.          | **Inferiore**. I dati (i nomi dei piatti) vengono inviati a OpenAI.  |
| **Stabilità** | **Media/Bassa**, specialmente su un telefono (processi interrotti). | **Altissima**. Servizio cloud professionale.                       |
| **Qualità**   | Dipende dal modello. I modelli più piccoli potrebbero essere meno "creativi". | Generalmente **molto alta**, anche con modelli economici come GPT-3.5. |

**Raccomandazione**: Dato il costo irrisorio e i notevoli benefici in termini di performance e stabilità, **l'utilizzo di un'API a pagamento come OpenAI è la scelta consigliata** se la privacy dei nomi dei piatti che inserisci non è una preoccupazione fondamentale.
