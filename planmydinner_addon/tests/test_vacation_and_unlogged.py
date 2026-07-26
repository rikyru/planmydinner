"""
Modalità vacanza (sospende i promemoria "pasti da registrare") e box
"pasti dimenticati" (GET /integration/unlogged-meals).
"""
from datetime import date, timedelta

from planmydinner_addon.database import ConsumedEntry, GeneratedWeeklyPlan

TODAY = date(2026, 2, 24)  # freeze_time in conftest
MONDAY = TODAY - timedelta(days=TODAY.weekday())


def _item(recipe_id="pasta_pomodoro_recipe", food_group="recipe"):
    return {
        "item_name": "Pasta al Pomodoro", "food_group": food_group, "quantity": 1,
        "unit": "recipe", "is_estimated_unit": False, "alternatives": [], "recipe_id": recipe_id,
    }


def _make_plan(db, profile_id="persona_a", start=MONDAY, days=7):
    db.add(GeneratedWeeklyPlan(
        id=f"plan-{start.isoformat()}", profile_id_A=profile_id, profile_id_B="persona_b",
        week_start_date=start.isoformat(), generated_at=start.isoformat(),
        daily_plans=[{
            "date": (start + timedelta(days=i)).isoformat(),
            "meals": [{"meal_type": "pranzo", "items": [_item()]}, {"meal_type": "cena", "items": [_item()]}],
        } for i in range(days)],
    ))
    db.commit()


class TestVacationEndpoints:
    def test_set_and_read_vacation(self, client, setup_database):
        resp = client.put("/planner/vacation", params={"profile_id": "persona_a"},
                          json={"start_date": "2026-02-20", "end_date": "2026-02-28"})
        assert resp.status_code == 200
        rules = client.get("/planner/rules", params={"profile_id_A": "persona_a"}).json()
        assert rules["plan_rules"]["vacation_start"] == "2026-02-20"
        assert rules["plan_rules"]["vacation_end"] == "2026-02-28"

    def test_clear_vacation(self, client, setup_database):
        client.put("/planner/vacation", params={"profile_id": "persona_a"},
                  json={"start_date": "2026-02-20", "end_date": "2026-02-28"})
        resp = client.delete("/planner/vacation", params={"profile_id": "persona_a"})
        assert resp.status_code == 200
        rules = client.get("/planner/rules", params={"profile_id_A": "persona_a"}).json()
        assert rules["plan_rules"]["vacation_start"] is None

    def test_invalid_range_422(self, client, setup_database):
        resp = client.put("/planner/vacation", params={"profile_id": "persona_a"},
                          json={"start_date": "2026-03-01", "end_date": "2026-02-20"})
        assert resp.status_code == 422


class TestTrackingStartDate:
    def test_set_and_read(self, client, setup_database):
        resp = client.put("/planner/tracking-start-date", params={"profile_id": "persona_a"},
                          json={"start_date": "2026-01-01"})
        assert resp.status_code == 200
        assert resp.json()["tracking_start_date"] == "2026-01-01"
        rules = client.get("/planner/rules", params={"profile_id_A": "persona_a"}).json()
        assert rules["plan_rules"]["tracking_start_date"] == "2026-01-01"

    def test_default_when_unset(self, client, setup_database):
        rules = client.get("/planner/rules", params={"profile_id_A": "persona_a"}).json()
        assert rules["plan_rules"] is None

    def test_invalid_date_422(self, client, setup_database):
        resp = client.put("/planner/tracking-start-date", params={"profile_id": "persona_a"},
                          json={"start_date": "non-una-data"})
        assert resp.status_code == 422


class TestTodayStatusRespectsVacation:
    def test_unlogged_suppressed_during_vacation(self, client, setup_database):
        _make_plan(setup_database)
        client.put("/planner/vacation", params={"profile_id": "persona_a"},
                  json={"start_date": TODAY.isoformat(), "end_date": (TODAY + timedelta(days=3)).isoformat()})

        data = client.get("/integration/today-status", params={"profile_id": "persona_a"}).json()
        assert data["vacation"] is True
        assert data["unlogged"] == []
        assert data["unlogged_count"] == 0
        # i pasti pianificati restano visibili, solo il "da registrare" tace
        assert len(data["meals"]) == 2

    def test_unlogged_normal_outside_vacation(self, client, setup_database):
        _make_plan(setup_database)
        client.put("/planner/vacation", params={"profile_id": "persona_a"},
                  json={"start_date": "2026-03-01", "end_date": "2026-03-10"})  # non copre oggi
        data = client.get("/integration/today-status", params={"profile_id": "persona_a"}).json()
        assert data["vacation"] is False
        assert data["unlogged_count"] == 2


class TestUnloggedMeals:
    def test_lists_unlogged_meals_in_range(self, client, setup_database):
        _make_plan(setup_database)
        # Segna un pasto come registrato: non deve comparire
        client.post("/consumed-entries/", json={
            "profile_id": "persona_a", "date": MONDAY.isoformat(), "meal_type": "pranzo",
            "type": "planned", "consumed_recipe_id": "pasta_pomodoro_recipe",
        })
        resp = client.get("/integration/unlogged-meals", params={
            "profile_id": "persona_a", "start_date": MONDAY.isoformat(), "end_date": TODAY.isoformat(),
        })
        assert resp.status_code == 200
        data = resp.json()
        # esclude il pranzo di lunedì (registrato) e i giorni futuri oltre "oggi"
        assert not any(u["date"] == MONDAY.isoformat() and u["meal_type"] == "pranzo" for u in data["unlogged"])
        assert any(u["date"] == MONDAY.isoformat() and u["meal_type"] == "cena" for u in data["unlogged"])
        assert all(u["date"] <= TODAY.isoformat() for u in data["unlogged"])

    def test_excludes_vacation_period(self, client, setup_database):
        _make_plan(setup_database)
        client.put("/planner/vacation", params={"profile_id": "persona_a"},
                  json={"start_date": MONDAY.isoformat(), "end_date": TODAY.isoformat()})
        resp = client.get("/integration/unlogged-meals", params={
            "profile_id": "persona_a", "start_date": MONDAY.isoformat(), "end_date": TODAY.isoformat(),
        })
        assert resp.json()["unlogged"] == []

    def test_free_meal_and_not_eaten_slots_are_not_unlogged(self, client, setup_database):
        db = setup_database
        db.add(GeneratedWeeklyPlan(
            id="plan-special", profile_id_A="persona_a", profile_id_B="persona_b",
            week_start_date=MONDAY.isoformat(), generated_at=MONDAY.isoformat(),
            daily_plans=[{
                "date": MONDAY.isoformat(),
                "meals": [
                    {"meal_type": "pranzo", "items": [_item(None, "free_meal")]},
                    {"meal_type": "cena", "items": [_item(None, "not_eaten")]},
                ],
            }],
        ))
        db.commit()
        resp = client.get("/integration/unlogged-meals", params={
            "profile_id": "persona_a", "start_date": MONDAY.isoformat(), "end_date": MONDAY.isoformat(),
        })
        assert resp.json()["unlogged"] == []

    def test_no_plan_returns_empty(self, client, setup_database):
        resp = client.get("/integration/unlogged-meals", params={
            "profile_id": "nessuno", "start_date": MONDAY.isoformat(), "end_date": TODAY.isoformat(),
        })
        assert resp.status_code == 200
        assert resp.json()["unlogged"] == []

    def test_end_date_defaults_and_future_range_returns_empty(self, client, setup_database):
        _make_plan(setup_database)
        resp = client.get("/integration/unlogged-meals", params={
            "profile_id": "persona_a", "start_date": (TODAY + timedelta(days=5)).isoformat(),
        })
        assert resp.status_code == 200
        assert resp.json()["unlogged"] == []

    def test_start_date_defaults_to_configured_tracking_start(self, client, setup_database):
        """Senza start_date esplicito usa la data configurata in Impostazioni
        (PUT /planner/tracking-start-date), non il default hardcoded."""
        _make_plan(setup_database)
        # Sposta l'inizio tracciamento a martedì (un giorno dopo l'inizio del piano):
        # il pranzo di lunedì non deve più comparire tra i dimenticati.
        tuesday = (MONDAY + timedelta(days=1)).isoformat()
        client.put("/planner/tracking-start-date", params={"profile_id": "persona_a"},
                  json={"start_date": tuesday})

        resp = client.get("/integration/unlogged-meals", params={"profile_id": "persona_a"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["start_date"] == tuesday
        assert not any(u["date"] == MONDAY.isoformat() for u in data["unlogged"])

    def test_start_date_defaults_to_hardcoded_default_when_unconfigured(self, client, setup_database):
        resp = client.get("/integration/unlogged-meals", params={"profile_id": "persona_a"})
        assert resp.status_code == 200
        assert resp.json()["start_date"] == "2026-07-06"
