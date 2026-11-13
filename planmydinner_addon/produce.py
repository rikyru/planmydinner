"""
Frutta e verdura del giorno, in grammi, dagli ingredienti dei pasti.

Il food_group degli ingredienti non è affidabile (la banana dei pasti fissi è
"altro", i pasti da foto usano gruppi diversi dalle ricette): si usa il gruppo
quando è esplicito e altrimenti il nome. Patate e legumi non contano come
verdura (come nelle linee guida); succhi, marmellate e yogurt "alla frutta" non
contano come frutta.

Riferimento: almeno 400 g al giorno di frutta + verdura (OMS), indicativamente
~250 g di verdura e ~250 g di frutta (5 porzioni, linee guida CREA).
"""
import re
from typing import Any, Dict, Iterable, Optional

from .nutrition import _content_ingredients, apply_portions

TARGET_TOTAL_G = 400
TARGET_VEG_G = 250
TARGET_FRUIT_G = 250

_VEG_GROUPS = {"verdure", "verdura", "ortaggi", "verdure_contorno", "contorno"}
_FRUIT_GROUPS = {"frutta", "frutto"}
_NOT_PRODUCE_GROUPS = {"legumi", "carboidrati", "carboidrato", "proteina", "latticini",
                       "carne_bianca", "carne_rossa", "pesce", "uova", "grassi"}

_FRUIT = re.compile(
    r"\b(mel[ae]|per[ae]|banan[ae]|arance?|arancia|mandarin\w*|clementin\w*|kiwi|ananas|"
    r"fragol\w*|frutti di bosco|mirtill\w*|lampon\w*|more\b|uva|pesc[ae]|albicocc\w*|"
    r"susin\w*|prugn\w*|cilieg\w*|melone|anguria|cachi|fich\w*|melagran\w*|pompelm\w*|"
    r"mango|papaya|frutta)\b", re.I)
_VEG = re.compile(
    r"\b(insalat\w*|lattug\w*|rucola|spinac\w*|zucchin\w*|pomodor\w*|pomodorini|carot\w*|"
    r"broccol\w*|cavol\w*|cavolfior\w*|verz\w*|finocch\w*|peperon\w*|melanzan\w*|"
    r"fagiolin\w*|funghi|champignon|verdur\w*|cetriol\w*|asparag\w*|bietol\w*|"
    r"radicchio|carciof\w*|zucca|cipoll\w*|porr\w*|sedano|catalogna|cicoria|"
    r"cime di rapa|friarielli|minestrone|ortaggi|songino|valeriana|germogli|"
    r"cavoletti|piselli|passata|pelati)\b", re.I)
# prodotti "alla frutta/verdura" che non sono porzioni di frutta o verdura
_EXCLUDE = re.compile(
    r"\b(yogurt|succo|spremut\w*|marmellat\w*|confettur\w*|biscott\w*|cereal\w*|"
    r"barrett\w*|muesli|musli|torta|crostat\w*|gelato|sorbetto|sciroppo|chips|"
    r"patat\w*|essiccat\w*|disidratat\w*|candit\w*)\b", re.I)


def classify(name: str, food_group: Optional[str] = None) -> Optional[str]:
    """'veg', 'fruit' o None."""
    n = (name or "").strip()
    if not n or _EXCLUDE.search(n):
        return None
    g = (food_group or "").strip().lower()
    if g in _VEG_GROUPS:
        return "fruit" if _FRUIT.search(n) and not _VEG.search(n) else "veg"
    if g in _FRUIT_GROUPS:
        return "fruit"
    if g in _NOT_PRODUCE_GROUPS:
        # gruppo esplicito diverso (es. pasta al pomodoro come "carboidrati"):
        # conta solo se il nome è proprio un vegetale semplice
        return None
    if _FRUIT.search(n):
        return "fruit"
    if _VEG.search(n):
        return "veg"
    return None


def _grams(ing: Dict[str, Any], profile_id: str) -> float:
    q = (ing.get("quantities") or {})
    qty = q.get(profile_id) or next(iter(q.values()), None) or {}
    if not isinstance(qty, dict):
        return 0.0
    g = qty.get("grams_equiv")
    if g is None and (qty.get("unit") or "g") in ("g", "gr", "grammi"):
        g = qty.get("qty")
    try:
        return max(float(g or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def content_produce(content: Any, profile_id: str, scale: float = 1.0,
                    portions: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Grammi di verdura e frutta di una ricetta/pasto (content strutturato)."""
    out = {"veg_g": 0.0, "fruit_g": 0.0}
    if not content:
        return out
    try:
        ings = apply_portions(content, portions, scale) if (portions or scale != 1.0) \
            else _content_ingredients(content)
    except Exception:
        ings = _content_ingredients(content)
    for ing in ings or []:
        if not isinstance(ing, dict):
            continue
        kind = classify(ing.get("name"), ing.get("food_group"))
        if kind:
            out["veg_g" if kind == "veg" else "fruit_g"] += _grams(ing, profile_id)
    return out


def items_produce(items: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    """Grammi da una lista piatta {name, food_group?, qty|grams} (merende extra)."""
    out = {"veg_g": 0.0, "fruit_g": 0.0}
    for i in items or []:
        kind = classify(i.get("name"), i.get("food_group"))
        if kind:
            try:
                g = float(i.get("grams") or i.get("qty") or 0)
            except (TypeError, ValueError):
                g = 0.0
            out["veg_g" if kind == "veg" else "fruit_g"] += max(g, 0.0)
    return out


def add(total: Dict[str, float], part: Dict[str, float]) -> None:
    for k in ("veg_g", "fruit_g"):
        total[k] = total.get(k, 0.0) + (part.get(k) or 0.0)
