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
from datetime import date, timedelta

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
    Uploads a PDF meal plan, extracts its text, and parses it via LLM.
    Falls back to regex-based parsing if LLM is unavailable.
    """
    if not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo file PDF sono accettati.")

    temp_dir = tempfile.gettempdir()
    temp_pdf_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")
    try:
        with open(temp_pdf_path, "wb") as buffer:
            shutil.copyfileobj(pdf_file.file, buffer)

        # Estrai testo dal PDF con pdfminer
        from pdfminer.high_level import extract_text as pdf_extract_text
        try:
            text_content = pdf_extract_text(temp_pdf_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Impossibile leggere il PDF: {e}")

        if not text_content or not text_content.strip():
            raise HTTPException(status_code=400, detail="Il PDF non contiene testo estraibile. Prova a incollare il contenuto nella tab Testo.")

        llm_gateway = request.app.state.llm_gateway

        # Se LLM disponibile: usa la stessa logica di /import/text
        if llm_gateway:
            return await _parse_text_with_llm(text_content, profile_id, llm_gateway)

        # Fallback: parser regex
        parser = PDFParser(db, llm_gateway=None)
        structured_plan = parser.parse_pdf(temp_pdf_path, profile_id, template_name)
        return structured_plan

    except PDFParsingError as e:
        raise HTTPException(status_code=400, detail=f"Errore nel parsing PDF: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore interno durante l'import PDF: {e}")
    finally:
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)

async def _parse_text_with_llm(text_content: str, profile_id: str, llm_gateway) -> schemas.StructuredMealPlan:
    """Parsa un testo di piano alimentare usando l'LLM e restituisce un StructuredMealPlan."""
    import json, re

    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    prompt = f"""Analizza il seguente piano alimentare settimanale in formato testo e restituisci un JSON strutturato.

Il JSON deve seguire questo schema esatto:
{{
  "profile_id": "{profile_id}",
  "start_date": "{week_start.isoformat()}",
  "rotation_rules": [],
  "allowed_cooking_methods": [],
  "daily_plans": [
    {{
      "date": "YYYY-MM-DD",
      "meals": [
        {{
          "meal_type": "pranzo",
          "items": [
            {{"item_name": "Nome alimento", "food_group": "gruppo", "quantity": 100, "unit": "g", "is_estimated_unit": false, "alternatives": []}}
          ]
        }},
        {{
          "meal_type": "cena",
          "items": []
        }}
      ]
    }}
  ]
}}

Includi 7 giorni partendo da {week_start.isoformat()}.
I food_group validi sono: carboidrati, verdure, frutta, proteina, legumi, pesce, pollo, carne_rossa, grassi, altro.

Testo del piano:
{text_content}

Rispondi SOLO con il JSON, senza testo aggiuntivo."""

    messages = [
        {"role": "system", "content": "Sei un assistente nutrizionale esperto. Rispondi SOLO con JSON valido, senza testo aggiuntivo."},
        {"role": "user", "content": prompt},
    ]
    try:
        if llm_gateway.provider == "openai":
            response = llm_gateway._client.chat.completions.create(
                model=llm_gateway.model,
                messages=messages,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
        elif llm_gateway.provider == "ollama":
            response = llm_gateway._client.chat(model=llm_gateway.model, messages=messages)
            raw = response["message"]["content"]
        else:
            raise HTTPException(status_code=503, detail="Provider LLM non supportato")

        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            raise HTTPException(status_code=422, detail="LLM non ha restituito un JSON valido")
        parsed = json.loads(json_match.group())
        parsed.setdefault("id", str(uuid.uuid4()))
        return schemas.StructuredMealPlan(**parsed)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nell'elaborazione del testo: {e}")


@router.post("/text", response_model=schemas.StructuredMealPlan)
async def import_text_meal_plan(
    request: Request,
    profile_id: str = Form(...),
    text_content: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Parses a free-text meal plan using the LLM and returns structured data.
    """
    llm_gateway = request.app.state.llm_gateway
    if not llm_gateway:
        raise HTTPException(status_code=503, detail="LLM non disponibile per import da testo")

    return await _parse_text_with_llm(text_content, profile_id, llm_gateway)


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