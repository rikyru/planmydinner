"""Prodotti di cui si conoscono i valori nutrizionali da etichetta.

Vengono da ciò che l'utente ha già scansionato (barcode o foto dell'etichetta)
e che è rimasto da qualche parte: prodotti in dispensa, pasti dello Storico,
prelievi dei pasti fissi, colazioni e merende fisse. Servono a dare a una riga
di scontrino ('YOMO DELT.YOG.GR.MIR') i valori veri invece di quelli generici
della tabella ('yogurt greco' intero: 5 g di grassi contro 0,1).
"""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .database import ConsumedEntry, PantryItem, PantryUse, UserProfile
from .nutrition import NUTRITION_KEYS
from .pantry_use import norm_name


def label_values(data: Any) -> Optional[Dict[str, float]]:
    """{kcal, protein_g, carbs_g, fat_g} numerici, o None se incompleti."""
    if not isinstance(data, dict) or data.get("kcal") is None:
        return None
    try:
        values = {k: round(float(data.get(k) or 0), 2) for k in NUTRITION_KEYS}
    except (TypeError, ValueError):
        return None
    return values if 0 < values["kcal"] <= 950 else None


def collect_known_products(db: Session, limit: int = 80) -> List[Dict[str, Any]]:
    """[{name, barcode, nutrition}] senza doppioni (stesso nome normalizzato),
    dai più recenti: prima la dispensa attuale, poi lo Storico dal più nuovo."""
    out: List[Dict[str, Any]] = []
    seen = set()

    def add(name: Optional[str], nutrition: Any, barcode: Optional[str] = None):
        values = label_values(nutrition)
        key = norm_name(name or "")
        if not values or not key or key in seen:
            return
        seen.add(key)
        out.append({"name": name.strip(), "barcode": barcode or None, "nutrition": values})

    for p in db.query(PantryItem).filter(PantryItem.nutrition.isnot(None)).all():
        add(p.name, p.nutrition, p.barcode)

    for e in db.query(ConsumedEntry).order_by(ConsumedEntry.date.desc()).all():
        details = e.override_details if isinstance(e.override_details, dict) else {}
        for ing in details.get("ingredients") or []:
            if not isinstance(ing, dict):
                continue
            used = ing.get("pantry_used") or []
            barcode = next((u.get("barcode") for u in used if isinstance(u, dict) and u.get("barcode")), None)
            add(ing.get("name"), ing.get("per_100g"), barcode)

    for u in db.query(PantryUse).order_by(PantryUse.date.desc()).all():
        for d in u.deductions or []:
            if isinstance(d, dict):
                add(d.get("name"), d.get("nutrition"), d.get("barcode"))

    try:   # colazioni e merende fisse (salvate come ricette di routine)
        from .api.routine import get_routine_meals
        for prof in db.query(UserProfile).all():
            for meal in (get_routine_meals(db, prof.id) or {}).values():
                for ing in (meal or {}).get("content") or []:
                    if isinstance(ing, dict) and ing.get("pantry_id"):
                        add(ing.get("name"), ing.get("nutrition"))
    except Exception:
        pass

    return out[:limit]
