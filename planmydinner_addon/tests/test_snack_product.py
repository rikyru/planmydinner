"""Merende extra da snack confezionato: codice a barre (Open Food Facts) o foto."""
import pytest

from planmydinner_addon.api import routine as routine_api

TODAY = "2026-02-24"

_OFF = {"found": True, "barcode": "8000500310427", "name": "Kinder Bueno", "brands": "Ferrero",
        "quantity_text": "43 g", "nutrition": {"kcal": 572, "protein_g": 8.6, "carbs_g": 49.5, "fat_g": 37.3}}


@pytest.mark.parametrize("text,grams", [("45 g", 45), ("0,33 l", 330), ("6 x 25 g", 25),
                                        ("1 kg", 1000), ("pz", None), ("", None)])
def test_pack_grams(text, grams):
    assert routine_api.pack_grams(text) == grams


def test_product_by_barcode(client, setup_database, monkeypatch):
    monkeypatch.setattr(routine_api, "lookup_barcode",
                        lambda code: _OFF if code == _OFF["barcode"] else {"found": False, "barcode": code})
    p = client.get("/routine/product/8000500310427").json()
    assert p["found"] and p["source"] == "barcode"
    assert p["name"] == "Kinder Bueno · Ferrero" and p["grams"] == 43
    assert p["nutrition"]["fat_g"] == 37.3
    assert client.get("/routine/product/123456789").json()["found"] is False


class _FakeGw:
    _client = object()

    def __init__(self, guess):
        self.guess = guess

    def identify_product_from_photo(self, b64, mime):
        return self.guess


def _photo(client):
    return client.post("/routine/product-photo", files={"file": ("snack.jpg", b"\xff\xd8fake", "image/jpeg")})


def test_photo_with_readable_barcode_uses_open_food_facts(client, setup_database, monkeypatch):
    monkeypatch.setattr(routine_api, "lookup_barcode", lambda code: _OFF)
    monkeypatch.setattr(client.app.state, "llm_gateway", _FakeGw({"barcode": _OFF["barcode"], "name": "Bueno", "brand": "",
                                            "net_grams": None, "per_100g": None, "from_label": False}), raising=False)
    p = _photo(client).json()
    assert p["source"] == "barcode" and p["nutrition"]["kcal"] == 572 and p["grams"] == 43


def test_photo_without_barcode_uses_label_or_estimate(client, setup_database, monkeypatch):
    monkeypatch.setattr(routine_api, "lookup_barcode", lambda code: pytest.fail("niente codice da cercare"))
    monkeypatch.setattr(client.app.state, "llm_gateway", _FakeGw({"barcode": None, "name": "Crackers", "brand": "Mulino",
                                            "net_grams": 30.0, "from_label": True,
                                            "per_100g": {"kcal": 430, "protein_g": 10, "carbs_g": 70, "fat_g": 11}}), raising=False)
    p = _photo(client).json()
    assert p["found"] and p["source"] == "etichetta"
    assert p["name"] == "Crackers · Mulino" and p["grams"] == 30 and p["nutrition"]["fat_g"] == 11


def test_extra_with_scanned_values(client, setup_database):
    # valori per 100 g del prodotto scansionato, senza passare dalla dispensa
    r = client.post("/routine/extra", params={"profile_id": "persona_a", "meal_date": TODAY},
                    json={"name": "Kinder Bueno", "ingredients": [
                        {"name": "Kinder Bueno · Ferrero", "grams": 43, "per_100g": _OFF["nutrition"]}]})
    assert r.status_code == 200, r.text
    n = r.json()["nutrition"]
    assert n["kcal"] == pytest.approx(572 * 0.43, abs=0.2)
    assert n["fat_g"] == pytest.approx(37.3 * 0.43, abs=0.1)
