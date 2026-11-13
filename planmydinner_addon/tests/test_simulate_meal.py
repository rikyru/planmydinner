from planmydinner_addon.api.simulate import simulate_day

T = {"kcal": 2000, "protein_g": 130}


def _day(other=None, routine=600, target=1855):
    meals = {}
    if other:
        meals["pranzo"] = other
    return {"target_kcal": target, "routine_kcal": routine, "extra_kcal": 0, "meals": meals}


def test_chinese_dinner_leaves_less_for_planned_lunch():
    # budget 1855-600 = 1255; quota cena 627; cinese 900 -> pranzo ha 355 kcal
    lunch = {"consumed": False, "nutrition": {"kcal": 630}, "target": {"protein_g": 43}}
    r = simulate_day(_day(lunch), T, "cena", {"kcal": 900, "protein_g": 35, "carbs_g": 100, "fat_g": 35})
    assert r["quota_kcal"] == 628 and r["diff_quota"] == 272
    assert r["rebalance"] == {"meal_type": "pranzo", "planned_kcal": 630, "left_kcal": 355, "factor": 0.56}
    assert r["day_total"] == 2130 and r["verdict"]["level"] == "over"
    assert any("porzioni al ~56%" in l for l in r["verdict"]["lines"])


def test_lunch_already_eaten_gives_whole_remainder_as_quota():
    lunch = {"consumed": True, "nutrition": {"kcal": 500}}
    r = simulate_day(_day(lunch), T, "cena", {"kcal": 760, "protein_g": 40, "carbs_g": 80, "fat_g": 25})
    assert r["quota_kcal"] == 755 and r["rebalance"] is None
    assert r["verdict"]["level"] == "ok" and r["day_total"] == 1860


def test_too_heavy_meal_warns_other_cannot_compensate():
    lunch = {"consumed": False, "nutrition": {"kcal": 630}}
    r = simulate_day(_day(lunch), T, "cena", {"kcal": 1300, "protein_g": 40, "carbs_g": 150, "fat_g": 60})
    assert r["verdict"]["level"] == "way_over"
    assert any("difficile compensare" in l for l in r["verdict"]["lines"])


def test_no_target_only_reports_kcal():
    r = simulate_day({"meals": {}}, {}, "pranzo", {"kcal": 700, "protein_g": 30, "carbs_g": 80, "fat_g": 20})
    assert r["verdict"]["level"] == "unknown"


def test_unplanned_other_meal_assumed_at_its_quota():
    # pranzo non nel piano (mensa): si assume alla sua quota (1255/2), non a zero
    r = simulate_day(_day(None), T, "cena", {"kcal": 1500, "protein_g": 70, "carbs_g": 130, "fat_g": 70})
    assert r["day_total"] == 2728 and r["verdict"]["level"] == "way_over"
    assert any("alla sua quota" in l for l in r["verdict"]["lines"])
    assert any("quota della cena" in l for l in r["verdict"]["lines"])


def test_macros_flag_fat_over_and_low_protein():
    day = _day({"consumed": False, "nutrition": {"kcal": 630, "protein_g": 40, "carbs_g": 70, "fat_g": 18}})
    day["fixed_nutrition"] = {"kcal": 600, "protein_g": 30, "carbs_g": 80, "fat_g": 15}
    day["day_targets"] = {"protein_g": 130, "carbs_g": 200, "fat_g": 60}
    r = simulate_day(day, T, "cena", {"kcal": 900, "protein_g": 20, "carbs_g": 90, "fat_g": 45})
    m = {x["key"]: x for x in r["macros"]}
    assert m["fat_g"]["total"] == 78 and m["fat_g"]["status"] == "high"
    assert m["protein_g"]["total"] == 90 and m["protein_g"]["status"] == "low"
    assert m["carbs_g"]["status"] == "ok"
    assert any("Proteine basse" in l and "a pranzo" in l for l in r["verdict"]["lines"])


def test_choose_puts_meal_in_plan_without_consuming(client, setup_database):
    from planmydinner_addon.database import ConsumedEntry, GeneratedWeeklyPlan
    from planmydinner_addon.tests.conftest import TestingSessionLocal
    body = {"name": "Cinese leggero", "ingredients": [{"name": "Riso bianco", "food_group": "carboidrati", "grams": 120},
                                                      {"name": "Pollo", "food_group": "carne_bianca", "grams": 150}]}
    r = client.post("/simulate/choose?profile_id=persona_a&meal_type=cena&target_date=2026-02-24", json=body)
    assert r.status_code == 200, r.text
    r2 = client.post("/simulate/choose?profile_id=persona_a&meal_type=pranzo&target_date=2026-02-24",
                     json={**body, "name": "Kebab", "as_free_meal": True})
    assert r2.status_code == 200, r2.text
    db = TestingSessionLocal()
    try:
        assert db.query(ConsumedEntry).filter(ConsumedEntry.date == "2026-02-24").count() == 0
        plan = db.query(GeneratedWeeklyPlan).first()
        day = next(d for d in plan.daily_plans if d["date"] == "2026-02-24")
        slots = {m["meal_type"]: m["items"][0] for m in day["meals"]}
        assert slots["cena"]["food_group"] == "recipe" and slots["cena"]["item_name"] == "Cinese leggero"
        assert slots["pranzo"]["food_group"] == "free_meal" and slots["pranzo"]["recipe_id"]
    finally:
        db.close()
