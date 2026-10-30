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
    [ex] = day["extras"]
    assert (ex["name"], ex["kcal"], ex["description"]) == (
        "Aperitivo", round(52 * 1.5), "aperitivo: birra media, pane e salumi")
    assert ex["fat_g"] is not None
    other = next(d for d in s["days"] if d["date"] == MONDAY)
    assert other["extras"] == []


def test_fat_sources_list_the_fattiest_items_of_the_day(client, setup_database):
    _add(client, name="Frutta secca", ingredients=[{"name": "Mandorle", "food_group": "grassi", "grams": 30}])
    _add(client, name="Mela", ingredients=[{"name": "Mela", "food_group": "frutta", "grams": 150}])
    s = client.get("/integration/summary", params={
        "profile_id": "persona_a", "start_date": TODAY, "end_date": TODAY,
        "meal_detail": "true"}).json()
    src = s["days"][0]["fat_sources"]
    assert src[0]["fat_g"] == max(x["fat_g"] for x in src)
    almonds = next(x for x in src if x["name"] == "Frutta secca")
    assert almonds["where"] == "extra" and almonds["fat_g"] > 10
    assert all(x["name"] != "Mela" for x in src)          # sotto 1 g: non è una fonte


def test_extra_from_pantry_uses_label_values(client, setup_database):
    # yogurt greco scansionato: valori per 100 g dall'etichetta, non stimati dal nome
    from planmydinner_addon.database import PantryItem
    from planmydinner_addon.tests.conftest import TestingSessionLocal as SessionLocal
    db = SessionLocal()
    db.add(PantryItem(id="yog", name="Yogurt greco 0%", quantity=2, unit="pz",
                      nutrition={"kcal": 57, "protein_g": 10.3, "carbs_g": 3.4, "fat_g": 0.2}))
    db.commit()
    db.close()
    r = client.post("/routine/extra",
                    params={"profile_id": "persona_a", "meal_date": TODAY},
                    json={"name": "Yogurt", "ingredients": [
                        {"name": "Yogurt greco 0%", "grams": 170, "pantry_id": "yog"},
                        {"name": "Mela", "food_group": "frutta", "grams": 150}]})
    assert r.status_code == 200, r.text
    n = r.json()["nutrition"]
    assert n["kcal"] == pytest.approx(57 * 1.7 + 52 * 1.5, abs=3)
    assert n["protein_g"] == pytest.approx(10.3 * 1.7, abs=1)
    # valori copiati sull'extra: togliere il prodotto dalla dispensa non cambia la merenda
    db = SessionLocal()
    db.query(PantryItem).filter(PantryItem.id == "yog").delete()
    db.commit()
    db.close()
    lst = client.get("/routine/extras", params={"profile_id": "persona_a", "meal_date": TODAY}).json()
    assert lst["extras"][0]["nutrition"]["kcal"] == pytest.approx(n["kcal"], abs=0.5)
    s = client.get("/integration/summary", params={
        "profile_id": "persona_a", "start_date": MONDAY, "end_date": "2026-03-01"}).json()
    day = next(d for d in s["days"] if d["date"] == TODAY)
    assert day["extra_kcal"] == pytest.approx(n["kcal"], abs=0.5)
