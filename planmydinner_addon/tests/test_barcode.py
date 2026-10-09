"""Lookup barcode (Open Food Facts) per popolare la dispensa."""
import io
import json

from planmydinner_addon import barcode as bc


class _FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _patch_off(monkeypatch, payload):
    def fake_urlopen(req, timeout=8):
        return _FakeResp(json.dumps(payload).encode("utf-8"))
    monkeypatch.setattr(bc.urllib.request, "urlopen", fake_urlopen)


def test_lookup_parses_product_and_nutrition(monkeypatch):
    _patch_off(monkeypatch, {"status": 1, "product": {
        "product_name_it": "Fagioli cannellini", "brands": "Valfrutta",
        "quantity": "400 g",
        "nutriments": {"energy-kcal_100g": 91, "proteins_100g": 6.6,
                       "carbohydrates_100g": 12.0, "fat_100g": 0.5},
        "image_front_small_url": "http://x/img.jpg",
        "ingredients_text_it": "fagioli, acqua, sale"}})
    r = bc.lookup_barcode("8001080011234")
    assert r["found"] is True
    assert r["name"] == "Fagioli cannellini"
    assert r["nutrition"] == {"kcal": 91.0, "protein_g": 6.6, "carbs_g": 12.0, "fat_g": 0.5}
    assert r["quantity_text"] == "400 g"


def test_lookup_not_found(monkeypatch):
    _patch_off(monkeypatch, {"status": 0})
    r = bc.lookup_barcode("0000000000000")
    assert r["found"] is False


def test_invalid_code_without_network(monkeypatch):
    # un codice non numerico non deve nemmeno chiamare la rete
    def boom(*a, **k):
        raise AssertionError("non deve chiamare la rete")
    monkeypatch.setattr(bc.urllib.request, "urlopen", boom)
    assert bc.lookup_barcode("abc")["found"] is False


def test_endpoint(client, setup_database, monkeypatch):
    _patch_off(monkeypatch, {"status": 1, "product": {
        "product_name": "Tonno", "nutriments": {"energy-kcal_100g": 116, "proteins_100g": 25}}})
    r = client.get("/pantry/barcode/8001080019999")
    assert r.status_code == 200
    assert r.json()["name"] == "Tonno"
    assert r.json()["nutrition"]["protein_g"] == 25.0
