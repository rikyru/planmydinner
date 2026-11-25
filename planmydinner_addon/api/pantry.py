from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime
import logging
import os
import uuid

from .. import lidl, schemas
from ..barcode import lookup_barcode
from ..database import get_db, PantryItem, AppSettings, LidlImport
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
    items_only = [it for it, _ in expiring]
    scored = []
    for r in eng._get_all_recipes():
        ings = r.content.components if r.is_composed_dish else r.content
        uses = [it.name for it in items_only
                if any(eng._pantry_matches(getattr(i, "name", "") or "", [it]) for i in ings)]
        if uses:
            scored.append({"id": r.id, "name": r.name, "uses": uses, "n": len(uses)})
    scored.sort(key=lambda x: -x["n"])
    return {
        "expiring": [{"name": it.name, "expiration_date": it.expiration_date, "days": n}
                     for it, n in sorted(expiring, key=lambda x: x[1])],
        "recipes": scored[:limit],
    }


@router.get("/low-stock", response_model=List[schemas.PantryItem])
def low_stock_items(db: Session = Depends(get_db)):
    """Articoli scesi a/sotto la loro soglia minima (da ricomprare)."""
    items = db.query(PantryItem).all()
    return [i for i in items
            if i.min_quantity and i.min_quantity > 0 and (i.quantity or 0) <= i.min_quantity]


@router.get("/barcode/{code}")
def pantry_barcode_lookup(code: str):
    """Cerca un prodotto da codice a barre (Open Food Facts): nome, marca,
    quantità confezione e valori nutrizionali per 100 g, per pre-compilare
    l'aggiunta in dispensa (stile Yuka)."""
    res = lookup_barcode(code)
    if res is None:
        raise HTTPException(status_code=502, detail="Servizio barcode non raggiungibile.")
    return res

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

    gw = getattr(request.app.state, "llm_gateway", None)
    items = gw.normalize_lidl_receipt(raw_items, receipt_date) if gw else None
    if items is None:
        raise HTTPException(status_code=503, detail={
            "code": "llm_unavailable",
            "message": "L'AI non ha risposto: riprova (lo scontrino non è stato importato)."})
    return {
        "ticket": dict(target, date=receipt_date, already_imported=target["id"] in seen),
        "raw_items": raw_items,
        "items": items,
        "pending": [t for t in pending if t["id"] != target["id"]],
    }


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


@router.post("/sync-lidl/confirm")
def sync_lidl_confirm(body: LidlConfirmBody, db: Session = Depends(get_db)):
    """Salva le righe riviste: una riga di dispensa per confezione (come col
    barcode), così il consumo scala prima le confezioni aperte."""
    _mark_seen(db, body.ticket_id, body.receipt_date, body.total_amount,
               sum(max(1, it.count) for it in body.items), skipped=False)
    created = 0
    for it in body.items:
        data = it.model_dump(exclude={"count"})
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