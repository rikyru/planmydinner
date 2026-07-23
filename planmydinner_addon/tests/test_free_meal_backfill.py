"""POST /planner/backfill-free-meal-estimates: stima retroattivamente i pasti
liberi già registrati (senza recipe_id) prima che la stima fosse automatica."""
import pytest

from planmydinner_addon.database import GeneratedWeeklyPlan
from planmydinner_addon.main import app

MONDAY = "2026-02-23"


class FakeTextGateway:
    _client = object()

    def __init__(self):
        self.calls = []

    def estimate_meal_from_text(self, description, use_cache=True):
        self.calls.append(description)
        if description == "boh":
            return None  # simula descrizione non riconoscibile
        return {
            "name": description,
            "ingredients": [{"name": "ingrediente", "food_group": "altro", "grams": 200}],
        }


@pytest.fixture
def fake_gateway():
    original = getattr(app.state, "llm_gateway", None)
    fake = FakeTextGateway()
    app.state.llm_gateway = fake
    yield fake
    app.state.llm_gateway = original


def _item(name, recipe_id=None):
    return {
        "item_name": name, "food_group": "free_meal", "quantity": 0, "unit": "",
        "is_estimated_unit": False, "alternatives": [], "recipe_id": recipe_id,
    }


def _make_old_plan(db):
    db.add(GeneratedWeeklyPlan(
        id="plan-old-free-meals", profile_id_A="persona_a", profile_id_B="persona_b",
        week_start_date=MONDAY, generated_at=MONDAY,
        daily_plans=[
            {"date": "2026-02-23", "meals": [
                {"meal_type": "pranzo", "items": [_item("kebab")]},
                {"meal_type": "cena", "items": []},
            ]},
            {"date": "2026-02-24", "meals": [
                {"meal_type": "pranzo", "items": [_item("boh")]},   # non stimabile
                {"meal_type": "cena", "items": [_item("pizza", recipe_id="already-there")]},  # già stimato
            ]},
        ],
    ))
    db.commit()


class TestBackfillFreeMealEstimates:
    def test_backfill_estimates_only_unestimated_free_meals(self, client, setup_database, fake_gateway):
        _make_old_plan(setup_database)
        resp = client.post("/planner/backfill-free-meal-estimates", params={"profile_id_A": "persona_a"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["estimated"] == 1   # solo "kebab"
        assert data["skipped"] == 1     # "boh" non riconosciuto; "pizza" già stimato non viene nemmeno contato

        assert "kebab" in fake_gateway.calls
        assert "pizza" not in fake_gateway.calls  # già aveva recipe_id: saltato, nessuna chiamata sprecata

        setup_database.expire_all()
        plan = setup_database.query(GeneratedWeeklyPlan).filter(
            GeneratedWeeklyPlan.id == "plan-old-free-meals").first()
        kebab_item = plan.daily_plans[0]["meals"][0]["items"][0]
        assert kebab_item["recipe_id"] is not None
        assert kebab_item["food_group"] == "free_meal"  # badge/aderenza invariati

    def test_backfill_is_idempotent_for_already_estimated_items(self, client, setup_database, fake_gateway):
        _make_old_plan(setup_database)
        client.post("/planner/backfill-free-meal-estimates", params={"profile_id_A": "persona_a"})
        fake_gateway.calls.clear()

        # Rilanciare non ristima "kebab" (ha già un recipe_id) né richiama mai
        # "pizza" (partiva già stimata); "boh" viene ritentato (nessun recipe_id
        # salvato dopo un fallimento) — comportamento voluto: si riprova solo
        # ciò che non è mai stato risolto, senza sprecare chiamate su ciò che lo è già.
        resp = client.post("/planner/backfill-free-meal-estimates", params={"profile_id_A": "persona_a"})
        assert resp.json()["estimated"] == 0
        assert fake_gateway.calls == ["boh"]

    def test_backfill_without_llm_returns_503(self, client, setup_database):
        _make_old_plan(setup_database)
        resp = client.post("/planner/backfill-free-meal-estimates", params={"profile_id_A": "persona_a"})
        assert resp.status_code == 503
