"""
Valori nutrizionali (kcal + macro) per ingrediente e per ricetta.

Fonti, in ordine di priorità:
1. valori espliciti salvati nell'ingrediente (``nutrition`` con source ``manual`` o ``llm``)
2. tabella di composizione locale (``NUTRITION_TABLE``, source ``table``)
3. stima via LLM (``llm_gateway.estimate_nutrition``, source ``llm``)

Tutti i valori sono PER 100 g. Per cereali, pasta e legumi i valori si riferiscono
al peso a crudo/secco, coerentemente con le grammature dei piani nutrizionali.
"""
import logging
import re
from typing import Any, Dict, List, Optional, Union

_LOGGER = logging.getLogger(__name__)

NUTRITION_KEYS = ("kcal", "protein_g", "carbs_g", "fat_g")


def _v(kcal: float, protein_g: float, carbs_g: float, fat_g: float) -> Dict[str, float]:
    return {"kcal": kcal, "protein_g": protein_g, "carbs_g": carbs_g, "fat_g": fat_g}


# Composizione per 100 g (peso a crudo/secco per cereali e legumi).
# Valori indicativi da tabelle di composizione alimentare italiane.
NUTRITION_TABLE: Dict[str, Dict[str, float]] = {
    # Carboidrati
    "pasta": _v(353, 11.0, 72.0, 1.5),
    "spaghetti": _v(353, 11.0, 72.0, 1.5),
    "trofie": _v(353, 11.0, 72.0, 1.5),
    "penne": _v(353, 11.0, 72.0, 1.5),
    "fusilli": _v(353, 11.0, 72.0, 1.5),
    "gnocchi": _v(133, 3.7, 28.0, 0.5),
    "riso": _v(358, 6.7, 80.0, 0.4),
    "farro": _v(335, 15.0, 67.0, 2.5),
    "orzo": _v(319, 10.4, 70.0, 1.4),
    "couscous": _v(376, 12.8, 77.4, 0.6),
    "quinoa": _v(368, 14.0, 64.0, 6.0),
    "patate": _v(77, 2.0, 17.0, 0.1),
    "patata": _v(77, 2.0, 17.0, 0.1),
    "pane": _v(265, 9.0, 49.0, 3.2),
    "polenta": _v(361, 8.7, 79.0, 2.7),
    # Proteine animali
    "pollo": _v(110, 23.0, 0.0, 1.5),
    "tacchino": _v(107, 24.0, 0.0, 1.0),
    "manzo": _v(158, 26.0, 0.0, 6.0),
    "vitellone": _v(131, 21.8, 0.0, 5.0),
    "vitello": _v(107, 20.7, 0.0, 2.7),
    "maiale": _v(157, 21.0, 0.0, 8.0),
    "salmone": _v(185, 20.4, 1.0, 11.0),
    "merluzzo": _v(82, 17.8, 0.3, 0.9),
    "branzino": _v(97, 18.5, 0.6, 2.5),
    "orata": _v(100, 19.8, 1.2, 2.4),
    "tonno": _v(159, 21.5, 0.0, 8.0),
    "gamberetti": _v(85, 18.0, 0.5, 1.0),
    "gamberi": _v(85, 18.0, 0.5, 1.0),
    "uova": _v(143, 12.4, 0.5, 9.5),
    "uovo": _v(143, 12.4, 0.5, 9.5),
    "bresaola": _v(151, 32.0, 0.4, 2.0),
    "prosciutto crudo": _v(224, 26.9, 0.3, 12.9),
    "prosciutto cotto": _v(132, 19.8, 0.9, 5.5),
    # Legumi (secchi)
    "ceci": _v(316, 20.9, 46.9, 6.3),
    "lenticchie": _v(325, 25.0, 54.0, 2.5),
    "fagioli": _v(311, 23.6, 47.5, 2.0),
    "fagioli cannellini": _v(311, 23.6, 47.5, 2.0),
    "piselli": _v(76, 5.5, 12.4, 0.6),
    "tofu": _v(76, 8.0, 1.9, 4.8),
    # Latticini
    "ricotta": _v(146, 8.8, 3.5, 10.9),
    "mozzarella": _v(253, 18.7, 0.7, 19.5),
    "parmigiano": _v(392, 33.0, 0.0, 28.0),
    "grana": _v(392, 33.0, 0.0, 28.0),
    "feta": _v(264, 14.0, 4.0, 21.0),
    "yogurt greco": _v(97, 9.0, 3.9, 5.0),
    "yogurt": _v(66, 3.8, 4.3, 3.9),
    # Verdure
    "zucchina": _v(14, 1.3, 1.4, 0.1),
    "zucchine": _v(14, 1.3, 1.4, 0.1),
    "melanzana": _v(20, 1.1, 2.6, 0.4),
    "melanzane": _v(20, 1.1, 2.6, 0.4),
    "broccoli": _v(30, 3.0, 2.0, 0.4),
    "spinaci": _v(23, 2.9, 2.9, 0.4),
    "insalata": _v(15, 1.4, 2.2, 0.2),
    "lattuga": _v(15, 1.4, 2.2, 0.2),
    "rucola": _v(28, 2.6, 3.9, 0.3),
    "pomodoro": _v(18, 1.0, 3.5, 0.2),
    "pomodori": _v(18, 1.0, 3.5, 0.2),
    "pomodorini": _v(18, 1.0, 3.5, 0.2),
    "pomodorino": _v(18, 1.0, 3.5, 0.2),
    "carota": _v(35, 1.1, 7.6, 0.2),
    "carote": _v(35, 1.1, 7.6, 0.2),
    "peperone": _v(26, 0.9, 4.2, 0.3),
    "peperoni": _v(26, 0.9, 4.2, 0.3),
    "fagiolini": _v(25, 2.1, 2.4, 0.1),
    "funghi": _v(22, 3.1, 3.3, 0.3),
    "funghi porcini": _v(22, 3.1, 3.3, 0.3),
    "zucca": _v(26, 1.1, 6.5, 0.1),
    "asparagi": _v(24, 3.0, 3.0, 0.2),
    "sedano": _v(16, 0.7, 3.0, 0.2),
    "cipolla": _v(40, 1.0, 9.0, 0.1),
    "aglio": _v(41, 0.9, 8.4, 0.6),
    "finocchio": _v(31, 1.2, 7.0, 0.2),
    "radicchio": _v(23, 1.4, 4.5, 0.3),
    "carciofi": _v(47, 2.7, 10.5, 0.2),
    "cavolo": _v(25, 2.1, 2.5, 0.1),
    "cavolfiore": _v(25, 2.1, 2.5, 0.1),
    "limone": _v(29, 1.1, 9.3, 0.3),
    # Grassi e condimenti
    "olio": _v(899, 0.0, 0.0, 99.9),
    "burro": _v(758, 0.8, 1.1, 83.4),
    "pesto": _v(450, 5.0, 6.0, 45.0),
    "avocado": _v(160, 2.0, 8.5, 15.0),
    "noci": _v(654, 15.2, 13.7, 65.2),
    "mandorle": _v(603, 22.0, 4.6, 55.3),
}

# Chiavi ordinate per lunghezza decrescente: la corrispondenza più specifica vince
# (es. "yogurt greco" prima di "yogurt").
_TABLE_KEYS_BY_LENGTH = sorted(NUTRITION_TABLE.keys(), key=len, reverse=True)

# Resa in cottura (peso cotto / peso a crudo) per gli alimenti che in tabella sono
# a crudo o secco. In cottura assorbono acqua: 100 g di lenticchie COTTE valgono
# molto meno di 100 g di lenticchie secche. Senza questa correzione una ricetta
# con "lenticchie cotte 220 g" veniva contata al valore del secco, circa 2,6
# volte le calorie reali.
_COOKED_YIELD: Dict[str, float] = {
    "pasta": 2.3,
    "spaghetti": 2.3,
    "penne": 2.3,
    "fusilli": 2.3,
    "trofie": 2.3,
    "riso": 2.8,
    "farro": 2.7,
    "orzo": 2.6,
    "couscous": 3.0,
    "quinoa": 3.0,
    "ceci": 2.4,
    "lenticchie": 2.6,
    "fagioli": 2.6,
    "fagioli cannellini": 2.6,
    "polenta": 4.0,
}

# Diciture che indicano il peso DA COTTO: "lenticchie cotte", "ceci in scatola",
# "riso lessato". Le voci di tabella che contengono gia' una di queste parole
# (es. "prosciutto cotto") non sono in _COOKED_YIELD, quindi restano invariate:
# la conversione scatta solo su crudo/secco.
_COOKED_RE = re.compile(
    r"\b(cott[oaie]|lessat[oaie]|bollit[oaie]|precott[oaie]|scolat[oaie]|"
    r"in scatola|in barattolo)\b",
    re.IGNORECASE,
)


def _match_table_key(name: str) -> Optional[str]:
    """Chiave di tabella corrispondente al nome (parola intera, la piu' lunga vince)."""
    if name in NUTRITION_TABLE:
        return name
    for key in _TABLE_KEYS_BY_LENGTH:
        if re.search(rf"\b{re.escape(key)}\b", name):
            return key
    return None


def is_cooked_weight(item_name: str) -> bool:
    """True se il nome indica un alimento pesato da cotto la cui voce e' a crudo."""
    name = (item_name or "").strip().lower()
    key = _match_table_key(name)
    return bool(key and key in _COOKED_YIELD and _COOKED_RE.search(name))



def lookup_nutrition_table(item_name: str) -> Optional[Dict[str, float]]:
    """
    Cerca un ingrediente nella tabella locale (parola intera, chiave piu' lunga
    prima). Se il nome indica il peso da cotto di un alimento che in tabella e'
    a crudo o secco, i valori vengono riportati al peso cotto.
    """
    if not item_name:
        return None
    name = item_name.strip().lower()
    key = _match_table_key(name)
    if key is None:
        return None
    values = dict(NUTRITION_TABLE[key])
    if key in _COOKED_YIELD and _COOKED_RE.search(name):
        # solo diluizione in acqua: kcal e macro scalano con lo stesso fattore
        cooked_yield = _COOKED_YIELD[key]
        values = {k: round(v / cooked_yield, 1) for k, v in values.items()}
    return values


def _valid_nutrition(data: Any) -> Optional[Dict[str, float]]:
    """Normalizza un dict nutrition arbitrario; None se mancano i campi o non sono numerici."""
    if not isinstance(data, dict):
        return None
    try:
        values = {k: float(data[k]) for k in NUTRITION_KEYS}
    except (KeyError, TypeError, ValueError):
        return None
    if values["kcal"] < 0 or values["kcal"] > 950:
        return None
    return values


def resolve_ingredient_nutrition(
    ingredient: Dict[str, Any],
    llm_gateway: Any = None,
) -> Optional[Dict[str, Any]]:
    """
    Risolve i valori per 100 g di un ingrediente (dict RecipeIngredient).
    Ritorna {kcal, protein_g, carbs_g, fat_g, source} oppure None.
    """
    # 1. Valori espliciti salvati nell'ingrediente (manual o llm persistito)
    stored = _valid_nutrition(ingredient.get("nutrition"))
    if stored:
        stored["source"] = (ingredient.get("nutrition") or {}).get("source") or "manual"
        return stored

    name = ingredient.get("name") or ""

    # 2. Tabella locale
    table = lookup_nutrition_table(name)
    if table:
        table["source"] = "table_cooked" if is_cooked_weight(name) else "table"
        return table

    # 3. Stima LLM (cachata su disco dal gateway)
    if llm_gateway is not None:
        try:
            estimated = _valid_nutrition(llm_gateway.estimate_nutrition(name))
        except Exception as e:
            _LOGGER.warning(f"Stima LLM nutrizione fallita per '{name}': {e}")
            estimated = None
        if estimated:
            estimated["source"] = "llm"
            return estimated

    return None


def _ingredient_grams(ingredient: Dict[str, Any], profile_id: str) -> Optional[float]:
    """Grammi dell'ingrediente per il profilo (grams_equiv, fallback qty se unit='g').

    Stessa logica di fallback di PlannerEngine._get_qty_for_profile: prima il
    profile_id reale, poi le chiavi posizionali usate dalle ricette seed.
    """
    quantities = ingredient.get("quantities") or {}
    qty_data = (
        quantities.get(profile_id)
        or quantities.get("persona_a")
        or quantities.get("persona_b")
    )
    if not isinstance(qty_data, dict):
        return None
    grams = qty_data.get("grams_equiv")
    if grams is None and str(qty_data.get("unit", "")).lower() == "g":
        grams = qty_data.get("qty")
    try:
        return float(grams) if grams is not None else None
    except (TypeError, ValueError):
        return None


def _content_ingredients(content: Union[List, Dict, None]) -> List[Dict[str, Any]]:
    """Estrae la lista di ingredienti da Recipe.content (lista o ComposedDishContent)."""
    if isinstance(content, list):
        return [i for i in content if isinstance(i, dict)]
    if isinstance(content, dict):
        return [i for i in content.get("components", []) if isinstance(i, dict)]
    return []


def compute_recipe_nutrition(
    content: Union[List, Dict, None],
    profile_id: str,
    llm_gateway: Any = None,
) -> Optional[Dict[str, Any]]:
    """
    Calcola kcal e macro totali di una porzione (i grammi del profilo indicato).

    Ritorna::

        {"kcal": ..., "protein_g": ..., "carbs_g": ..., "fat_g": ...,
         "coverage": matched/total, "sources": {"table": n, "llm": n, "manual": n}}

    oppure None se nessun ingrediente con grammi noti è risolvibile.
    """
    ingredients = _content_ingredients(content)
    totals = {k: 0.0 for k in NUTRITION_KEYS}
    with_grams = 0
    matched = 0
    sources: Dict[str, int] = {}

    for ing in ingredients:
        grams = _ingredient_grams(ing, profile_id)
        if not grams or grams <= 0:
            continue
        with_grams += 1
        nutrition = resolve_ingredient_nutrition(ing, llm_gateway=llm_gateway)
        if not nutrition:
            continue
        matched += 1
        sources[nutrition["source"]] = sources.get(nutrition["source"], 0) + 1
        factor = grams / 100.0
        for k in NUTRITION_KEYS:
            totals[k] += nutrition[k] * factor

    if matched == 0:
        return None

    result: Dict[str, Any] = {k: round(totals[k], 1) for k in NUTRITION_KEYS}
    result["coverage"] = round(matched / with_grams, 2) if with_grams else 0.0
    result["sources"] = sources
    return result
