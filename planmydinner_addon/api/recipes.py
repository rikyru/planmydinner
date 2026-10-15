from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional, Any, Dict
import uuid
import json as _json
import re as _re
import html as _html
import urllib.request as _urlreq

from pydantic import BaseModel as _BaseModel
from sqlalchemy.orm.attributes import flag_modified
from .. import schemas
from ..database import get_db, Recipe, CandidateRecipe, PlanRules, UserProfile
from ..nutrition import (DEFAULT_COOKING_FAT_G, analyze_recipe, compute_recipe_nutrition,
                         recipe_balance, resolve_ingredient_nutrition, _PROTEIN_GROUPS_BAL)

# Quota di proteine giornaliere attesa da un pasto principale (pranzo/cena);
# il resto arriva da colazione/spuntini. Usata per il check di bilanciamento.
PROTEIN_SHARE_PER_MEAL = 0.35


def _per_meal_protein_target(db: Session) -> Optional[float]:
    """Target proteico per pasto principale: proteine giornaliere (da OpenFit,
    in PlanRules.nutrition_targets) × quota pasto. None se non impostato."""
    row = (db.query(PlanRules)
             .filter(PlanRules.nutrition_targets.isnot(None))
             .order_by(PlanRules.imported_at.desc()).first())
    daily = (row.nutrition_targets or {}).get("protein_g") if row else None
    return daily * PROTEIN_SHARE_PER_MEAL if daily else None


class BulkIngredient(_BaseModel):
    name: str
    food_group: str
    grams: float


class BulkRecipeItem(_BaseModel):
    name: str
    time: int = 30
    difficulty: str = "facile"
    mood: str = "normale"
    cooking: str = "tegame"
    ingredients: List[BulkIngredient]


class BulkImportResult(_BaseModel):
    created: int
    skipped: int
    errors: List[str]

router = APIRouter(
    prefix="/recipes",
    tags=["recipes"],
)


# ── Import ricetta da URL (Schema.org JSON-LD + LLM per strutturare) ──────────

def _fetch_url(url: str) -> str:
    req = _urlreq.Request(url, headers={"User-Agent": "Mozilla/5.0 (PlanMyDinner recipe import)"})
    with _urlreq.urlopen(req, timeout=12) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        raw = resp.read(2_000_000)   # cap 2 MB
    return raw.decode(charset, errors="replace")


def _strip_tags(s: str) -> str:
    return _html.unescape(_re.sub(r"<[^>]+>", " ", s or "")).strip()


def _as_str_list(val) -> List[str]:
    if not val:
        return []
    if isinstance(val, str):
        return [_strip_tags(val)]
    out = []
    for x in val:
        if isinstance(x, str):
            out.append(_strip_tags(x))
        elif isinstance(x, dict):
            out.append(_strip_tags(x.get("text") or x.get("name") or ""))
    return [s for s in out if s]


def _parse_instructions(val) -> List[str]:
    if not val:
        return []
    if isinstance(val, str):
        # a volte è un unico blocco: spezza su a capo / punti elenco
        parts = _re.split(r"\n+|\r+", _strip_tags(val))
        return [p.strip() for p in parts if p.strip()]
    steps: List[str] = []
    for x in val:
        if isinstance(x, str):
            steps.append(_strip_tags(x))
        elif isinstance(x, dict):
            if x.get("@type") == "HowToSection" and x.get("itemListElement"):
                steps.extend(_parse_instructions(x["itemListElement"]))
            else:
                t = x.get("text") or x.get("name")
                if t:
                    steps.append(_strip_tags(t))
    return [s for s in steps if s]


def _iso_minutes(val) -> Optional[int]:
    if not val or not isinstance(val, str):
        return None
    m = _re.match(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?", val.strip())
    if not m:
        return None
    h, mi = int(m.group(1) or 0), int(m.group(2) or 0)
    total = h * 60 + mi
    return total or None


def _find_recipe_node(obj) -> Optional[dict]:
    found: List[dict] = []

    def walk(o):
        if isinstance(o, list):
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            if "@graph" in o:
                walk(o["@graph"])
            t = o.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(str(x).lower() == "recipe" for x in types):
                found.append(o)

    walk(obj)
    return found[0] if found else None


def _parse_jsonld_recipe(html_text: str) -> Optional[dict]:
    for m in _re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                          html_text, _re.S | _re.I):
        try:
            data = _json.loads(m.group(1).strip())
        except Exception:
            continue
        node = _find_recipe_node(data)
        if node:
            return {
                "name": _strip_tags(node.get("name") or ""),
                "ingredients": _as_str_list(node.get("recipeIngredient") or node.get("ingredients")),
                "steps": _parse_instructions(node.get("recipeInstructions")),
                "minutes": _iso_minutes(node.get("totalTime") or node.get("cookTime")),
            }
    return None


def _visible_text(html_text: str) -> str:
    body = _re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=_re.S | _re.I)
    return _re.sub(r"\s+", " ", _strip_tags(body))


class ImportUrlBody(_BaseModel):
    url: str


@router.post("/import-url")
def import_recipe_from_url(body: ImportUrlBody, request: Request):
    """Importa una ricetta da un link: estrae i dati Schema.org (JSON-LD) e, se
    disponibile l'LLM, struttura gli ingredienti in food_group + grammi. Ritorna
    una BOZZA (non salvata) da rivedere e salvare dall'editor ricette."""
    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Inserisci un URL valido (http/https).")
    try:
        html_text = _fetch_url(url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Impossibile scaricare la pagina: {e}")

    data = _parse_jsonld_recipe(html_text) or {}
    name = data.get("name") or ""
    ing_lines = data.get("ingredients") or []
    steps = data.get("steps") or []
    minutes = data.get("minutes") or 30

    gw = getattr(request.app.state, "llm_gateway", None)
    ingredients = None
    if gw is not None and getattr(gw, "_client", None) is not None:
        text = (f"{name}. Ingredienti: " + "; ".join(ing_lines)) if ing_lines \
            else _visible_text(html_text)[:2500]
        try:
            structured = gw.estimate_meal_from_text(text)
        except Exception:
            structured = None
        if structured and structured.get("ingredients"):
            ingredients = structured["ingredients"]
            name = name or structured.get("name") or ""

    if ingredients is None:
        # fallback senza LLM: righe grezze, l'utente mette gruppi/grammi nell'editor
        ingredients = [{"name": line[:80], "food_group": "altro", "grams": 0}
                       for line in ing_lines]

    if not name and not ingredients:
        raise HTTPException(status_code=422,
                            detail="Nessuna ricetta riconosciuta in questa pagina.")
    return {
        "name": name or "Ricetta importata",
        "total_time_minutes": minutes,
        "difficulty": "facile",
        "steps": steps,
        "ingredients": ingredients,
        "source_url": url,
    }

@router.post("/", response_model=schemas.Recipe)
def create_recipe(recipe: schemas.RecipeCreate, db: Session = Depends(get_db)):
    """
    Create a new recipe.
    """
    # If ID is not provided in the request, generate one
    recipe_id = recipe.id if recipe.id else str(uuid.uuid4())
    
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe:
        raise HTTPException(status_code=400, detail="Recipe with this ID already exists")
    
    # Create the SQLAlchemy model instance
    # Ensure the ID from the Pydantic model is used, or the generated one
    recipe_data = recipe.model_dump()
    recipe_data["id"] = recipe_id # Ensure the ID is set from our determined recipe_id

    # Tag ricette aggiunte manualmente: peso alto nel planner
    if recipe_data.get("tags") is None:
        recipe_data["tags"] = {}
    recipe_data["tags"]["manual"] = ["true"]

    db_recipe = Recipe(**recipe_data)
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)
    return db_recipe

@router.post("/bulk", response_model=BulkImportResult)
def bulk_import_recipes(
    items: List[BulkRecipeItem],
    profile_a_id: str = "persona_a",
    profile_b_id: str = "persona_b",
    db: Session = Depends(get_db),
):
    """
    Importa in blocco una lista di ricette nel formato semplificato.
    Ogni ricetta viene taggata come 'manual' → peso alto nel planner.
    Ricette con lo stesso nome vengono saltate.
    """
    created = 0
    skipped = 0
    errors: List[str] = []

    _DIFFICULTY_MAP = {
        "easy": "facile", "facile": "facile",
        "medium": "media", "media": "media",
        "hard": "difficile", "difficile": "difficile",
    }

    def _qty(g: float) -> dict:
        return {"qty": float(g), "unit": "g", "grams_equiv": float(g)}

    for item in items:
        try:
            # Controlla duplicati per nome
            existing = db.query(Recipe).filter(Recipe.name == item.name).first()
            if existing:
                skipped += 1
                continue

            difficulty = _DIFFICULTY_MAP.get(item.difficulty.lower(), "sconosciuto")

            content = [
                {
                    "name": ing.name,
                    "food_group": ing.food_group,
                    "quantities": {
                        profile_a_id: _qty(ing.grams),
                        profile_b_id: _qty(ing.grams),
                    },
                }
                for ing in item.ingredients
            ]
            recipe_data = {
                "id": str(uuid.uuid4()),
                "name": item.name,
                "description": "",
                "is_composed_dish": False,
                "content": content,
                "steps": [],
                "total_time_minutes": item.time,
                "difficulty": difficulty,
                "tags": {
                    "manual": ["true"],
                    "mood": [item.mood],
                    "cooking_methods": [item.cooking],
                    "cleanup": ["facile"],
                },
            }
            db.add(Recipe(**recipe_data))
            created += 1
        except Exception as e:
            errors.append(f"{item.name}: {e}")

    db.commit()
    return BulkImportResult(created=created, skipped=skipped, errors=errors)


@router.get("/")
def read_recipes(request: Request, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Retrieve all recipes, skipping any with invalid data.

    Include nutrition_per_portion (kcal + macro per profilo) quando calcolabile,
    cosi' la lista Ricette puo' mostrare le calorie a porzione: le stime
    sbagliate si notano subito invece di restare nascoste nel dettaglio.
    """
    llm_gateway = getattr(request.app.state, "llm_gateway", None)
    protein_target = _per_meal_protein_target(db)
    db_recipes = db.query(Recipe).offset(skip).limit(limit).all()
    result = []
    for r in db_recipes:
        try:
            validated = schemas.Recipe.from_orm(r)
            validated = _attach_nutrition_per_portion(validated, db, llm_gateway, protein_target)
            result.append(validated.model_dump())
        except Exception:
            # Ricetta con dati non conformi: restituisce raw per permettere la visualizzazione/modifica
            result.append({
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "is_composed_dish": r.is_composed_dish or False,
                "content": r.content or [],
                "steps": r.steps or [],
                "total_time_minutes": r.total_time_minutes or 0,
                "difficulty": r.difficulty or "sconosciuto",
                "tags": r.tags or {},
            })
    return result

@router.delete("/all")
def delete_all_recipes(db: Session = Depends(get_db)):
    """
    Delete all recipes from the database.
    """
    count = db.query(Recipe).count()
    db.query(Recipe).delete()
    db.commit()
    return {"deleted": count}


def _attach_nutrition_per_portion(validated: schemas.Recipe, db: Session, llm_gateway=None,
                                  protein_target_g=None) -> schemas.Recipe:
    """Calcola i macro per porzione per ogni profilo e il bilanciamento del pasto
    (proteine vs target, macro) e li allega alla risposta (best-effort)."""
    try:
        profile_ids = [p.id for p in db.query(UserProfile).all()]
        content = validated.model_dump()["content"]
        if not profile_ids and isinstance(content, list) and content:
            profile_ids = list((content[0].get("quantities") or {}).keys())
        per_portion = {}
        for pid in profile_ids:
            nutrition = compute_recipe_nutrition(content, pid, llm_gateway=llm_gateway)
            if nutrition:
                per_portion[pid] = nutrition
        validated.nutrition_per_portion = per_portion or None
        # Bilanciamento sul profilo principale (il primo)
        if profile_ids:
            validated.balance = recipe_balance(
                content, profile_ids[0], protein_target_g=protein_target_g,
                llm_gateway=llm_gateway)
    except Exception:
        validated.nutrition_per_portion = None
    return validated


class PreviewNutritionBody(_BaseModel):
    content: Any                       # lista di ingredienti o {components:[...]}
    profile_id: Optional[str] = None   # se assente: tutti i profili


@router.post("/preview-nutrition")
def preview_nutrition(body: PreviewNutritionBody, request: Request,
                      db: Session = Depends(get_db)):
    """Nutrizione + diagnostica di una ricetta in BOZZA (non salvata), per dare
    feedback durante l'inserimento: kcal/macro per profilo, ingredienti senza
    grammi o sconosciuti, e l'avviso se manca un grasso di cottura. Include la
    stima dell'olio di cottura (come nei pasti) così l'anteprima è realistica."""
    llm_gateway = getattr(request.app.state, "llm_gateway", None)
    if body.profile_id:
        pids = [body.profile_id]
    else:
        pids = [p.id for p in db.query(UserProfile).all()]
    if not pids:
        ings = body.content if isinstance(body.content, list) else \
            (body.content or {}).get("components", [])
        if ings and isinstance(ings[0], dict):
            pids = list((ings[0].get("quantities") or {}).keys())
    by_profile = {
        pid: analyze_recipe(body.content, pid, llm_gateway=llm_gateway,
                            add_cooking_fat_g=DEFAULT_COOKING_FAT_G)
        for pid in pids
    }
    return {"by_profile": by_profile}


@router.post("/{recipe_id}/apply-protein-target", response_model=schemas.Recipe)
def apply_protein_target(recipe_id: str, request: Request, db: Session = Depends(get_db)):
    """Aggiorna la ricetta per rispettare la dose di proteine: alza i grammi
    dell'ingrediente proteico principale fino a raggiungere il target per pasto.
    Applica l'aumento a tutti i profili. Ritorna la ricetta aggiornata."""
    llm_gateway = getattr(request.app.state, "llm_gateway", None)
    target = _per_meal_protein_target(db)
    if not target:
        raise HTTPException(status_code=400, detail="Nessun target proteico impostato.")
    r = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Ricetta non trovata.")
    content = r.content
    if not isinstance(content, list):
        raise HTTPException(status_code=400, detail="Ricetta non adattabile (piatto composto).")

    profile_ids = [p.id for p in db.query(UserProfile).all()]
    pid0 = profile_ids[0] if profile_ids else (
        list((content[0].get("quantities") or {}).keys()) or [None])[0]
    # ingrediente proteico principale (con densità proteica nota)
    prot = None
    for ing in content:
        if (ing.get("food_group") or "").strip().lower() in _PROTEIN_GROUPS_BAL:
            n = resolve_ingredient_nutrition(ing, llm_gateway=llm_gateway)
            if n and n.get("protein_g", 0) > 0:
                prot, dens = ing, n["protein_g"]
                break
    if not prot:
        raise HTTPException(status_code=400,
                            detail="Nessun ingrediente proteico riconosciuto da aumentare.")
    cur = (compute_recipe_nutrition(content, pid0, llm_gateway=llm_gateway) or {}).get("protein_g", 0)
    if cur >= target:
        raise HTTPException(status_code=400, detail="La ricetta è già a target.")
    delta_g = (target - cur) / (dens / 100.0)   # grammi di proteina-food da aggiungere
    for q in (prot.get("quantities") or {}).values():
        base = q.get("grams_equiv") or q.get("qty") or 0
        q["grams_equiv"] = round(base + delta_g)
        q["qty"] = round(base + delta_g)
    r.content = content
    flag_modified(r, "content")
    db.commit()
    db.refresh(r)
    validated = schemas.Recipe.model_validate(r)
    return _attach_nutrition_per_portion(validated, db, llm_gateway, target)


class RateBody(_BaseModel):
    rating: str   # "up" (preferita) | "down" (non proporre più) | "none" (azzera)


@router.post("/{recipe_id}/rate")
def rate_recipe(recipe_id: str, body: RateBody, db: Session = Depends(get_db)):
    """Preferenza esplicita sulla ricetta: 'up' la premia nel planner, 'down' la
    esclude di fatto, 'none' azzera. Memorizzata nei tag della ricetta."""
    r = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Ricetta non trovata")
    tags = dict(r.tags or {})
    tags.pop("favorite", None)
    tags.pop("disliked", None)
    if body.rating == "up":
        tags["favorite"] = ["true"]
    elif body.rating == "down":
        tags["disliked"] = ["true"]
    r.tags = tags
    flag_modified(r, "tags")
    db.commit()
    return {"id": recipe_id, "rating": body.rating}


@router.get("/detail/{recipe_id}", response_model=schemas.Recipe)
def get_recipe_detail(recipe_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Retrieve full recipe detail (content with quantities) from Recipe or CandidateRecipe.
    Used by the UI to display meal components and ingredient doses.
    Includes nutrition_per_portion (kcal + macro per profilo) when computable.
    """
    llm_gateway = getattr(request.app.state, "llm_gateway", None)
    protein_target = _per_meal_protein_target(db)

    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe:
        validated = schemas.Recipe.model_validate(db_recipe)
        return _attach_nutrition_per_portion(validated, db, llm_gateway, protein_target)

    candidate = db.query(CandidateRecipe).filter(CandidateRecipe.id == recipe_id).first()
    if candidate:
        data = candidate.recipe_data if isinstance(candidate.recipe_data, dict) else candidate.recipe_data.model_dump()
        # Inject the candidate's own id so schemas.Recipe validation passes
        validated = schemas.Recipe.model_validate({**data, "id": recipe_id})
        return _attach_nutrition_per_portion(validated, db, llm_gateway, protein_target)

    raise HTTPException(status_code=404, detail=f"Recipe {recipe_id} not found")


@router.get("/{recipe_id}", response_model=schemas.Recipe)
def read_recipe(recipe_id: str, db: Session = Depends(get_db)):
    """
    Retrieve a single recipe by ID.
    """
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return db_recipe

@router.put("/{recipe_id}", response_model=schemas.Recipe)
def update_recipe(recipe_id: str, recipe: schemas.RecipeCreate, db: Session = Depends(get_db)):
    """
    Update an existing recipe.
    """
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    
    update_data = recipe.model_dump(exclude_unset=True)
    # Ensure ID is not updated
    if "id" in update_data:
        del update_data["id"]

    for key, value in update_data.items():
        setattr(db_recipe, key, value)
        
    db.commit()
    db.refresh(db_recipe)
    return db_recipe

@router.delete("/{recipe_id}", response_model=schemas.Recipe)
def delete_recipe(recipe_id: str, db: Session = Depends(get_db)):
    """
    Delete a recipe.
    """
    db_recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if db_recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    db.delete(db_recipe)
    db.commit()
    return db_recipe

@router.post("/candidate/{candidate_recipe_id}/approve", response_model=schemas.Recipe)
def approve_candidate_recipe(candidate_recipe_id: str, db: Session = Depends(get_db)):
    """
    Approves a candidate recipe, converting it into a full recipe. The candidate recipe's status is updated to "approved".
    """
    db_candidate = db.query(CandidateRecipe).filter(CandidateRecipe.id == candidate_recipe_id).first()
    if not db_candidate:
        raise HTTPException(status_code=404, detail="Candidate Recipe not found")
    
    # Ensure recipe_data is loaded correctly from JSON
    recipe_create_data = schemas.RecipeCreate(**db_candidate.recipe_data)
    
    # Create the new Recipe, using the ID from the candidate recipe's data or generate a new one
    db_recipe_id = recipe_create_data.id if recipe_create_data.id else str(uuid.uuid4())

    # Check if a recipe with this ID already exists
    if db.query(Recipe).filter(Recipe.id == db_recipe_id).first():
        raise HTTPException(status_code=400, detail=f"A recipe with ID {db_recipe_id} already exists.")

    db_recipe = Recipe(**recipe_create_data.model_dump(), id=db_recipe_id)
        
    db.add(db_recipe)
    
    # Update candidate status
    db_candidate.status = "approved"
    db.add(db_candidate)

    db.commit()
    db.refresh(db_recipe)
    
    return db_recipe
