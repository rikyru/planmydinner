"""
Pasti fissi (colazione e spuntini) con logica opt-out.

Si definiscono una volta per profilo; i totali giornalieri li assumono
consumati ogni giorno (slot con default_on) senza bisogno di registrarli.
Si interviene solo per le eccezioni: "saltato oggi" oppure un pasto diverso
(via flusso mensa con meal_type = slot). Lo slot "dopo_cena" è opt-in:
conta solo quando lo si segna (es. gelato).
"""
import base64
import json
import logging
import re
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel as _BaseModel
from sqlalchemy.orm import Session

from ..barcode import lookup_barcode
from ..database import get_db, CandidateRecipe, ConsumedEntry, PantryItem
from ..nutrition import NUTRITION_KEYS, compute_recipe_nutrition, resolve_ingredient_nutrition

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
    # prodotto della dispensa: si usano i valori per 100 g dell'etichetta invece
    # di stimarli dal nome; per_100g resta come copia se il prodotto sparisce
    pantry_id: Optional[str] = None
    per_100g: Optional[dict] = None


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


def _slot_today_nutrition(db: Session, profile_id: str, entries, meal, default_nutrition,
                          state: str, llm_gateway=None):
    """(nutrizione, nome) di ciò che conta oggi per lo slot, come in
    /integration/summary: saltato → nulla; registrato → il pasto registrato
    (es. da foto); altrimenti il pasto fisso se è attivo di default."""
    if state == "assumed":
        return default_nutrition, None
    if state != "logged":
        return None, None
    logged = [e for e in entries if e.type != "skipped" and e.consumed_recipe_id]
    if not logged:
        return None, None
    e = logged[0]
    if meal and e.consumed_recipe_id == meal["id"]:
        return default_nutrition, None
    from .integration import _get_recipe_content
    content = _get_recipe_content(db, e.consumed_recipe_id)
    try:
        n = compute_recipe_nutrition(content, profile_id, llm_gateway=llm_gateway) if content else None
    except Exception:
        n = None
    return n, (e.override_details or {}).get("free_text_name")


@router.get("/suggest")
def suggest_routine(request: Request, slot: str, avoid: Optional[str] = None,
                    from_pantry: bool = False, db: Session = Depends(get_db)):
    """Propone (via AI) un pasto fisso per lo slot, da rivedere e salvare.
    `avoid`: pasto attuale da NON riproporre, per varietà.
    `from_pantry=true`: compone usando PRINCIPALMENTE ciò che hai in dispensa
    (es. muesli proteico + latte di mandorla)."""
    if slot not in SLOTS:
        raise HTTPException(status_code=404, detail=f"Slot sconosciuto: {slot}")
    gw = getattr(request.app.state, "llm_gateway", None)
    if gw is None or getattr(gw, "_client", None) is None:
        raise HTTPException(status_code=503, detail="AI non disponibile.")
    pantry = None
    if from_pantry:
        pantry = [p.name for p in db.query(PantryItem).all()
                  if p.name and (p.quantity or 0) > 0]
        if not pantry:
            raise HTTPException(status_code=422, detail="Dispensa vuota: aggiungi prima qualche prodotto.")
    proposal = gw.suggest_meal(SLOTS[slot]["label"].lower(), avoid=avoid or None, pantry=pantry)
    if not proposal:
        raise HTTPException(status_code=502, detail="Nessuna proposta generata.")
    return proposal


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
        state = _slot_today_state(entries, meal)
        today_nutrition, today_name = _slot_today_nutrition(
            db, profile_id, entries, meal, nutrition, state, gw)
        ingredients = []
        for ing in (meal or {}).get("content", []):
            if isinstance(ing, dict):
                qty = (ing.get("quantities") or {}).get(profile_id) or {}
                row = {"name": ing.get("name"), "food_group": ing.get("food_group"),
                       "grams": qty.get("grams_equiv") or qty.get("qty") or 0}
                if ing.get("pantry_id") and ing.get("nutrition"):
                    row.update(pantry_id=ing["pantry_id"],
                               per_100g={k: ing["nutrition"].get(k) for k in NUTRITION_KEYS})
                ingredients.append(row)
        out.append({
            "slot": slot,
            "label": info["label"],
            "icon": info["icon"],
            "defined": meal is not None,
            "name": (meal or {}).get("name"),
            "ingredients": ingredients,
            "default_on": meal["default_on"] if meal else info["default_on"],
            "nutrition": nutrition,
            "today": state,
            # cosa conta davvero oggi: il pasto fisso o quello diverso registrato
            "today_nutrition": today_nutrition,
            "today_name": today_name,
        })
    return {"date": iso, "slots": out}


def _label_values(db: Session, ing: RoutineIngredient) -> Optional[dict]:
    """Valori per 100 g da etichetta di un ingrediente preso dalla dispensa: quelli
    attuali del prodotto, o la copia salvata se il prodotto non c'è più."""
    if not ing.pantry_id:
        return None
    item = db.query(PantryItem).filter(PantryItem.id == ing.pantry_id).first()
    per100 = (item.nutrition or {}) if item else (ing.per_100g or {})
    if per100.get("kcal") is None:
        return None
    return {**{k: float(per100.get(k) or 0) for k in NUTRITION_KEYS}, "source": "pantry"}


def _routine_content(profile_id: str, ingredients: List[RoutineIngredient], db: Session) -> list:
    out = []
    for ing in ingredients:
        if ing.grams <= 0 or not ing.name.strip():
            continue
        row = {
            "name": ing.name.strip(),
            "food_group": ing.food_group,
            "quantities": {profile_id: {"qty": float(ing.grams), "unit": "g", "grams_equiv": float(ing.grams)}},
        }
        label = _label_values(db, ing)
        if label:
            row.update(pantry_id=ing.pantry_id, nutrition=label)
        out.append(row)
    return out


class RoutinePreview(_BaseModel):
    profile_id: str
    ingredients: List[RoutineIngredient]


@router.post("/preview")
def preview_routine_meal(body: RoutinePreview, request: Request, db: Session = Depends(get_db)):
    """kcal/macro di un pasto fisso in modifica (non salvato), totale e per
    ingrediente, così si vede subito chi porta i grassi. Niente olio di cottura:
    colazione e spuntini non lo prevedono."""
    gw = getattr(request.app.state, "llm_gateway", None)
    content = _routine_content(body.profile_id, body.ingredients, db)
    try:
        total = compute_recipe_nutrition(content, body.profile_id, llm_gateway=gw) if content else None
    except Exception:
        total = None
    per = []
    for c in content:
        grams = c["quantities"][body.profile_id]["grams_equiv"]
        try:
            n = resolve_ingredient_nutrition(c, llm_gateway=gw)
        except Exception:
            n = None
        row = {"name": c["name"], "grams": grams, "known": bool(n)}
        if n:
            row.update({k: round(n[k] * grams / 100.0, 1) for k in NUTRITION_KEYS})
        per.append(row)
    return {"nutrition": total, "ingredients": per}


@router.put("/{slot}")
def save_routine_meal(slot: str, body: RoutineMealSave, db: Session = Depends(get_db)):
    """Definisce (o aggiorna) il pasto fisso di uno slot per un profilo."""
    if slot not in SLOTS:
        raise HTTPException(status_code=404, detail=f"Slot sconosciuto: {slot}")
    if not body.ingredients:
        raise HTTPException(status_code=422, detail="Serve almeno un ingrediente.")

    content = _routine_content(body.profile_id, body.ingredients, db)
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


# ----------------------------------------------------------------- merende extra
# Spuntini liberi, SLEGATI dai 5 slot fissi: se ne possono annotare quanti si
# vuole in un giorno (una barretta, un frutto, uno sgarro). Contano nei totali
# del giorno come i pasti fissi. Salvate come ConsumedEntry type="extra".

EXTRA_TYPE = "extra"
EXTRA_MEAL_TYPE = "extra_snack"


class ExtraSnackIngredient(_BaseModel):
    name: str
    food_group: str = "altro"
    grams: float
    # prodotto della dispensa (es. yogurt scansionato): si usano i SUOI valori per
    # 100 g dall'etichetta invece di stimare dal nome
    pantry_id: Optional[str] = None
    # prodotto scansionato al volo (barcode o foto, es. snack della macchinetta):
    # valori per 100 g già noti, senza passare dalla dispensa
    per_100g: Optional[dict] = None


class ExtraSnackBody(_BaseModel):
    name: str
    ingredients: List[ExtraSnackIngredient]
    # descrizione libera (es. "aperitivo: birra media, pane e salumi"): da qui l'AI
    # stima gli ingredienti; si conserva per mostrarla e per il coach di OpenFit
    description: str = ""


def _extra_content(ings: list, profile_id: str) -> list:
    """Content (per il calcolo nutrizionale) dagli ingredienti di una merenda extra."""
    return [{
        "name": ing.get("name"),
        "food_group": ing.get("food_group") or "altro",
        "quantities": {profile_id: {"qty": ing.get("qty") or 0, "unit": "g",
                                    "grams_equiv": ing.get("qty") or 0}},
    } for ing in ings]


def extra_nutrition(override_details: dict, profile_id: str, llm_gateway=None):
    """Macro di una merenda extra: gli ingredienti presi dalla dispensa usano i
    valori per 100 g dell'etichetta (salvati sull'extra), gli altri il calcolo
    standard per nome. None se non si riesce a stimare nulla."""
    ings = (override_details or {}).get("ingredients") or []
    label = [i for i in ings if i.get("per_100g")]
    rest = [i for i in ings if not i.get("per_100g")]
    total = {k: 0.0 for k in NUTRITION_KEYS}
    for i in label:
        f = (i.get("qty") or 0) / 100.0
        for k in NUTRITION_KEYS:
            total[k] += float(i["per_100g"].get(k) or 0) * f
    if rest:
        try:
            n = compute_recipe_nutrition(_extra_content(rest, profile_id), profile_id,
                                         llm_gateway=llm_gateway)
        except Exception:
            n = None
        if not n and not label:
            return None
        for k in NUTRITION_KEYS:
            total[k] += (n or {}).get(k) or 0
    elif not label:
        return None
    return {k: round(v, 1) for k, v in total.items()}


def _extra_nutrition(entry: ConsumedEntry, llm_gateway=None):
    return extra_nutrition(entry.override_details, entry.profile_id, llm_gateway)


@router.post("/extra")
def add_extra_snack(profile_id: str, meal_date: str, body: ExtraSnackBody,
                    request: Request, db: Session = Depends(get_db)):
    """Annota una merenda extra (fuori dai 5 slot fissi) per un giorno."""
    ings = [i for i in body.ingredients if i.name.strip() and i.grams > 0]
    if not ings:
        raise HTTPException(status_code=422, detail="Serve almeno un ingrediente.")

    def _ing(i):
        row = {"name": i.name.strip(), "food_group": i.food_group, "qty": float(i.grams), "unit": "g"}
        item = db.query(PantryItem).filter(PantryItem.id == i.pantry_id).first() if i.pantry_id else None
        per100 = (item.nutrition or {}) if item else (i.per_100g or {})
        if per100.get("kcal") is not None:
            # copia dei valori: se poi il prodotto esce dalla dispensa la merenda non cambia
            if item:
                row["pantry_id"] = item.id
            row["per_100g"] = {k: float(per100.get(k) or 0) for k in NUTRITION_KEYS}
        return row
    entry = ConsumedEntry(
        id=str(uuid.uuid4()), profile_id=profile_id, date=meal_date,
        meal_type=EXTRA_MEAL_TYPE, type=EXTRA_TYPE,
        override_details={
            "free_text_name": body.name.strip() or "Merenda extra",
            "ingredients": [_ing(i) for i in ings],
            "notes": "extra",
            **({"description": body.description.strip()} if body.description.strip() else {}),
        },
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    gw = getattr(request.app.state, "llm_gateway", None)
    return {"id": entry.id, "name": entry.override_details["free_text_name"],
            "nutrition": _extra_nutrition(entry, gw)}


@router.get("/extras")
def list_extra_snacks(profile_id: str, meal_date: str, request: Request,
                      db: Session = Depends(get_db)):
    """Le merende extra annotate per un giorno, con i macro."""
    gw = getattr(request.app.state, "llm_gateway", None)
    rows = db.query(ConsumedEntry).filter(
        ConsumedEntry.profile_id == profile_id,
        ConsumedEntry.date == meal_date,
        ConsumedEntry.type == EXTRA_TYPE,
    ).all()
    out = []
    for e in rows:
        od = e.override_details or {}
        out.append({
            "id": e.id,
            "name": od.get("free_text_name"),
            "description": od.get("description"),
            "ingredients": od.get("ingredients") or [],
            "nutrition": _extra_nutrition(e, gw),
        })
    return {"date": meal_date, "extras": out}


@router.delete("/extra/{entry_id}")
def delete_extra_snack(entry_id: str, db: Session = Depends(get_db)):
    e = db.query(ConsumedEntry).filter(
        ConsumedEntry.id == entry_id, ConsumedEntry.type == EXTRA_TYPE).first()
    if not e:
        raise HTTPException(status_code=404, detail="Merenda extra non trovata.")
    db.delete(e)
    db.commit()
    return {"deleted": entry_id}


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


# ------------------------------------------------- prodotto scansionato (merende)
# Snack confezionati (es. dalla macchinetta) aggiunti come merenda extra dal
# codice a barre o da una foto: stessa risposta per entrambe le strade,
#   {found, source: barcode|etichetta|stima, barcode, name, grams, nutrition}
# con grams = peso della confezione (la merenda tipica è la confezione intera).

_MAX_PHOTO_BYTES = 10 * 1024 * 1024


def pack_grams(quantity_text: str) -> Optional[float]:
    """Peso netto in grammi dal testo della confezione ("45 g", "0,33 l", "6 x 25 g")."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|cl|l)\b", (quantity_text or "").lower())
    if not m:
        return None
    q = float(m.group(1).replace(",", "."))
    return q * {"kg": 1000, "l": 1000, "cl": 10}.get(m.group(2), 1)


def _product_from_barcode(code: str) -> Optional[dict]:
    res = lookup_barcode(code)
    if res is None:
        raise HTTPException(status_code=502, detail="Servizio barcode non raggiungibile.")
    if not res.get("found"):
        return None
    n = res.get("nutrition") or {}
    return {"found": True, "source": "barcode", "barcode": res["barcode"],
            "name": " · ".join(x for x in (res.get("name"), res.get("brands")) if x) or ("Prodotto " + code),
            "grams": pack_grams(res.get("quantity_text")),
            "nutrition": n if n.get("kcal") is not None else None}


@router.get("/product/{code}")
def product_by_barcode(code: str):
    """Snack dal codice a barre (Open Food Facts)."""
    return _product_from_barcode(code) or {"found": False, "barcode": code}


@router.post("/product-photo")
async def product_from_photo(request: Request, file: UploadFile = File(...)):
    """Snack da una foto: se l'AI legge il codice a barre si usano i dati di Open
    Food Facts, altrimenti la tabella nutrizionale letta dalla foto o, in mancanza,
    una stima per quel prodotto."""
    gw = getattr(request.app.state, "llm_gateway", None)
    if gw is None or gw._client is None:
        raise HTTPException(status_code=503, detail="LLM non configurato: impossibile analizzare la foto.")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=422, detail="Il file deve essere un'immagine.")
    raw = await file.read()
    if len(raw) > _MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Immagine troppo grande (max 10 MB).")
    guess = gw.identify_product_from_photo(base64.b64encode(raw).decode(), file.content_type)
    if not guess:
        raise HTTPException(status_code=422, detail="Non riconosco un prodotto nella foto.")
    if guess.get("barcode"):
        try:
            p = _product_from_barcode(guess["barcode"])
        except HTTPException:
            p = None
        if p and p["nutrition"]:
            p["grams"] = p["grams"] or guess.get("net_grams")
            return p
    name = " · ".join(x for x in (guess.get("name"), guess.get("brand")) if x)
    return {"found": bool(name), "source": "etichetta" if guess.get("from_label") else "stima",
            "barcode": guess.get("barcode"), "name": name or "Snack",
            "grams": guess.get("net_grams"), "nutrition": guess.get("per_100g")}
