"""
Equilibrio dell'alimentazione su 7 giorni: frutta/verdura (calcolate dagli
ingredienti, vedi produce.py) e una valutazione AI a richiesta di varietà, fibre
e micronutrienti (stime qualitative dagli alimenti: il database ha solo kcal e
macro).
"""
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from .integration import get_integration_summary
from .routine import get_routine_meals

router = APIRouter(prefix="/balance", tags=["balance"])

MIN_DAYS = 3   # sotto i 3 giorni registrati la valutazione non dice nulla di utile


def week_payload(summary: Dict[str, Any], routine: Dict[str, Any], profile_id: str) -> Dict[str, Any]:
    """Settimana compatta per l'LLM: solo giorni con dati, alimenti e grammi."""
    def _content(c) -> List[str]:
        out = []
        for ing in c or []:
            if not isinstance(ing, dict):
                continue
            q = (ing.get("quantities") or {})
            qty = q.get(profile_id) or next(iter(q.values()), {}) or {}
            g = qty.get("grams_equiv") or qty.get("qty") if isinstance(qty, dict) else None
            out.append(f"{ing.get('name')} {round(g)} g" if g else str(ing.get("name")))
        return out

    fixed = {m["name"]: _content(m["content"]) for m in routine.values() if m.get("name")}
    days = []
    for d in summary.get("days") or []:
        if not d.get("nutrition") or d.get("future"):
            continue
        meals = {}
        for mt, m in (d.get("meals") or {}).items():
            if not m.get("consumed"):
                continue
            meals[mt] = [f"{i['name']} {round(i['grams'])} g" for i in m.get("ingredients") or []] \
                or ["(pasto senza dettaglio ingredienti)"]
        days.append({
            "data": d["date"],
            "pasti_fissi": d.get("routine_items") or [],
            **meals,
            "extra": [e.get("description") or e.get("name") for e in d.get("extras") or []],
            "frutta_g": (d.get("produce") or {}).get("fruit_g"),
            "verdura_g": (d.get("produce") or {}).get("veg_g"),
            "kcal": round(d["nutrition"]["kcal"]),
            "proteine_g": round(d["nutrition"]["protein_g"]),
            "carbo_g": round(d["nutrition"]["carbs_g"]),
            "grassi_g": round(d["nutrition"]["fat_g"]),
        })
    return {"composizione_pasti_fissi": fixed, "obiettivi": summary.get("targets") or {},
            "giorni": days}


@router.get("/week")
def balance_week(request: Request, profile_id: str, end_date: Optional[date] = None,
                 db: Session = Depends(get_db)):
    """Frutta/verdura per giorno e media della settimana che finisce a end_date
    (solo pasti registrati, come lo Storico)."""
    end = end_date or date.today()
    start = end - timedelta(days=6)
    s = get_integration_summary(request, profile_id, start, end, True, False, db)
    days = [{"date": d["date"], **(d.get("produce") or {}), "has_data": bool(d.get("nutrition"))}
            for d in s.get("days") or [] if not d.get("future")]
    with_data = [d for d in days if d["has_data"]]
    avg = None
    if with_data:
        avg = {k: round(sum(d.get(k) or 0 for d in with_data) / len(with_data))
               for k in ("veg_g", "fruit_g", "total_g")}
    return {"start_date": start.isoformat(), "end_date": end.isoformat(), "days": days,
            "average": avg, "target_g": 400}


@router.post("/review")
def balance_review(request: Request, profile_id: str, end_date: Optional[date] = None,
                   db: Session = Depends(get_db)):
    """Valutazione AI dell'equilibrio degli ultimi 7 giorni registrati."""
    gw = getattr(request.app.state, "llm_gateway", None)
    if gw is None or gw._client is None:
        raise HTTPException(status_code=503, detail="LLM non configurato.")
    end = end_date or date.today()
    start = end - timedelta(days=6)
    s = get_integration_summary(request, profile_id, start, end, True, True, db)
    week = week_payload(s, get_routine_meals(db, profile_id), profile_id)
    if len(week["giorni"]) < MIN_DAYS:
        raise HTTPException(status_code=422,
                            detail=f"Servono almeno {MIN_DAYS} giorni registrati nella settimana.")
    res = gw.review_diet_balance(week)
    if not res:
        raise HTTPException(status_code=502, detail="Nessuna valutazione dall'AI, riprova.")
    return {"start_date": start.isoformat(), "end_date": end.isoformat(),
            "days": len(week["giorni"]), **res}
