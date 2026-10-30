"""La dispensa si consuma con ciò che si mangia: merende extra e pasti fissi."""
import pytest

from planmydinner_addon.database import PantryItem, PantryUse
from planmydinner_addon.tests.conftest import TestingSessionLocal as SessionLocal

# freeze_time in conftest: today = 2026-02-24
TODAY = "2026-02-24"
P = {"profile_id": "persona_a"}


def _pantry(*rows):
    db = SessionLocal()
    for r in rows:
        db.add(PantryItem(synonyms=[], **r))
    db.commit()
    db.close()


MINE = ("Yogurt greco · Delta", "Musli LIDL", "Mozzarella")


def _stock():
    """(quantità per nome, numero di righe) dei soli prodotti di questi test."""
    db = SessionLocal()
    out, n = {}, 0
    for p in db.query(PantryItem).filter(PantryItem.name.in_(MINE)).all():
        out[p.name] = round(out.get(p.name, 0) + p.quantity, 3)
        n += 1
    db.close()
    return out, n


def _yogurts():
    # 3 vasetti scansionati uno a uno, uno già aperto
    _pantry({"id": "y1", "name": "Yogurt greco · Delta", "quantity": 150, "unit": "g",
             "nutrition": {"kcal": 97, "protein_g": 9, "carbs_g": 4, "fat_g": 5}},
            {"id": "y2", "name": "Yogurt greco · Delta", "quantity": 150, "unit": "g"},
            {"id": "y3", "name": "Yogurt greco · Delta", "quantity": 50, "unit": "g"},
            {"id": "m", "name": "Musli LIDL", "quantity": 500, "unit": "g"})


def test_routine_meal_consumes_once_and_gives_back_when_skipped(client, setup_database):
    _yogurts()
    client.put("/routine/merenda_tardo", json={**P, "name": "Yogurt e musli", "ingredients": [
        {"name": "Yogurt greco · Delta", "grams": 150, "pantry_id": "y2"},
        {"name": "musli lidl", "grams": 40},          # per nome, senza id
        {"name": "Banana", "grams": 70}]})           # non in dispensa: ignorata

    client.get("/routine/", params=P)
    client.get("/routine/", params=P)                # due aperture: si scala una volta sola
    stock, rows = _stock()
    assert stock["Yogurt greco · Delta"] == 200      # 350 - 150
    assert stock["Musli LIDL"] == 460
    assert rows == 3                                  # il vasetto aperto (50 g) è finito ed è sparito

    client.post("/routine/merenda_tardo/skip", params={**P, "meal_date": TODAY})
    client.get("/routine/", params=P)
    stock, rows = _stock()
    assert stock == {"Yogurt greco · Delta": 350, "Musli LIDL": 500}
    assert rows == 4                                  # ricreato

    client.post("/routine/merenda_tardo/skip", params={**P, "meal_date": TODAY})   # ripensamento
    client.get("/routine/", params=P)
    assert _stock()[0]["Yogurt greco · Delta"] == 200


def test_no_backfill_of_past_days(client, setup_database):
    _yogurts()
    client.put("/routine/colazione", json={**P, "name": "Musli", "ingredients": [
        {"name": "Musli LIDL", "grams": 50}]})
    client.get("/routine/", params=P)
    assert _stock()[0]["Musli LIDL"] == 450          # solo oggi, non i giorni prima
    db = SessionLocal()
    assert {u.date for u in db.query(PantryUse).all()} == {TODAY}
    db.close()


def test_extra_from_pantry_consumes_and_delete_gives_back(client, setup_database):
    _yogurts()
    r = client.post("/routine/extra", params={**P, "meal_date": TODAY}, json={
        "name": "Yogurt", "ingredients": [{"name": "Yogurt greco · Delta", "grams": 150, "pantry_id": "y1"}]})
    assert r.status_code == 200, r.text
    assert r.json()["nutrition"]["kcal"] == pytest.approx(97 * 1.5, abs=0.2)
    assert _stock()[0]["Yogurt greco · Delta"] == 200

    client.delete(f"/routine/extra/{r.json()['id']}")
    assert _stock()[0]["Yogurt greco · Delta"] == 350


def test_pieces_count_one_per_use(client, setup_database):
    _pantry({"id": "moz", "name": "Mozzarella", "quantity": 2, "unit": "pz",
             "nutrition": {"kcal": 250, "protein_g": 17, "carbs_g": 1, "fat_g": 20}})
    client.post("/routine/extra", params={**P, "meal_date": TODAY}, json={
        "name": "Mozzarella", "ingredients": [{"name": "Mozzarella", "grams": 125, "pantry_id": "moz"}]})
    assert _stock()[0]["Mozzarella"] == 1
