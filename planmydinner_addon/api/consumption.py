from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session
from typing import List, Optional
import base64
import copy
import uuid
from datetime import date
import logging # Added import
import json # Added import

from pydantic import BaseModel as _BaseModel

_LOGGER = logging.getLogger(__name__) # Added logger setup

from .. import schemas
from ..database import get_db, ConsumedEntry, Recipe, CandidateRecipe, consume_ingredients_from_pantry
from ..nutrition import compute_recipe_nutrition

router = APIRouter(
    prefix="/consumed-entries",
    tags=["consumption"],
)

@router.post("/", response_model=schemas.ConsumedEntry)
def create_consumed_entry(entry: schemas.ConsumedEntryCreate, db: Session = Depends(get_db)):
    """
    Create a new consumed entry. This is a generic endpoint.
    Specific endpoints for 'planned' and 'override' are likely more useful.

    Idempotente per i pasti 'planned': ripremere "Ho mangiato" sullo stesso
    slot aggiorna la registrazione esistente invece di creare un duplicato.
    """
    if entry.type == "planned":
        existing = db.query(ConsumedEntry).filter(
            ConsumedEntry.profile_id == entry.profile_id,
            ConsumedEntry.date == entry.date,
            ConsumedEntry.meal_type == entry.meal_type,
            ConsumedEntry.type == "planned",
        ).first()
        if existing:
            existing.consumed_recipe_id = entry.consumed_recipe_id
            db.commit()
            db.refresh(existing)
            return existing

    db_entry = ConsumedEntry(**entry.model_dump(), id=str(uuid.uuid4()))
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry

@router.post("/mark-planned", response_model=schemas.ConsumedEntry)
def mark_meal_as_consumed_planned(profile_id: str, meal_date: str, meal_type: str, recipe_id: str, db: Session = Depends(get_db)):
    """
    Mark a planned meal as consumed.
    """
    entry_data = schemas.ConsumedEntryCreate(
        profile_id=profile_id,
        date=meal_date,
        meal_type=meal_type,
        type="planned",
        consumed_recipe_id=recipe_id
    )
    db_entry = ConsumedEntry(**entry_data.model_dump(), id=str(uuid.uuid4()))
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)

    # --- Consume ingredients from pantry ---
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe:
        ingredients_to_consume_data = []
        # _LOGGER.debug(f"Raw recipe content for {db_recipe.name}: {db_recipe.content}") # Debugging
        
        # Access content as a dictionary first
        recipe_content_dict = db_recipe.content
        
        if db_recipe.is_composed_dish and "components" in recipe_content_dict:
            # Handle composed dish - extract from components
            for component_item in recipe_content_dict["components"]: # Iterate through components if it's a list
                if "quantities" in component_item and profile_id in component_item["quantities"]:
                    qty_data = component_item["quantities"][profile_id]
                    ingredients_to_consume_data.append({
                        "name": component_item["name"],
                        "quantity": qty_data["qty"],
                        "unit": qty_data["unit"]
                    })
        elif isinstance(db_recipe.content, list): # List of RecipeIngredient
            for ingredient_item in db_recipe.content: # Iterate through each ingredient in the list
                if "quantities" in ingredient_item and profile_id in ingredient_item["quantities"]:
                    qty_data = ingredient_item["quantities"][profile_id]
                    ingredients_to_consume_data.append({
                        "name": ingredient_item["name"],
                        "quantity": qty_data["qty"],
                        "unit": qty_data["unit"]
                    })
        
        if ingredients_to_consume_data:
            consume_ingredients_from_pantry(db, ingredients_to_consume_data)
        else:
            _LOGGER.warning(f"No ingredients found for recipe {recipe_id} and profile {profile_id} or recipe content format unrecognized.")
    else:
        _LOGGER.warning(f"Recipe {recipe_id} not found when trying to consume planned meal ingredients.")
    
    return db_entry


@router.post("/override", response_model=schemas.ConsumedEntry)
async def mark_meal_as_consumed_override(
    profile_id: str,
    meal_date: str,
    meal_type: str,
    override_details: schemas.OverrideConsumedDetails,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Mark a meal as consumed with override details.
    """
    entry_data = schemas.ConsumedEntryCreate(
        profile_id=profile_id,
        date=meal_date,
        meal_type=meal_type,
        type="override",
        override_details=override_details
    )
    db_entry = ConsumedEntry(**entry_data.model_dump(), id=str(uuid.uuid4()))
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)

    # --- Consume ingredients from pantry based on override details ---
    if override_details.ingredients:
        ingredients_to_consume_data = []
        for ing in override_details.ingredients:
            ingredients_to_consume_data.append({
                "name": ing.name,
                "quantity": ing.qty,
                "unit": ing.unit
            })
        if ingredients_to_consume_data:
            consume_ingredients_from_pantry(db, ingredients_to_consume_data)
        
        # Create a CandidateRecipe if structured ingredients are provided
        candidate_recipe_data = schemas.RecipeCreate(
            name=override_details.free_text_name,
            content=[
                schemas.RecipeIngredient(
                    name=ing.name,
                    food_group="altro", # LLM or user can refine this later
                    quantities={profile_id: schemas.QuantityPerProfile(qty=ing.qty, unit=ing.unit)}
                ) for ing in override_details.ingredients
            ],
            steps=[], # Not provided in override
            total_time_minutes=0, # Not provided in override
            difficulty="sconosciuto", # Not provided in override
            tags={"mood": ["override"]},
            llm_generated_metadata={"source_prompt": override_details.free_text_name}
        )
        db_candidate_recipe = CandidateRecipe(
            id=str(uuid.uuid4()),
            status="draft_structured",
            usage_count=1,
            origin_override_id=db_entry.id,
            recipe_data=candidate_recipe_data.model_dump_json() # Store as JSON
        )
        db.add(db_candidate_recipe)
        db.commit()
        _LOGGER.info(f"Created draft_structured CandidateRecipe from override: {db_candidate_recipe.id}")

    elif override_details.free_text_name:
        llm_gateway = request.app.state.llm_gateway
        if llm_gateway:
            # Attempt to generate structured recipe from free text
            # Placeholder for actual profile IDs needed for quantities
            profile_ids = [profile_id] # Assuming single profile for now
            structured_recipe_data = llm_gateway.generate_structured_recipe_from_text(
                override_details.free_text_name,
                profile_ids
            )
            
            if structured_recipe_data:
                candidate_recipe_data = schemas.RecipeCreate(**structured_recipe_data)
                db_candidate_recipe = CandidateRecipe(
                    id=str(uuid.uuid4()),
                    status="draft_structured",
                    usage_count=1,
                    origin_override_id=db_entry.id,
                    recipe_data=candidate_recipe_data.model_dump_json()
                )
                db.add(db_candidate_recipe)
                db.commit()
                _LOGGER.info(f"Created draft_structured CandidateRecipe from LLM override: {db_candidate_recipe.id}")
            else:
                _LOGGER.warning(f"LLM failed to generate structured recipe for '{override_details.free_text_name}'. Storing as draft_free_text.")
                # Store as draft_free_text if LLM fails
                candidate_recipe_data = {
                    "id": str(uuid.uuid4()),
                    "name": override_details.free_text_name,
                    "description": override_details.notes,
                    "is_composed_dish": False, # Assume simple for free text
                    "content": [],
                    "steps": [],
                    "total_time_minutes": 0,
                    "difficulty": "sconosciuto",
                    "tags": {"mood": ["override"]},
                    "llm_generated_metadata":{"source_prompt": override_details.free_text_name}
                }
                db_candidate_recipe = CandidateRecipe(
                    id=candidate_recipe_data["id"],
                    status="draft_free_text",
                    usage_count=1,
                    origin_override_id=db_entry.id,
                    recipe_data=json.dumps(candidate_recipe_data)
                )
                db.add(db_candidate_recipe)
                db.commit()
                _LOGGER.info(f"Created draft_free_text CandidateRecipe from override: {db_candidate_recipe.id}")
        else:
            _LOGGER.warning("LLM Gateway not initialized. Cannot generate structured recipe from free text.")
            # Store as draft_free_text if LLM is not available
            candidate_recipe_data = {
                "id": str(uuid.uuid4()),
                "name": override_details.free_text_name,
                "description": override_details.notes,
                "is_composed_dish": False, # Assume simple for free text
                "content": [],
                "steps": [],
                "total_time_minutes": 0,
                "difficulty": "sconosciuto",
                "tags": {"mood": ["override"]},
                "llm_generated_metadata":{"source_prompt": override_details.free_text_name}
            }
            db_candidate_recipe = CandidateRecipe(
                id=candidate_recipe_data["id"],
                status="draft_free_text",
                usage_count=1,
                origin_override_id=db_entry.id,
                recipe_data=json.dumps(candidate_recipe_data)
            )
            db.add(db_candidate_recipe)
            db.commit()
            _LOGGER.info(f"Created draft_free_text CandidateRecipe from override (LLM not available): {db_candidate_recipe.id}")
    else:
        _LOGGER.debug("No ingredients or free_text_name specified in override_details. No CandidateRecipe created.")
    
    return db_entry


@router.post("/mark-day")
def mark_day_as_consumed(profile_id: str, day: str, db: Session = Depends(get_db)):
    """
    Segna come consumati, in un colpo solo, tutti i pasti pianificati del giorno
    che hanno una ricetta assegnata e non sono già stati registrati.
    Salta pasti liberi, "non mangiato" e slot vuoti. Idempotente.
    """
    from datetime import date as _date
    from .planner import _find_plan_covering_date

    try:
        target_date = _date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=422, detail="day must be an ISO date (YYYY-MM-DD)")

    plan = _find_plan_covering_date(db, profile_id, target_date)
    if not plan:
        return {"marked": 0, "skipped": 0, "detail": "No plan covers this date."}

    daily = next((dp for dp in plan.daily_plans if dp.get("date") == day), None)
    if not daily:
        return {"marked": 0, "skipped": 0, "detail": "No meals planned for this date."}

    already = {
        e.meal_type
        for e in db.query(ConsumedEntry).filter(
            ConsumedEntry.profile_id == profile_id,
            ConsumedEntry.date == day,
        ).all()
    }

    marked = 0
    skipped = 0
    for meal in daily.get("meals", []):
        meal_type = meal.get("meal_type")
        items = meal.get("items", [])
        recipe_id = items[0].get("recipe_id") if items else None
        fg = items[0].get("food_group") if items else None
        if not recipe_id or fg in ("free_meal", "not_eaten") or meal_type in already:
            skipped += 1
            continue
        # Riusa la logica del singolo pasto (crea l'entry e scala la dispensa)
        mark_meal_as_consumed_planned(profile_id, day, meal_type, recipe_id, db)
        marked += 1

    return {"marked": marked, "skipped": skipped}


# ---------------------------------------------------------------------------
# Pasti da foto (mensa): analizza la foto, salva nel catalogo mensa, riusa
# ---------------------------------------------------------------------------

_MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB


class PhotoIngredient(_BaseModel):
    name: str
    food_group: str = "altro"
    grams: float


class MensaMealSave(_BaseModel):
    profile_id: str
    date: str            # ISO YYYY-MM-DD
    meal_type: str       # pranzo | cena
    name: str
    ingredients: List[PhotoIngredient]
    register_consumption: bool = True


def _mensa_content(ingredients: List[PhotoIngredient], profile_id: str) -> list:
    return [
        {
            "name": ing.name,
            "food_group": ing.food_group,
            "quantities": {profile_id: {"qty": float(ing.grams), "unit": "g", "grams_equiv": float(ing.grams)}},
        }
        for ing in ingredients if ing.grams > 0
    ]


def _is_mensa_candidate(cand: CandidateRecipe) -> Optional[dict]:
    """Restituisce recipe_data (dict) se il candidato è un pasto mensa, altrimenti None."""
    data = cand.recipe_data
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    tags = data.get("tags") or {}
    return data if "true" in (tags.get("mensa") or []) else None


def _apply_mensa_to_plan(db: Session, profile_id: str, meal_date: str, meal_type: str,
                         name: str, recipe_id: str) -> bool:
    """Sostituisce lo slot del piano con il pasto mensa realmente consumato,
    così Oggi/Settimana (e i macro giornalieri) mostrano ciò che si è mangiato
    e non la ricetta suggerita. Se la settimana non ha ancora un piano ne crea
    uno vuoto, così si può registrare un pasto anche senza aver generato nulla.
    Ritorna False se la data non è valida."""
    from .planner import ensure_plan_for_date
    try:
        target = date.fromisoformat(meal_date)
    except ValueError:
        return False
    plan = ensure_plan_for_date(db, profile_id, target)
    updated = copy.deepcopy(plan.daily_plans)
    changed = False
    for day in updated:
        if day.get("date") == meal_date:
            for meal in day.get("meals", []):
                if meal.get("meal_type") == meal_type:
                    meal["items"] = [{
                        "item_name": f"🍱 {name}",
                        "food_group": "mensa",
                        "quantity": 1,
                        "unit": "recipe",
                        "is_estimated_unit": False,
                        "alternatives": [],
                        "recipe_id": recipe_id,
                    }]
                    changed = True
    if changed:
        plan.daily_plans = updated
        db.add(plan)
        db.commit()
    return changed


def _register_mensa_consumption(db: Session, cand: CandidateRecipe, data: dict,
                                profile_id: str, meal_date: str, meal_type: str) -> ConsumedEntry:
    ingredients = [
        {"name": ing.get("name"), "qty": (ing.get("quantities") or {}).get(profile_id, {}).get("qty", 0), "unit": "g"}
        for ing in data.get("content", []) if isinstance(ing, dict)
    ]
    entry = ConsumedEntry(
        id=str(uuid.uuid4()),
        profile_id=profile_id,
        date=meal_date,
        meal_type=meal_type,
        type="override",
        consumed_recipe_id=cand.id,
        override_details={"free_text_name": data.get("name"), "ingredients": ingredients, "notes": "mensa"},
    )
    db.add(entry)
    cand.usage_count = (cand.usage_count or 0) + 1
    db.add(cand)
    db.commit()
    db.refresh(entry)
    # Aggiorna anche lo slot del piano (se un piano copre la data)
    _apply_mensa_to_plan(db, profile_id, meal_date, meal_type, data.get("name") or "Pasto mensa", cand.id)
    return entry


@router.post("/photo/analyze")
async def analyze_meal_photo(request: Request, profile_id: str, file: UploadFile = File(...)):
    """
    Analizza la foto di un pasto con il modello vision e restituisce la proposta
    strutturata (nome + ingredienti con grammi stimati + kcal/macro).
    Non salva nulla: la conferma avviene con POST /consumed-entries/mensa.
    """
    gw = getattr(request.app.state, "llm_gateway", None)
    if gw is None or gw._client is None:
        raise HTTPException(status_code=503, detail="LLM non configurato: impossibile analizzare la foto.")

    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=422, detail="Il file deve essere un'immagine.")
    raw = await file.read()
    if len(raw) > _MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Immagine troppo grande (max 10 MB).")

    result = gw.estimate_meal_from_photo(base64.b64encode(raw).decode(), file.content_type)
    if not result:
        raise HTTPException(status_code=422, detail="Impossibile riconoscere un pasto nella foto.")

    ingredients = [PhotoIngredient(**ing) for ing in result["ingredients"]]
    nutrition = None
    try:
        nutrition = compute_recipe_nutrition(_mensa_content(ingredients, profile_id), profile_id, llm_gateway=gw)
    except Exception:
        _LOGGER.exception("Nutrition estimate failed for photo meal")
    return {"name": result["name"], "ingredients": [i.model_dump() for i in ingredients], "nutrition": nutrition}


class TextAnalyzeBody(_BaseModel):
    description: str


@router.post("/text/analyze")
def analyze_meal_text(body: TextAnalyzeBody, request: Request, profile_id: str):
    """
    Spacchetta la descrizione libera di un pasto (es. "tramezzini tonno e maionese,
    insalata a parte") in ingredienti con grammi stimati + kcal/macro.
    Stessa risposta di /photo/analyze: la conferma passa da POST /consumed-entries/mensa.
    """
    gw = getattr(request.app.state, "llm_gateway", None)
    if gw is None or gw._client is None:
        raise HTTPException(status_code=503, detail="LLM non configurato: impossibile analizzare la descrizione.")
    description = (body.description or "").strip()
    if len(description) < 3:
        raise HTTPException(status_code=422, detail="Descrizione troppo corta.")

    result = gw.estimate_meal_from_text(description)
    if not result:
        raise HTTPException(status_code=422, detail="Impossibile riconoscere un pasto nella descrizione.")

    ingredients = [PhotoIngredient(**ing) for ing in result["ingredients"]]
    nutrition = None
    try:
        nutrition = compute_recipe_nutrition(_mensa_content(ingredients, profile_id), profile_id, llm_gateway=gw)
    except Exception:
        _LOGGER.exception("Nutrition estimate failed for text meal")
    return {"name": result["name"], "ingredients": [i.model_dump() for i in ingredients], "nutrition": nutrition}


@router.get("/mensa")
def list_mensa_meals(request: Request, profile_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Catalogo dei pasti mensa già mappati (per riuso senza LLM), più usati prima."""
    gw = getattr(request.app.state, "llm_gateway", None)
    out = []
    for cand in db.query(CandidateRecipe).filter(CandidateRecipe.status == "draft_structured").all():
        data = _is_mensa_candidate(cand)
        if not data:
            continue
        ingredients = []
        any_profile = None
        for ing in data.get("content", []):
            if not isinstance(ing, dict):
                continue
            quantities = ing.get("quantities") or {}
            any_profile = any_profile or next(iter(quantities), None)
            qty = quantities.get(profile_id) or quantities.get(any_profile) or {}
            ingredients.append({
                "name": ing.get("name"),
                "food_group": ing.get("food_group"),
                "grams": qty.get("grams_equiv") or qty.get("qty") or 0,
            })
        nutrition = None
        try:
            # Stima LLM cachata su disco: nessuna chiamata di rete se l'ingrediente
            # è già stato risolto in precedenza (analisi foto/testo o vista precedente).
            nutrition = compute_recipe_nutrition(data.get("content"), profile_id or any_profile or "", llm_gateway=gw)
        except Exception:
            pass
        out.append({
            "id": cand.id,
            "name": data.get("name"),
            "usage_count": cand.usage_count or 0,
            "ingredients": ingredients,
            "nutrition": nutrition,
        })
    out.sort(key=lambda m: (-m["usage_count"], (m["name"] or "").lower()))
    return out


@router.post("/mensa")
def save_mensa_meal(body: MensaMealSave, db: Session = Depends(get_db)):
    """
    Salva (o aggiorna) un pasto mensa nel catalogo e, di default, lo registra
    come consumato per la data/pasto indicati.
    """
    if not body.ingredients:
        raise HTTPException(status_code=422, detail="Serve almeno un ingrediente.")

    # Dedupe per nome: se esiste già un pasto mensa omonimo lo riusa (aggiornando le dosi)
    cand = None
    for existing in db.query(CandidateRecipe).filter(CandidateRecipe.status == "draft_structured").all():
        data = _is_mensa_candidate(existing)
        if data and (data.get("name") or "").strip().lower() == body.name.strip().lower():
            cand = existing
            break

    recipe_data = {
        "name": body.name.strip(),
        "description": "Pasto mensa (mappato da foto)",
        "is_composed_dish": False,
        "content": _mensa_content(body.ingredients, body.profile_id),
        "steps": [],
        "total_time_minutes": 0,
        "difficulty": "sconosciuto",
        "tags": {"mensa": ["true"]},
    }
    if cand is None:
        cand = CandidateRecipe(id=str(uuid.uuid4()), status="draft_structured", usage_count=0,
                               recipe_data=recipe_data)
    else:
        cand.recipe_data = recipe_data
    db.add(cand)
    db.commit()
    db.refresh(cand)

    entry_id = None
    if body.register_consumption:
        entry = _register_mensa_consumption(db, cand, recipe_data, body.profile_id, body.date, body.meal_type)
        entry_id = entry.id

    return {"recipe_id": cand.id, "consumed_entry_id": entry_id}


@router.post("/mensa/{candidate_id}/consume")
def consume_mensa_meal(candidate_id: str, profile_id: str, meal_date: str, meal_type: str,
                       db: Session = Depends(get_db)):
    """Registra come consumato un pasto mensa già mappato (nessuna chiamata LLM)."""
    cand = db.query(CandidateRecipe).filter(CandidateRecipe.id == candidate_id).first()
    data = _is_mensa_candidate(cand) if cand else None
    if not data:
        raise HTTPException(status_code=404, detail="Pasto mensa non trovato.")
    entry = _register_mensa_consumption(db, cand, data, profile_id, meal_date, meal_type)
    return {"consumed_entry_id": entry.id, "name": data.get("name")}


class MensaMealUpdate(_BaseModel):
    name: str
    ingredients: List[PhotoIngredient]


@router.put("/mensa/{candidate_id}")
def update_mensa_meal(candidate_id: str, body: MensaMealUpdate, db: Session = Depends(get_db)):
    """Modifica nome e ingredienti/grammature di un pasto mensa del catalogo."""
    cand = db.query(CandidateRecipe).filter(CandidateRecipe.id == candidate_id).first()
    data = _is_mensa_candidate(cand) if cand else None
    if not data:
        raise HTTPException(status_code=404, detail="Pasto mensa non trovato.")
    if not body.ingredients:
        raise HTTPException(status_code=422, detail="Serve almeno un ingrediente.")

    # Mantiene le chiavi profilo già presenti nel content (di norma una sola)
    profile_keys = set()
    for ing in data.get("content", []):
        if isinstance(ing, dict):
            profile_keys.update((ing.get("quantities") or {}).keys())
    if not profile_keys:
        profile_keys = {"riccardo"}

    content = []
    for ing in body.ingredients:
        if ing.grams <= 0:
            continue
        content.append({
            "name": ing.name,
            "food_group": ing.food_group,
            "quantities": {pk: {"qty": float(ing.grams), "unit": "g", "grams_equiv": float(ing.grams)}
                           for pk in profile_keys},
        })
    cand.recipe_data = {**data, "name": body.name.strip(), "content": content}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(cand, "recipe_data")
    db.commit()
    return {"recipe_id": cand.id, "name": body.name.strip()}


@router.delete("/mensa/{candidate_id}")
def delete_mensa_meal(candidate_id: str, db: Session = Depends(get_db)):
    """Elimina un pasto mensa dal catalogo (i consumi già registrati restano)."""
    cand = db.query(CandidateRecipe).filter(CandidateRecipe.id == candidate_id).first()
    if not (_is_mensa_candidate(cand) if cand else None):
        raise HTTPException(status_code=404, detail="Pasto mensa non trovato.")
    db.delete(cand)
    db.commit()
    return {"deleted": candidate_id}


@router.get("/", response_model=List[schemas.ConsumedEntry])
def read_consumed_entries(profile_id: str = None, start_date: str = None, end_date: str = None, db: Session = Depends(get_db)):
    """
    Retrieve consumed entries, with optional filters.
    """
    query = db.query(ConsumedEntry)
    if profile_id:
        query = query.filter(ConsumedEntry.profile_id == profile_id)
    if start_date:
        query = query.filter(ConsumedEntry.date >= start_date)
    if end_date:
        query = query.filter(ConsumedEntry.date <= end_date)
    
    entries = query.all()
    return entries