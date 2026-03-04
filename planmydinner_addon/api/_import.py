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
    return f"""CLASSIFICAZIONE DEL DOCUMENTO (OBBLIGATORIA)

Prima di generare il JSON, analizza il testo e determina il tipo di documento.

1) Se nel testo compaiono intestazioni di giorni della settimana (es. LUNEDÌ, MARTEDÌ, MERCOLEDÌ, GIOVEDÌ, VENERDÌ, SABATO, DOMENICA) e i pasti sono raggruppati per ciascun giorno, allora il documento è di tipo "calendar".

2) Se NON compaiono giorni della settimana e il documento contiene solo sezioni generiche (COLAZIONE, PRANZO, CENA) con liste di alternative e grammature, allora il documento è di tipo "template".

COMPORTAMENTO IN BASE AL TIPO:

=== SE document_type = "calendar" ===

- NON generare una settimana artificiale.
- Usa ESATTAMENTE i pasti presenti sotto ciascun giorno.
- Ogni giorno nel JSON deve corrispondere a un giorno reale trovato nel documento.
- Mappa il primo giorno trovato a {week_start.isoformat()} e i successivi ai giorni seguenti.
- Se il documento contiene meno di 7 giorni, replica la struttura dell'ultimo giorno disponibile per i giorni mancanti.
- Le alternative devono essere inserite nel campo "alternatives" degli item, NON trasformate in pasti separati.
- NON inventare alimenti. NON cambiare le grammature.

=== SE document_type = "template" ===

- Genera una settimana di 7 giorni partendo da {week_start.isoformat()}.
- Usa le regole di rotazione e le grammature target del documento.
- Compila sempre pranzo e cena per ogni giorno.
- Rispetta le frequenze settimanali come vincoli hard.
- Non lasciare mai meals.items vuoto.

Il JSON deve seguire questo schema esatto:
{{
  "profile_id": "{profile_id}",
  "start_date": "{week_start.isoformat()}",
  "rotation_rules": [
    {{"food_group_or_item": "carne_rossa", "max_per_week": 1, "min_per_week": 0, "is_hard_constraint": true}}
  ],
  "allowed_cooking_methods": [],
  "plan_rules": {{
    "carb_target": {{"pranzo": 80, "cena": 60}},
    "protein_target": {{"pranzo": 150, "cena": 130}},
    "carb_options": {{
      "pranzo": ["pasta", "riso", "farro", "couscous", "orzo"],
      "cena": ["pane", "patate", "polenta"]
    }},
    "protein_options": {{
      "pranzo": ["pollo", "tacchino", "salmone", "tonno", "uova", "legumi"],
      "cena": ["carne_bianca", "pesce", "uova"]
    }},
    "frequency_targets": {{
      "carne_bianca": {{"min": 2, "max": 3}},
      "carne_rossa": {{"min": 0, "max": 1}},
      "pesce": {{"min": 2, "max": 3}},
      "legumi": {{"min": 2, "max": 4}},
      "uova": {{"min": 1, "max": 3}}
    }},
    "free_meal_quota": null
  }},
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

I food_group validi sono: carboidrati, verdure, frutta, proteina, legumi, pesce, pollo, carne_rossa, grassi, altro.

IMPORTANTE sulle rotation_rules: estrai TUTTE le frequenze settimanali menzionate nel documento.
Usa food_group_or_item: pollo, carne_rossa, pesce, legumi, uova, carne_bianca.
Esempio: {{"food_group_or_item":"carne_rossa","max_per_week":1,"min_per_week":0,"is_hard_constraint":true}}
Se non ci sono frequenze esplicite, lascia rotation_rules come lista vuota [].

IMPORTANTE sulle quantità: usa le grammature TARGET esatte del documento, senza inventare variazioni.

ISTRUZIONI PER IL CAMPO plan_rules (FONDAMENTALE):
Estrai DIRETTAMENTE dal documento le regole del piano, NON derivarle dai daily_plans generati:
- carb_target: grammi di carboidrati target per pasto (pranzo/cena). null se non specificato.
- protein_target: grammi di proteine target per pasto (pranzo/cena). null se non specificato.
- carb_options: LISTA COMPLETA di tutti i carboidrati permessi dal documento (non solo quelli usati nei 7 giorni generati).
  Includi tutte le opzioni elencate nelle sezioni PRANZO/CENA del documento originale.
- protein_options: LISTA COMPLETA di tutte le fonti proteiche permesse.
  Usa nomi in minuscolo: pollo, tacchino, salmone, tonno, branzino, spigola, orata, gamberi, uova, legumi, carne_rossa, vitello, maiale, tofu.
- frequency_targets: frequenze settimanali per categoria proteica (min/max a settimana).
- free_meal_quota: numero massimo di pasti liberi a settimana. null se non menzionato.
NON inventare opzioni non menzionate nel documento. Se cena non ha opzioni specifiche, ometti la chiave "cena" da carb_options/protein_options.

Testo del piano:
{text_content}

Rispondi SOLO con il JSON, senza testo aggiuntivo."""


async def _parse_text_with_llm(text_content: str, profile_id: str, llm_gateway) -> Dict[str, Any]:
    """Parsa un testo di piano alimentare usando l'LLM.
    Restituisce {"plan": StructuredMealPlan dict, "plan_rules": dict | None}."""
    import json, re

    prompt = _build_import_prompt(text_content, profile_id)

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
                result["llm_raw_response"] = response.choices[0].message.content
            elif llm_gateway.provider == "ollama":
                response = llm_gateway._client.chat(model=llm_gateway.model, messages=messages)
                result["llm_raw_response"] = response["message"]["content"]
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