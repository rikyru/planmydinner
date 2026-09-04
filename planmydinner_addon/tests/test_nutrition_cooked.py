"""
Correzione crudo → cotto nella tabella nutrizionale.

Legumi e cereali in NUTRITION_TABLE sono a peso secco/crudo: un ingrediente
scritto come "lenticchie cotte 220 g" veniva contato al valore del secco
(~2,6x le calorie reali) e gonfiava i totali del giorno.
"""
import pytest

from planmydinner_addon.nutrition import (
    NUTRITION_TABLE,
    compute_recipe_nutrition,
    is_cooked_weight,
    lookup_nutrition_table,
)


def _qty(g):
    return {"qty": float(g), "unit": "g", "grams_equiv": float(g)}


class TestCookedDetection:
    @pytest.mark.parametrize("name", [
        "Lenticchie cotte", "ceci cotti", "Riso lessato", "fagioli bolliti",
        "Ceci in scatola", "fagioli scolati", "pasta cotta", "orzo precotto",
    ])
    def test_cooked_names_are_detected(self, name):
        assert is_cooked_weight(name) is True

    @pytest.mark.parametrize("name", [
        "lenticchie", "ceci", "Pasta", "pasta di semola", "riso", "pane",
    ])
    def test_raw_names_are_not_touched(self, name):
        assert is_cooked_weight(name) is False
        assert lookup_nutrition_table(name) == pytest.approx(
            NUTRITION_TABLE[lookup_key(name)], rel=1e-6
        )

    @pytest.mark.parametrize("name", ["Prosciutto cotto", "prosciutto cotto a fette"])
    def test_already_cooked_table_entries_are_unchanged(self, name):
        """'prosciutto cotto' è già il prodotto finito: non va diviso per nulla."""
        assert is_cooked_weight(name) is False
        assert lookup_nutrition_table(name)["kcal"] == NUTRITION_TABLE["prosciutto cotto"]["kcal"]


def lookup_key(name):
    """Chiave di tabella attesa per i nomi 'crudi' usati nei test."""
    return {
        "lenticchie": "lenticchie", "ceci": "ceci", "Pasta": "pasta",
        "pasta di semola": "pasta", "riso": "riso", "pane": "pane",
    }[name]


class TestCookedValues:
    def test_cooked_lentils_are_much_lighter_than_dry(self):
        dry = lookup_nutrition_table("lenticchie")
        cooked = lookup_nutrition_table("lenticchie cotte")
        assert dry["kcal"] == 325
        # 325 / 2.6 = 125
        assert cooked["kcal"] == pytest.approx(125, abs=1)
        # i macro scalano con lo stesso fattore (è solo acqua assorbita)
        assert cooked["protein_g"] == pytest.approx(dry["protein_g"] / 2.6, abs=0.1)
        assert cooked["carbs_g"] == pytest.approx(dry["carbs_g"] / 2.6, abs=0.1)

    def test_source_marks_the_conversion(self):
        from planmydinner_addon.nutrition import resolve_ingredient_nutrition
        assert resolve_ingredient_nutrition({"name": "Ceci cotti"})["source"] == "table_cooked"
        assert resolve_ingredient_nutrition({"name": "ceci"})["source"] == "table"

    def test_recipe_with_cooked_legumes_loses_the_dry_weight_inflation(self):
        """Scenario reale (polpette di lenticchie del catalogo): l'unica differenza
        e' il nome dell'ingrediente, ma pesare 220 g di lenticchie COTTE al valore
        del secco aggiungeva ~440 kcal fantasma alla porzione."""
        def _plate(lentil_name):
            return [
                {"name": lentil_name, "food_group": "legumi", "quantities": {"aa": _qty(220)}},
                {"name": "Melanzane", "food_group": "verdure", "quantities": {"aa": _qty(250)}},
                {"name": "Pane (mollica)", "food_group": "carboidrati", "quantities": {"aa": _qty(40)}},
                {"name": "Parmigiano", "food_group": "latticini", "quantities": {"aa": _qty(20)}},
                {"name": "Olio extravergine d'oliva", "food_group": "condimenti", "quantities": {"aa": _qty(10)}},
            ]

        cooked = compute_recipe_nutrition(_plate("Lenticchie cotte"), "aa")
        as_dry = compute_recipe_nutrition(_plate("Lenticchie"), "aa")
        assert cooked["coverage"] == 1.0

        # 220 g: 715 kcal contate a secco contro 275 da cotte
        assert as_dry["kcal"] - cooked["kcal"] == pytest.approx(440, abs=5)
        assert cooked["kcal"] == pytest.approx(599, abs=5)
        assert as_dry["kcal"] == pytest.approx(1039, abs=5)  # il valore gonfiato di prima

    def test_explicit_nutrition_still_wins(self):
        """Valori salvati sull'ingrediente battono comunque la tabella."""
        content = [{
            "name": "Lenticchie cotte", "food_group": "legumi",
            "quantities": {"aa": _qty(100)},
            "nutrition": {"kcal": 200, "protein_g": 10, "carbs_g": 30, "fat_g": 1, "source": "manual"},
        }]
        n = compute_recipe_nutrition(content, "aa")
        assert n["kcal"] == pytest.approx(200, abs=0.1)


class TestRecipeListNutrition:
    def test_recipe_list_includes_per_portion_nutrition(self, client, setup_database):
        """La lista Ricette deve poter mostrare le kcal senza aprire il dettaglio."""
        resp = client.post("/recipes/", json={
            "name": "Test kcal in lista",
            "content": [
                {"name": "Pasta", "food_group": "carboidrati",
                 "quantities": {"persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80}}},
                {"name": "Ceci cotti", "food_group": "legumi",
                 "quantities": {"persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150}}},
            ],
            "steps": [], "total_time_minutes": 20, "difficulty": "facile", "tags": {},
        })
        assert resp.status_code == 200

        recipes = client.get("/recipes/").json()
        created = next(r for r in recipes if r["name"] == "Test kcal in lista")
        per = created["nutrition_per_portion"]
        assert per, "la lista deve includere nutrition_per_portion"
        n = per["persona_a"]
        # pasta 80 g a crudo (353/100g) + ceci COTTI 150 g (~132/100g)
        assert n["kcal"] == pytest.approx(353 * 0.8 + 131.7 * 1.5, abs=2)
        assert n["sources"].get("table_cooked") == 1
