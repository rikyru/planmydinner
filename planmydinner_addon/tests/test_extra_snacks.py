"""Merende extra: spuntini liberi fuori dai 5 slot fissi, contati nei totali."""
import pytest

TODAY = "2026-02-24"   # freeze_time in conftest
MONDAY = "2026-02-23"


def _add(client, name="Spuntino", ingredients=None):
    ingredients = ingredients or [{"name": "Mela", "food_group": "frutta", "grams": 150}]
    return client.post("/routine/extra",
                       params={"profile_id": "persona_a", "meal_date": TODAY},
                       json={"name": name, "ingredients": ingredients})


def test_add_list_delete_extra(client, setup_database):
    r = _add(client)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    assert r.json()["nutrition"]["kcal"] == pytest.approx(52 * 1.5, abs=3)  # mela 150g

    lst = client.get("/routine/extras", params={"profile_id": "persona_a", "meal_date": TODAY})
    assert lst.status_code == 200
    extras = lst.json()["extras"]
    assert len(extras) == 1 and extras[0]["id"] == eid

    # più merende nello stesso giorno (non legate a uno slot)
    _add(client, name="Barretta", ingredients=[{"name": "Mandorle", "food_group": "grassi", "grams": 20}])
    assert len(client.get("/routine/extras", params={"profile_id": "persona_a", "meal_date": TODAY}).json()["extras"]) == 2

    d = client.delete(f"/routine/extra/{eid}")
    assert d.status_code == 200
    assert len(client.get("/routine/extras", params={"profile_id": "persona_a", "meal_date": TODAY}).json()["extras"]) == 1


def test_extra_counts_in_summary(client, setup_database):
    _add(client, ingredients=[{"name": "Mela", "food_group": "frutta", "grams": 150}])
    s = client.get("/integration/summary", params={
        "profile_id": "persona_a", "start_date": MONDAY, "end_date": "2026-03-01"})
    assert s.status_code == 200
    day = next(d for d in s.json()["days"] if d["date"] == TODAY)
    assert day["extra_kcal"] == pytest.approx(52 * 1.5, abs=3)
    assert day["nutrition"]["kcal"] >= day["extra_kcal"]


def test_add_requires_ingredient(client, setup_database):
    r = client.post("/routine/extra",
                    params={"profile_id": "persona_a", "meal_date": TODAY},
                    json={"name": "Vuoto", "ingredients": [{"name": "", "food_group": "altro", "grams": 0}]})
    assert r.status_code == 422


def test_extra_free_description_kept_and_listed_in_summary(client, setup_database):
    # merenda descritta a parole (stimata dall'AI nel frontend): la descrizione
    # resta e il riepilogo per OpenFit dice COSA è stato mangiato, non solo le kcal
    r = client.post("/routine/extra",
                    params={"profile_id": "persona_a", "meal_date": TODAY},
                    json={"name": "Aperitivo",
                          "description": "aperitivo: birra media, pane e salumi",
                          "ingredients": [{"name": "Mela", "food_group": "frutta", "grams": 150}]})
    assert r.status_code == 200, r.text
    lst = client.get("/routine/extras", params={"profile_id": "persona_a", "meal_date": TODAY}).json()
    assert lst["extras"][0]["description"] == "aperitivo: birra media, pane e salumi"
    s = client.get("/integration/summary", params={
        "profile_id": "persona_a", "start_date": MONDAY, "end_date": "2026-03-01"}).json()
    day = next(d for d in s["days"] if d["date"] == TODAY)
    assert day["extras"] == [{"name": "Aperitivo", "kcal": round(52 * 1.5),
                              "description": "aperitivo: birra media, pane e salumi"}]
    other = next(d for d in s["days"] if d["date"] == MONDAY)
    assert other["extras"] == []
