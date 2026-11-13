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
