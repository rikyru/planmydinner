"""Fallback LLM per ingredienti non in tabella (prima mancava del metodo)."""
from unittest.mock import MagicMock

from planmydinner_addon import nutrition
from planmydinner_addon.llm_gateway import LLMGateway


def _gateway_with_response(content: str, tmp_path, monkeypatch) -> LLMGateway:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))  # cache su disco isolata
    gw = LLMGateway(provider="openai", api_key="x", base_url="http://x", model="m")
    gw._client = MagicMock()
    gw._client.chat.completions.create.return_value.choices[0].message.content = content
    return gw


def test_estimate_nutrition_parses_and_caches(tmp_path, monkeypatch):
    gw = _gateway_with_response(
        '{"kcal":250,"protein_g":10,"carbs_g":30,"fat_g":8}', tmp_path, monkeypatch)
    r = gw.estimate_nutrition("Ingrediente sconosciuto")
    assert r == {"kcal": 250.0, "protein_g": 10.0, "carbs_g": 30.0, "fat_g": 8.0}
    # seconda chiamata servita dalla cache: nessuna nuova call all'LLM
    gw._client.chat.completions.create.reset_mock()
    again = gw.estimate_nutrition("Ingrediente sconosciuto")
    assert again == r
    assert gw._client.chat.completions.create.call_count == 0


def test_estimate_nutrition_rejects_implausible_kcal(tmp_path, monkeypatch):
    gw = _gateway_with_response(
        '{"kcal":5000,"protein_g":1,"carbs_g":1,"fat_g":1}', tmp_path, monkeypatch)
    assert gw.estimate_nutrition("Roba assurda") is None


def test_estimate_nutrition_without_client_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    gw = LLMGateway(provider="none")  # provider non supportato -> nessun client
    assert gw._client is None
    assert gw.estimate_nutrition("Qualcosa") is None


def test_resolve_ingredient_uses_llm_when_not_in_table():
    """Il percorso prima morto (estimate_nutrition assente) ora riempie i buchi."""
    fake = MagicMock()
    fake.estimate_nutrition.return_value = {
        "kcal": 200, "protein_g": 5, "carbs_g": 40, "fat_g": 2}
    res = nutrition.resolve_ingredient_nutrition(
        {"name": "IngredienteFuoriTabella"}, llm_gateway=fake)
    assert res is not None
    assert res["source"] == "llm"
    assert res["kcal"] == 200
    fake.estimate_nutrition.assert_called_once()
