"""Modelli che accettano solo la temperatura di default (gpt-5.x / reasoning).

Caso reale: 'Cioccolata fondente 72%' non è nella tabella locale, la stima LLM
passava temperature=0.1, il modello rispondeva HTTP 400 e l'alimento restava
senza valori (0 kcal)."""
import pytest

from planmydinner_addon.llm_gateway import LLMGateway

TEMP_ERROR = ("Error code: 400 - Unsupported value: 'temperature' does not support 0.1 "
              "with this model. Only the default (1) value is supported.")


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    """Finto client OpenAI: rifiuta `temperature` come gpt-5.x."""
    def __init__(self, error=TEMP_ERROR):
        self.calls, self.error = [], error

    def create(self, **kw):
        self.calls.append(dict(kw))
        if self.error and "temperature" in kw:
            raise Exception(self.error)
        return _Resp('{"kcal": 560, "protein_g": 8, "carbs_g": 33, "fat_g": 42}')


def _gateway(tmp_path, monkeypatch, completions):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))          # cache LLM isolata
    gw = LLMGateway(provider="openai", api_key="test", model="gpt-5.5")
    chat = type("Chat", (), {})()
    chat.completions = completions
    gw._client = type("Client", (), {})()
    gw._client.chat = chat
    return gw


def test_nutrition_estimate_works_on_model_without_temperature(tmp_path, monkeypatch):
    fake = _Completions()
    gw = _gateway(tmp_path, monkeypatch, fake)
    v = gw.estimate_nutrition("Cioccolata fondente 72%")
    assert v == {"kcal": 560.0, "protein_g": 8.0, "carbs_g": 33.0, "fat_g": 42.0}
    assert "temperature" in fake.calls[0] and "temperature" not in fake.calls[1]
    # dalla chiamata successiva la temperatura non viene più passata: niente 400 a vuoto
    gw.estimate_nutrition("Macinato")
    assert len(fake.calls) == 3 and "temperature" not in fake.calls[2]


def test_models_with_temperature_unchanged(tmp_path, monkeypatch):
    fake = _Completions(error=None)                         # es. gpt-4o: accetta temperature
    gw = _gateway(tmp_path, monkeypatch, fake)
    gw.estimate_nutrition("Cioccolata fondente 72%")
    assert len(fake.calls) == 1 and fake.calls[0]["temperature"] == 0.1


def test_other_errors_are_not_swallowed(tmp_path, monkeypatch):
    fake = _Completions(error="Error code: 401 - invalid api key")
    gw = _gateway(tmp_path, monkeypatch, fake)
    with pytest.raises(Exception, match="401"):
        gw._chat_create(model="gpt-5.5", messages=[], temperature=0.1)
    assert len(fake.calls) == 1                             # nessun retry su errori diversi
