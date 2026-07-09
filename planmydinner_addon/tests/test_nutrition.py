import pytest

from planmydinner_addon.nutrition import (
    NUTRITION_TABLE,
    compute_recipe_nutrition,
    lookup_nutrition_table,
    resolve_ingredient_nutrition,
)


def _qty(grams, profile="persona_a", unit="g"):
    return {profile: {"qty": grams, "unit": unit, "grams_equiv": grams}}


class TestLookupNutritionTable:
    def test_exact_match(self):
        v = lookup_nutrition_table("pasta")
        assert v == NUTRITION_TABLE["pasta"]

    def test_keyword_match_inside_name(self):
        v = lookup_nutrition_table("Pasta di semola integrale")
        assert v == NUTRITION_TABLE["pasta"]

    def test_longest_key_wins(self):
        # "yogurt greco magro" deve matchare "yogurt greco", non "yogurt"
        v = lookup_nutrition_table("yogurt greco magro")
        assert v == NUTRITION_TABLE["yogurt greco"]

    def test_word_boundary_no_false_positive(self):
        # "riso" non deve matchare dentro un'altra parola
        assert lookup_nutrition_table("frisone stagionato") is None

    def test_unknown_returns_none(self):
        assert lookup_nutrition_table("ingrediente inventato xyz") is None
        assert lookup_nutrition_table("") is None


class TestSeedCoverage:
    def test_all_seed_ingredients_resolve_from_table(self):
        """Ogni ingrediente delle ricette seed deve risolversi dalla tabella locale
        (niente LLM necessario per il catalogo seed)."""
        import re as _re
        from pathlib import Path
        seed_src = (Path(__file__).parent.parent / "api" / "seed.py").read_text(encoding="utf-8")
        names = set(_re.findall(r'"name": "([^"]+)", "food_group"', seed_src))
        assert names, "nessun ingrediente estratto da seed.py: pattern cambiato?"
        missing = sorted(n for n in names if lookup_nutrition_table(n) is None)
        assert not missing, f"Ingredienti seed senza valori in tabella: {missing}"


class TestResolveIngredientNutrition:
    def test_table_source(self):
        ing = {"name": "petto di pollo", "food_group": "carne_bianca", "quantities": _qty(150)}
        n = resolve_ingredient_nutrition(ing)
        assert n["source"] == "table"
        assert n["kcal"] == NUTRITION_TABLE["pollo"]["kcal"]

    def test_stored_manual_wins_over_table(self):
        ing = {
            "name": "pollo",
            "food_group": "carne_bianca",
            "quantities": _qty(150),
            "nutrition": {"kcal": 120, "protein_g": 22, "carbs_g": 0, "fat_g": 3, "source": "manual"},
        }
        n = resolve_ingredient_nutrition(ing)
        assert n["source"] == "manual"
        assert n["kcal"] == 120

    def test_llm_fallback_for_unknown(self):
        class FakeGateway:
            def estimate_nutrition(self, name):
                return {"kcal": 200, "protein_g": 10, "carbs_g": 20, "fat_g": 8}

        ing = {"name": "ingrediente inventato xyz", "food_group": "altro", "quantities": _qty(100)}
        n = resolve_ingredient_nutrition(ing, llm_gateway=FakeGateway())
        assert n["source"] == "llm"
        assert n["kcal"] == 200

    def test_llm_failure_returns_none(self):
        class BrokenGateway:
            def estimate_nutrition(self, name):
                raise RuntimeError("boom")

        ing = {"name": "ingrediente inventato xyz", "food_group": "altro", "quantities": _qty(100)}
        assert resolve_ingredient_nutrition(ing, llm_gateway=BrokenGateway()) is None

    def test_invalid_stored_nutrition_falls_back_to_table(self):
        ing = {
            "name": "pollo",
            "food_group": "carne_bianca",
            "quantities": _qty(150),
            "nutrition": {"kcal": None, "protein_g": "n/a"},
        }
        n = resolve_ingredient_nutrition(ing)
        assert n["source"] == "table"


class TestComputeRecipeNutrition:
    def test_grams_to_macros(self):
        # pasta 80 g + tonno 70 g + pomodorini 100 g (valori tabella)
        content = [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "tonno", "food_group": "pesce", "quantities": _qty(70)},
            {"name": "pomodorini", "food_group": "verdure", "quantities": _qty(100)},
        ]
        n = compute_recipe_nutrition(content, "persona_a")
        expected_kcal = 353 * 0.8 + 159 * 0.7 + 18 * 1.0     # 411.7
        expected_protein = 11.0 * 0.8 + 21.5 * 0.7 + 1.0     # 24.85
        assert n["kcal"] == pytest.approx(expected_kcal, abs=0.11)
        assert n["protein_g"] == pytest.approx(expected_protein, abs=0.11)
        assert n["coverage"] == 1.0
        assert n["sources"] == {"table": 3}

    def test_profile_fallback_to_persona_a(self):
        # Ricetta seed con chiavi persona_a/persona_b, profilo reale 'aa'
        content = [{"name": "riso", "food_group": "carboidrati", "quantities": _qty(100)}]
        n = compute_recipe_nutrition(content, "aa")
        assert n["kcal"] == pytest.approx(358, abs=0.11)

    def test_qty_used_when_grams_equiv_missing(self):
        content = [{
            "name": "pasta", "food_group": "carboidrati",
            "quantities": {"persona_a": {"qty": 100, "unit": "g"}},
        }]
        n = compute_recipe_nutrition(content, "persona_a")
        assert n["kcal"] == pytest.approx(353, abs=0.11)

    def test_partial_coverage(self):
        content = [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(100)},
            {"name": "ingrediente inventato xyz", "food_group": "altro", "quantities": _qty(50)},
        ]
        n = compute_recipe_nutrition(content, "persona_a")
        assert n["coverage"] == 0.5
        assert n["kcal"] == pytest.approx(353, abs=0.11)  # solo la pasta

    def test_zero_grams_ignored(self):
        # Verdure "a piacere" (qty 0) non contano né nei totali né nella coverage
        content = [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(100)},
            {"name": "insalata", "food_group": "verdure", "quantities": _qty(0)},
        ]
        n = compute_recipe_nutrition(content, "persona_a")
        assert n["coverage"] == 1.0
        assert n["kcal"] == pytest.approx(353, abs=0.11)

    def test_composed_dish_content(self):
        content = {
            "dish_name": "Pasta al tonno",
            "components": [
                {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(80)},
                {"name": "tonno", "food_group": "pesce", "quantities": _qty(70)},
            ],
        }
        n = compute_recipe_nutrition(content, "persona_a")
        assert n["kcal"] == pytest.approx(353 * 0.8 + 159 * 0.7, abs=0.11)

    def test_no_resolvable_ingredients_returns_none(self):
        content = [{"name": "ingrediente inventato xyz", "food_group": "altro", "quantities": _qty(100)}]
        assert compute_recipe_nutrition(content, "persona_a") is None
        assert compute_recipe_nutrition([], "persona_a") is None
        assert compute_recipe_nutrition(None, "persona_a") is None
