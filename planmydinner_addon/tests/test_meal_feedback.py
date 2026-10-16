"""Feedback per pasto: macro vs obiettivo del pasto + suggerimenti concreti."""
from planmydinner_addon.nutrition import meal_feedback


def _ing(name, fg, grams):
    return {"name": name, "food_group": fg,
            "quantities": {"persona_a": {"qty": grams, "unit": "g", "grams_equiv": grams}}}


def _types(fb):
    return [t["type"] for t in fb["tips"]]


def test_on_target_meal_is_ok():
    content = [
        _ing("Pollo", "carne_bianca", 150),
        _ing("Pasta", "carboidrati", 80),
        _ing("Zucchine", "verdure", 200),
        _ing("Olio extravergine d'oliva", "condimenti", 10),
    ]
    fb = meal_feedback(content, "persona_a",
                       target={"kcal": 620, "protein_g": 45, "fat_g": 15})
    assert fb["ok"] is True, fb["tips"]
    assert fb["nutrition"]["kcal"] > 0


def test_fatty_meal_suggests_less_oil_and_lean_swap():
    content = [
        _ing("Salmone", "pesce", 200),
        _ing("Riso", "carboidrati", 70),
        _ing("Olio extravergine d'oliva", "condimenti", 20),
    ]
    fb = meal_feedback(content, "persona_a", target={"kcal": 650, "fat_g": 15})
    assert "fat" in _types(fb)
    texts = " ".join(t["text"] for t in fb["tips"])
    assert "5 g d'olio" in texts
    assert "Salmone" in texts and "merluzzo" in texts


def test_estimated_cooking_oil_is_considered():
    # niente olio in ricetta → olio di cottura stimato (8 g) entra nel conto
    content = [_ing("Pollo", "carne_bianca", 150), _ing("Riso", "carboidrati", 80)]
    with_oil = meal_feedback(content, "persona_a")
    without = meal_feedback(content, "persona_a", add_cooking_fat_g=0)
    assert with_oil["nutrition"]["fat_g"] > without["nutrition"]["fat_g"]


def test_too_many_kcal_cuts_carbs():
    content = [_ing("Pollo", "carne_bianca", 150), _ing("Pasta", "carboidrati", 150)]
    fb = meal_feedback(content, "persona_a", target={"kcal": 550})
    tip = next(t for t in fb["tips"] if t["type"] == "kcal_high")
    assert "Pasta" in tip["text"] and "kcal" in tip["text"]


def test_too_few_kcal_adds_carbs():
    content = [_ing("Pollo", "carne_bianca", 150), _ing("Riso", "carboidrati", 50)]
    fb = meal_feedback(content, "persona_a", target={"kcal": 800})
    assert "kcal_low" in _types(fb)


def test_low_protein_scales_main_protein_or_suggests_lean_add():
    small = [_ing("Pollo", "carne_bianca", 100), _ing("Pasta", "carboidrati", 80)]
    fb = meal_feedback(small, "persona_a", target={"protein_g": 40})
    tip = next(t for t in fb["tips"] if t["type"] == "protein")
    assert tip["text"].startswith("Aumenta Pollo")

    no_protein = [_ing("Pasta", "carboidrati", 100), _ing("Zucchine", "verdure", 200)]
    fb = meal_feedback(no_protein, "persona_a", target={"protein_g": 40})
    tip = next(t for t in fb["tips"] if t["type"] == "protein")
    assert "petto di pollo" in tip["text"]


def test_no_target_flags_unbalanced_carbs():
    content = [_ing("Pasta", "carboidrati", 150), _ing("Pomodoro", "verdure", 100)]
    fb = meal_feedback(content, "persona_a")
    assert "carbs" in _types(fb)


def test_unresolvable_meal_returns_none():
    assert meal_feedback([], "persona_a") is None
