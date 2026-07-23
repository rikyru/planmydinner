"""
Pasto libero con stima automatica delle kcal dalla descrizione (best-effort,
via LLM: es. "kebab" -> ingredienti + grammi ipotizzati). Se la stima riesce,
il giorno non viene più escluso dalle medie di /integration/summary.
"""
import pytest

from planmydinner_addon.database import GeneratedWeeklyPlan
from planmydinner_addon.main import app

TODAY = "2026-02-24"
MONDAY = "2026-02-23"


class FakeTextGateway:
    """Gateway finto: stima sempre lo stesso pasto ('kebab')."""
    _client = object()

    def __init__(self, result=None):
        self.result = result if result is not None else {
            "name": "Kebab",
            "ingredients": [
                {"name": "pane pita", "food_group": "carboidrati", "grams": 100},
                {"name": "pollo", "food_group": "carne_bianca", "grams": 150},
                {"name": "insalata", "food_group": "verdure", "grams": 50},
            ],
        }
        self.calls = 0

    def estimate_meal_from_text(self, description, use_cache=True):
        self.calls += 1
        self.last_description = description
        return self.result


@pytest.fixture
def fake_gateway():
    original = getattr(app.state, "llm_gateway", None)
    fake = FakeTextGateway()
    app.state.llm_gateway = fake
    yield fake
    app.state.llm_gateway = original


def _make_plan(db, profile_id="persona_a"):
    db.add(GeneratedWeeklyPlan(
        id="plan-free-meal-estimate", profile_id_A=profile_id, profile_id_B="persona_b",
        week_start_date=MONDAY, generated_at=MONDAY,
        daily_plans=[{
            "date": TODAY,
            "meals": [
                {"meal_type": "pranzo", "items": [{
                    "item_name": "Pasta al Pomodoro", "food_group": "recipe", "quantity": 1,
                    "unit": "recipe", "is_estimated_unit": False, "alternatives": [],
                    "recipe_id": "pasta_pomodoro_recipe",
                }]},
                {"meal_type": "cena", "items": []},
            ],
        }],
    ))
    db.commit()


class TestFreeMealEstimation:
    def test_free_meal_gets_estimated_and_counted(self, client, setup_database, fake_gateway):
        _make_plan(setup_database)
        resp = client.post(
            "/planner/free-meal",
            params={"profile_id_A": "persona_a", "profile_id_B": "persona_b",
                    "meal_type": "cena", "current_date": TODAY},
            json={"title": "kebab", "notes": ""},
        )
        assert resp.status_code == 200
        assert resp.json()["estimated"] is True
        assert "kebab" in fake_gateway.last_description.lower()

        data = client.get("/integration/summary", params={
            "profile_id": "persona_a", "start_date": MONDAY, "end_date": "2026-03-01",
        }).json()
        today = next(d for d in data["days"] if d["date"] == TODAY)
        assert today["free_meals"] == 1
        assert today["complete"] is True          # non più escluso dalle medie
        assert today["has_estimated_meal"] is True
        # pollo 150g (110kcal/100g) + pane pita 100g (265kcal/100g) + insalata 50g
        # + pranzo noto (pasta 100g + pomodoro 200g)
        assert today["nutrition"]["kcal"] > 353  # somma di piu' pasti, non solo il pranzo
        assert data["averages"]["days_with_data"] >= 1

    def test_free_meal_without_llm_stays_unestimated(self, client, setup_database):
        # Nessun fake_gateway: il gateway reale di test ha _client=None (ollama
        # non installato) -> comportamento invariato, nessuna stima possibile.
        _make_plan(setup_database)
        resp = client.post(
            "/planner/free-meal",
            params={"profile_id_A": "persona_a", "profile_id_B": "persona_b",
                    "meal_type": "cena", "current_date": TODAY},
            json={"title": "qualcosa fuori", "notes": ""},
        )
        assert resp.status_code == 200
        assert resp.json()["estimated"] is False

        data = client.get("/integration/summary", params={
            "profile_id": "persona_a", "start_date": MONDAY, "end_date": "2026-03-01",
        }).json()
        today = next(d for d in data["days"] if d["date"] == TODAY)
        assert today["complete"] is False
        assert today["has_estimated_meal"] is False

    def test_estimation_failure_falls_back_gracefully(self, client, setup_database):
        class _NoResultGateway:
            _client = object()

            def estimate_meal_from_text(self, description, use_cache=True):
                return None  # "nessun pasto riconosciuto" nella descrizione

        original = getattr(app.state, "llm_gateway", None)
        app.state.llm_gateway = _NoResultGateway()
        try:
            _make_plan(setup_database)
            resp = client.post(
                "/planner/free-meal",
                params={"profile_id_A": "persona_a", "profile_id_B": "persona_b",
                        "meal_type": "cena", "current_date": TODAY},
                json={"title": "boh", "notes": ""},
            )
            assert resp.status_code == 200
            assert resp.json()["estimated"] is False
        finally:
            app.state.llm_gateway = original
