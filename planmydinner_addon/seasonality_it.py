"""Calendario di stagionalità italiano di base (verdura e frutta per mese).

Usato quando la tabella ``seasonality_items`` è vuota, per dire all'AI cosa
è di stagione quando propone nuove ricette.
"""
from typing import Dict, List

_MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
         "agosto", "settembre", "ottobre", "novembre", "dicembre"]

# mese (1-12) → verdure/frutta tipicamente di stagione in Italia
SEASONAL_IT: Dict[int, List[str]] = {
    1:  ["cavolfiore", "broccoli", "cavolo nero", "verza", "finocchi", "radicchio", "carciofi",
         "porri", "zucca", "spinaci", "arance", "mandarini", "kiwi"],
    2:  ["cavolfiore", "broccoli", "cavolo nero", "verza", "finocchi", "radicchio", "carciofi",
         "porri", "spinaci", "bietole", "arance", "kiwi"],
    3:  ["carciofi", "asparagi", "finocchi", "spinaci", "bietole", "piselli", "porri",
         "cavolfiore", "arance", "kiwi"],
    4:  ["asparagi", "carciofi", "piselli", "fave", "spinaci", "bietole", "zucchine",
         "lattuga", "fragole"],
    5:  ["asparagi", "piselli", "fave", "zucchine", "fagiolini", "lattuga", "rucola",
         "fragole", "ciliegie"],
    6:  ["zucchine", "fagiolini", "pomodori", "peperoni", "melanzane", "cetrioli", "lattuga",
         "albicocche", "ciliegie", "pesche"],
    7:  ["pomodori", "peperoni", "melanzane", "zucchine", "fagiolini", "cetrioli",
         "anguria", "melone", "pesche"],
    8:  ["pomodori", "peperoni", "melanzane", "zucchine", "fagiolini", "cetrioli",
         "anguria", "melone", "fichi", "pesche"],
    9:  ["pomodori", "peperoni", "melanzane", "zucchine", "zucca", "funghi", "fagiolini",
         "uva", "fichi", "mele", "pere"],
    10: ["zucca", "funghi", "broccoli", "cavolfiore", "spinaci", "bietole", "radicchio",
         "finocchi", "castagne", "uva", "mele", "pere", "cachi"],
    11: ["zucca", "cavolfiore", "broccoli", "cavolo nero", "verza", "radicchio", "finocchi",
         "spinaci", "carciofi", "mele", "pere", "cachi", "mandarini"],
    12: ["cavolfiore", "broccoli", "cavolo nero", "verza", "radicchio", "finocchi", "carciofi",
         "zucca", "spinaci", "arance", "mandarini", "kiwi"],
}


def month_name(month: int) -> str:
    return _MESI[month - 1]
