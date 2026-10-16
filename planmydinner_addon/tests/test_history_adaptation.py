"""Piano "dal mio storico" adattato: frequenze della nutrizionista e porzioni
giorno per giorno sulla quota (ricette base intatte)."""
import uuid
from datetime import date, timedelta

import pytest

from planmydinner_addon import schemas
from planmydinner_addon.database import ConsumedEntry, GeneratedWeeklyPlan, PlanRules, Recipe
from planmydinner_addon.nutrition import apply_portions, compute_recipe_nutrition, plan_portions
from planmydinner_addon.planner import PlannerEngine

TODAY = date(2026, 2, 24)  # freeze_time in conftest (martedì)


def _ing(name, fg, grams):
    return {"name": name, "food_group": fg,
            "quantities": {"persona_a": {"qty": grams, "unit": "g", "grams_equiv": grams}}}


def _recipe(db, rid, name, content):
    db.add(Recipe(id=rid, name=name, is_composed_dish=False, content=content, steps=[],
                  total_time_minutes=20, difficulty="facile", tags={}))


def _eaten(db, rid, days_ago):
    for n in days_ago:
        db.add(ConsumedEntry(id=str(uuid.uuid4()), profile_id="persona_a",
                             date=(TODAY - timedelta(days=n)).isoformat(),
                             meal_type="cena", type="planned", consumed_recipe_id=rid))


def _rules(db, **kw):
    rules = db.query(PlanRules).filter(PlanRules.profile_id == "persona_a").first()
    if rules is None:
        rules = PlanRules(id="rules-adapt", profile_id="persona_a", imported_at=TODAY.isoformat(),
                          frequency_targets={})
        db.add(rules)
    for k, v in kw.items():
        setattr(rules, k, v)
    db.commit()
    return rules


# ── plan_portions ──────────────────────────────────────────────────────────

def test_protein_goes_to_nutritionist_portion():
    content = [_ing("Uova", "uova", 60), _ing("Pane", "carboidrati", 60)]
    res = plan_portions(content, "persona_a",
                        portion_for=lambda kind, p: ("uova di gallina - intero", 120) if kind == "protein" else None)
    assert res["portions"]["uova"] == pytest.approx(2.0)
    assert any("Uova 60 → 120 g" in n for n in res["notes"])


def test_cooked_portion_converted_to_dry_by_protein_equivalence():
    # nutrizionista: ceci BOLLITI 120 g; la ricetta pesa ceci SECCHI → ~50 g, non 120
    content = [_ing("Ceci", "legumi", 80)]
    res = plan_portions(content, "persona_a",
                        portion_for=lambda kind, p: ("ceci secchi - bolliti", 120) if kind == "protein" else None)
    grams = 80 * res["portions"]["ceci"]
    assert 40 <= grams <= 60


def test_carbs_fit_kcal_quota_within_range():
    content = [_ing("Pollo", "carne_bianca", 150), _ing("Pasta", "carboidrati", 100)]
    nutri = lambda kind, p: ("pasta di semola", 70) if kind == "carb" else None
    low = plan_portions(content, "persona_a", quota={"kcal": 450}, portion_for=nutri)
    high = plan_portions(content, "persona_a", quota={"kcal": 560}, portion_for=nutri)
    g_low = 100 * low["portions"].get("pasta", 1.0)
    g_high = 100 * high["portions"].get("pasta", 1.0)
    assert g_low < g_high
    assert 0.75 * 70 - 1 <= g_low and g_high <= 1.25 * 70 + 1   # vicino alla grammatura della nutrizionista
    assert abs(high["nutrition"]["kcal"] - 560) < abs(
        compute_recipe_nutrition(content, "persona_a", add_cooking_fat_g=8)["kcal"] - 560)


def test_explicit_oil_reduced_when_fat_over_quota():
    content = [_ing("Pollo", "carne_bianca", 150), _ing("Olio extravergine d'oliva", "condimenti", 25)]
    res = plan_portions(content, "persona_a", quota={"fat_g": 10})
    assert 25 * res["portions"]["olio extravergine d'oliva"] == pytest.approx(5, abs=0.5)


def test_apply_portions_leaves_base_untouched():
    content = [_ing("Pasta", "carboidrati", 100)]
    out = apply_portions(content, {"pasta": 0.8})
    assert out[0]["quantities"]["persona_a"]["grams_equiv"] == 80
    assert content[0]["quantities"]["persona_a"]["grams_equiv"] == 100


# ── selezione con frequenze ────────────────────────────────────────────────

def test_history_respects_weekly_max_per_category(setup_database):
    db = setup_database
    # due ricette di carne rossa mangiatissime, una di legumi meno
    _recipe(db, "manzo1", "Manzo e riso", [_ing("Manzo", "carne_rossa", 150), _ing("Riso", "carboidrati", 80)])
    _recipe(db, "manzo2", "Hamburger", [_ing("Manzo", "carne_rossa", 150), _ing("Pane", "carboidrati", 80)])
    _recipe(db, "ceci1", "Ceci e pasta", [_ing("Ceci", "legumi", 80), _ing("Pasta", "carboidrati", 70)])
    _recipe(db, "pollo1", "Pollo e patate", [_ing("Pollo", "carne_bianca", 150), _ing("Patate", "carboidrati", 200)])
    _eaten(db, "manzo1", [1, 2, 3, 4, 5])
    _eaten(db, "manzo2", [6, 7, 8, 9])
    _eaten(db, "ceci1", [10])
    _eaten(db, "pollo1", [11])
    db.commit()
    _rules(db, frequency_targets={"carne_rossa": {"min": 0, "max": 1}, "legumi": {"min": 2, "max": 4}},
           generation_slots={"pranzo": [], "cena": [0, 1, 2, 3, 4, 5, 6]})
    plan = PlannerEngine(db).generate_from_history("persona_a", "persona_b", TODAY)
    picked = [m.items[0].recipe_id for d in plan for m in d.meals]
    rossa = [r for r in picked if r in ("manzo1", "manzo2")]
    assert len(rossa) <= 1, picked
    assert picked.count("ceci1") >= 2, picked     # il minimo legumi viene recuperato


# ── end-to-end: generate-week dal mio storico ──────────────────────────────

def test_generate_from_history_adapts_portions_and_summary_matches(client, setup_database):
    db = setup_database
    _recipe(db, "pp", "Pollo e pasta", [_ing("Pollo", "carne_bianca", 100), _ing("Pasta", "carboidrati", 100)])
    _eaten(db, "pp", [1, 2, 3])
    db.commit()
    _rules(db, nutrition_targets={"kcal": 1400},
           protein_target={"pranzo": 150, "cena": 150},
           carb_options={"cena": [{"name": "pasta di semola", "quantity": 70, "unit": "g"}]},
           generation_slots={"pranzo": [], "cena": [0, 1, 2, 3, 4, 5, 6]})
    resp = client.post("/planner/generate-week", params={
        "profile_id_A": "persona_a", "profile_id_B": "persona_b",
        "current_date": TODAY.isoformat(), "from_history": True})
    assert resp.status_code == 200, resp.text
    cena = next(m for m in resp.json()[0]["meals"] if m["meal_type"] == "cena")
    item = cena["items"][0]
    assert item["recipe_id"] == "pp"
    assert item["portions"]["pollo"] == pytest.approx(1.5)          # 100 → 150 g (nutrizionista)
    assert 49 <= 100 * item["portions"].get("pasta", 1.0) <= 100             # attorno ai 70 g, regolata sulla quota
    assert item["adapt_note"][0].startswith("quota")
    # la ricetta base non cambia
    db.expire_all()
    assert db.query(Recipe).get("pp").content[0]["quantities"]["persona_a"]["grams_equiv"] == 100

    day = client.get("/integration/summary", params={
        "profile_id": "persona_a", "start_date": TODAY.isoformat(),
        "end_date": TODAY.isoformat(), "meal_detail": True}).json()["days"][0]
    meal = day["meals"]["cena"]
    pollo = next(i for i in meal["ingredients"] if i["name"] == "Pollo")
    assert pollo["grams"] == 150
    assert meal["nutrition"]["kcal"] == pytest.approx(sum(i["kcal"] for i in meal["ingredients"]), abs=1)


def test_history_works_with_rules_without_frequencies(setup_database):
    db = setup_database
    _recipe(db, "pp2", "Pollo e riso", [_ing("Pollo", "carne_bianca", 150), _ing("Riso", "carboidrati", 80)])
    _eaten(db, "pp2", [1, 2])
    db.commit()
    _rules(db, frequency_targets=None, nutrition_targets={"kcal": 1800})
    plan = PlannerEngine(db).generate_from_history("persona_a", "persona_b", TODAY)
    assert any(m.items for d in plan for m in d.meals)


def test_puff_pastry_is_not_semolina_pasta():
    from planmydinner_addon.adaptation import _same_food
    assert not _same_food("Pasta sfoglia", "pasta di semola")
    assert _same_food("Pasta", "pasta di semola")
    assert _same_food("Tonno", "tonno sott'olio - sgocciolato")


def test_quota_raise_is_moderate_and_skips_fatty_proteins():
    lean = plan_portions([_ing("Gamberetti", "pesce", 60)], "persona_a", quota={"protein_g": 60})
    assert 60 * lean["portions"]["gamberetti"] <= 90 + 0.5        # max 1,5× senza grammatura del piano
    fatty = plan_portions([_ing("Ricotta", "latticini", 80)], "persona_a", quota={"protein_g": 60})
    assert "ricotta" not in fatty["portions"]                      # formaggio: non si aumenta a quota
