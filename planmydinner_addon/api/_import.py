from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Dict, Any, Optional
from pydantic import BaseModel as _BaseModel
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

@router.post("/pdf")
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

def _build_import_prompt(text_content: str, profile_id: str) -> str:
    """Costruisce il prompt da inviare all'LLM per l'import del piano alimentare."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    return f"""Sei un parser deterministico di piani alimentari da testo estratto da PDF (pdfminer).
Devi restituire SOLO un JSON valido conforme allo schema richiesto.

CONTESTO
- Il testo proviene da pdfminer: potrebbe avere a capo irregolari, parole spezzate, colonne "Alternative" appiattite.
- Obiettivo: estrarre le regole (plan_rules) DIRETTAMENTE dal documento e generare daily_plans coerenti.

TASK 1 — Classificazione documento
- "calendar": contiene giorni specifici (Lunedì/Martedì o date) con pasti già assegnati.
- "template": contiene solo regole/grammature/opzioni senza giorni specifici.

TASK 2 — Estrazione plan_rules (OBBLIGATORIA, estrai SEMPRE direttamente dal testo)

a) carb_options e protein_options per PRANZO e CENA:
   - Includi TUTTE le opzioni elencate nel documento con quantità proprie.
   - Formato: [{{"name": "pasta", "quantity": 70, "unit": "g", "portion_text": null}}]
   - portion_text: se trovi "2 Fette 80g", metti portion_text="2 Fette" e quantity=80.
   - NON limitare alle sole opzioni usate nei daily_plans generati.
   - NON inventare opzioni non menzionate nel documento.
   - Se cena non ha opzioni proprie, ometti la chiave "cena".

b) carb_target / protein_target: grammi target espliciti del documento per pranzo/cena. null se non specificato.

c) frequency_targets: frequenze settimanali per categoria proteica (min/max a settimana).
   Chiavi: carne_bianca, carne_rossa, pesce, legumi, uova, formaggio.

d) free_meal_quota: numero di pasti/giorni liberi a settimana. null se non menzionato.

e) meal_slots: struttura completa della giornata tipo del documento.
   Sezioni: colazione, spuntino_mattina, pranzo, merenda, cena, idratazione (solo quelle presenti).
   Formato item: {{"name": string, "quantity": number|null, "unit": "g"|"ml"|"L"|null, "portion_text": string|null, "alternatives": [...]}}

f) rotation_rules: vincoli strutturati per categoria proteica (es. max carne rossa 1/sett).

REGOLE CRITICHE DI PARSING (NON VIOLABILI)

1) ALTERNATIVE BINDING:
   Quando compare "Alternative:" (anche su riga separata), le righe successive con alimento+quantità
   sono alternative dell'item BASE immediatamente precedente.
   Lo stop avviene solo quando trovi una nuova sezione (COLAZIONE/PRANZO/CENA/MERENDA/CENA/ecc.)
   oppure un nuovo item base di pari livello.

2) ALTERNATIVE CON QUANTITÀ:
   Ogni alternativa deve essere {{"name": "...", "quantity": N, "unit": "g"}} — NON stringa semplice.

3) RIGHE SPEZZATE:
   Se il nome dell'alimento è spezzato su più righe (es. "Prosciutto cotto" poi "sgrassato 100 g"),
   concatena le parti finché non trovi "numero + unità".

4) PORZIONE TESTUALE:
   "1 Tazzina 30 g" → quantity=30, unit="g", portion_text="1 Tazzina"
   "3 Fette e 1/2 100 g" → quantity=100, unit="g", portion_text="3 Fette e 1/2"

5) UNITÀ: usa solo "g", "ml", "L".

6) DETERMINISMO: mantieni l'ordine in cui le opzioni compaiono nel documento.

TASK 3 — Generazione daily_plans

SE document_type = "calendar":
- Usa ESATTAMENTE i pasti indicati per ciascun giorno.
- Mappa il primo giorno trovato a {week_start.isoformat()} e i successivi ai giorni seguenti.
- Le alternative vanno in alternatives[], NON come pasti separati.
- NON inventare alimenti, NON cambiare le grammature.

SE document_type = "template":
- Genera 7 giorni partendo da {week_start.isoformat()}.
- Scegli 1 carb_option + 1 protein_option per pranzo e cena rispettando frequency_targets.
- Rispetta: carne_rossa max 1/sett, carne_bianca 2-3/sett, legumi 3-5/sett, uova 2-4/sett, formaggio max 2/sett.
- Non lasciare mai meals.items vuoto.

SCHEMA OUTPUT ESATTO:
{{
  "profile_id": "{profile_id}",
  "start_date": "{week_start.isoformat()}",
  "rotation_rules": [
    {{"food_group_or_item": "carne_rossa", "max_per_week": 1, "min_per_week": 0, "is_hard_constraint": true}}
  ],
  "allowed_cooking_methods": [],
  "plan_rules": {{
    "carb_target": {{"pranzo": 80, "cena": null}},
    "protein_target": {{"pranzo": 150, "cena": null}},
    "carb_options": {{
      "pranzo": [{{"name": "pasta", "quantity": 70, "unit": "g", "portion_text": null}}],
      "cena": [{{"name": "pane", "quantity": 80, "unit": "g", "portion_text": "2 Fette"}}]
    }},
    "protein_options": {{
      "pranzo": [{{"name": "pollo", "quantity": 120, "unit": "g", "portion_text": null}}],
      "cena": [{{"name": "salmone", "quantity": 120, "unit": "g", "portion_text": null}}]
    }},
    "frequency_targets": {{
      "carne_bianca": {{"min": 2, "max": 3}},
      "carne_rossa": {{"min": 0, "max": 1}},
      "pesce": {{"min": 2, "max": 3}},
      "legumi": {{"min": 2, "max": 4}},
      "uova": {{"min": 1, "max": 3}},
      "formaggio": {{"min": 0, "max": 2}}
    }},
    "free_meal_quota": null,
    "meal_slots": {{
      "colazione": {{ "notes": null, "items": [{{"name": "pane", "quantity": 50, "unit": "g", "portion_text": "2 Fette", "alternatives": []}}] }},
      "spuntino_mattina": {{ "notes": null, "items": [] }},
      "pranzo": {{ "notes": null, "items": [] }},
      "merenda": {{ "notes": null, "items": [] }},
      "cena": {{ "notes": null, "items": [] }},
      "idratazione": {{ "notes": null, "items": [] }}
    }},
    "rotation_rules": [
      {{"group": "carne_rossa", "max_per_week": 1}},
      {{"group": "carne_bianca", "min_per_week": 2, "max_per_week": 3}}
    ]
  }},
  "daily_plans": [
    {{
      "date": "YYYY-MM-DD",
      "meals": [
        {{
          "meal_type": "pranzo",
          "items": [
            {{"item_name": "Nome alimento", "food_group": "carboidrati", "quantity": 80, "unit": "g", "is_estimated_unit": false, "alternatives": []}}
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

I food_group validi per daily_plans: carboidrati, verdure, frutta, proteina, legumi, pesce, pollo, carne_rossa, grassi, altro.
Le grammature nei daily_plans devono corrispondere alle quantità delle opzioni scelte.

Testo del piano:
{text_content}

Rispondi SOLO con il JSON, senza testo aggiuntivo."""


async def _parse_text_with_llm(text_content: str, profile_id: str, llm_gateway) -> Dict[str, Any]:
    """Parsa un testo di piano alimentare usando l'LLM.
    Restituisce {"plan": StructuredMealPlan dict, "plan_rules": dict | None}."""
    import json, re

    prompt = _build_import_prompt(text_content, profile_id)

    try:
        raw = llm_gateway.generate_meal_plan_json(prompt)
        if not raw:
            raise HTTPException(status_code=503, detail="LLM non ha restituito una risposta")

        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            raise HTTPException(status_code=422, detail="LLM non ha restituito un JSON valido")
        parsed = json.loads(json_match.group())
        parsed.setdefault("id", str(uuid.uuid4()))

        # Extract plan_rules before building StructuredMealPlan (it's not part of that schema)
        plan_rules_raw = parsed.pop("plan_rules", None)

        # Strip alternatives: LLM spesso restituisce stringhe anziché PlannedItem
        for day in parsed.get("daily_plans", []):
            for meal in day.get("meals", []):
                for item in meal.get("items", []):
                    item["alternatives"] = []

        plan = schemas.StructuredMealPlan(**parsed)
        return {"plan": plan.model_dump(), "plan_rules": plan_rules_raw}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nell'elaborazione del testo: {e}")


@router.post("/pdf-debug")
async def debug_pdf_import(
    request: Request,
    profile_id: str = Form(...),
    pdf_file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Debug endpoint: esegue la pipeline PDF → pdfminer → LLM senza salvare nulla.
    Restituisce il testo estratto, il prompt inviato all'LLM e la risposta grezza.
    """
    import json, re

    if not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo file PDF sono accettati.")

    temp_dir = tempfile.gettempdir()
    temp_pdf_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")
    try:
        with open(temp_pdf_path, "wb") as buffer:
            shutil.copyfileobj(pdf_file.file, buffer)

        # Step 1: pdfminer
        from pdfminer.high_level import extract_text as pdf_extract_text
        try:
            pdf_text = pdf_extract_text(temp_pdf_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"pdfminer error: {e}")

        result = {
            "pdf_text_length": len(pdf_text),
            "pdf_text": pdf_text,
            "llm_prompt": None,
            "llm_raw_response": None,
            "llm_error": None,
        }

        # Step 2: build prompt
        prompt = _build_import_prompt(pdf_text, profile_id)
        result["llm_prompt"] = prompt

        # Step 3: call LLM
        llm_gateway = request.app.state.llm_gateway
        if not llm_gateway:
            result["llm_error"] = "LLM non configurato"
            return result

        try:
            # use_cache=False nel debug: vogliamo sempre risposta fresca
            result["llm_raw_response"] = llm_gateway.generate_meal_plan_json(prompt, use_cache=False)
        except Exception as e:
            result["llm_error"] = str(e)

        return result

    finally:
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)


@router.post("/text")
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


def _build_recipe_name_from_items(items: list) -> str:
    """Builds a display name for a recipe from its PlannedItem list."""
    group_order = ["proteina", "pollo", "carne_rossa", "pesce", "legumi", "uova", "carboidrati", "verdure"]
    sorted_items = sorted(
        items,
        key=lambda x: group_order.index(x.food_group) if x.food_group in group_order else 99
    )
    names = [i.item_name for i in sorted_items[:3]]
    if len(names) == 1:
        return names[0]
    elif len(names) == 2:
        return f"{names[0]} con {names[1]}"
    return f"{names[0]} con {names[1]} e {names[2]}"


def _create_recipes_from_plan(plan: schemas.StructuredMealPlan, db: Session, skip_names: Optional[List[str]] = None):
    """For each unique meal in the plan, creates a Recipe in the DB (skips duplicates by name)."""
    skip_lower = {n.lower().strip() for n in (skip_names or [])}
    seen_fps: set = set()
    for day in plan.daily_plans:
        for meal in day.meals:
            if not meal.items:
                continue
            fp = frozenset(i.item_name.lower().strip() for i in meal.items)
            if fp in seen_fps:
                continue
            seen_fps.add(fp)

            name = _build_recipe_name_from_items(meal.items)
            if name.lower().strip() in skip_lower:
                continue
            if db.query(database.Recipe).filter(
                func.lower(database.Recipe.name) == name.lower()
            ).first():
                continue

            content = [
                {
                    "name": item.item_name,
                    "food_group": item.food_group,
                    "quantities": {
                        plan.profile_id: {"qty": item.quantity, "unit": item.unit}
                    },
                }
                for item in meal.items
            ]
            recipe = database.Recipe(
                id=str(uuid.uuid4()),
                name=name,
                is_composed_dish=len(meal.items) > 1,
                content=content,
                steps=[],
                total_time_minutes=30,
                difficulty="facile",
                tags={"imported": ["true"]},
            )
            db.add(recipe)


class SavePlanBody(_BaseModel):
    plan: schemas.StructuredMealPlan
    skip_recipe_names: List[str] = []
    target_override: Optional[Dict[str, Any]] = None        # legacy: {"carb": {"pranzo": 80}, "protein": {"pranzo": 120}}
    plan_rules_override: Optional[Dict[str, Any]] = None    # direct extraction: {carb_target, protein_target, carb_options, protein_options, frequency_targets, free_meal_quota}


def _plan_rules_from_override(plan: schemas.StructuredMealPlan, override: Dict[str, Any]) -> schemas.PlanRules:
    """Builds PlanRules from the directly-extracted plan_rules dict."""
    freq = dict(override.get("frequency_targets") or {})
    # Also apply rotation_rules from the plan (for calendar-type imports)
    _fg_to_cat = {
        "pollo": "carne_bianca", "carne_bianca": "carne_bianca",
        "carne_rossa": "carne_rossa", "pesce": "pesce",
        "legumi": "legumi", "uova": "uova", "proteina": "uova",
    }
    for rule in (plan.rotation_rules or []):
        fg = (rule.food_group_or_item if hasattr(rule, "food_group_or_item")
              else rule.get("food_group_or_item", "")).lower()
        cat = _fg_to_cat.get(fg)
        if not cat:
            continue
        max_pw = rule.max_per_week if hasattr(rule, "max_per_week") else rule.get("max_per_week")
        min_pw = rule.min_per_week if hasattr(rule, "min_per_week") else rule.get("min_per_week")
        if cat not in freq:
            freq[cat] = {}
        if max_pw is not None:
            freq[cat]["max"] = max_pw
        if min_pw is not None:
            freq[cat]["min"] = min_pw

    return schemas.PlanRules(
        id=str(uuid.uuid4()),
        profile_id=plan.profile_id,
        imported_at=date.today().isoformat(),
        carb_target=override.get("carb_target"),
        protein_target=override.get("protein_target"),
        carb_options=override.get("carb_options"),
        protein_options=override.get("protein_options"),
        frequency_targets=freq or None,
        free_meal_quota=override.get("free_meal_quota"),
        meal_slots=override.get("meal_slots"),
    )


@router.post("/save", status_code=201)
async def save_structured_meal_plan(
    body: SavePlanBody,
    db: Session = Depends(get_db)
):
    """
    Saves a (potentially modified) structured meal plan to the database.
    Also derives and upserts PlanRules from the plan, and creates Recipe entries.
    skip_recipe_names: recipe names the user chose NOT to import.
    """
    plan = body.plan
    try:
        db_plan = StructuredMealPlan(**plan.model_dump())
        db.add(db_plan)

        # Derive and upsert PlanRules
        if body.plan_rules_override:
            # Use directly-extracted plan_rules (richer: includes carb_options, protein_options)
            plan_rules = _plan_rules_from_override(plan, body.plan_rules_override)
        else:
            # Legacy: derive from daily_plans by averaging
            plan_rules = _derive_plan_rules(plan)
        # Apply legacy gram-only overrides on top if provided
        if body.target_override:
            if body.target_override.get("carb"):
                plan_rules.carb_target = body.target_override["carb"]
            if body.target_override.get("protein"):
                plan_rules.protein_target = body.target_override["protein"]
        db.query(database.PlanRules).filter(
            database.PlanRules.profile_id == plan.profile_id
        ).delete()
        db_rules = database.PlanRules(**plan_rules.model_dump())
        db.add(db_rules)

        # Create Recipe entries for each unique meal (skipping user-excluded ones)
        _create_recipes_from_plan(plan, db, skip_names=body.skip_recipe_names)

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error while saving plan: {e}")
    return {"message": "Plan saved successfully"}