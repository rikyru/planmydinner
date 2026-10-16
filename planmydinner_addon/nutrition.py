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
    "fregola": _v(356, 12.0, 72.0, 1.5),
    "quinoa": _v(368, 14.0, 64.0, 6.0),
    "patate": _v(77, 2.0, 17.0, 0.1),
    "patata": _v(77, 2.0, 17.0, 0.1),
    "pane": _v(265, 9.0, 49.0, 3.2),
    "farina": _v(340, 11.0, 72.0, 1.0),
    "impasto pizza": _v(250, 7.5, 50.0, 2.5),   # impasto crudo (farina + acqua + lievito)
    "piadina": _v(310, 8.0, 48.0, 9.0),
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
    "speck": _v(303, 28.0, 0.5, 21.0),
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
    "formaggio spalmabile": _v(250, 6.0, 4.0, 23.0),
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
    "bietola": _v(17, 1.8, 2.6, 0.2),
    "bietole": _v(17, 1.8, 2.6, 0.2),
    "limone": _v(29, 1.1, 9.3, 0.3),
    # Frutta
    "mela": _v(52, 0.3, 14.0, 0.2),
    # Grassi e condimenti
    "olio": _v(899, 0.0, 0.0, 99.9),
    "burro": _v(758, 0.8, 1.1, 83.4),
    "pesto": _v(450, 5.0, 6.0, 45.0),
    "avocado": _v(160, 2.0, 8.5, 15.0),
    "noci": _v(654, 15.2, 13.7, 65.2),
    "mandorle": _v(603, 22.0, 4.6, 55.3),
    "curry": _v(325, 13.0, 55.0, 14.0),
    "maionese": _v(680, 1.1, 1.8, 75.0),
    "ketchup": _v(110, 1.2, 25.0, 0.1),
    "senape": _v(95, 6.0, 6.0, 4.0),
    # Bevande (valori per 100 ml ≈ 100 g)
    "coca cola": _v(42, 0.0, 10.6, 0.0),
    "cola": _v(42, 0.0, 10.6, 0.0),
    "bibita": _v(45, 0.0, 11.0, 0.0),
    "aranciata": _v(45, 0.0, 11.0, 0.0),
    "succo": _v(46, 0.2, 11.0, 0.1),
    "birra": _v(43, 0.5, 3.6, 0.0),
    "vino": _v(85, 0.1, 2.6, 0.0),
    # Zero-kcal: evitano stime LLM inutili e non abbassano la coverage
    "sale": _v(0, 0.0, 0.0, 0.0),
    "pepe": _v(0, 0.0, 0.0, 0.0),
    "spezie": _v(0, 0.0, 0.0, 0.0),
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
    "fregola": 2.3,
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


_PAREN_RE = re.compile(r"\([^)]*\)")


def _match_table_key(name: str) -> Optional[str]:
    """Chiave di tabella corrispondente al nome (parola intera, la piu' lunga vince).
    Le parentesi sono una descrizione, non l'alimento: "Impasto pizza (farina,
    acqua, lievito, sale)" non deve diventare "sale" (0 kcal). Si cerca prima
    sul nome senza parentesi; se non c'è nulla l'ingrediente resta sconosciuto
    (→ stima AI) invece di prendere un componente a caso dalla descrizione."""
    if name in NUTRITION_TABLE:
        return name
    bare = _PAREN_RE.sub(" ", name).strip()
    if bare and bare != name:
        return _match_table_key(bare)
    for key in _TABLE_KEYS_BY_LENGTH:
        if re.search(rf"\b{re.escape(key)}\b", name):
            return key
    # Secondo tentativo tollerante alla scrittura: spazi e apostrofi rimossi, cosi'
    # "Cous Cous" trova "couscous" e "fregola sarda"/"d'oliva" restano gestiti.
    compact = name.replace(" ", "").replace("'", "").replace("’", "")
    if compact != name:
        for key in _TABLE_KEYS_BY_LENGTH:
            if re.search(rf"\b{re.escape(key.replace(' ', ''))}\b", compact):
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


def analyze_recipe(
    content: Union[List, Dict, None],
    profile_id: str,
    llm_gateway: Any = None,
    add_cooking_fat_g: float = 0.0,
) -> Dict[str, Any]:
    """Diagnostica per l'inserimento di una ricetta: nutrizione calcolata +
    problemi per ingrediente, così la UI può segnalare cosa manca prima di
    salvare. Non solleva: i problemi sono dati, non errori.

    Ritorna::

        {"nutrition": {...} | None,
         "issues": [{"ingredient": nome, "issue": "no_grams"|"unknown"|"estimated_llm"}],
         "warnings": ["no_added_fat", "no_vegetables", ...],
         "suggestions": [{"action": "add_ingredient"|"set_grams", ...}]}

    `suggestions` sono azioni concrete che la UI può proporre con un click:
    aggiungere l'olio di cottura, mettere una grammatura mancante, aggiungere la
    verdura. Es. "verdure cotte ma niente olio? aggiungi 10 g".
    """
    ingredients = _content_ingredients(content)
    issues: List[Dict[str, str]] = []
    suggestions: List[Dict[str, Any]] = []
    for ing in ingredients:
        name = (ing.get("name") or "?").strip()
        grams = _ingredient_grams(ing, profile_id)
        if not grams or grams <= 0:
            issues.append({"ingredient": name, "issue": "no_grams"})
            fg = (ing.get("food_group") or "altro").strip().lower()
            suggestions.append({"action": "set_grams", "ingredient": name,
                                "grams": _SUGGESTED_GRAMS.get(fg, 50),
                                "reason": "grammatura mancante"})
            continue
        n = resolve_ingredient_nutrition(ing, llm_gateway=llm_gateway)
        if not n:
            issues.append({"ingredient": name, "issue": "unknown"})
        elif n.get("source") == "llm":
            issues.append({"ingredient": name, "issue": "estimated_llm"})

    nutrition = compute_recipe_nutrition(
        content, profile_id, llm_gateway=llm_gateway, add_cooking_fat_g=add_cooking_fat_g)

    warnings: List[str] = []
    groups = {(ing.get("food_group") or "").strip().lower() for ing in ingredients}
    if nutrition is not None and not _has_added_fat(ingredients):
        warnings.append("no_added_fat")
        suggestions.append({"action": "add_ingredient", "name": "Olio extravergine d'oliva",
                            "food_group": "condimenti", "grams": 10,
                            "reason": "i piatti cotti assorbono olio: aggiungilo per kcal realistiche"})
    if ingredients and not (groups & {"verdure", "verdura"}):
        warnings.append("no_vegetables")
        suggestions.append({"action": "add_ingredient", "name": "Verdure miste",
                            "food_group": "verdure", "grams": 200,
                            "reason": "nessuna verdura nel piatto"})
    return {"nutrition": nutrition, "issues": issues, "warnings": warnings,
            "suggestions": suggestions}


# Grammature tipiche per gruppo, suggerite quando manca la dose di un ingrediente.
_SUGGESTED_GRAMS = {
    "carboidrati": 80, "carboidrato": 80, "proteina": 150, "proteine": 150,
    "carne_bianca": 150, "carne_rossa": 150, "pesce": 150, "uova": 100,
    "legumi": 120, "latticini": 60, "formaggio": 60, "verdure": 200, "verdura": 200,
    "condimenti": 10, "grassi": 10, "frutta": 150, "altro": 50,
}


def _content_ingredients(content: Union[List, Dict, None]) -> List[Dict[str, Any]]:
    """Estrae la lista di ingredienti da Recipe.content (lista o ComposedDishContent)."""
    if isinstance(content, list):
        return [i for i in content if isinstance(i, dict)]
    if isinstance(content, dict):
        return [i for i in content.get("components", []) if isinstance(i, dict)]
    return []


# Grasso di cottura di default (g di olio) per i piatti salati inseriti senza
# alcun condimento grasso: molte ricette del nutrizionista non elencano l'olio
# pur assumendone l'uso, azzerando ~70-90 kcal a porzione. Allowance non
# distruttiva (non modifica la ricetta), applicata solo da chi la richiede
# esplicitamente (pranzo/cena), mai colazione/spuntini.
DEFAULT_COOKING_FAT_G = 8.0
_ADDED_FAT_KEYS = ("olio", "burro", "pesto", "avocado", "noci", "mandorle")


def _has_added_fat(ingredients: List[Dict[str, Any]]) -> bool:
    """True se la ricetta contiene già un grasso da condimento/cottura."""
    for ing in ingredients:
        if (ing.get("food_group") or "").strip().lower() in ("condimenti", "grasso"):
            return True
        if _match_table_key((ing.get("name") or "").strip().lower()) in _ADDED_FAT_KEYS:
            return True
    return False


def compute_recipe_nutrition(
    content: Union[List, Dict, None],
    profile_id: str,
    llm_gateway: Any = None,
    add_cooking_fat_g: float = 0.0,
) -> Optional[Dict[str, Any]]:
    """
    Calcola kcal e macro totali di una porzione (i grammi del profilo indicato).

    Ritorna::

        {"kcal": ..., "protein_g": ..., "carbs_g": ..., "fat_g": ...,
         "coverage": matched/total, "sources": {"table": n, "llm": n, "manual": n}}

    oppure None se nessun ingrediente con grammi noti è risolvibile.

    ``add_cooking_fat_g``: se > 0 e la ricetta non ha già un grasso aggiunto,
    somma quel quantitativo di olio come stima del grasso di cottura. Pensato
    per i soli pasti principali (pranzo/cena); i chiamanti di colazione/spuntini
    lasciano 0 per non inventare olio dove non serve.
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

    cooking_fat_added = False
    if add_cooking_fat_g and add_cooking_fat_g > 0 and not _has_added_fat(ingredients):
        oil = NUTRITION_TABLE["olio"]
        factor = add_cooking_fat_g / 100.0
        for k in NUTRITION_KEYS:
            totals[k] += oil[k] * factor
        cooking_fat_added = True

    result: Dict[str, Any] = {k: round(totals[k], 1) for k in NUTRITION_KEYS}
    result["coverage"] = round(matched / with_grams, 2) if with_grams else 0.0
    result["sources"] = sources
    result["cooking_fat_added"] = cooking_fat_added
    return result


# Gruppi "scalabili": in un deficit/surplus si agisce sui CARBOIDRATI, lasciando
# proteine e verdure intatte (scaling per-componente). È la leva energetica
# principale e la più sensata da ridurre/aumentare per centrare le kcal.
_SCALABLE_GROUPS = ("carboidrati", "carboidrato")


def recipe_nutrition_split(
    content: Union[List, Dict, None],
    profile_id: str,
    llm_gateway: Any = None,
    add_cooking_fat_g: float = 0.0,
) -> Optional[tuple]:
    """Nutrizione divisa in (fissa, scalabile): 'scalabile' = ingredienti del
    gruppo carboidrati (la leva per tagliare/aggiungere energia), 'fissa' = tutto
    il resto (proteine, verdure, grassi) + l'olio di cottura stimato. La porzione
    scalata vale fissa + scalabile × fattore. Entrambe hanno NUTRITION_KEYS.
    None se nessun ingrediente è risolvibile."""
    ingredients = _content_ingredients(content)
    fixed = {k: 0.0 for k in NUTRITION_KEYS}
    scal = {k: 0.0 for k in NUTRITION_KEYS}
    matched = 0
    for ing in ingredients:
        grams = _ingredient_grams(ing, profile_id)
        if not grams or grams <= 0:
            continue
        nutrition = resolve_ingredient_nutrition(ing, llm_gateway=llm_gateway)
        if not nutrition:
            continue
        matched += 1
        factor = grams / 100.0
        bucket = scal if (ing.get("food_group") or "").strip().lower() in _SCALABLE_GROUPS else fixed
        for k in NUTRITION_KEYS:
            bucket[k] += nutrition[k] * factor
    if matched == 0:
        return None
    if add_cooking_fat_g and add_cooking_fat_g > 0 and not _has_added_fat(ingredients):
        oil = NUTRITION_TABLE["olio"]
        f = add_cooking_fat_g / 100.0
        for k in NUTRITION_KEYS:
            fixed[k] += oil[k] * f   # l'olio di cottura è "fisso", non si taglia
    return fixed, scal


def scaled_nutrition(split: tuple, scale: float) -> Dict[str, float]:
    """Combina (fissa, scalabile) applicando il fattore solo ai carboidrati."""
    fixed, scal = split
    return {k: round(fixed[k] + scal[k] * scale, 1) for k in NUTRITION_KEYS}


# Soglie di bilanciamento di un pasto (su % delle kcal).
BALANCE_FAT_PCT = 0.40     # oltre → troppi grassi
BALANCE_CARB_PCT = 0.65    # oltre → troppi carboidrati
PROTEIN_LOW_RATIO = 0.80   # sotto l'80% del target → proteine insufficienti
_PROTEIN_GROUPS_BAL = ("proteina", "proteine", "carne_bianca", "carne_rossa",
                       "pesce", "uova", "legumi", "latticini", "formaggio")


def _protein_add_hint(content, profile_id, add_protein_g, llm_gateway=None) -> str:
    """Quanti grammi della proteina del piatto aggiungere per colmare il deficit."""
    for ing in _content_ingredients(content):
        if (ing.get("food_group") or "").strip().lower() in _PROTEIN_GROUPS_BAL:
            n = resolve_ingredient_nutrition(ing, llm_gateway=llm_gateway)
            if n and n.get("protein_g", 0) > 0:
                grams = add_protein_g / (n["protein_g"] / 100.0)
                return f"aggiungi ~{round(grams)} g di {ing.get('name')}"
    return f"aggiungi ~{round(add_protein_g)} g di proteine"


# Spuntini proteici suggeriti per integrare le proteine nella giornata (g proteine/100 g).
_PROTEIN_SNACKS = [
    ("yogurt greco", 9.0), ("fiocchi di latte", 12.0), ("grana", 33.0),
    ("bresaola", 32.0), ("uova sode", 12.4),
]


_SNACK_FOOD_GROUP = {"yogurt greco": "latticini", "fiocchi di latte": "latticini",
                     "grana": "latticini", "bresaola": "carne_rossa", "uova sode": "uova"}


def _protein_snack_hint(add_protein_g: float) -> Dict[str, Any]:
    """Spuntino proteico sensato per colmare il deficit: yogurt greco se la
    porzione resta ragionevole (≤200 g), altrimenti un formaggio più compatto.
    Ritorna {text, name, food_group, grams, protein_g} per il bottone 'aggiungi'."""
    name, dens = _PROTEIN_SNACKS[0]              # yogurt greco
    grams = add_protein_g / (dens / 100.0)
    if grams > 200:                              # porzione troppo grande → formaggio
        name, dens = "grana", 33.0
        grams = add_protein_g / (dens / 100.0)
    grams = round(grams)
    return {
        "name": name.capitalize(), "food_group": _SNACK_FOOD_GROUP.get(name, "altro"),
        "grams": grams, "protein_g": round(add_protein_g),
        "text": f"oppure uno spuntino: ~{grams} g di {name} (+{round(add_protein_g)} g proteine)",
    }


def recipe_balance(content, profile_id: str, protein_target_g: Optional[float] = None,
                   llm_gateway: Any = None,
                   add_cooking_fat_g: float = DEFAULT_COOKING_FAT_G) -> Optional[Dict[str, Any]]:
    """Valuta l'equilibrio di un pasto a porzione: proteine vs target e split
    macro. Ritorna {protein_g, protein_target_g, protein_to_add_g, pct, warnings,
    ok}. `warnings` sono {type, text, adapt?}: low_protein / too_much_fat /
    too_many_carbs. None se la nutrizione non è calcolabile."""
    n = compute_recipe_nutrition(content, profile_id, llm_gateway=llm_gateway,
                                 add_cooking_fat_g=add_cooking_fat_g)
    if not n:
        return None
    out: Dict[str, Any] = {"protein_g": round(n["protein_g"], 1)}
    warnings: List[Dict[str, Any]] = []

    pk, ck, fk = n["protein_g"] * 4, n["carbs_g"] * 4, n["fat_g"] * 9
    tot = pk + ck + fk
    if tot > 0:
        out["pct"] = {"protein": round(pk / tot * 100), "carbs": round(ck / tot * 100),
                      "fat": round(fk / tot * 100)}
        if fk / tot > BALANCE_FAT_PCT:
            warnings.append({"type": "too_much_fat", "text": "pasto sbilanciato: troppi grassi"})
        elif ck / tot > BALANCE_CARB_PCT:
            warnings.append({"type": "too_many_carbs", "text": "pasto sbilanciato: troppi carboidrati"})

    if protein_target_g and protein_target_g > 0:
        out["protein_target_g"] = round(protein_target_g)
        if n["protein_g"] < PROTEIN_LOW_RATIO * protein_target_g:
            add = protein_target_g - n["protein_g"]
            out["protein_to_add_g"] = round(add)
            warnings.append({
                "type": "low_protein",
                "text": f"non rispetta la dose di proteine (~{round(n['protein_g'])}/{round(protein_target_g)} g)",
                "adapt": _protein_add_hint(content, profile_id, add, llm_gateway),
                "extra": _protein_snack_hint(add)})

    out["warnings"] = warnings
    out["ok"] = not warnings
    return out


# ── Feedback per pasto: macro vs obiettivo + suggerimenti concreti ──────────

MEAL_TOLERANCE = 0.10          # ±10% dall'obiettivo del pasto è "in linea"
MEAL_FAT_FALLBACK_PCT = 0.35   # senza target grassi: tetto al 35% delle kcal
_ADDED_FAT_GROUPS = ("condimenti", "grasso", "grassi")

# Alternativa più magra per gli ingredienti grassi più comuni (chiave di tabella
# → (testo, chiave di tabella dell'alternativa per stimare il risparmio)).
_LEAN_SWAPS: Dict[str, tuple] = {
    "salmone": ("merluzzo o orata", "orata"),
    "tonno": ("tonno al naturale o merluzzo", "merluzzo"),
    "manzo": ("vitello o pollo", "vitello"),
    "vitellone": ("vitello o pollo", "vitello"),
    "maiale": ("lonza magra o tacchino", "tacchino"),
    "speck": ("bresaola", "bresaola"),
    "prosciutto crudo": ("bresaola o cotto sgrassato", "bresaola"),
    "mozzarella": ("mozzarella light o fiocchi di latte", "ricotta"),
    "feta": ("ricotta o feta light", "ricotta"),
    "formaggio spalmabile": ("yogurt greco", "yogurt greco"),
    "uova": ("1 uovo intero + albumi", None),
    "uovo": ("1 uovo intero + albumi", None),
    "burro": ("5 g d'olio", None),
    "pesto": ("pomodoro fresco e basilico", "pomodoro"),
}


def _round5(x: float) -> int:
    return int(5 * round(x / 5.0))


def _meal_parts(content, profile_id: str, scale: float, llm_gateway: Any,
                add_cooking_fat_g: float) -> List[Dict[str, Any]]:
    """Ingredienti del pasto con i loro macro a porzione (carboidrati scalati
    come nel piano), più l'olio di cottura stimato se la ricetta non ne ha."""
    ingredients = _content_ingredients(content)
    parts: List[Dict[str, Any]] = []
    for ing in ingredients:
        grams = _ingredient_grams(ing, profile_id)
        if not grams or grams <= 0:
            continue
        n = resolve_ingredient_nutrition(ing, llm_gateway=llm_gateway)
        if not n:
            continue
        fg = (ing.get("food_group") or "").strip().lower()
        if fg in _SCALABLE_GROUPS:
            grams *= scale
        name = (ing.get("name") or "?").strip()
        key = _match_table_key(name.lower())
        parts.append({
            "name": name, "key": key, "food_group": fg, "grams": grams,
            "added_fat": fg in _ADDED_FAT_GROUPS or key in _ADDED_FAT_KEYS,
            **{k: n[k] * grams / 100.0 for k in NUTRITION_KEYS},
            "per100": {k: n[k] for k in NUTRITION_KEYS},
        })
    if parts and add_cooking_fat_g > 0 and not _has_added_fat(ingredients):
        oil = NUTRITION_TABLE["olio"]
        parts.append({
            "name": "olio di cottura", "key": "olio", "food_group": "condimenti",
            "grams": add_cooking_fat_g, "added_fat": True, "estimated": True,
            **{k: oil[k] * add_cooking_fat_g / 100.0 for k in NUTRITION_KEYS},
            "per100": dict(oil),
        })
    return parts


def _fat_tips(parts: List[Dict[str, Any]], excess_fat: float,
              protect_protein: bool = False) -> List[Dict[str, Any]]:
    """Fino a 2 interventi sugli ingredienti più grassi per coprire l'eccesso.
    I carboidrati non si toccano qui (li gestisce il suggerimento sulle kcal,
    così lo stesso ingrediente non viene ridotto due volte); con
    `protect_protein` la proteina del piatto non si riduce, si sostituisce."""
    tips: List[Dict[str, Any]] = []
    covered = 0.0
    for p in sorted(parts, key=lambda p: p["fat_g"], reverse=True):
        if len(tips) >= 2 or covered >= excess_fat or p["fat_g"] < 3:
            break
        if p["food_group"] in _SCALABLE_GROUPS or p.get("estimated"):
            continue   # olio di cottura stimato: è un'ipotesi, non un dato da correggere
        g = p["grams"]
        is_protein = p["food_group"] in _PROTEIN_GROUPS_BAL
        if p["added_fat"] and p["key"] != "burro" and p["key"] != "pesto":
            if g <= 5.5:
                continue
            saving = p["fat_g"] - p["per100"]["fat_g"] * 5 / 100.0
            text = (f"Usa 5 g d'olio (1 cucchiaino) invece di {round(g)} g: cottura al forno, "
                    f"al vapore o in padella antiaderente")
        elif p["key"] in _LEAN_SWAPS:
            swap_text, swap_key = _LEAN_SWAPS[p["key"]]
            if swap_key:
                saving = p["fat_g"] - NUTRITION_TABLE[swap_key]["fat_g"] * g / 100.0
            elif p["key"] in ("burro",):
                saving = p["fat_g"] - 5.0
            else:   # uova: metà tuorli
                saving = p["fat_g"] / 2
            text = f"Sostituisci {p['name']} con {swap_text}"
        elif is_protein and protect_protein:
            continue
        else:
            new_g = max(_round5(g / 2), 5)
            saving = p["fat_g"] * (1 - new_g / g)
            text = f"Riduci {p['name']} da {round(g)} a {new_g} g"
        if saving < 3:
            continue
        tips.append({"type": "fat", "text": f"{text} (−{round(saving)} g grassi)",
                     "saving_fat_g": round(saving), "ingredient": p["name"]})
        covered += saving
    return tips


def _carb_part(parts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    carbs = [p for p in parts if p["food_group"] in _SCALABLE_GROUPS and p["per100"]["kcal"] > 0]
    return max(carbs, key=lambda p: p["kcal"]) if carbs else None


_LEAN_PROTEINS = (("petto di pollo", "pollo"), ("bresaola", "bresaola"),
                  ("fiocchi di latte", None))


def _meal_protein_tip(parts: List[Dict[str, Any]], add_g: float, exclude=()) -> str:
    """Grammi in più della proteina principale del piatto; se servirebbe più che
    raddoppiarla (o se quell'ingrediente è già da sostituire), propone
    un'aggiunta magra a parte."""
    prot = [p for p in parts if p["food_group"] in _PROTEIN_GROUPS_BAL
            and p["per100"]["protein_g"] >= 5 and p["name"] not in exclude]
    main = max(prot, key=lambda p: p["protein_g"]) if prot else None
    if main:
        extra = _round5(add_g / (main["per100"]["protein_g"] / 100.0))
        if 5 <= extra <= main["grams"]:
            return (f"Aumenta {main['name']} a {round(main['grams'] + extra)} g "
                    f"(+{round(add_g)} g proteine)")
    name, key = _LEAN_PROTEINS[0]
    grams = _round5(add_g / (NUTRITION_TABLE[key]["protein_g"] / 100.0))
    alt = _round5(add_g / (NUTRITION_TABLE["bresaola"]["protein_g"] / 100.0))
    return (f"Mancano ~{round(add_g)} g di proteine: aggiungi ~{grams} g di {name} "
            f"o ~{alt} g di bresaola")


def meal_feedback(content, profile_id: str, scale: float = 1.0,
                  target: Optional[Dict[str, float]] = None, llm_gateway: Any = None,
                  add_cooking_fat_g: float = DEFAULT_COOKING_FAT_G) -> Optional[Dict[str, Any]]:
    """Confronta un pasto (pranzo/cena) con il suo obiettivo e propone
    interventi concreti: meno grassi (olio, ingrediente grasso → alternativa
    magra), grammi di carboidrati da togliere/aggiungere per centrare le kcal,
    proteina da aggiungere. `target` = {kcal, protein_g, carbs_g, fat_g} del
    singolo pasto (chiavi opzionali); senza target valuta solo l'equilibrio
    dei macro. Ritorna {nutrition, pct, target, tips, ok} o None."""
    parts = _meal_parts(content, profile_id, scale or 1.0, llm_gateway, add_cooking_fat_g)
    if not parts:
        return None
    n = {k: sum(p[k] for p in parts) for k in NUTRITION_KEYS}
    t = {k: v for k, v in (target or {}).items() if k in NUTRITION_KEYS and v and v > 0}
    tips: List[Dict[str, Any]] = []

    pk, ck, fk = n["protein_g"] * 4, n["carbs_g"] * 4, n["fat_g"] * 9
    tot = pk + ck + fk
    pct = {"protein": round(pk / tot * 100), "carbs": round(ck / tot * 100),
           "fat": round(fk / tot * 100)} if tot > 0 else None

    # 1. Grassi
    fat_goal = t.get("fat_g") or (n["kcal"] * MEAL_FAT_FALLBACK_PCT / 9 if n["kcal"] else 0)
    fat_limit = t["fat_g"] * (1 + MEAL_TOLERANCE) if "fat_g" in t else n["kcal"] * BALANCE_FAT_PCT / 9
    protein_low = "protein_g" in t and n["protein_g"] < t["protein_g"] * (1 - MEAL_TOLERANCE * 1.5)
    if fat_goal and n["fat_g"] > fat_limit and n["fat_g"] - fat_goal >= 3:
        protect = "protein_g" not in t or n["protein_g"] <= t["protein_g"] * (1 + MEAL_TOLERANCE)
        tips += _fat_tips(parts, n["fat_g"] - fat_goal, protect_protein=protect)

    # 2. Energia: si agisce sui carboidrati (la leva usata anche dallo scaling)
    carb = _carb_part(parts)
    if "kcal" in t:
        diff = n["kcal"] - t["kcal"]
        tol = max(t["kcal"] * MEAL_TOLERANCE, 60)
        # i grassi già suggeriti contano nella riduzione
        diff_after_fat = diff - 9 * sum(tp.get("saving_fat_g", 0) for tp in tips)
        if diff > tol and diff_after_fat > tol / 2 and carb:
            per_g = carb["per100"]["kcal"] / 100.0
            cut = min(_round5(diff_after_fat / per_g), _round5(carb["grams"] * 0.4))
            if cut >= 5:
                tips.append({"type": "kcal_high",
                             "text": f"Riduci {carb['name']} da {round(carb['grams'])} a "
                                     f"{round(carb['grams'] - cut)} g (−{round(cut * per_g)} kcal)"})
        elif diff > tol and not tips:
            tips.append({"type": "kcal_high",
                         "text": f"Pasto sopra l'obiettivo di ~{round(diff)} kcal: riduci la porzione"})
        elif diff < -tol:
            if carb:
                per_g = carb["per100"]["kcal"] / 100.0
                add = min(_round5(-diff / per_g), _round5(max(carb["grams"], 40) * 0.5))
                if add >= 5:
                    tips.append({"type": "kcal_low",
                                 "text": f"Puoi aumentare {carb['name']} a "
                                         f"{round(carb['grams'] + add)} g (+{round(add * per_g)} kcal)"})
            else:
                bread = min(_round5(-diff / 2.65), 80)
                tips.append({"type": "kcal_low",
                             "text": f"Mancano ~{round(-diff)} kcal: aggiungi una fonte di carboidrati "
                                     f"(es. {bread} g di pane, +{round(bread * 2.65)} kcal)"})
    elif pct and ck / tot > BALANCE_CARB_PCT and carb:
        per_g = carb["per100"]["kcal"] / 100.0
        cut = _round5((ck - 0.55 * tot) / per_g)   # porta i carbo verso il 55%
        cut = min(cut, _round5(carb["grams"] * 0.4))
        if cut >= 5:
            tips.append({"type": "carbs",
                         "text": f"Troppi carboidrati: riduci {carb['name']} di {cut} g "
                                 f"e aggiungi verdure"})

    # 3. Proteine: più della proteina già nel piatto, se la dose resta sensata
    if protein_low:
        add = t["protein_g"] - n["protein_g"]
        touched = {tp.get("ingredient") for tp in tips if tp.get("ingredient")}
        if fat_goal and n["fat_g"] >= 0.9 * fat_goal:
            # grassi già al limite: non aumentare una proteina grassa (salmone, speck...)
            touched |= {p["name"] for p in parts if p["per100"]["fat_g"] > 8}
        tips.append({"type": "protein", "text": _meal_protein_tip(parts, add, exclude=touched)})

    return {
        "nutrition": {k: round(n[k], 1) for k in NUTRITION_KEYS},
        "pct": pct,
        "target": {k: round(v) for k, v in t.items()} or None,
        "tips": tips,
        "ok": not tips,
    }


_MACRO_LABELS = {"kcal": "kcal", "fat_g": "Grassi", "carbs_g": "Carboidrati", "protein_g": "Proteine"}


def meal_breakdown(content, profile_id: str, scale: float = 1.0,
                   target: Optional[Dict[str, float]] = None, llm_gateway: Any = None,
                   add_cooking_fat_g: float = DEFAULT_COOKING_FAT_G) -> Optional[Dict[str, Any]]:
    """Contributo di ogni ingrediente a kcal e macro del pasto e, per i valori
    che sforano la quota (>10%), gli ingredienti che pesano di più.

    Ritorna {"ingredients": [{name, grams, kcal, protein_g, carbs_g, fat_g,
    estimated}], "over": [{macro, label, value, target, excess, culprits:
    [{name, value, share}]}]} o None se il pasto non è calcolabile."""
    parts = _meal_parts(content, profile_id, scale or 1.0, llm_gateway, add_cooking_fat_g)
    if not parts:
        return None
    ingredients = [{
        "name": p["name"], "grams": round(p["grams"]),
        **{k: round(p[k], 1) for k in NUTRITION_KEYS},
        "estimated": bool(p.get("estimated")),
    } for p in sorted(parts, key=lambda p: p["kcal"], reverse=True)]

    over = []
    for k in ("kcal", "fat_g", "carbs_g"):
        t = (target or {}).get(k)
        total = sum(p[k] for p in parts)
        # stesse soglie dei suggerimenti: ±10% e almeno 60 kcal / 3 g
        if not t or total <= 0 or total <= t * (1 + MEAL_TOLERANCE) \
                or total - t < (60 if k == "kcal" else 3):
            continue
        culprits, covered = [], 0.0
        for p in sorted(parts, key=lambda p: p[k], reverse=True):
            if len(culprits) >= 2 or covered >= 0.6 * total or p[k] <= 0:
                break
            culprits.append({"name": p["name"], "value": round(p[k], 1),
                             "share": round(p[k] / total * 100), "estimated": bool(p.get("estimated"))})
            covered += p[k]
        over.append({"macro": k, "label": _MACRO_LABELS[k], "value": round(total, 1),
                     "target": round(t), "excess": round(total - t, 1), "culprits": culprits})
    return {"ingredients": ingredients, "over": over}
