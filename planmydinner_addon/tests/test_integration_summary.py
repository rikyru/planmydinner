"""Test per GET /integration/summary e per i macro in GET /recipes/detail."""
import pytest

from planmydinner_addon.database import GeneratedWeeklyPlan

# freeze_time in conftest: today = 2026-02-24 (martedì) → lunedì = 2026-02-23
TODAY = "2026-02-24"
MONDAY = "2026-02-23"


def _item(recipe_id=None, food_group="carboidrato", name="Pasta al Pomodoro"):
    return {
        "item_name": name,
        "food_group": food_group,
        "quantity": 0,
        "unit": "",
        "is_estimated_unit": False,
        "alternatives": [],
        "recipe_id": recipe_id,
    }


def _make_plan(db, profile_id="persona_a", week_start=MONDAY):
    """Piano di 7 giorni: pranzo+cena con la ricetta seed, tranne un pasto libero e un non mangiato."""
    from datetime import date, timedelta
    start = date.fromisoformat(week_start)
    daily_plans = []
    for i in range(7):
        d = (start + timedelta(days=i)).isoformat()
        meals = [
            {"meal_type": "pranzo", "items": [_item("pasta_pomodoro_recipe")]},
            {"meal_type": "cena", "items": [_item("pasta_pomodoro_recipe")]},
        ]
        if i == 1:  # martedì cena = pasto libero
            meals[1]["items"] = [_item(None, "free_meal", "Pizza")]
        if i == 2:  # mercoledì pranzo = non mangiato
            meals[0]["items"] = [_item(None, "not_eaten", "Non mangiato")]
        daily_plans.append({"date": d, "meals": meals})
    plan = GeneratedWeeklyPlan(
        id="gen-plan-test",
        profile_id_A=profile_id,
        profile_id_B="persona_b",
        week_start_date=week_start,
        generated_at=TODAY,
        daily_plans=daily_plans,
    )
    db.add(plan)
    db.commit()
    return plan


class TestIntegrationSummaryEmpty:
    def test_200_with_no_data(self, client, setup_database):
        resp = client.get("/integration/summary", params={
            "profile_id": "nessuno",
            "start_date": MONDAY,
            "end_date": "2026-03-01",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 1
        assert data["profile_id"] == "nessuno"
        assert data["adherence"]["planned_slots"] == 0
        assert data["adherence"]["adherence_score"] == 0.0
        assert len(data["days"]) == 7
        assert all(d["nutrition"] is None for d in data["days"])
        assert data["averages"] is None

    def test_defaults_to_current_week(self, client, setup_database):
        resp = client.get("/integration/summary", params={"profile_id": "nessuno"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["start_date"] == MONDAY
        assert len(data["days"]) == 7

    def test_invalid_range_422(self, client, setup_database):
        resp = client.get("/integration/summary", params={
            "profile_id": "nessuno",
            "start_date": "2026-03-01",
            "end_date": MONDAY,
        })
        assert resp.status_code == 422


class TestIntegrationSummaryWithData:
    def test_summary_with_plan(self, client, setup_database):
        _make_plan(setup_database)
        resp = client.get("/integration/summary", params={
            "profile_id": "persona_a",
            "start_date": MONDAY,
            "end_date": "2026-03-01",
        })
        assert resp.status_code == 200
        data = resp.json()

        # Aderenza: 14 slot pianificati, 1 libero, 1 non mangiato
        assert data["adherence"]["planned_slots"] == 14
        assert data["adherence"]["free_meals"] == 1
        assert data["adherence"]["not_eaten_slots"] == 1

        # Giorno pieno (lunedì): 2 pasti con la ricetta seed
        monday = data["days"][0]
        assert monday["date"] == MONDAY
        assert monday["meals_planned"] == 2
        # Ricetta seed per persona_a: Pasta 100 g (353 kcal) + Pomodoro 200 g (36 kcal)
        expected_meal_kcal = 353 + 18 * 2
        assert monday["nutrition"]["kcal"] == pytest.approx(2 * expected_meal_kcal, abs=0.3)
        assert monday["nutrition"]["coverage"] == 1.0

        # Martedì: cena libera → 1 pianificato, 1 libero, kcal di un solo pasto
        tuesday = data["days"][1]
        assert tuesday["meals_planned"] == 1
        assert tuesday["free_meals"] == 1
        assert tuesday["nutrition"]["kcal"] == pytest.approx(expected_meal_kcal, abs=0.2)

        # Mercoledì: pranzo non mangiato → conteggiato come not_eaten
        wednesday = data["days"][2]
        assert wednesday["not_eaten"] == 1

        # Medie sul periodo presenti
        assert data["averages"] is not None
        assert data["averages"]["days_with_data"] == 7
        assert data["averages"]["kcal"] > 0

    def test_period_without_plan_days(self, client, setup_database):
        _make_plan(setup_database)
        resp = client.get("/integration/summary", params={
            "profile_id": "persona_a",
            "start_date": "2026-06-01",
            "end_date": "2026-06-07",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert all(d["meals_planned"] == 0 and d["nutrition"] is None for d in data["days"])
        assert data["averages"] is None


class TestTodayStatus:
    def test_no_plan_returns_empty(self, client, setup_database):
        resp = client.get("/integration/today-status", params={"profile_id": "nessuno"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["meals"] == []
        assert data["unlogged_count"] == 0

    def test_unlogged_and_logged_meals(self, client, setup_database):
        _make_plan(setup_database)  # piano che copre TODAY (2026-02-24)
        # Nessun consumo registrato: pranzo e cena di oggi da registrare
        resp = client.get("/integration/today-status", params={"profile_id": "persona_a"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == TODAY
        # martedì: pranzo normale + cena free_meal (già "gestita")
        by_type = {m["meal_type"]: m for m in data["meals"]}
        assert by_type["pranzo"]["logged"] is False
        assert by_type["cena"]["logged"] is True       # free_meal = gestito
        assert data["unlogged"] == ["pranzo"]

        # Registro il pranzo → più nulla da registrare
        client.post("/consumed-entries/", json={
            "profile_id": "persona_a", "date": TODAY, "meal_type": "pranzo",
            "type": "planned", "consumed_recipe_id": "pasta_pomodoro_recipe",
        })
        data = client.get("/integration/today-status", params={"profile_id": "persona_a"}).json()
        assert data["unlogged_count"] == 0


class TestRecipeDetailNutrition:
    def test_detail_includes_macros_per_portion(self, client, setup_database):
        resp = client.get("/recipes/detail/pasta_pomodoro_recipe")
        assert resp.status_code == 200
        data = resp.json()
        npp = data["nutrition_per_portion"]
        assert npp is not None
        # I profili non esistono nel DB di test → fallback sulle chiavi delle quantities
        assert "persona_a" in npp
        # persona_a: Pasta 100 g + Pomodoro 200 g
        assert npp["persona_a"]["kcal"] == pytest.approx(353 + 36, abs=0.2)
        assert npp["persona_a"]["protein_g"] == pytest.approx(11 + 2, abs=0.2)
        # persona_b: Pasta 120 g + Pomodoro 200 g
        assert npp["persona_b"]["kcal"] == pytest.approx(353 * 1.2 + 36, abs=0.2)
        assert npp["persona_a"]["sources"] == {"table": 2}
