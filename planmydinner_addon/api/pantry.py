from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid

from .. import schemas
from ..database import get_db, PantryItem
from pydantic import BaseModel as _BaseModel

router = APIRouter(
    prefix="/pantry",
    tags=["pantry"],
)

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