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
