"""Copertura della tabella nutrizionale: ingredienti prima mancanti e matching
tollerante alla scrittura (es. "Cous Cous" -> couscous)."""
import pytest

from planmydinner_addon.nutrition import (
    DEFAULT_COOKING_FAT_G,
    compute_recipe_nutrition,
    lookup_nutrition_table,
)

_NO_FAT_MEAL = [
    {"name": "Riso", "food_group": "carboidrati",
     "quantities": {"persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80.0}}},
    {"name": "Pollo", "food_group": "proteina",
     "quantities": {"persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150.0}}},
]


@pytest.mark.parametrize("name", [
    "Piadina", "Fregola sarda", "Speck", "Formaggio spalmabile",
    "Bietole", "Mela", "Curry",
    # extra da aggiungere quando si segna un pasto
    "Maionese", "Ketchup", "Coca Cola", "Birra", "Vino rosso", "Succo d'arancia",
])
def test_new_ingredients_are_known(name):
    n = lookup_nutrition_table(name)
    assert n is not None, f"{name} non trovato in tabella"
    assert n["kcal"] > 0


def test_mayo_and_cola_counted_in_a_logged_meal():
    # "2 cucchiai di maionese" ~30 g + "una lattina di coca" ~330 ml
    content = [
        {"name": "Maionese", "food_group": "condimenti",
         "quantities": {"persona_a": {"qty": 30, "unit": "g", "grams_equiv": 30.0}}},
        {"name": "Coca Cola", "food_group": "altro",
         "quantities": {"persona_a": {"qty": 330, "unit": "ml", "grams_equiv": 330.0}}},
    ]
    n = compute_recipe_nutrition(content, "persona_a")
    assert n["coverage"] == 1.0
    # maionese 30g (~204 kcal) + coca 330ml (~139 kcal)
    assert n["kcal"] == pytest.approx(204 + 139, abs=6)


def test_couscous_matches_despite_spacing():
    spaced = lookup_nutrition_table("Cous Cous")
    assert spaced is not None and spaced["kcal"] > 0


def test_zero_kcal_condiments_known_but_zero():
    # sale/pepe/spezie risolti (niente stima LLM) ma a 0 kcal
    for name in ("Sale", "Pepe", "Spezie"):
        n = lookup_nutrition_table(name)
        assert n is not None and n["kcal"] == 0


def test_couscous_meal_no_longer_zero():
    """Un piatto di cous cous prima valeva ~0 kcal per il carb non trovato."""
    content = [
        {"name": "Cous Cous", "food_group": "carboidrati",
         "quantities": {"persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80.0}}},
        {"name": "Tonno", "food_group": "proteina",
         "quantities": {"persona_a": {"qty": 120, "unit": "g", "grams_equiv": 120.0}}},
        {"name": "Zucchine", "food_group": "verdura",
         "quantities": {"persona_a": {"qty": 200, "unit": "g", "grams_equiv": 200.0}}},
    ]
    n = compute_recipe_nutrition(content, "persona_a")
    assert n is not None
    assert n["coverage"] == 1.0
    # couscous 80g (~301 kcal) + tonno 120g (~191) + zucchine 200g (~28)
    assert n["kcal"] == pytest.approx(301 + 191 + 28, abs=5)


def test_cooking_fat_default_is_no_op():
    n = compute_recipe_nutrition(_NO_FAT_MEAL, "persona_a")
    assert n["cooking_fat_added"] is False


def test_cooking_fat_added_to_meal_without_fat():
    base = compute_recipe_nutrition(_NO_FAT_MEAL, "persona_a")
    withfat = compute_recipe_nutrition(_NO_FAT_MEAL, "persona_a",
                                       add_cooking_fat_g=DEFAULT_COOKING_FAT_G)
    assert withfat["cooking_fat_added"] is True
    # 8 g di olio = ~72 kcal e ~8 g di grassi in più
    assert withfat["kcal"] == pytest.approx(base["kcal"] + 8 * 8.999, abs=1)
    assert withfat["fat_g"] == pytest.approx(base["fat_g"] + 8 * 0.999, abs=0.5)


def test_cooking_fat_not_added_when_oil_present():
    meal = _NO_FAT_MEAL + [
        {"name": "Olio extravergine d'oliva", "food_group": "condimenti",
         "quantities": {"persona_a": {"qty": 10, "unit": "g", "grams_equiv": 10.0}}},
    ]
    n = compute_recipe_nutrition(meal, "persona_a", add_cooking_fat_g=DEFAULT_COOKING_FAT_G)
    assert n["cooking_fat_added"] is False
