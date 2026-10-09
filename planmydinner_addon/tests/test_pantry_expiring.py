"""Dispensa: ricette che consumano i prodotti in scadenza + proposta pasto AI."""
import uuid
from datetime import date, timedelta

from planmydinner_addon.database import PantryItem

TODAY = date(2026, 2, 24)   # freeze_time in conftest


def test_expiring_recipes_matches_catalog(client, setup_database):
    db = setup_database
    # pasta_pomodoro_recipe (seed) usa "Pomodoro": mettiamo il pomodoro in scadenza domani
    db.add(PantryItem(id=str(uuid.uuid4()), name="Pomodoro", quantity=200, unit="g",
                      expiration_date=(TODAY + timedelta(days=1)).isoformat(), synonyms=[]))
    db.commit()
    r = client.get("/pantry/expiring-recipes")
    assert r.status_code == 200
    data = r.json()
    assert any(e["name"] == "Pomodoro" for e in data["expiring"])
    names = [rec["name"] for rec in data["recipes"]]
    assert "Pasta al Pomodoro" in names
    rec = next(rec for rec in data["recipes"] if rec["name"] == "Pasta al Pomodoro")
    assert "Pomodoro" in rec["uses"]


def test_expiring_recipes_empty_when_nothing_expires(client, setup_database):
    r = client.get("/pantry/expiring-recipes")
    assert r.status_code == 200
    assert r.json()["expiring"] == []


def test_suggest_routine_uses_ai(client, setup_database, monkeypatch):
    from planmydinner_addon.main import app

    class _GW:
        _client = object()
        def suggest_meal(self, slot_label, avoid=None):
            return {"name": "Yogurt e noci", "ingredients": [
                {"name": "Yogurt greco", "food_group": "latticini", "grams": 170},
                {"name": "Noci", "food_group": "grassi", "grams": 20}]}

    monkeypatch.setattr(app.state, "llm_gateway", _GW())
    r = client.get("/routine/suggest?slot=colazione")
    assert r.status_code == 200
    assert r.json()["name"] == "Yogurt e noci"
    assert len(r.json()["ingredients"]) == 2
