from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime
import logging
import os
import uuid

from .. import lidl, schemas
from ..barcode import lookup_barcode
from ..database import get_db, PantryItem, AppSettings, LidlImport, ReceiptProductLink
from ..known_products import collect_known_products, label_values
from ..pantry_use import norm_name, same_food
from pydantic import BaseModel as _BaseModel

_LOG = logging.getLogger(__name__)

router = APIRouter(
    prefix="/pantry",
    tags=["pantry"],
)


@router.get("/expiring-recipes")
def expiring_recipes(days: int = 5, limit: int = 6, db: Session = Depends(get_db)):
    """Ricette del catalogo che usano i prodotti in dispensa in scadenza entro
    `days` giorni (o già scaduti), ordinate per quanti ne consumano. Aiuta a non
    buttare via nulla."""
    from datetime import date
    from ..planner import PlannerEngine
    today = date.today()
    expiring = []
    for it in db.query(PantryItem).all():
        if not it.expiration_date or (it.quantity or 0) <= 0:
            continue
        try:
            d = date.fromisoformat(it.expiration_date)
        except ValueError:
            continue
        if (d - today).days <= days:            # in scadenza o già scaduto
            expiring.append((it, (d - today).days))
    if not expiring:
        return {"expiring": [], "recipes": []}
    eng = PlannerEngine(db)
    # Le ricette si propongono solo per ciò che si può ancora mangiare: uno
    # scaduto (pesce, carne) va controllato, non cucinato. Più scade presto,
    # più conta: le zucchine fra 1 giorno prima dello yogurt fra 5.
    usable = [(it, n) for it, n in expiring if n >= 0]
    scored = []
    for r in eng._get_all_recipes():
        ings = r.content.components if r.is_composed_dish else r.content
        names = [getattr(i, "name", "") or "" for i in ings]
        uses, urgency, seen = [], 0.0, set()
        for it, n in usable:
            key = norm_name(it.name)
            if key in seen or not any(same_food(nm, it.name) for nm in names):
                continue
            seen.add(key)        # 3 yogurt uguali = un prodotto solo
            uses.append(it.name)
            urgency += 1.0 / (1 + n)
        if uses:
            scored.append({"id": r.id, "name": r.name, "uses": uses, "n": len(uses),
                           "urgency": round(urgency, 3)})
    scored.sort(key=lambda x: (-x["urgency"], -x["n"], x["name"]))
    return {
        "expiring": _one_per_product(expiring),
        "recipes": scored[:limit],
    }


def _one_per_product(expiring) -> list:
    """Una voce per prodotto (la confezione che scade prima), con quante sono."""
    out, index = [], {}
    for it, n in sorted(expiring, key=lambda x: x[1]):
        key = norm_name(it.name)
        if key in index:
            out[index[key]]["count"] += 1
            continue
        index[key] = len(out)
        out.append({"name": it.name, "expiration_date": it.expiration_date, "days": n, "count": 1})
    return out


@router.get("/low-stock", response_model=List[schemas.PantryItem])
def low_stock_items(db: Session = Depends(get_db)):
    """Articoli scesi a/sotto la loro soglia minima (da ricomprare)."""
    items = db.query(PantryItem).all()
    return [i for i in items
            if i.min_quantity and i.min_quantity > 0 and (i.quantity or 0) <= i.min_quantity]


@router.get("/barcode/{code}")
def pantry_barcode_lookup(code: str, db: Session = Depends(get_db)):
    """Cerca un prodotto da codice a barre (Open Food Facts): nome, marca,
    quantità confezione e valori nutrizionali per 100 g, per pre-compilare
    l'aggiunta in dispensa (stile Yuka)."""
    res = lookup_barcode(code)
    if res is None:
        raise HTTPException(status_code=502, detail="Servizio barcode non raggiungibile.")
    if res.get("found") and label_values(res.get("nutrition")):
        res["estimated_matches"] = _estimated_matches(db, res.get("name") or "")
    return res


def _estimated_matches(db: Session, product_name: str) -> list:
    """Prodotti in dispensa dello stesso cibo, senza barcode e con valori solo
    stimati (o nessuno): la scansione può dar loro quelli dell'etichetta.
    Una voce per nome, con quante confezioni sono."""
    out, index = [], {}
    for p in db.query(PantryItem).filter(PantryItem.barcode.is_(None)).all():
        source = (p.nutrition or {}).get("source") if isinstance(p.nutrition, dict) else None
        if (p.nutrition and source != "stima") or not same_food(product_name, p.name):
            continue
        key = norm_name(p.name)
        if key in index:
            out[index[key]]["count"] += 1
            continue
        index[key] = len(out)
        out.append({"id": p.id, "name": p.name, "count": 1, "nutrition": p.nutrition})
    return out


class LabelValuesBody(_BaseModel):
    nutrition: dict
    barcode: Optional[str] = None
    name: Optional[str] = None      # nome del prodotto scansionato (facoltativo)


@router.post("/items/{item_id}/label-values")
def set_label_values(item_id: str, body: LabelValuesBody, db: Session = Depends(get_db)):
    """Valori da etichetta (barcode) su un prodotto importato con la stima: si
    aggiornano tutte le sue confezioni senza barcode e, se veniva da uno
    scontrino, si ricorda l'abbinamento per gli scontrini futuri."""
    item = db.query(PantryItem).filter(PantryItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    values = label_values(body.nutrition)
    if not values:
        raise HTTPException(status_code=422, detail="Valori nutrizionali incompleti.")
    key = norm_name(item.name)
    receipt_names = set()
    rows = [p for p in db.query(PantryItem).filter(PantryItem.barcode.is_(None)).all()
            if norm_name(p.name) == key]
    new_name = (body.name or "").strip() or item.name
    for p in rows:
        receipt_names.update(s for s in (p.synonyms or []) if s and s == s.upper())
        p.nutrition = dict(values, source="etichetta")
        p.barcode = body.barcode
        p.name = new_name
    now = datetime.now().isoformat(timespec="seconds")
    for rn in receipt_names:     # dicitura dello scontrino (maiuscola, es. YOMO DELT.YOG.GR.CAF)
        link = db.query(ReceiptProductLink).filter(ReceiptProductLink.receipt_name == rn).first()
        if link is None:
            link = ReceiptProductLink(receipt_name=rn)
            db.add(link)
        link.product_name, link.barcode, link.nutrition, link.updated_at = \
            new_name, body.barcode, values, now
    db.commit()
    return {"updated": len(rows), "remembered": sorted(receipt_names), "name": new_name}

@router.post("/items", response_model=schemas.PantryItem)
def create_pantry_item(item: schemas.PantryItemCreate, db: Session = Depends(get_db)):
    """
    Add a new item to the pantry.
    An ID is generated automatically.
    """
    db_item = PantryItem(**item.model_dump(), id=str(uuid.uuid4()))
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@router.get("/items", response_model=List[schemas.PantryItem])
def read_pantry_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Retrieve all pantry items.
    """
    items = db.query(PantryItem).offset(skip).limit(limit).all()
    return items

@router.get("/items/{item_id}", response_model=schemas.PantryItem)
def read_pantry_item(item_id: str, db: Session = Depends(get_db)):
    """
    Retrieve a single pantry item by ID.
    """
    db_item = db.query(PantryItem).filter(PantryItem.id == item_id).first()
    if db_item is None:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    return db_item

@router.put("/items/{item_id}", response_model=schemas.PantryItem)
def update_pantry_item(item_id: str, item: schemas.PantryItemBase, db: Session = Depends(get_db)):
    """
    Update a pantry item.
    """
    db_item = db.query(PantryItem).filter(PantryItem.id == item_id).first()
    if db_item is None:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    
    update_data = item.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_item, key, value)
        
    db.commit()
    db.refresh(db_item)
    return db_item

@router.delete("/items/{item_id}", response_model=schemas.PantryItem)
def delete_pantry_item(item_id: str, db: Session = Depends(get_db)):
    """
    Delete a pantry item.
    """
    db_item = db.query(PantryItem).filter(PantryItem.id == item_id).first()
    if db_item is None:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    db.delete(db_item)
    db.commit()
    return db_item


@router.post("/items/bulk")
def bulk_upsert_pantry_items(items: List[schemas.PantryItemCreate], db: Session = Depends(get_db)):
    """
    Aggiunge o aggiorna più ingredienti nella dispensa in una sola chiamata.
    Cerca per nome (case-insensitive): se esiste aggiorna quantity/unit/category,
    altrimenti crea un nuovo elemento.

    Esempio body:
    [
      {"name": "pasta", "quantity": 500, "unit": "g"},
      {"name": "pollo", "quantity": 300, "unit": "g", "category": "proteina"},
      {"name": "riso", "quantity": 1, "unit": "kg"}
    ]
    """
    created = 0
    updated = 0
    for item_data in items:
        existing = db.query(PantryItem).filter(
            PantryItem.name.ilike(item_data.name)
        ).first()
        if existing:
            existing.quantity = item_data.quantity
            existing.unit = item_data.unit
            if item_data.category is not None:
                existing.category = item_data.category
            if item_data.expiration_date is not None:
                existing.expiration_date = item_data.expiration_date
            updated += 1
        else:
            db_item = PantryItem(**item_data.model_dump(), id=str(uuid.uuid4()))
            db.add(db_item)
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "total": created + updated}


# ---------------------------------------------------------------------------
# Scontrini digitali Lidl Plus -> dispensa
#
# 1. POST /pantry/sync-lidl          anteprima dell'ultimo scontrino non ancora
#                                    importato (NON scrive in dispensa)
# 2. POST /pantry/sync-lidl/confirm  salva le righe riviste dall'utente
#    POST /pantry/sync-lidl/skip     oppure lo segna come visto senza importarlo
# ---------------------------------------------------------------------------

def _settings_row(db: Session) -> AppSettings:
    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    if row is None:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
    return row


def _lidl_access_token(db: Session) -> str:
    """Rinnova l'access token e salva SUBITO il refresh token ruotato: se lo
    si perdesse (eccezione più avanti) il collegamento sarebbe da rifare."""
    row = _settings_row(db)
    refresh = row.lidl_refresh_token or os.getenv("LIDL_REFRESH_TOKEN")
    if not refresh:
        raise HTTPException(status_code=400, detail={
            "code": "lidl_not_configured",
            "message": "Lidl Plus non collegato: incolla il refresh token."})
    try:
        access, new_refresh = lidl.refresh_access_token(refresh)
    except lidl.LidlAuthError as e:
        raise HTTPException(status_code=401, detail={"code": "lidl_auth", "message": str(e)})
    except lidl.LidlError as e:
        raise HTTPException(status_code=502, detail={"code": "lidl_unreachable", "message": str(e)})
    if new_refresh != row.lidl_refresh_token:
        row.lidl_refresh_token = new_refresh
        db.commit()
    return access


def _ticket_summary(t: dict) -> dict:
    store = t.get("store") or {}
    return {
        "id": str(t.get("id")),
        "date": str(t.get("date") or "")[:10],
        "total": t.get("totalAmount"),
        "store": store.get("name") if isinstance(store, dict) else None,
    }


class LidlTokenBody(_BaseModel):
    refresh_token: str


class LidlImportItem(schemas.PantryItemCreate):
    count: int = 1
    receipt_name: Optional[str] = None   # dicitura grezza: chiave dell'abbinamento
    linked: bool = False                 # valori da un prodotto scansionato: ricordarlo


class LidlConfirmBody(_BaseModel):
    ticket_id: str
    receipt_date: Optional[str] = None
    total_amount: Optional[float] = None
    items: List[LidlImportItem] = []


class LidlSkipBody(_BaseModel):
    ticket_id: str
    receipt_date: Optional[str] = None
    total_amount: Optional[float] = None


@router.get("/lidl/status")
def lidl_status(db: Session = Depends(get_db)):
    row = _settings_row(db)
    last = db.query(LidlImport).order_by(LidlImport.receipt_date.desc()).limit(5).all()
    return {
        "configured": bool(row.lidl_refresh_token or os.getenv("LIDL_REFRESH_TOKEN")),
        "recent": [{"ticket_id": i.ticket_id, "date": i.receipt_date, "total": i.total_amount,
                    "items": i.items_count, "skipped": bool(i.skipped)} for i in last],
    }


@router.post("/lidl/token")
def lidl_set_token(body: LidlTokenBody, db: Session = Depends(get_db)):
    """Collega (o ricollega) l'account: il token si ottiene dal PC con manual_auth.py."""
    token = body.refresh_token.strip()
    if not token:
        raise HTTPException(status_code=422, detail="Token vuoto.")
    _settings_row(db).lidl_refresh_token = token
    db.commit()
    return {"configured": True}


@router.post("/sync-lidl")
def sync_lidl_preview(request: Request, ticket_id: Optional[str] = None,
                      db: Session = Depends(get_db)):
    """Anteprima dello scontrino più recente non ancora importato né saltato
    (o di `ticket_id`): articoli già normalizzati dall'LLM, da rivedere.
    Non scrive in dispensa."""
    access = _lidl_access_token(db)
    try:
        tickets = [_ticket_summary(t) for t in lidl.list_tickets(access)]
    except lidl.LidlAuthError as e:
        raise HTTPException(status_code=401, detail={"code": "lidl_auth", "message": str(e)})
    except lidl.LidlError as e:
        raise HTTPException(status_code=502, detail={"code": "lidl_unreachable", "message": str(e)})
    seen = {i.ticket_id for i in db.query(LidlImport.ticket_id).all()}
    pending = sorted([t for t in tickets if t["id"] not in seen],
                     key=lambda t: t["date"], reverse=True)
    if ticket_id:
        target = next((t for t in tickets if t["id"] == ticket_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Scontrino non trovato fra i recenti.")
    elif not pending:
        return {"ticket": None, "items": [], "raw_items": [], "pending": []}
    else:
        target = pending[0]

    try:
        detail = lidl.get_ticket(target["id"], access)
    except lidl.LidlError as e:
        raise HTTPException(status_code=502, detail={"code": "lidl_unreachable", "message": str(e)})
    raw_items = lidl.extract_items(detail)
    receipt_date = str(detail.get("date") or target["date"])[:10] or date.today().isoformat()

    known = collect_known_products(db)
    gw = getattr(request.app.state, "llm_gateway", None)
    items = (gw.normalize_lidl_receipt(raw_items, receipt_date, [k["name"] for k in known])
             if gw else None)
    if items is None:
        raise HTTPException(status_code=503, detail={
            "code": "llm_unavailable",
            "message": "L'AI non ha risposto: riprova (lo scontrino non è stato importato)."})
    links = {l.receipt_name: l for l in db.query(ReceiptProductLink).all()}
    items = [_with_label_values(it, known, links) for it in items]
    meals = _meals_since(db, receipt_date)
    for it in items:
        it["eaten_after"], it["eaten_grams"] = _eaten_in(meals, it)
        bought = (it.get("quantity") or 0) * (it.get("count") or 1)
        # Già mangiato almeno metà dopo l'acquisto: lo si dà per finito (il resto è
        # andato nello stesso piatto, spesso registrato per un profilo solo, o è da
        # buttare). Sotto, resta spuntato con la nota dei grammi usati.
        it["eaten_all"] = bool(it["eaten_after"]) and (
            it.get("unit") not in ("g", "ml") or it["eaten_grams"] >= 0.5 * bought)
    return {
        "ticket": dict(target, date=receipt_date, already_imported=target["id"] in seen),
        "raw_items": raw_items,
        "items": items,
        "known_products": known,
        "pending": [t for t in pending if t["id"] != target["id"]],
    }


def _meals_since(db: Session, since: str) -> list:
    """Pasti registrati dal giorno dello scontrino (compreso) a oggi:
    [{date, meal_type, name, ingredients}]. Servono a capire se qualcosa della
    spesa è già stato mangiato prima di importarla (i pasti del piano non
    scalano la dispensa, quindi l'import la gonfierebbe)."""
    from ..scaling import _recipe_content
    from ..nutrition import _content_ingredients
    from ..database import Recipe, CandidateRecipe, ConsumedEntry
    if not since or since >= date.today().isoformat():
        return []
    names = {}

    def recipe_name(rid):
        if rid not in names:
            r = db.query(Recipe).filter(Recipe.id == rid).first() or \
                db.query(CandidateRecipe).filter(CandidateRecipe.id == rid).first()
            names[rid] = getattr(r, "name", None)
        return names[rid]

    def grams(ing: dict, profile_id: str) -> float:
        q = (ing.get("quantities") or {})
        q = q.get(profile_id) or q.get("persona_a") or q.get("persona_b") or {}
        try:
            return float(q.get("grams_equiv") or q.get("qty") or ing.get("qty") or ing.get("grams") or 0)
        except (TypeError, ValueError):
            return 0.0

    out = []
    rows = db.query(ConsumedEntry).filter(ConsumedEntry.date >= since,
                                          ConsumedEntry.type != "skipped").all()
    for e in sorted(rows, key=lambda e: (e.date, e.meal_type or "")):
        details = e.override_details if isinstance(e.override_details, dict) else {}
        ings = [i for i in details.get("ingredients") or [] if isinstance(i, dict)]
        name = details.get("free_text_name")
        if not ings and e.consumed_recipe_id:
            ings = _content_ingredients(_recipe_content(db, e.consumed_recipe_id))
            name = recipe_name(e.consumed_recipe_id)
        ings = [(i.get("name"), grams(i, e.profile_id)) for i in ings if i.get("name")]
        if ings:             # una riga per profilo: i grammi si sommano
            out.append({"date": e.date, "meal_type": e.meal_type, "name": name or e.meal_type,
                        "ingredients": ings})
    return out


def _eaten_in(meals: list, item: dict):
    """(pasti in cui compare il prodotto, grammi mangiati in tutto)."""
    names = {item.get("name"), item.get("ai_name")} - {None, ""}
    found, seen, total = [], set(), 0.0
    for m in meals:
        used = [gr for ing, gr in m["ingredients"] if any(same_food(ing, n) for n in names)]
        if not used:
            continue
        total += sum(used)
        key = (m["date"], m["meal_type"], m["name"])
        if key not in seen:          # stesso pasto per i due profili: una voce
            seen.add(key)
            found.append({"date": m["date"], "meal_type": m["meal_type"], "name": m["name"]})
    return found, round(total)


def _with_label_values(item: dict, known: list, links: dict) -> dict:
    """Valori per 100 g della riga, in ordine di affidabilità:
    1. abbinamento già confermato dall'utente per questa dicitura di scontrino
    2. prodotto scansionato che l'AI riconosce come lo stesso
    3. stima dell'AI per quel prodotto (marca e linea comprese)
    `match` = indice in `known` (o None); `ai_name` = nome proposto dall'AI,
    per tornarci se nella finestra si sceglie la stima."""
    item = dict(item)
    item["ai_name"] = item["name"]
    est = item.pop("estimated_nutrition", None)
    item["ai_nutrition"] = dict(est, source="stima") if est else None
    link = links.get(item.get("receipt_name") or "")
    product = None
    if link and label_values(link.nutrition):
        product = {"name": link.product_name, "barcode": link.barcode,
                   "nutrition": label_values(link.nutrition)}
        item["match_from"] = "ricordato"
    elif item.get("known_product") is not None:
        product = known[item["known_product"]]
        item["match_from"] = "ai"
    item.pop("known_product", None)
    if product:
        norm = norm_name(product["name"])
        item["match"] = next((i for i, k in enumerate(known) if norm_name(k["name"]) == norm), None)
        if item["match"] is None:          # ricordato ma non più fra i noti: lo si aggiunge
            known.append(product)
            item["match"] = len(known) - 1
        item["name"] = product["name"]
        item["barcode"] = product.get("barcode")
        item["nutrition"] = dict(product["nutrition"], source="etichetta")
    else:
        item["match"] = None
        item["match_from"] = None
        item["barcode"] = None
        item["nutrition"] = item["ai_nutrition"]
    return item


def _valid_iso(d: Optional[str]) -> Optional[str]:
    try:
        return date.fromisoformat(d[:10]).isoformat() if d else None
    except ValueError:
        return None


def _mark_seen(db: Session, ticket_id: str, receipt_date, total, items_count: int, skipped: bool):
    if db.query(LidlImport).filter(LidlImport.ticket_id == ticket_id).first():
        raise HTTPException(status_code=409, detail="Scontrino già importato.")
    db.add(LidlImport(ticket_id=ticket_id, receipt_date=_valid_iso(receipt_date),
                      total_amount=total, items_count=items_count, skipped=skipped,
                      imported_at=datetime.now().isoformat(timespec="seconds")))


def _remember_link(db: Session, it: "LidlImportItem", now: str) -> None:
    """Abbinamento confermato -> ricordato per gli scontrini futuri; se per una
    dicitura già abbinata si è scelta la stima, l'abbinamento si dimentica."""
    if not it.receipt_name:
        return
    link = db.query(ReceiptProductLink).filter(
        ReceiptProductLink.receipt_name == it.receipt_name).first()
    values = label_values(it.nutrition)
    if it.linked and values:
        if link is None:
            link = ReceiptProductLink(receipt_name=it.receipt_name)
            db.add(link)
        link.product_name, link.barcode = it.name, it.barcode
        link.nutrition, link.updated_at = values, now
    elif link is not None:
        db.delete(link)


@router.post("/sync-lidl/confirm")
def sync_lidl_confirm(body: LidlConfirmBody, db: Session = Depends(get_db)):
    """Salva le righe riviste: una riga di dispensa per confezione (come col
    barcode), così il consumo scala prima le confezioni aperte."""
    _mark_seen(db, body.ticket_id, body.receipt_date, body.total_amount,
               sum(max(1, it.count) for it in body.items), skipped=False)
    created = 0
    now = datetime.now().isoformat(timespec="seconds")
    for it in body.items:
        _remember_link(db, it, now)
        data = it.model_dump(exclude={"count", "receipt_name", "linked"})
        data["expiration_date"] = _valid_iso(data.get("expiration_date"))
        for _ in range(max(1, min(it.count, 50))):
            db.add(PantryItem(**data, id=str(uuid.uuid4())))
            created += 1
    db.commit()
    _LOG.info("Lidl: scontrino %s importato, %d righe in dispensa", body.ticket_id, created)
    return {"created": created, "ticket_id": body.ticket_id}


@router.post("/sync-lidl/skip")
def sync_lidl_skip(body: LidlSkipBody, db: Session = Depends(get_db)):
    """Segna lo scontrino come visto senza importare nulla (es. spesa vecchia)."""
    _mark_seen(db, body.ticket_id, body.receipt_date, body.total_amount, 0, skipped=True)
    db.commit()
    return {"skipped": body.ticket_id}