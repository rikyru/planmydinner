"""
Pasti fissi (colazione e spuntini) con logica opt-out.

Si definiscono una volta per profilo; i totali giornalieri li assumono
consumati ogni giorno (slot con default_on) senza bisogno di registrarli.
Si interviene solo per le eccezioni: "saltato oggi" oppure un pasto diverso
(via flusso mensa con meal_type = slot). Lo slot "dopo_cena" è opt-in:
conta solo quando lo si segna (es. gelato).
"""
import json
import logging
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel as _BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, CandidateRecipe, ConsumedEntry
from ..nutrition import compute_recipe_nutrition

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/routine", tags=["routine"])

# Slot supportati (ordine = ordine di visualizzazione)
SLOTS = {
    "colazione":          {"label": "Colazione",            "icon": "☕", "default_on": True},
    "spuntino_mattina":   {"label": "Spuntino mattina",     "icon": "🍎", "default_on": True},
    "merenda_pomeriggio": {"label": "Merenda pomeriggio",   "icon": "🥪", "default_on": True},
    "merenda_tardo":      {"label": "Merenda tardo pom.",   "icon": "🍌", "default_on": True},
    "dopo_cena":          {"label": "Dopo cena",            "icon": "🍨", "default_on": False},
}


class RoutineIngredient(_BaseModel):
    name: str
    food_group: str = "altro"
    grams: float


class RoutineMealSave(_BaseModel):
    profile_id: str
    name: str
    ingredients: List[RoutineIngredient]
    default_on: Optional[bool] = None   # None = default dello slot


def _routine_data(cand: CandidateRecipe) -> Optional[dict]:
    data = cand.recipe_data
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    tags = data.get("tags") or {}
    return data if "true" in (tags.get("routine") or []) else None


def get_routine_meals(db: Session, profile_id: str) -> dict:
    """slot -> {id, name, content, default_on} per il profilo (usato anche da /integration/summary)."""
    out = {}
    for cand in db.query(CandidateRecipe).filter(CandidateRecipe.status == "draft_structured").all():
        data = _routine_data(cand)
        if not data or data.get("profile_id") != profile_id:
            continue
        slot = data.get("meal_slot")
        if slot in SLOTS:
            out[slot] = {
                "id": cand.id,
                "name": data.get("name"),
                "content": data.get("content", []),
                "default_on": bool(data.get("default_on", SLOTS[slot]["default_on"])),
            }
    return out


def _day_entries(db: Session, profile_id: str, iso_date: str, slot: str):
    return db.query(ConsumedEntry).filter(
        ConsumedEntry.profile_id == profile_id,
        ConsumedEntry.date == iso_date,
        ConsumedEntry.meal_type == slot,
    ).all()


def _slot_today_state(entries, meal) -> str:
    """'skipped' | 'logged' (qualcosa registrato) | 'assumed' (default) | 'off'."""
    if any(e.type == "skipped" for e in entries):
        return "skipped"
    if any(e.type != "skipped" for e in entries):
        return "logged"
    return "assumed" if meal and meal["default_on"] else "off"


@router.get("/")
def list_routine(request: Request, profile_id: str, target_date: Optional[date] = None,
                 db: Session = Depends(get_db)):
    """Slot con pasto fisso definito (se c'è), macro e stato del giorno."""
    gw = getattr(request.app.state, "llm_gateway", None)
    meals = get_routine_meals(db, profile_id)
    iso = (target_date or date.today()).isoformat()
    out = []
    for slot, info in SLOTS.items():
        meal = meals.get(slot)
        nutrition = None
        if meal:
            try:
                nutrition = compute_recipe_nutrition(meal["content"], profile_id, llm_gateway=gw)
            except Exception:
                pass
        entries = _day_entries(db, profile_id, iso, slot)
        ingredients = []
        for ing in (meal or {}).get("content", []):
            if isinstance(ing, dict):
                qty = (ing.get("quantities") or {}).get(profile_id) or {}
                ingredients.append({"name": ing.get("name"), "food_group": ing.get("food_group"),
                                    "grams": qty.get("grams_equiv") or qty.get("qty") or 0})
        out.append({
            "slot": slot,
            "label": info["label"],
            "icon": info["icon"],
            "defined": meal is not None,
            "name": (meal or {}).get("name"),
            "ingredients": ingredients,
            "default_on": meal["default_on"] if meal else info["default_on"],
            "nutrition": nutrition,
            "today": _slot_today_state(entries, meal),
        })
    return {"date": iso, "slots": out}


@router.put("/{slot}")
def save_routine_meal(slot: str, body: RoutineMealSave, db: Session = Depends(get_db)):
    """Definisce (o aggiorna) il pasto fisso di uno slot per un profilo."""
    if slot not in SLOTS:
        raise HTTPException(status_code=404, detail=f"Slot sconosciuto: {slot}")
    if not body.ingredients:
        raise HTTPException(status_code=422, detail="Serve almeno un ingrediente.")

    content = [
        {
            "name": ing.name,
            "food_group": ing.food_group,
            "quantities": {body.profile_id: {"qty": float(ing.grams), "unit": "g", "grams_equiv": float(ing.grams)}},
        }
        for ing in body.ingredients if ing.grams > 0
    ]
    default_on = SLOTS[slot]["default_on"] if body.default_on is None else bool(body.default_on)
    recipe_data = {
        "name": body.name.strip(),
        "description": f"Pasto fisso: {SLOTS[slot]['label']}",
        "is_composed_dish": False,
        "content": content,
        "steps": [],
        "total_time_minutes": 0,
        "difficulty": "sconosciuto",
        "tags": {"routine": ["true"]},
        "meal_slot": slot,
        "profile_id": body.profile_id,
        "default_on": default_on,
    }

    existing = get_routine_meals(db, body.profile_id).get(slot)
    if existing:
        cand = db.query(CandidateRecipe).filter(CandidateRecipe.id == existing["id"]).first()
        cand.recipe_data = recipe_data
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(cand, "recipe_data")
    else:
        cand = CandidateRecipe(id=str(uuid.uuid4()), status="draft_structured", usage_count=0,
                               recipe_data=recipe_data)
        db.add(cand)
    db.commit()
    db.refresh(cand)
    return {"slot": slot, "recipe_id": cand.id, "default_on": default_on}


@router.delete("/{slot}")
def delete_routine_meal(slot: str, profile_id: str, db: Session = Depends(get_db)):
    existing = get_routine_meals(db, profile_id).get(slot)
    if not existing:
        raise HTTPException(status_code=404, detail="Nessun pasto fisso per questo slot.")
    cand = db.query(CandidateRecipe).filter(CandidateRecipe.id == existing["id"]).first()
    db.delete(cand)
    db.commit()
    return {"deleted": slot}


@router.post("/{slot}/skip")
def toggle_skip(slot: str, profile_id: str, meal_date: str, db: Session = Depends(get_db)):
    """Toggle 'saltato oggi': crea (o rimuove) l'eccezione per il giorno."""
    if slot not in SLOTS:
        raise HTTPException(status_code=404, detail=f"Slot sconosciuto: {slot}")
    entries = [e for e in _day_entries(db, profile_id, meal_date, slot) if e.type == "skipped"]
    if entries:
        for e in entries:
            db.delete(e)
        db.commit()
        return {"slot": slot, "date": meal_date, "state": "assumed"}
    db.add(ConsumedEntry(id=str(uuid.uuid4()), profile_id=profile_id, date=meal_date,
                         meal_type=slot, type="skipped"))
    db.commit()
    return {"slot": slot, "date": meal_date, "state": "skipped"}


@router.post("/{slot}/log")
def toggle_log(slot: str, profile_id: str, meal_date: str, db: Session = Depends(get_db)):
    """Toggle registrazione del pasto fisso (per gli slot opt-in, es. gelato dopo cena)."""
    meal = get_routine_meals(db, profile_id).get(slot)
    if not meal:
        raise HTTPException(status_code=404, detail="Nessun pasto fisso definito per questo slot.")
    entries = [e for e in _day_entries(db, profile_id, meal_date, slot)
               if e.type != "skipped" and e.consumed_recipe_id == meal["id"]]
    if entries:
        for e in entries:
            db.delete(e)
        db.commit()
        return {"slot": slot, "date": meal_date, "state": "off"}
    db.add(ConsumedEntry(id=str(uuid.uuid4()), profile_id=profile_id, date=meal_date,
                         meal_type=slot, type="override", consumed_recipe_id=meal["id"],
                         override_details={"free_text_name": meal["name"], "notes": "routine"}))
    db.commit()
    return {"slot": slot, "date": meal_date, "state": "logged"}
