"""Test per il flusso 'pasto da foto' (mensa): analyze, salvataggio catalogo, riuso."""
import uuid

import pytest

from planmydinner_addon.database import GeneratedWeeklyPlan
from planmydinner_addon.main import app


class FakeVisionGateway:
    """Gateway finto: risponde come farebbe il modello vision."""
    _client = object()  # non-None → il check di disponibilità passa

    def __init__(self, result=None):
        self.result = result if result is not None else {
            "name": "Vassoio mensa: pasta e frittata",
            "ingredients": [
                {"name": "pasta", "food_group": "carboidrati", "grams": 80},
                {"name": "frittata di uova", "food_group": "uova", "grams": 120},
                {"name": "insalata", "food_group": "verdure", "grams": 100},
            ],
        }
        self.calls = 0

    def estimate_meal_from_photo(self, image_b64, mime_type="image/jpeg"):
        self.calls += 1
        return self.result

    def estimate_nutrition(self, item_name):
        return None  # forza l'uso della sola tabella locale


@pytest.fixture
def fake_gateway():
    original = getattr(app.state, "llm_gateway", None)
    fake = FakeVisionGateway()
    app.state.llm_gateway = fake
    yield fake
    app.state.llm_gateway = original


def _analyze(client, profile_id="persona_a"):
    return client.post(
        f"/consumed-entries/photo/analyze?profile_id={profile_id}",
        files={"file": ("vassoio.jpg", b"finta-foto-jpeg", "image/jpeg")},
    )


class TestPhotoAnalyze:
    def test_analyze_returns_proposal_with_nutrition(self, client, setup_database, fake_gateway):
        resp = _analyze(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"].startswith("Vassoio")
        assert len(data["ingredients"]) == 3
        # pasta 80 g (353/100g) + uova 120 g (143/100g) + insalata 100 g (15/100g)
        expected = 353 * 0.8 + 143 * 1.2 + 15
        assert data["nutrition"]["kcal"] == pytest.approx(expected, abs=0.3)
        assert fake_gateway.calls == 1

    def test_analyze_rejects_non_image(self, client, setup_database, fake_gateway):
        resp = client.post(
            "/consumed-entries/photo/analyze?profile_id=persona_a",
            files={"file": ("doc.pdf", b"%PDF", "application/pdf")},
        )
        assert resp.status_code == 422

    def test_analyze_unrecognized_meal_422(self, client, setup_database):
        original = getattr(app.state, "llm_gateway", None)
        app.state.llm_gateway = FakeVisionGateway(result=False)
        try:
            app.state.llm_gateway.result = None
            resp = _analyze(client)
            assert resp.status_code == 422
        finally:
            app.state.llm_gateway = original


class TestMensaCatalog:
    def test_save_list_and_reuse(self, client, setup_database, fake_gateway):
        body = {
            "profile_id": "persona_a",
            "date": "2026-02-24",
            "meal_type": "pranzo",
            "name": "Pasta e frittata",
            "ingredients": [
                {"name": "pasta", "food_group": "carboidrati", "grams": 80},
                {"name": "frittata di uova", "food_group": "uova", "grams": 120},
            ],
        }
        resp = client.post("/consumed-entries/mensa", json=body)
        assert resp.status_code == 200
        recipe_id = resp.json()["recipe_id"]
        assert resp.json()["consumed_entry_id"]

        # Catalogo: 1 pasto, usage_count 1, macro dalla tabella
        resp = client.get("/consumed-entries/mensa", params={"profile_id": "persona_a"})
        assert resp.status_code == 200
        meals = resp.json()
        assert len(meals) == 1
        assert meals[0]["id"] == recipe_id
        assert meals[0]["usage_count"] == 1
        assert meals[0]["nutrition"]["kcal"] == pytest.approx(353 * 0.8 + 143 * 1.2, abs=0.3)

        # Dedupe per nome: risalvare lo stesso pasto non crea doppioni
        resp = client.post("/consumed-entries/mensa", json={**body, "date": "2026-02-25"})
        assert resp.json()["recipe_id"] == recipe_id
        assert len(client.get("/consumed-entries/mensa").json()) == 1

        # Riuso senza LLM
        resp = client.post(
            f"/consumed-entries/mensa/{recipe_id}/consume",
            params={"profile_id": "persona_a", "meal_date": "2026-02-26", "meal_type": "pranzo"},
        )
        assert resp.status_code == 200
        assert fake_gateway.calls == 0  # nessuna chiamata vision per il riuso

        # 3 consumi registrati (save + save + consume)
        entries = client.get("/consumed-entries/", params={"profile_id": "persona_a"}).json()
        mensa_entries = [e for e in entries if e.get("consumed_recipe_id") == recipe_id]
        assert len(mensa_entries) == 3
        assert all(e["type"] == "override" for e in mensa_entries)

    def test_register_replaces_plan_slot(self, client, setup_database):
        """Registrare un pasto mensa deve sostituire lo slot del piano (non lasciare
        la ricetta suggerita)."""
        db = setup_database
        db.add(GeneratedWeeklyPlan(
            id=str(uuid.uuid4()), profile_id_A="persona_a", profile_id_B="persona_b",
            week_start_date="2026-02-23", generated_at="2026-02-23",
            daily_plans=[{"date": "2026-02-24", "meals": [
                {"meal_type": "pranzo", "items": [{
                    "item_name": "Ricetta suggerita", "food_group": "recipe",
                    "quantity": 1, "unit": "recipe", "is_estimated_unit": False,
                    "alternatives": [], "recipe_id": "pasta_pomodoro_recipe",
                }]},
                {"meal_type": "cena", "items": []},
            ]}],
        ))
        db.commit()

        resp = client.post("/consumed-entries/mensa", json={
            "profile_id": "persona_a", "date": "2026-02-24", "meal_type": "pranzo",
            "name": "Vassoio pasta e uova",
            "ingredients": [{"name": "pasta", "food_group": "carboidrati", "grams": 80}],
        })
        assert resp.status_code == 200
        recipe_id = resp.json()["recipe_id"]

        db.expire_all()
        plan = db.query(GeneratedWeeklyPlan).filter(
            GeneratedWeeklyPlan.profile_id_A == "persona_a").first()
        item = plan.daily_plans[0]["meals"][0]["items"][0]
        assert item["food_group"] == "mensa"
        assert item["recipe_id"] == recipe_id
        assert "Vassoio pasta e uova" in item["item_name"]
        # la cena non viene toccata
        assert plan.daily_plans[0]["meals"][1]["items"] == []

    def test_update_and_delete_mensa_meal(self, client, setup_database):
        resp = client.post("/consumed-entries/mensa", json={
            "profile_id": "persona_a", "date": "2026-02-24", "meal_type": "pranzo",
            "name": "Pasta della mensa",
            "ingredients": [{"name": "pasta", "food_group": "carboidrati", "grams": 80}],
        })
        recipe_id = resp.json()["recipe_id"]

        # Modifica grammature e nome
        resp = client.put(f"/consumed-entries/mensa/{recipe_id}", json={
            "name": "Pasta della mensa (abbondante)",
            "ingredients": [{"name": "pasta", "food_group": "carboidrati", "grams": 120}],
        })
        assert resp.status_code == 200
        meals = client.get("/consumed-entries/mensa", params={"profile_id": "persona_a"}).json()
        assert meals[0]["name"] == "Pasta della mensa (abbondante)"
        assert meals[0]["ingredients"][0]["grams"] == 120
        assert meals[0]["nutrition"]["kcal"] == pytest.approx(353 * 1.2, abs=0.2)

        # Elimina dal catalogo
        resp = client.delete(f"/consumed-entries/mensa/{recipe_id}")
        assert resp.status_code == 200
        assert client.get("/consumed-entries/mensa").json() == []
        resp = client.post(f"/consumed-entries/mensa/{recipe_id}/consume",
                           params={"profile_id": "persona_a", "meal_date": "2026-02-25", "meal_type": "pranzo"})
        assert resp.status_code == 404

    def test_ho_mangiato_is_idempotent(self, client, setup_database):
        """Ripremere 'Ho mangiato' sullo stesso pasto non crea duplicati."""
        body = {
            "profile_id": "persona_a", "date": "2026-02-24", "meal_type": "pranzo",
            "type": "planned", "consumed_recipe_id": "pasta_pomodoro_recipe",
        }
        id1 = client.post("/consumed-entries/", json=body).json()["id"]
        id2 = client.post("/consumed-entries/", json=body).json()["id"]
        assert id1 == id2
        entries = client.get("/consumed-entries/", params={"profile_id": "persona_a"}).json()
        planned = [e for e in entries if e["meal_type"] == "pranzo" and e["type"] == "planned"]
        assert len(planned) == 1

    def test_update_unknown_404(self, client, setup_database):
        resp = client.put("/consumed-entries/mensa/nope", json={
            "name": "x", "ingredients": [{"name": "pasta", "food_group": "carboidrati", "grams": 80}],
        })
        assert resp.status_code == 404

    def test_consume_unknown_id_404(self, client, setup_database):
        resp = client.post(
            "/consumed-entries/mensa/id-inesistente/consume",
            params={"profile_id": "persona_a", "meal_date": "2026-02-24", "meal_type": "cena"},
        )
        assert resp.status_code == 404

    def test_save_requires_ingredients(self, client, setup_database):
        resp = client.post("/consumed-entries/mensa", json={
            "profile_id": "persona_a", "date": "2026-02-24", "meal_type": "pranzo",
            "name": "Vuoto", "ingredients": [],
        })
        assert resp.status_code == 422
