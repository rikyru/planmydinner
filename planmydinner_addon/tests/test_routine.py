"""Pasti fissi (colazione/spuntini) con logica opt-out: definizione, eccezioni, summary."""
import pytest

# freeze_time in conftest: today = 2026-02-24; lunedì = 2026-02-23
TODAY = "2026-02-24"
MONDAY = "2026-02-23"
SUNDAY = "2026-03-01"

# pane 30 g (265 kcal/100g) + yogurt greco 150 g (97 kcal/100g) = 79.5 + 145.5
COLAZIONE_KCAL = 265 * 0.3 + 97 * 1.5


def _define(client, slot="colazione", name="Colazione tipo", default_on=None,
            ingredients=None, profile="persona_a"):
    body = {
        "profile_id": profile,
        "name": name,
        "ingredients": ingredients or [
            {"name": "pane", "food_group": "carboidrati", "grams": 30},
            {"name": "yogurt greco", "food_group": "latticini", "grams": 150},
        ],
    }
    if default_on is not None:
        body["default_on"] = default_on
    return client.put(f"/routine/{slot}", json=body)


def _summary(client, profile="persona_a"):
    return client.get("/integration/summary", params={
        "profile_id": profile, "start_date": MONDAY, "end_date": SUNDAY,
    }).json()


class TestRoutineCrud:
    def test_define_and_list(self, client, setup_database):
        assert _define(client).status_code == 200
        data = client.get("/routine/", params={"profile_id": "persona_a"}).json()
        by_slot = {s["slot"]: s for s in data["slots"]}
        col = by_slot["colazione"]
        assert col["defined"] and col["default_on"] and col["today"] == "assumed"
        assert col["nutrition"]["kcal"] == pytest.approx(COLAZIONE_KCAL, abs=0.2)
        # dopo_cena: opt-in di default, non definito
        assert by_slot["dopo_cena"]["defined"] is False
        assert by_slot["dopo_cena"]["default_on"] is False

    def test_update_and_delete(self, client, setup_database):
        _define(client)
        _define(client, name="Colazione nuova",
                ingredients=[{"name": "pane", "food_group": "carboidrati", "grams": 60}])
        data = client.get("/routine/", params={"profile_id": "persona_a"}).json()
        col = next(s for s in data["slots"] if s["slot"] == "colazione")
        assert col["name"] == "Colazione nuova"
        assert col["nutrition"]["kcal"] == pytest.approx(265 * 0.6, abs=0.2)

        assert client.delete("/routine/colazione", params={"profile_id": "persona_a"}).status_code == 200
        data = client.get("/routine/", params={"profile_id": "persona_a"}).json()
        assert next(s for s in data["slots"] if s["slot"] == "colazione")["defined"] is False

    def test_unknown_slot_404(self, client, setup_database):
        assert _define(client, slot="brunch").status_code == 404


class TestRoutineInSummary:
    def test_counts_every_day_retroactively(self, client, setup_database):
        _define(client)
        data = _summary(client)
        assert all(d["nutrition"] is not None for d in data["days"])
        for d in data["days"]:
            assert d["nutrition"]["kcal"] == pytest.approx(COLAZIONE_KCAL, abs=0.2)
            assert d["routine_kcal"] == pytest.approx(COLAZIONE_KCAL, abs=0.2)
        assert data["averages"]["days_with_data"] == 7

    def test_skip_excludes_single_day(self, client, setup_database):
        _define(client)
        resp = client.post("/routine/colazione/skip",
                           params={"profile_id": "persona_a", "meal_date": TODAY})
        assert resp.json()["state"] == "skipped"
        data = _summary(client)
        today = next(d for d in data["days"] if d["date"] == TODAY)
        other = next(d for d in data["days"] if d["date"] != TODAY)
        assert today["routine_kcal"] == 0 and today["nutrition"] is None
        assert other["routine_kcal"] > 0

        # toggle: ripristina
        resp = client.post("/routine/colazione/skip",
                           params={"profile_id": "persona_a", "meal_date": TODAY})
        assert resp.json()["state"] == "assumed"
        data = _summary(client)
        assert next(d for d in data["days"] if d["date"] == TODAY)["routine_kcal"] > 0

    def test_opt_in_slot_counts_only_when_logged(self, client, setup_database):
        _define(client, slot="dopo_cena", name="Gelato",
                ingredients=[{"name": "yogurt", "food_group": "latticini", "grams": 100}])
        data = _summary(client)
        assert all(d["routine_kcal"] == 0 for d in data["days"])  # opt-in: mai assunto

        resp = client.post("/routine/dopo_cena/log",
                           params={"profile_id": "persona_a", "meal_date": TODAY})
        assert resp.json()["state"] == "logged"
        data = _summary(client)
        today = next(d for d in data["days"] if d["date"] == TODAY)
        assert today["routine_kcal"] == pytest.approx(66, abs=0.2)  # yogurt 100 g
        assert sum(1 for d in data["days"] if d["routine_kcal"] > 0) == 1

        # toggle: tolto
        resp = client.post("/routine/dopo_cena/log",
                           params={"profile_id": "persona_a", "meal_date": TODAY})
        assert resp.json()["state"] == "off"
        data = _summary(client)
        assert all(d["routine_kcal"] == 0 for d in data["days"])

    def test_different_meal_replaces_assumed(self, client, setup_database):
        """'Diversa oggi' via flusso mensa con meal_type = slot: sostituisce il pasto fisso."""
        _define(client)
        resp = client.post("/consumed-entries/mensa", json={
            "profile_id": "persona_a", "date": TODAY, "meal_type": "colazione",
            "name": "Brioche al bar",
            "ingredients": [{"name": "pane", "food_group": "carboidrati", "grams": 100}],
        })
        assert resp.status_code == 200
        data = _summary(client)
        today = next(d for d in data["days"] if d["date"] == TODAY)
        assert today["routine_kcal"] == pytest.approx(265, abs=0.3)  # la brioche, non la colazione tipo
        other = next(d for d in data["days"] if d["date"] != TODAY)
        assert other["routine_kcal"] == pytest.approx(COLAZIONE_KCAL, abs=0.2)
