"""Feedback per pasto: macro vs obiettivo del pasto + suggerimenti concreti."""
import pytest
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


def test_low_protein_meal_never_cuts_its_protein():
    # polpette grasse ma proteine sotto target: niente "riduci polpette"
    # seguito da "aumenta polpette"
    content = [_ing("Polpette", "carne_rossa", 100), _ing("Pane", "carboidrati", 100),
               _ing("Mozzarella", "latticini", 0)]
    content[0]["nutrition"] = {"kcal": 250, "protein_g": 15, "carbs_g": 8, "fat_g": 18}
    fb = meal_feedback(content, "persona_a",
                       target={"kcal": 600, "protein_g": 38, "fat_g": 10})
    texts = [t["text"] for t in fb["tips"]]
    assert not any(t.startswith("Riduci Polpette") for t in texts), texts
    assert any(t["type"] == "protein" for t in fb["tips"])


def test_carb_is_cut_once_and_estimated_oil_not_flagged():
    # pizza grassa e sopra le kcal: un solo taglio (kcal), niente consiglio
    # sull'olio di cottura stimato
    content = [_ing("Pizza margherita", "carboidrati", 300)]
    content[0]["nutrition"] = {"kcal": 270, "protein_g": 11, "carbs_g": 33, "fat_g": 10}
    fb = meal_feedback(content, "persona_a", target={"kcal": 550, "fat_g": 9})
    pizza = [t for t in fb["tips"] if "Pizza" in t["text"]]
    assert len(pizza) == 1 and pizza[0]["type"] == "kcal_high"
    assert not any("olio" in t["text"] for t in fb["tips"])


def test_swapped_ingredient_is_not_also_increased():
    # speck grasso e proteine basse: "sostituisci speck" e NON "aumenta speck"
    content = [_ing("Speck", "carne_rossa", 60), _ing("Riso", "carboidrati", 80)]
    fb = meal_feedback(content, "persona_a",
                       target={"kcal": 700, "protein_g": 40, "fat_g": 8})
    texts = [t["text"] for t in fb["tips"]]
    assert any(t.startswith("Sostituisci Speck") for t in texts), texts
    assert not any(t.startswith("Aumenta Speck") for t in texts), texts


def test_breakdown_lists_ingredients_and_fat_culprits():
    from planmydinner_addon.nutrition import meal_breakdown
    content = [
        _ing("Speck", "carne_rossa", 80),
        _ing("Riso", "carboidrati", 80),
        _ing("Burro", "condimenti", 10),
        _ing("Zucchine", "verdure", 150),
    ]
    bd = meal_breakdown(content, "persona_a", target={"kcal": 900, "fat_g": 12})
    names = [i["name"] for i in bd["ingredients"]]
    assert set(names) == {"Speck", "Riso", "Burro", "Zucchine"}   # burro presente: niente olio stimato
    # la somma degli ingredienti è il totale del pasto
    fb = meal_feedback(content, "persona_a")
    assert sum(i["kcal"] for i in bd["ingredients"]) == pytest.approx(fb["nutrition"]["kcal"], abs=1)
    over = {o["macro"]: o for o in bd["over"]}
    assert "fat_g" in over and "kcal" not in over
    assert over["fat_g"]["culprits"][0]["name"] == "Speck"
    assert over["fat_g"]["excess"] > 0


def test_breakdown_includes_estimated_cooking_oil():
    from planmydinner_addon.nutrition import meal_breakdown
    bd = meal_breakdown([_ing("Pollo", "carne_bianca", 150)], "persona_a")
    oil = [i for i in bd["ingredients"] if i["estimated"]]
    assert len(oil) == 1 and oil[0]["grams"] == 8
    assert bd["over"] == []   # senza quota nessuno "sfora"


def test_fat_at_limit_protein_tip_avoids_fatty_protein():
    # salmone: proteine sotto quota ma grassi al limite → niente "aumenta salmone"
    content = [_ing("Salmone", "pesce", 150), _ing("Pasta", "carboidrati", 80),
               _ing("Olio extravergine d'oliva", "condimenti", 10)]
    fb = meal_feedback(content, "persona_a",
                       target={"kcal": 800, "protein_g": 51, "fat_g": 26})
    texts = [t["text"] for t in fb["tips"]]
    assert not any(t.startswith("Aumenta Salmone") for t in texts), texts
    assert any("petto di pollo" in t for t in texts), texts
