from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..planner import PlannerEngine
from ..database import get_db
from .. import schemas
from datetime import date

router = APIRouter(prefix="/shopping-list", tags=["shopping-list"])

@router.get("", response_model=schemas.AggregatedShoppingList)
async def get_shopping_list(
    profile_id_A: str,
    profile_id_B: str,
    start_date: date,
    db: Session = Depends(get_db)
):
    """
    Generate a shopping list for a given week.
    """
    planner = PlannerEngine(db)
    return planner.generate_shopping_list_for_week(profile_id_A, profile_id_B, start_date)
