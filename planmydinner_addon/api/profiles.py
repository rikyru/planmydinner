from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

import schemas
from database import get_db, UserProfile

router = APIRouter(
    prefix="/profiles",
    tags=["profiles"],
)

@router.post("/", response_model=schemas.UserProfile)
def create_user_profile(profile: schemas.UserProfileCreate, db: Session = Depends(get_db)):
    """
    Create a new user profile.
    """
    db_profile = db.query(UserProfile).filter(UserProfile.id == profile.id).first()
    if db_profile:
        raise HTTPException(status_code=400, detail="Profile with this ID already exists")
    db_profile = UserProfile(**profile.model_dump())
    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    return db_profile

@router.get("/", response_model=List[schemas.UserProfile])
def read_user_profiles(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Retrieve all user profiles.
    """
    profiles = db.query(UserProfile).offset(skip).limit(limit).all()
    return profiles

@router.get("/{profile_id}", response_model=schemas.UserProfile)
def read_user_profile(profile_id: str, db: Session = Depends(get_db)):
    """
    Retrieve a single user profile by ID.
    """
    db_profile = db.query(UserProfile).filter(UserProfile.id == profile_id).first()
    if db_profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return db_profile

@router.put("/{profile_id}", response_model=schemas.UserProfile)
def update_user_profile(profile_id: str, profile: schemas.UserProfileCreate, db: Session = Depends(get_db)):
    """
    Update a user profile.
    """
    db_profile = db.query(UserProfile).filter(UserProfile.id == profile_id).first()
    if db_profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    update_data = profile.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_profile, key, value)
        
    db.commit()
    db.refresh(db_profile)
    return db_profile

@router.delete("/{profile_id}", response_model=schemas.UserProfile)
def delete_user_profile(profile_id: str, db: Session = Depends(get_db)):
    """
    Delete a user profile.
    """
    db_profile = db.query(UserProfile).filter(UserProfile.id == profile_id).first()
    if db_profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(db_profile)
    db.commit()
    return db_profile