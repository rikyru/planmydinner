from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any
import uuid
import shutil
import os
import tempfile

from .. import schemas
from .. import database
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
  "rotation_rules": [
    {{"food_group_or_item": "carne_rossa", "max_per_week": 1, "min_per_week": 0, "is_hard_constraint": true}}
  ],
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

IMPORTANTE: rotation_rules deve contenere le frequenze settimanali menzionate nel piano.
Usa food_group_or_item con valori: pollo, carne_rossa, pesce, legumi, uova.
Esempio: {{"food_group_or_item":"carne_rossa","max_per_week":1,"min_per_week":0,"is_hard_constraint":true}}
Se il piano non menziona frequenze esplicite, lascia rotation_rules come lista vuota [].

IMPORTANTE sulle quantità: usa le grammature TARGET tipiche del piano (ripeti gli stessi grammi
ogni giorno, non inventare variazioni). Esempio: se il piano indica "80g pasta a pranzo", scrivi
80g in tutti i giorni.
IMPORTANTE sulle rotation_rules: estrai TUTTE le frequenze settimanali menzionate.
Usa food_group_or_item: pollo, carne_rossa, pesce, legumi, uova, carne_bianca.
Es: {{"food_group_or_item":"carne_rossa","max_per_week":1,"min_per_week":0,"is_hard_constraint":true}}

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


def _derive_plan_rules(plan: schemas.StructuredMealPlan) -> schemas.PlanRules:
    """
    Derives PlanRules from a StructuredMealPlan by averaging grams and collecting options.
    """
    # Accumulate totals for averaging
    carb_sums: Dict[str, List[float]] = {}
    protein_sums: Dict[str, List[float]] = {}
    carb_opts: Dict[str, set] = {}
    protein_opts: Dict[str, set] = {}

    protein_food_groups = {"proteina", "proteine", "pollo", "pesce", "carne_rossa", "legumi", "uova"}
    carb_food_groups = {"carboidrati", "carboidrato"}

    for dp in plan.daily_plans:
        for meal in dp.meals:
            mt = meal.meal_type
            for item in meal.items:
                fg = (item.food_group or "").lower()
                name = (item.item_name or "").strip()
                qty = item.quantity or 0.0

                if fg in carb_food_groups and qty > 0:
                    carb_sums.setdefault(mt, []).append(qty)
                    if name and name.lower() not in carb_food_groups:
                        carb_opts.setdefault(mt, set()).add(name.lower())

                if fg in protein_food_groups and qty > 0:
                    protein_sums.setdefault(mt, []).append(qty)
                    if name and name.lower() not in protein_food_groups:
                        protein_opts.setdefault(mt, set()).add(name.lower())

    carb_target = {mt: round(sum(vals) / len(vals)) for mt, vals in carb_sums.items() if vals}
    protein_target = {mt: round(sum(vals) / len(vals)) for mt, vals in protein_sums.items() if vals}
    carb_options = {mt: sorted(opts) for mt, opts in carb_opts.items()}
    protein_options = {mt: sorted(opts) for mt, opts in protein_opts.items()}

    # Defaults for frequency_targets
    freq_defaults: Dict[str, Dict[str, Any]] = {
        "carne_bianca": {"min": 2, "max": 3, "hard_max": None},
        "carne_rossa":  {"min": 0, "max": 1, "hard_max": 1},
        "pesce":        {"min": 2, "max": 3, "hard_max": None},
        "legumi":       {"min": 3, "max": 5, "hard_max": None},
        "uova":         {"min": 2, "max": 4, "hard_max": None},
    }
    _fg_to_cat = {
        "pollo": "carne_bianca", "carne_bianca": "carne_bianca",
        "carne_rossa": "carne_rossa",
        "pesce": "pesce",
        "legumi": "legumi",
        "uova": "uova", "proteina": "uova",
    }
    frequency_targets = {k: dict(v) for k, v in freq_defaults.items()}
    for rule in (plan.rotation_rules or []):
        fg = (rule.food_group_or_item if hasattr(rule, "food_group_or_item")
              else rule.get("food_group_or_item", "")).lower()
        cat = _fg_to_cat.get(fg)
        if not cat:
            continue
        max_pw = (rule.max_per_week if hasattr(rule, "max_per_week")
                  else rule.get("max_per_week"))
        min_pw = (rule.min_per_week if hasattr(rule, "min_per_week")
                  else rule.get("min_per_week"))
        is_hard = (rule.is_hard_constraint if hasattr(rule, "is_hard_constraint")
                   else rule.get("is_hard_constraint", False))
        if cat not in frequency_targets:
            frequency_targets[cat] = {"min": 0, "max": 7, "hard_max": None}
        if max_pw is not None:
            frequency_targets[cat]["max"] = max_pw
            if is_hard:
                frequency_targets[cat]["hard_max"] = max_pw
        if min_pw is not None:
            frequency_targets[cat]["min"] = min_pw

    return schemas.PlanRules(
        id=str(uuid.uuid4()),
        profile_id=plan.profile_id,
        imported_at=date.today().isoformat(),
        carb_target=carb_target,
        protein_target=protein_target,
        carb_options=carb_options,
        protein_options=protein_options,
        frequency_targets=frequency_targets,
    )


@router.post("/save", status_code=201)
async def save_structured_meal_plan(
    plan: schemas.StructuredMealPlan,
    db: Session = Depends(get_db)
):
    """
    Saves a (potentially modified) structured meal plan to the database.
    Also derives and upserts PlanRules from the plan.
    """
    try:
        db_plan = StructuredMealPlan(**plan.model_dump())
        db.add(db_plan)

        # Derive and upsert PlanRules
        plan_rules = _derive_plan_rules(plan)
        db.query(database.PlanRules).filter(
            database.PlanRules.profile_id == plan.profile_id
        ).delete()
        db_rules = database.PlanRules(**plan_rules.model_dump())
        db.add(db_rules)

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error while saving plan: {e}")
    return {"message": "Plan saved successfully"}