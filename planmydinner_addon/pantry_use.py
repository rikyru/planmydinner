"""Scalare dalla dispensa ciò che si mangia (merende extra, pasti fissi) e
restituirlo se ci si ripensa.

La dispensa ha spesso una riga per confezione (es. 4 yogurt da 150 g scansionati
uno a uno): si consuma per nome, prima le confezioni già aperte (le più piccole),
e una riga che arriva a zero sparisce, salvo abbia una soglia minima (allora
resta a zero e finisce nella lista della spesa). Ogni prelievo è registrato così
da poterlo restituire tale e quale.
"""
import re
import uuid
from typing import List, Optional

from sqlalchemy.orm import Session

from .database import PantryItem


def norm_name(name: str) -> str:
    """"High Protein Crunchy Musli · LIDL" == "high protein crunchy musli lidl"."""
    return " ".join(re.sub(r"[^\w]+", " ", (name or "").lower()).split())


# --- Stesso cibo? -----------------------------------------------------------
# Prima bastava UNA parola in comune: "Tentacoli Di Polpo · Gastronomia Di Mare"
# condivideva "di" con "petto di pollo", e il polpo finiva in ogni ricetta (nei
# suggerimenti per i prodotti in scadenza e nel bonus dispensa del planner).
# Ora si confronta il cibo principale del nome.

_STOP = {"di", "del", "della", "dello", "dei", "degli", "delle", "d", "e", "ed", "a", "il", "lo",
         "la", "i", "gli", "le", "l", "un", "una", "uno", "per", "da", "by", "tipo"}
# ciò che segue è un gusto o un contorno, non il cibo: "cioccolato al latte"
_FLAVOR = {"al", "alla", "allo", "all", "ai", "agli", "alle", "con", "in", "su", "sul", "sulla",
           "aromatizzato", "aromatizzata", "gusto",
           "base"}   # "bevanda a base di mandorla" non è mandorle
# tagli e formati: il cibo è quello dopo "di" ("filetti di merluzzo")
_CUTS = {"filetto", "filetti", "cuori", "cuore", "tentacoli", "petto", "petti", "fesa", "fetta",
         "fette", "fettine", "fettina", "carpaccio", "bocconcini", "cubetti", "trancio", "tranci",
         "fuso", "fusi", "coscia", "cosce", "sovracosce", "spiedini", "polpa", "medaglioni",
         "hamburger", "burger", "porzioni", "porzione", "confezione"}
_QUALIFIERS = {"bio", "biologico", "biologica", "biologici", "biologiche", "fresco", "fresca",
               "freschi", "fresche", "light", "magro", "magra", "intero", "intera", "interi",
               "integrale", "integrali", "naturale", "classico", "classica", "dop", "igp", "msc",
               "surgelato", "surgelata", "surgelati", "surgelate", "high", "extra", "mini", "maxi",
               "vegetale", "vegetali", "autentico", "autentica", "bianco", "bianca", "nuovo"}


def _stem(word: str) -> str:
    """zucchina/zucchine, uovo/uova, polpo (≠ pollo): via la vocale finale."""
    return word[:-1] if len(word) > 3 and word[-1] in "aeiouàèéìòù" else word


def food_words(name: str):
    """(cibo principale, parole che descrivono il prodotto), già ridotte alla radice.

    Il marchio dopo '·' e i gusti dopo 'al'/'con' non contano; se il nome inizia
    con un taglio ('Filetti di merluzzo') il cibo è la parola dopo 'di'."""
    text = (name or "").split("·")[0].lower()
    words = re.findall(r"[^\W\d_]+", text)
    head, phrase, skip = None, [], False
    for w in words:
        if w in _FLAVOR:
            skip = True               # da qui in poi gusto/contorno
            continue
        if skip or w in _STOP or w in _QUALIFIERS or len(w) < 2:
            continue
        if w in _CUTS:
            continue
        if head is None:
            head = _stem(w)
        phrase.append(_stem(w))
    return head, set(phrase)


def same_food(ingredient_name: str, pantry_name: str) -> bool:
    """L'ingrediente di una ricetta è quel prodotto della dispensa?
    'polpo' ~ 'Tentacoli Di Polpo · Lidl', 'yogurt' ~ 'Delta yogurt greco';
    NON 'petto di pollo' ~ polpo, NON 'latte' ~ 'Cioccolato al latte'."""
    h1, p1 = food_words(ingredient_name)
    h2, p2 = food_words(pantry_name)
    if not h1 or not h2:
        return False
    return h1 in p2 or h2 in p1


def _amount(grams: float, unit: str) -> float:
    """Quanto togliere da una riga della dispensa per `grams` mangiati."""
    u = (unit or "").lower()
    if u in ("g", "ml"):
        return grams
    if u in ("kg", "l"):
        return grams / 1000.0
    return 1.0   # pz, confezioni: un pezzo per volta


def take(db: Session, name: str, grams: float, pantry_id: Optional[str] = None) -> List[dict]:
    """Scala `grams` del prodotto dalla dispensa (per id o per nome) e ritorna i
    prelievi fatti; lista vuota se il prodotto non c'è. Non fa commit."""
    if grams <= 0:
        return []
    item = db.query(PantryItem).filter(PantryItem.id == pantry_id).first() if pantry_id else None
    key = norm_name(item.name if item else name)
    if not key:
        return []
    rows = [p for p in db.query(PantryItem).all()
            if norm_name(p.name) == key and (p.quantity or 0) > 0]
    if not rows:
        return []
    unit = (rows[0].unit or "").lower()
    rows = [p for p in rows if (p.unit or "").lower() == unit]
    rows.sort(key=lambda p: p.quantity or 0)
    need = _amount(grams, unit)
    out = []
    for p in rows:
        if need <= 1e-9:
            break
        qty = min(need, p.quantity or 0)
        need -= qty
        out.append({"id": p.id, "name": p.name, "unit": p.unit, "qty": round(qty, 3),
                    "category": p.category, "barcode": p.barcode, "nutrition": p.nutrition,
                    "min_quantity": p.min_quantity})
        p.quantity = round((p.quantity or 0) - qty, 3)
        if p.quantity <= 1e-9 and not p.min_quantity:
            db.delete(p)
    return out


def give_back(db: Session, deductions: List[dict]) -> None:
    """Rimette in dispensa i prelievi di `take` (ricreando le righe sparite). Non fa commit."""
    for d in deductions or []:
        p = db.query(PantryItem).filter(PantryItem.id == d.get("id")).first()
        if p:
            p.quantity = round((p.quantity or 0) + d["qty"], 3)
            continue
        db.add(PantryItem(id=d.get("id") or str(uuid.uuid4()), name=d["name"], quantity=d["qty"],
                          unit=d.get("unit"), category=d.get("category"), barcode=d.get("barcode"),
                          nutrition=d.get("nutrition"), min_quantity=d.get("min_quantity"),
                          synonyms=[]))
