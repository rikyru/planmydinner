"""Copertura della tabella nutrizionale: ingredienti prima mancanti e matching
tollerante alla scrittura (es. "Cous Cous" -> couscous)."""
import pytest

from planmydinner_addon.nutrition import (
    compute_recipe_nutrition,
    lookup_nutrition_table,
)


@pytest.mark.parametrize("name", [
    "Piadina", "Fregola sarda", "Speck", "Formaggio spalmabile",
    "Bietole", "Mela", "Curry",
])
def test_new_ingredients_are_known(name):
    n = lookup_nutrition_table(name)
    assert n is not None, f"{name} non trovato in tabella"
    assert n["kcal"] > 0


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
