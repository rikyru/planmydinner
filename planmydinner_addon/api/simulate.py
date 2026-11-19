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
MIN_OTHER_KCAL = 300    # sotto questa quota l'altro pasto diventa poco realistico
SUGGEST_AIM = 0.9       # tetto chiesto all'LLM per i consigli, rispetto alla quota


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
    # "deciso" (es. stasera pizza): non ancora mangiato ma non si ribilancia più
    other_locked = other_eaten or bool(other and other.get("decided"))
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
    quota = budget - other_kcal if other_locked and other_kcal is not None else budget / 2
    left_for_other = budget - meal["kcal"]
    out.update(budget_kcal=round(budget), quota_kcal=round(quota),
               diff_quota=round(meal["kcal"] - quota))

    # l'altro pasto: registrato o previsto; se non è nel piano (es. mensa non
    # pianificata) si assume che stia nella sua quota
    other_assumed = other_kcal is None and not other_eaten
    other_day = budget / 2 if other_assumed else (other_kcal or 0)
    day_total = fixed + meal["kcal"] + other_day
    out["other"].update(day_kcal=round(other_day), assumed=other_assumed)
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
    if not other_locked:
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
    how = ("mangiato" if other_eaten else "decisa" if other_locked and other_mt == "cena"
           else "deciso" if other_locked else "alla sua quota" if other_assumed else "come previsto")
    lines.append(f"Giornata con {_FOR[other_mt]} {how}: "
                 f"{round(day_total)} / {round(t['kcal'])} kcal ({out['day_pct']}%).")

    # Macro della giornata, con le stesse ipotesi delle kcal sull'altro pasto
    out["macros"] = macros = _day_macros(day, t, meal, other, other_assumed)
    for m in macros:
        if m["status"] == "high":
            lines.append(f"{m['label']}: {m['total']} / {m['target']} g nella giornata ({m['pct']}%), "
                         f"{m['meal']} g da questo pasto.")
        elif m["status"] == "low" and m["key"] == "protein_g":
            tail = (f": a {_FOR[other_mt].split()[1]} punta su una proteina magra"
                    if not other_locked else "")
            lines.append(f"Proteine basse: {m['total']} / {m['target']} g ({m['pct']}%){tail}.")
    out["verdict"] = {"level": level, "lines": lines,
                      "text": {"ok": "Si può fare", "over": "Sgarro gestibile",
                               "way_over": "Sgarro pesante", "under": "Leggero",
                               }.get(level, "")}
    return out


MACROS = (("protein_g", "Proteine"), ("carbs_g", "Carboidrati"), ("fat_g", "Grassi"))
# soglie sul totale della giornata (% dell'obiettivo): proteine sono un minimo,
# grassi un tetto, carboidrati il "resto" (si segnala solo se molto fuori)
_LOW = {"protein_g": 85, "carbs_g": 70, "fat_g": 60}
_HIGH = {"protein_g": 160, "carbs_g": 120, "fat_g": 115}


def _day_macros(day: Dict[str, Any], t: Dict[str, float], meal: Dict[str, float],
                other: Optional[Dict[str, Any]], other_assumed: bool) -> List[Dict[str, Any]]:
    """Proteine/carbo/grassi della giornata se si mangia `meal`: fissi + pasto +
    altro pasto (registrato, previsto, o alla sua quota se non è nel piano)."""
    fixed = day.get("fixed_nutrition") or {}
    dt = dict(t)
    dt.update({k: float(v) for k, v in (day.get("day_targets") or {}).items() if k != "kcal" and v})
    out = []
    for k, label in MACROS:
        if not dt.get(k):
            continue
        f = float(fixed.get(k) or 0)
        o = (max(dt[k] - f, 0) / 2 if other_assumed
             else float(((other or {}).get("nutrition") or {}).get(k) or 0))
        total = f + float(meal.get(k) or 0) + o
        pct = round(total / dt[k] * 100)
        status = "low" if pct < _LOW[k] else "high" if pct > _HIGH[k] else "ok"
        out.append({"key": k, "label": label, "meal": round(meal.get(k) or 0),
                    "fixed": round(f), "other": round(o), "total": round(total),
                    "target": round(dt[k]), "pct": pct, "status": status})
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


# ---------------------------------------------------------------------------
# "Stasera pizza: cosa prendo in mensa?" — dai vassoi mensa registrati (porzioni
# della mensa, sempre quelle) le combinazioni che stanno nel posto lasciato
# dall'altro pasto, una per tipo di secondo: così qualunque cosa ci sia, sai già
# cosa prendere. Niente LLM per le proposte (solo, se serve, per stimare l'altro pasto).
# ---------------------------------------------------------------------------

MENSA_DAYS = 180
MENSA_MIN_KCAL = 350    # sotto, un pranzo in mensa non regge: meglio sforare un po' la giornata
# (chiave, etichetta, parole) in ordine di priorità per il "secondo" del vassoio
MENSA_CATS = (
    ("pesce", "🐟 Pesce", ("pesce", "salmone", "tonno", "merluzzo", "calamar", "polpo", "gamber", "orata",
                          "branzino", "sgombro", "nasello", "platessa", "sogliola", "cozze", "baccal")),
    ("carne_bianca", "🍗 Pollo / tacchino", ("pollo", "tacchino", "coscia", "petto", "kebab")),
    ("carne_rossa", "🥩 Carne", ("manzo", "vitello", "hamburger", "maiale", "salsiccia", "bresaola", "prosciutto",
                                "polpett", "arrosto", "brasato", "speck", "pancetta", "fassona", "lonza", "arista",
                                "cotolett", "scaloppin", "spezzatino", "roast", "bollito", "wurstel", "cotechino")),
    ("uova", "🍳 Uova / frittata", ("uov", "frittata")),
    ("formaggi", "🧀 Formaggi", ("mozzarell", "formaggio", "ricotta", "feta", "sformato", "stracchino",
                                "scamorza", "caprese")),
    ("legumi", "🫘 Legumi", ("lenticch", "ceci", "fagioli", "edamame", "legum", "hummus")),
    ("primo", "🍕 Pizza / primo", ("pizza", "pasta", "lasagn", "riso", "risotto", "piadina", "torta salata",
                                  "gnocchi", "ravioli", "focaccia", "cous")),
)
_CARB_WORDS = ("pane", "panino", "grissin", "crackers", "pizza", "pasta", "lasagn", "riso", "piadina", "focaccia",
               "gnocchi", "ravioli", "patate", "cous", "brisée", "brisee", "impasto")
_FRUIT_WORDS = ("mela", "banana", "uva", "pesca", "pesche", "anguria", "melone", "pera", "arancia", "kiwi",
                "frutta", "ananas", "fragol", "mandarin", "clementin", "susin", "prugn", "albicocc", "peach", "melon")
_DROPPABLE = (("pane", ("pane", "panino", "grissin", "crackers")), ("frutta", _FRUIT_WORDS),
              ("yogurt", ("yogurt",)))


def _has(name: str, words) -> bool:
    n = (name or "").lower().replace("_", " ")
    return any(w in n for w in words)


def _food_group(name: str) -> str:
    for key, _, words in MENSA_CATS[:-1]:
        if _has(name, words):
            return key
    if _has(name, _CARB_WORDS):
        return "carboidrati"
    if _has(name, _FRUIT_WORDS):
        return "frutta"
    return "verdura"


def _tray_category(ings: List[Dict[str, Any]]) -> str:
    """Tipo di secondo del vassoio: la proteina col peso maggiore (o pizza/primo)."""
    best, best_g = None, -1.0
    for i, (key, _, words) in enumerate(MENSA_CATS[:-1]):
        for ing in ings:
            if _has(ing["name"], words) and ing["grams"] > best_g:
                best, best_g = key, ing["grams"]
    if best and not any(_has(x["name"], MENSA_CATS[-1][2]) and x["grams"] > best_g for x in ings):
        return best
    return "primo" if any(_has(x["name"], MENSA_CATS[-1][2]) for x in ings) else (best or "altro")


def mensa_history(db: Session, profile_id: str, meal_type: str, today: date) -> List[Dict[str, Any]]:
    """Vassoi mensa distinti registrati (stessi ingredienti e grammi = stesso vassoio),
    con quante volte e l'ultima data. Solo giorni feriali, ultimi MENSA_DAYS giorni."""
    from datetime import timedelta
    from ..database import ConsumedEntry
    since = (today - timedelta(days=MENSA_DAYS)).isoformat()
    rows = db.query(ConsumedEntry).filter(ConsumedEntry.profile_id == profile_id,
                                          ConsumedEntry.meal_type == meal_type,
                                          ConsumedEntry.date >= since).all()
    trays: Dict[tuple, Dict[str, Any]] = {}
    for e in rows:
        od = e.override_details or {}
        if od.get("notes") != "mensa":
            continue
        try:
            if date.fromisoformat(e.date).weekday() >= 5:
                continue
        except ValueError:
            continue
        ings = [{"name": str(i.get("name") or "").strip(), "grams": float(i.get("qty") or 0)}
                for i in od.get("ingredients") or [] if isinstance(i, dict)]
        ings = [i for i in ings if i["name"] and i["grams"] > 0]
        if not ings:
            continue
        key = tuple(sorted((i["name"].lower(), round(i["grams"])) for i in ings))
        t = trays.setdefault(key, {"ingredients": ings, "count": 0, "last": e.date})
        t["count"] += 1
        t["last"] = max(t["last"], e.date)
    return list(trays.values())


def _variants(ings: List[Dict[str, Any]]):
    """Il vassoio com'è, poi senza pane, poi senza pane e frutta: le porzioni non
    cambiano, si può solo lasciare un componente."""
    out, cur, dropped = [(ings, [])], ings, []
    for label, words in _DROPPABLE[:2]:
        rest = [i for i in cur if not _has(i["name"], words)]
        if rest and len(rest) < len(cur):
            dropped = dropped + [label]
            out.append((rest, dropped))
            cur = rest
    return out


_NAME_ORDER = {"verdura": 1, "carboidrati": 2, "frutta": 3}


def _tray_name(ings: List[Dict[str, Any]]) -> str:
    """Il secondo per primo, poi contorno, pane/primo, frutta."""
    order = sorted(ings, key=lambda i: (_NAME_ORDER.get(_food_group(i["name"]), 0), -i["grams"]))
    return " · ".join(i["name"].replace("_", " ").strip().capitalize() if k == 0 else i["name"].replace("_", " ").strip().lower()
                      for k, i in enumerate(order))


def rank_mensa(trays: List[Dict[str, Any]], nutr, room: Optional[float], protein_quota: Optional[float],
               avoid_cats=(), per_cat: int = 1, limit: int = 7) -> List[Dict[str, Any]]:
    """Per ogni tipo di secondo la variante di vassoio che meglio sta in `room` kcal.
    `nutr(ings)` -> dict kcal/macro (o None). Funzione pura, testabile."""
    scored = []
    for t in trays:
        cat = _tray_category(t["ingredients"])
        for ings, dropped in _variants(t["ingredients"]):
            n = nutr(ings)
            if not n or not n.get("kcal"):
                continue
            k = float(n["kcal"])
            score = 0.0
            if room:
                score += 2.0 * max(0.0, k - room) + 0.7 * max(0.0, room - 80 - k)
            if protein_quota:
                score += 8.0 * max(0.0, 0.75 * protein_quota - float(n.get("protein_g") or 0))
            score += 60.0 * len(dropped) + (150.0 if cat in avoid_cats else 0.0) - 12.0 * min(t["count"], 5)
            scored.append({"category": cat, "ingredients": ings, "dropped": dropped, "nutrition": n,
                           "count": t["count"], "last": t["last"], "score": score,
                           "fits": room is None or k <= room * 1.08})
    scored.sort(key=lambda x: x["score"])
    out, per = [], {}
    for s in scored:
        sig = tuple(sorted(i["name"].lower() for i in s["ingredients"]))
        if per.get(s["category"], 0) >= per_cat or any(sig == o["_sig"] for o in out):
            continue
        per[s["category"]] = per.get(s["category"], 0) + 1
        out.append({**s, "_sig": sig})
        if len(out) >= limit:
            break
    for o in out:
        o.pop("_sig")
    return out


class MensaBody(_BaseModel):
    other_description: Optional[str] = None   # "stasera pizza margherita"
    other_candidate_id: Optional[str] = None


@router.post("/mensa")
def mensa_options(body: MensaBody, request: Request, profile_id: str, meal_type: str = "pranzo",
                  target_date: Optional[date] = None, db: Session = Depends(get_db)):
    """Proposte dalla mensa per `meal_type`, dato l'altro pasto (descritto ora,
    salvato, o quello del piano)."""
    if meal_type not in MAIN_MEALS:
        raise HTTPException(status_code=422, detail="meal_type deve essere pranzo o cena.")
    d = target_date or date.today()
    gw = getattr(request.app.state, "llm_gateway", None)
    trays = mensa_history(db, profile_id, meal_type, d)
    if not trays:
        raise HTTPException(status_code=404, detail="Nessun pasto in mensa registrato: "
                                                    "registra qualche vassoio con 📷 e poi riprova.")
    day, targets = _day(request, db, profile_id, d)
    other_mt = next(m for m in MAIN_MEALS if m != meal_type)
    other_name, other_ings, other_n = None, None, None
    desc = (body.other_description or "").strip()
    if body.other_candidate_id:
        r = simulate_meal(SimulateBody(candidate_id=body.other_candidate_id), request, profile_id, other_mt, d, db)
        other_name, other_ings, other_n = r["name"], r["ingredients"], r["meal"]
    elif desc:
        if len(desc) < 3:
            raise HTTPException(status_code=422, detail="Descrivi l'altro pasto (almeno 3 caratteri).")
        if gw is None or gw._client is None:
            raise HTTPException(status_code=503, detail="LLM non configurato: non riesco a stimare l'altro pasto.")
        res = gw.estimate_meal_from_text(desc)
        if not res:
            raise HTTPException(status_code=422, detail="Non riconosco un pasto nella descrizione.")
        other_name = res["name"]
        other_ings = [PhotoIngredient(**i).model_dump() for i in res["ingredients"]]
        other_n = _r(_nutrition([PhotoIngredient(**i) for i in other_ings], profile_id, gw))
    if other_n:
        day = {**day, "meals": {**(day.get("meals") or {}),
                                other_mt: {"consumed": False, "decided": True, "nutrition": other_n}}}
    else:   # niente descrizione: vale l'altro pasto del piano, come già deciso
        planned = (day.get("meals") or {}).get(other_mt)
        if planned and (planned.get("nutrition") or {}).get("kcal"):
            other_name, other_n = planned.get("name") or other_mt, _r(planned["nutrition"])
            day = {**day, "meals": {**day["meals"], other_mt: {**planned, "decided": True}}}
    probe = simulate_day(day, targets, meal_type, {k: 0.0 for k in KEYS})
    room = probe.get("quota_kcal")
    aim = max(room, MENSA_MIN_KCAL) if room is not None else None
    pq = probe.get("protein_quota_g")
    avoid = {_tray_category(other_ings)} if other_ings else set()
    cache: Dict[tuple, Any] = {}

    def nutr(ings):
        key = tuple((i["name"].lower(), i["grams"]) for i in ings)
        if key not in cache:
            try:
                cache[key] = compute_recipe_nutrition(
                    _mensa_content([PhotoIngredient(name=i["name"], food_group=_food_group(i["name"]),
                                                    grams=i["grams"]) for i in ings], profile_id),
                    profile_id, llm_gateway=gw)
            except Exception:  # noqa: BLE001
                cache[key] = None
        return cache[key]

    labels = {k: lbl for k, lbl, _ in MENSA_CATS}
    options = []
    for o in rank_mensa(trays, nutr, aim, pq, avoid):
        ings = [{"name": i["name"], "food_group": _food_group(i["name"]), "grams": i["grams"]}
                for i in o["ingredients"]]
        options.append({"name": _tray_name(o["ingredients"]), "category": o["category"],
                        "category_label": labels.get(o["category"], "Altro"),
                        "dropped": o["dropped"], "fits": o["fits"], "times": o["count"], "last": o["last"],
                        "ingredients": ings, **simulate_day(day, targets, meal_type, o["nutrition"])})
    return {"room_kcal": room, "aim_kcal": aim, "protein_quota_g": pq, "trays": len(trays),
            "other": ({"meal_type": other_mt, "name": other_name, "ingredients": other_ings, "nutrition": other_n}
                      if other_n else None),
            "options": options}


class ChooseBody(_BaseModel):
    name: str
    ingredients: List[PhotoIngredient]
    as_free_meal: bool = False
    profile_id_B: Optional[str] = None


@router.post("/choose")
def choose_meal(body: ChooseBody, profile_id: str, meal_type: str,
                target_date: Optional[date] = None, db: Session = Depends(get_db)):
    """Mette il pasto simulato nel piano per (data, pasto) SENZA registrarlo come
    mangiato: lo si segna consumato dopo, come ogni pasto del piano.
    - normale: pasto salvato fra i "pasti da foto" (riusabile dal simulatore, mai
      proposto dal generatore) e messo nello slot come pasto pianificato;
    - as_free_meal: slot "pasto libero" con la stima già fatta (niente nuova
      chiamata all'LLM), conta nella quota settimanale dei liberi."""
    import copy
    import uuid
    from .planner import _set_day_slot, ensure_plan_for_date

    if meal_type not in MAIN_MEALS:
        raise HTTPException(status_code=422, detail="meal_type deve essere pranzo o cena.")
    ings = [i for i in body.ingredients if i.name and i.grams > 0]
    name = (body.name or "").strip() or "Pasto"
    if not ings:
        raise HTTPException(status_code=422, detail="Serve almeno un ingrediente.")
    d = target_date or date.today()
    content = _mensa_content(ings, profile_id)
    if body.as_free_meal:
        cand = CandidateRecipe(id=str(uuid.uuid4()), status="draft_structured", recipe_data={
            "name": name, "description": f"Pasto libero (stima automatica): {name}",
            "is_composed_dish": False, "content": content, "steps": [],
            "total_time_minutes": 0, "difficulty": "sconosciuto",
            "tags": {"free_meal_estimate": ["true"]}})
        item = {"item_name": name, "food_group": "free_meal", "quantity": 0, "unit": "",
                "is_estimated_unit": False, "alternatives": [], "recipe_id": cand.id}
    else:
        cand = None
        for existing in db.query(CandidateRecipe).filter(CandidateRecipe.status == "draft_structured").all():
            data = _is_mensa_candidate(existing)
            if data and (data.get("name") or "").strip().lower() == name.lower():
                cand = existing
                break
        recipe_data = {"name": name, "description": "Pasto fuori casa (dal simulatore)",
                       "is_composed_dish": False, "content": content, "steps": [],
                       "total_time_minutes": 0, "difficulty": "sconosciuto",
                       "tags": {"mensa": ["true"]}, "plan_eligible": False}
        if cand is None:
            cand = CandidateRecipe(id=str(uuid.uuid4()), status="draft_structured", usage_count=0,
                                   recipe_data=recipe_data)
        else:
            cand.recipe_data = recipe_data
        item = {"item_name": name, "food_group": "recipe", "quantity": 1, "unit": "recipe",
                "is_estimated_unit": False, "alternatives": [], "recipe_id": cand.id}
    db.add(cand)
    db.commit()
    plan = ensure_plan_for_date(db, profile_id, d, body.profile_id_B)
    updated = copy.deepcopy(plan.daily_plans)
    if not _set_day_slot(updated, d.isoformat(), meal_type, item):
        raise HTTPException(status_code=409, detail="Giorno non presente nel piano.")
    plan.daily_plans = updated
    db.add(plan)
    db.commit()
    return {"recipe_id": cand.id, "free_meal": body.as_free_meal}
