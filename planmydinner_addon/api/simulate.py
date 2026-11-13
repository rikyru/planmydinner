"""
Simulatore di pasto: "se a pranzo prendo questo / stasera mangio cinese, come
chiudo la giornata e cosa resta per l'altro pasto?". Non salva nulla: per
registrare il pasto scelto si passa da POST /consumed-entries/mensa.

Il bilancio usa gli stessi numeri della vista Oggi (/integration/summary con
meal_detail): obiettivo del giorno (periodizzato), colazione/spuntini fissi,
extra, e l'altro pasto principale (registrato o da piano).
"""
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel as _BaseModel
from sqlalchemy.orm import Session

from ..database import CandidateRecipe, get_db
from ..nutrition import compute_recipe_nutrition
from .consumption import PhotoIngredient, _is_mensa_candidate, _mensa_content
from .integration import MAIN_MEALS, get_integration_summary

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/simulate", tags=["simulate"])

KEYS = ("kcal", "protein_g", "carbs_g", "fat_g")
DAY_TOL = 0.10          # giornata "in linea" entro ±10% dell'obiettivo
MIN_OTHER_KCAL = 300
SUGGEST_AIM = 0.8       # tetto chiesto all'LLM per i consigli, rispetto alla quota    # sotto questa quota l'altro pasto diventa poco realistico


_OF = {"pranzo": "del pranzo", "cena": "della cena"}
_FOR = {"pranzo": "il pranzo", "cena": "la cena"}


def _r(n: Dict[str, float]) -> Dict[str, int]:
    return {k: round(n.get(k) or 0) for k in KEYS}


def simulate_day(day: Dict[str, Any], targets: Dict[str, Any], meal_type: str,
                 meal: Dict[str, float]) -> Dict[str, Any]:
    """Bilancio della giornata se a `meal_type` si mangia `meal` (kcal/macro).

    `day` è una riga di /integration/summary con meal_detail; `targets` i suoi
    obiettivi piatti. Ritorna quota del pasto, cosa resta per l'altro pasto
    principale e come chiude la giornata (con l'altro pasto com'è previsto)."""
    t = {k: float(targets[k]) for k in KEYS if targets.get(k)}
    if day.get("target_kcal"):
        t["kcal"] = float(day["target_kcal"])
    meals = day.get("meals") or {}
    other_mt = next(m for m in MAIN_MEALS if m != meal_type)
    other = meals.get(other_mt)
    other_kcal = (other or {}).get("nutrition", {}).get("kcal")
    other_eaten = bool(other and other.get("consumed"))
    fixed = float(day.get("routine_kcal") or 0) + float(day.get("extra_kcal") or 0)
    out: Dict[str, Any] = {
        "meal": _r(meal), "meal_type": meal_type, "fixed_kcal": round(fixed),
        "target": _r(t) if t else None,
        "other": {"meal_type": other_mt, "planned": other is not None,
                  "consumed": other_eaten,
                  "kcal": round(other_kcal) if other_kcal is not None else None},
    }
    if "kcal" not in t:
        out["verdict"] = {"level": "unknown", "text": "Nessun obiettivo kcal impostato: "
                          f"il pasto vale ~{round(meal['kcal'])} kcal."}
        return out

    budget = t["kcal"] - fixed
    # quota del pasto: metà del budget, oppure quel che resta se l'altro è già mangiato
    quota = budget - other_kcal if other_eaten and other_kcal is not None else budget / 2
    left_for_other = budget - meal["kcal"]
    out.update(budget_kcal=round(budget), quota_kcal=round(quota),
               diff_quota=round(meal["kcal"] - quota))

    # l'altro pasto: registrato o previsto; se non è nel piano (es. mensa non
    # pianificata) si assume che stia nella sua quota
    other_assumed = other_kcal is None and not other_eaten
    other_day = budget / 2 if other_assumed else (other_kcal or 0)
    day_total = fixed + meal["kcal"] + other_day
    gap = day_total - t["kcal"]
    out.update(day_total=round(day_total), day_gap=round(gap),
               day_pct=round(day_total / t["kcal"] * 100))

    # proteine: obiettivo del giorno contro il pasto (le fisse non le sappiamo
    # qui: si guarda solo che il pasto ne porti una quota sensata)
    if t.get("protein_g") and meal.get("protein_g") is not None:
        quota_p = (meals.get(meal_type) or {}).get("target", {}) or {}
        out["protein_quota_g"] = round(quota_p.get("protein_g") or t["protein_g"] / 3)

    lines: List[str] = []
    tol = max(quota * DAY_TOL, 60)
    if abs(meal["kcal"] - quota) <= tol:
        lines.append(f"In linea con la quota {_OF[meal_type]} ({round(quota)} kcal).")
    elif meal["kcal"] > quota:
        lines.append(f"{round(meal['kcal'] - quota)} kcal sopra la quota {_OF[meal_type]} "
                     f"({round(quota)} kcal).")
    else:
        lines.append(f"{round(quota - meal['kcal'])} kcal sotto la quota {_OF[meal_type]} "
                     f"({round(quota)} kcal).")

    rebalance = None
    if not other_eaten:
        if left_for_other < MIN_OTHER_KCAL:
            lines.append(f"Per {_FOR[other_mt]} resterebbero solo ~{round(max(left_for_other, 0))} kcal: "
                         "difficile compensare in un pasto solo, meglio scegliere più leggero.")
        else:
            lines.append(f"Per {_FOR[other_mt]} restano ~{round(left_for_other)} kcal.")
        if other_kcal:
            factor = left_for_other / other_kcal
            rebalance = {"meal_type": other_mt, "planned_kcal": round(other_kcal),
                         "left_kcal": round(max(left_for_other, 0)),
                         "factor": round(max(factor, 0), 2)}
            if factor < 0.9 and left_for_other >= MIN_OTHER_KCAL:
                lines.append(f"Previsto per {_FOR[other_mt]}: {round(other_kcal)} kcal → "
                             f"porzioni al ~{round(factor * 100)}% (o un piatto più leggero).")
            elif factor > 1.1:
                lines.append(f"Previsto per {_FOR[other_mt]}: {round(other_kcal)} kcal → "
                             "c'è margine per una porzione più abbondante.")
    out["rebalance"] = rebalance

    over = gap / t["kcal"]
    if abs(over) <= DAY_TOL:
        level = "ok"
    elif over > 0:
        level = "over" if over <= 0.25 else "way_over"
    else:
        level = "under"
    how = ("mangiato" if other_eaten else "alla sua quota" if other_assumed else "come previsto")
    lines.append(f"Giornata con {_FOR[other_mt]} {how}: "
                 f"{round(day_total)} / {round(t['kcal'])} kcal ({out['day_pct']}%).")
    out["verdict"] = {"level": level, "lines": lines,
                      "text": {"ok": "Si può fare", "over": "Sgarro gestibile",
                               "way_over": "Sgarro pesante", "under": "Leggero",
                               }.get(level, "")}
    return out


def _day(request: Request, db: Session, profile_id: str, d: date):
    s = get_integration_summary(request, profile_id, d, d, False, True, db)
    return (s.get("days") or [{}])[0], s.get("targets") or {}


def _nutrition(ingredients: List[PhotoIngredient], profile_id: str, gw) -> Dict[str, float]:
    n = compute_recipe_nutrition(_mensa_content(ingredients, profile_id), profile_id, llm_gateway=gw)
    if not n or not n.get("kcal"):
        raise HTTPException(status_code=422, detail="Non riesco a stimare kcal per questo pasto.")
    return n


class SimulateBody(_BaseModel):
    description: Optional[str] = None
    candidate_id: Optional[str] = None
    name: Optional[str] = None
    ingredients: Optional[List[PhotoIngredient]] = None


@router.post("/meal")
def simulate_meal(body: SimulateBody, request: Request, profile_id: str, meal_type: str,
                  target_date: Optional[date] = None, db: Session = Depends(get_db)):
    """Stima il pasto (ingredienti dati, pasto salvato o descrizione libera via
    LLM) e lo mette nella giornata. Non registra nulla."""
    if meal_type not in MAIN_MEALS:
        raise HTTPException(status_code=422, detail="meal_type deve essere pranzo o cena.")
    gw = getattr(request.app.state, "llm_gateway", None)
    name, ingredients = body.name, body.ingredients
    if not ingredients and body.candidate_id:
        cand = db.get(CandidateRecipe, body.candidate_id)
        data = _is_mensa_candidate(cand) if cand else None
        if not data:
            raise HTTPException(status_code=404, detail="Pasto salvato non trovato.")
        name = data.get("name")
        ingredients = []
        for ing in data.get("content") or []:
            q = ing.get("quantities") or {}
            qty = q.get(profile_id) or next(iter(q.values()), {}) or {}
            ingredients.append(PhotoIngredient(name=ing.get("name"), food_group=ing.get("food_group") or "altro",
                                               grams=float(qty.get("grams_equiv") or qty.get("qty") or 0)))
    if not ingredients:
        desc = (body.description or "").strip()
        if len(desc) < 3:
            raise HTTPException(status_code=422, detail="Descrivi il pasto (almeno 3 caratteri).")
        if gw is None or gw._client is None:
            raise HTTPException(status_code=503, detail="LLM non configurato: impossibile stimare il pasto.")
        res = gw.estimate_meal_from_text(desc)
        if not res:
            raise HTTPException(status_code=422, detail="Non riconosco un pasto nella descrizione.")
        name = res["name"]
        ingredients = [PhotoIngredient(**i) for i in res["ingredients"]]
    nutrition = _nutrition(ingredients, profile_id, gw)
    day, targets = _day(request, db, profile_id, target_date or date.today())
    return {"name": name or "Pasto", "ingredients": [i.model_dump() for i in ingredients],
            **simulate_day(day, targets, meal_type, nutrition)}


class SuggestBody(_BaseModel):
    place: str
    notes: str = ""


@router.post("/suggest")
def suggest_order(body: SuggestBody, request: Request, profile_id: str, meal_type: str,
                  target_date: Optional[date] = None, db: Session = Depends(get_db)):
    """"Stasera cinese: cosa prendo?" — l'LLM propone 3 ordini realistici per quel
    locale/cucina, dimensionati sulla quota del pasto; kcal/macro ricalcolati
    col database nutrizionale (non quelli dichiarati dall'LLM)."""
    if meal_type not in MAIN_MEALS:
        raise HTTPException(status_code=422, detail="meal_type deve essere pranzo o cena.")
    place = (body.place or "").strip()
    if len(place) < 2:
        raise HTTPException(status_code=422, detail="Dimmi dove o cosa mangi (es. cinese, pizzeria).")
    gw = getattr(request.app.state, "llm_gateway", None)
    if gw is None or gw._client is None:
        raise HTTPException(status_code=503, detail="LLM non configurato.")
    day, targets = _day(request, db, profile_id, target_date or date.today())
    probe = simulate_day(day, targets, meal_type, {k: 0.0 for k in KEYS})
    quota = probe.get("quota_kcal") or 700
    protein = probe.get("protein_quota_g") or 35
    # l'LLM tende a sovrastimare porzioni e a sottostimare i condimenti: gli si
    # chiede un tetto più basso, così ricalcolati col database restano vicini alla quota
    res = gw.suggest_restaurant_order(place, quota * SUGGEST_AIM, protein, body.notes)
    if not res or not res.get("options"):
        raise HTTPException(status_code=502, detail="Nessun consiglio dall'AI, riprova.")
    options = []
    for opt in res["options"]:
        ings = [PhotoIngredient(**i) for i in opt["ingredients"]]
        try:
            n = _nutrition(ings, profile_id, gw)
        except HTTPException:
            continue
        options.append({"name": opt["name"], "why": opt.get("why") or "",
                        "ingredients": [i.model_dump() for i in ings],
                        **simulate_day(day, targets, meal_type, n)})
    if not options:
        raise HTTPException(status_code=502, detail="Non riesco a stimare i consigli, riprova.")
    options.sort(key=lambda o: abs(o.get("diff_quota") or 0))
    return {"place": place, "quota_kcal": quota, "protein_quota_g": protein,
            "options": options, "avoid": res.get("avoid") or [], "tips": res.get("tips") or []}
