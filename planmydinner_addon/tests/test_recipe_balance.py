"""Bilanciamento pasto: proteine sotto target + macro sbilanciati."""
from planmydinner_addon.nutrition import recipe_balance


def _ing(name, fg, grams):
    return {"name": name, "food_group": fg,
            "quantities": {"persona_a": {"qty": grams, "unit": "g", "grams_equiv": grams}}}


def test_low_protein_and_too_many_carbs():
    # solo pasta: pochi proteine, tanti carbo
    content = [_ing("Pasta", "carboidrati", 150)]
    b = recipe_balance(content, "persona_a", protein_target_g=40)
    types = {w["type"] for w in b["warnings"]}
    assert "low_protein" in types
    assert "too_many_carbs" in types
    assert b["ok"] is False
    low = next(w for w in b["warnings"] if w["type"] == "low_protein")
    assert "adapt" in low and low["adapt"]          # suggerimento di adattamento
    assert b["protein_to_add_g"] > 0


def test_balanced_meal_ok():
    content = [
        _ing("Pollo", "proteina", 150),       # ~34.5 g proteine
        _ing("Pasta", "carboidrati", 80),
    ]
    b = recipe_balance(content, "persona_a", protein_target_g=40)
    assert b["ok"] is True
    assert not b["warnings"]


def test_too_much_fat():
    content = [
        _ing("Pollo", "proteina", 100),
        _ing("Olio extravergine d'oliva", "condimenti", 40),  # grasso dominante
    ]
    b = recipe_balance(content, "persona_a", protein_target_g=20)
    assert any(w["type"] == "too_much_fat" for w in b["warnings"])


def test_no_protein_target_skips_protein_check():
    b = recipe_balance([_ing("Pasta", "carboidrati", 80)], "persona_a", protein_target_g=None)
    assert all(w["type"] != "low_protein" for w in b["warnings"])
