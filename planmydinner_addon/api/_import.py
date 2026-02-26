from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List
import uuid
import shutil
import os
import tempfile

from .. import schemas
from ..database import get_db, StructuredMealPlan
from ..pdf_parser import PDFParser, PDFParsingError

router = APIRouter(
    prefix="/import",
    tags=["import"],
)

@router.post("/pdf", response_model=schemas.StructuredMealPlan)
async def import_pdf_meal_plan(
    request: Request,
    profile_id: str = Form(...),
    pdf_file: UploadFile = File(...),
    template_name: str = Form("default"),
    db: Session = Depends(get_db)
):
    """
    Uploads and parses a PDF meal plan, then returns the structured data.
    """
    if not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    # Save the uploaded PDF temporarily in a cross-platform way
    temp_dir = tempfile.gettempdir()
    temp_pdf_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")
    try:
        with open(temp_pdf_path, "wb") as buffer:
            shutil.copyfileobj(pdf_file.file, buffer)
        
        llm_gateway = request.app.state.llm_gateway
        parser = PDFParser(db, llm_gateway=llm_gateway)
        structured_plan = parser.parse_pdf(temp_pdf_path, profile_id, template_name)

        return structured_plan
    except PDFParsingError as e:
        raise HTTPException(status_code=400, detail=f"PDF parsing error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error during PDF import: {e}")
    finally:
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)

@router.post("/save", status_code=201)
async def save_structured_meal_plan(
    plan: schemas.StructuredMealPlan,
    db: Session = Depends(get_db)
):
    """
    Saves a (potentially modified) structured meal plan to the database.
    """
    try:
        db_plan = StructuredMealPlan(**plan.model_dump())
        db.add(db_plan)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error while saving plan: {e}")
    return {"message": "Plan saved successfully"}