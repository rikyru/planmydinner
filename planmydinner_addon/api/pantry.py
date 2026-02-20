from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid

import schemas
from database import get_db, PantryItem

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