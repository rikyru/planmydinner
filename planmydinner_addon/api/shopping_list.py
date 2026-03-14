from fastapi import APIRouter, Depends
from fastapi.responses import Response
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
    exclude_consumed: bool = False,
    db: Session = Depends(get_db)
):
    """
    Generate a shopping list for a given week.
    If exclude_consumed=true, skips meals already marked as consumed from the plan.
    """
    planner = PlannerEngine(db)
    return planner.generate_shopping_list_for_week(profile_id_A, profile_id_B, start_date, exclude_consumed)


@router.get("/export/csv")
async def export_shopping_list_csv(
    profile_id_A: str,
    profile_id_B: str,
    start_date: date,
    exclude_consumed: bool = False,
    db: Session = Depends(get_db)
):
    """
    Export the shopping list as a CSV file.
    """
    planner = PlannerEngine(db)
    shopping_list = planner.generate_shopping_list_for_week(profile_id_A, profile_id_B, start_date, exclude_consumed)
    lines = ["Nome,Quantità,Unità,Categoria"]
    for category, items in shopping_list.items_by_category.items():
        for item in items:
            lines.append(f"{item.name},{item.quantity},{item.unit},{category}")
    csv_content = "\n".join(lines)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=lista_spesa.csv"}
    )
