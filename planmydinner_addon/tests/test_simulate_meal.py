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


# ---- "stasera pizza: cosa prendo in mensa?" ----

from planmydinner_addon.api.simulate import _tray_category, rank_mensa, simulate_day as _sd


def _tray(count, *ings):
    return {"ingredients": [{"name": n, "grams": g} for n, g in ings], "count": count, "last": "2026-11-18"}


def _kcal_table(ings):
    per_g = {"pane": 2.6, "petto di pollo": 1.1, "fagiolini": 0.3, "mela": 0.5, "pizza margherita": 2.7,
             "salmone": 2.0, "spinaci": 0.3, "frittata": 1.8, "banana": 0.9}
    k = sum(per_g.get(i["name"], 1.0) * i["grams"] for i in ings)
    p = sum(i["grams"] * (0.23 if i["name"] in ("petto di pollo", "salmone") else 0.1 if i["name"] == "frittata" else 0.02)
            for i in ings)
    return {"kcal": k, "protein_g": p, "carbs_g": 0, "fat_g": 0}


def test_tray_category_is_the_main_protein():
    assert _tray_category([{"name": "pane", "grams": 80}, {"name": "petto di pollo", "grams": 150}]) == "carne_bianca"
    assert _tray_category([{"name": "Filetto_di_pesce", "grams": 150}, {"name": "uva", "grams": 80}]) == "pesce"
    assert _tray_category([{"name": "pizza margherita", "grams": 150}, {"name": "bresaola", "grams": 100}]) == "primo"


def test_rank_mensa_one_per_kind_fits_room_and_drops_bread_if_needed():
    trays = [_tray(5, ("petto di pollo", 150), ("fagiolini", 100), ("pane", 80), ("mela", 150)),
             _tray(1, ("salmone", 150), ("spinaci", 100), ("pane", 50)),
             _tray(2, ("frittata", 150), ("pane", 100), ("banana", 120)),
             _tray(1, ("pizza margherita", 150), ("spinaci", 100))]
    out = rank_mensa(trays, _kcal_table, room=400, protein_quota=35, avoid_cats={"primo"})
    cats = [o["category"] for o in out]
    assert len(cats) == len(set(cats)) == 4          # un'alternativa per tipo di secondo
    assert cats[0] == "carne_bianca"                 # pollo: in quota, proteico, abituale
    chicken = out[0]
    assert chicken["dropped"] == ["pane"] and chicken["fits"]   # 478 kcal col pane, quota 400 -> senza
    assert cats[-1] == "primo"                       # stasera pizza: pizza anche a pranzo in fondo


def test_decided_other_meal_sets_quota_and_no_rebalance():
    day = {"target_kcal": 1855, "routine_kcal": 600, "extra_kcal": 0,
           "meals": {"cena": {"consumed": False, "decided": True, "nutrition": {"kcal": 900}}}}
    r = _sd(day, T, "pranzo", {"kcal": 400, "protein_g": 40, "carbs_g": 30, "fat_g": 10})
    assert r["quota_kcal"] == 355 and r["rebalance"] is None
    assert any("cena decisa" in l for l in r["verdict"]["lines"])


def test_mensa_endpoint_uses_history_and_described_dinner(client, setup_database, monkeypatch):
    import uuid
    from planmydinner_addon.database import ConsumedEntry
    from planmydinner_addon.tests.conftest import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        for d, ings in (("2026-02-16", [("Petto di pollo", 150), ("Fagiolini", 100), ("Pane", 80), ("Mela", 150)]),
                        ("2026-02-17", [("Salmone", 150), ("Spinaci", 100), ("Pane", 50)]),
                        ("2026-02-21", [("Pizza", 300)])):          # sabato: non è mensa
            db.add(ConsumedEntry(id=str(uuid.uuid4()), profile_id="persona_a", date=d, meal_type="pranzo",
                                 type="override", override_details={
                                     "free_text_name": "Pasto mensa", "notes": "mensa",
                                     "ingredients": [{"name": n, "qty": g, "unit": "g"} for n, g in ings]}))
        db.commit()
    finally:
        db.close()

    class GW:
        _client = object()

        def estimate_meal_from_text(self, desc):
            return {"name": "Pizza margherita", "ingredients": [{"name": "Pizza margherita", "food_group": "carboidrati", "grams": 350}]}

    client.app.state.llm_gateway = GW()
    monkeypatch.setattr("planmydinner_addon.api.simulate.compute_recipe_nutrition",
                        lambda content, pid, llm_gateway=None: _kcal_table(
                            [{"name": c["name"].lower(), "grams": c["quantities"][pid]["grams_equiv"]} for c in content]))
    try:
        r = client.post("/simulate/mensa?profile_id=persona_a&meal_type=pranzo&target_date=2026-02-24",
                        json={"other_description": "stasera pizza"})
    finally:
        client.app.state.llm_gateway = None
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["trays"] == 2 and j["other"]["name"] == "Pizza margherita"
    assert {o["category"] for o in j["options"]} == {"carne_bianca", "pesce"}
    assert all(o["ingredients"] and "verdict" in o for o in j["options"])
