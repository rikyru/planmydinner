"""Scontrini Lidl Plus -> dispensa: parser, normalizzazione, endpoint."""
import json
import uuid
from types import SimpleNamespace

import pytest

from planmydinner_addon import lidl
from planmydinner_addon.database import (AppSettings, ConsumedEntry, LidlImport, PantryItem,
                                         ReceiptProductLink)
from planmydinner_addon.known_products import collect_known_products
from planmydinner_addon.llm_gateway import LLMGateway
from planmydinner_addon.main import app

# Righe come nello scontrino HTML vero di Lidl Italia: l'articolo in 2 pezzi ha
# una seconda riga "Cad ... Pz. 2" con gli STESSI attributi.
HTML = """
<span id="purchase_list_line_2" class="article" data-art-id="0069948" data-unit-price="4,49" data-tax-type="10%" data-art-description="MSC FIL.MERL.IN PORZ">MSC FIL.MERL.IN PORZ     10%       4,49</span>
<span id="purchase_list_line_10" class="article" data-art-id="6014905" data-unit-price="1,29" data-art-quantity="2" data-art-description="YOMO DELT.YOG.GR.MIR">YOMO DELT.YOG.GR.MIR     10%       2,58</span>
<span id="purchase_list_line_11" class="article" data-art-id="6014905" data-unit-price="1,29" data-art-quantity="2" data-art-description="YOMO DELT.YOG.GR.MIR">Cad 1,29 Pz. 2            </span>
<span id="purchase_list_line_12" class="article" data-art-id="0001" data-unit-price="2,99" data-art-quantity="0,532" data-art-description="MELE GOLDEN">MELE GOLDEN       4%     1,59</span>
<span id="purchase_list_line_13" class="article" data-art-id="0001" data-unit-price="2,99" data-art-quantity="0,532" data-art-description="MELE GOLDEN">kg 0,532 x 2,99 EUR/kg</span>
<span class="discount">Sconto -0,61</span>
"""


def test_parser_counts_multi_piece_articles_once():
    items = lidl.parse_html_receipt(HTML)
    assert [i["name"] for i in items] == ["MSC FIL.MERL.IN PORZ", "YOMO DELT.YOG.GR.MIR", "MELE GOLDEN"]
    yog = items[1]
    assert yog["quantity"] == 2 and yog["unit_price"] == 1.29 and yog["weight_kg"] is None
    mele = items[2]
    assert mele["weight_kg"] == pytest.approx(0.532) and mele["quantity"] == 1


class _FakeOpenAI:
    """Risposta LLM volutamente imprecisa: count sbagliato, kg, categoria inventata."""
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        self.last_user = kwargs["messages"][-1]["content"]
        msg = SimpleNamespace(content=json.dumps(self.payload))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _gateway(tmp_path, monkeypatch, payload):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    gw = LLMGateway(provider="openai", api_key="x", model="m")
    gw._client = _FakeOpenAI(payload)
    return gw


def test_normalize_trusts_receipt_for_pieces_and_weight(tmp_path, monkeypatch):
    raw = lidl.parse_html_receipt(HTML)
    gw = _gateway(tmp_path, monkeypatch, {"pantry_items": [
        {"source": 0, "name": "Filetti di merluzzo", "quantity": 0.4, "unit": "kg", "count": 1,
         "category": "proteine", "expiration_date": "2027-05-20", "synonyms": [], "known": 7,
         "per_100g": {"kcal": 82, "protein_g": 17.8, "carbs_g": 0, "fat_g": 0.9}},
        {"source": 1, "name": "Yogurt greco Yomo Delta ai mirtilli", "quantity": 150, "unit": "g",
         "count": 1, "category": "latticini", "expiration_date": "2026-12-06", "known": 0,
         "per_100g": {"kcal": 70, "protein_g": 8, "carbs_g": 8.5, "fat_g": 0.1}},
        {"source": 2, "name": "Mele golden", "quantity": 1, "unit": "pz", "count": 3,
         "category": "frutto", "expiration_date": "boh", "known": None, "per_100g": {"kcal": "?"}},
    ]})
    out = gw.normalize_lidl_receipt(raw, "2026-11-21", ["Yogurt greco mirtillo · Delta"])
    merluzzo, yogurt, mele = out
    assert merluzzo["known_product"] is None                              # indice fuori elenco
    assert yogurt["known_product"] == 0 and yogurt["receipt_name"] == "YOMO DELT.YOG.GR.MIR"
    assert yogurt["estimated_nutrition"]["fat_g"] == 0.1
    assert mele["estimated_nutrition"] is None                             # stima malformata
    assert "Yogurt greco mirtillo · Delta" in gw._client.last_user        # l'AI vede i prodotti noti
    assert (merluzzo["quantity"], merluzzo["unit"]) == (400, "g")          # kg -> g
    assert merluzzo["synonyms"] == ["MSC FIL.MERL.IN PORZ"]                # voce originale sempre
    assert yogurt["count"] == 2                                            # i pezzi li dice lo scontrino
    assert (mele["quantity"], mele["unit"], mele["count"]) == (532, "g", 1)  # pesato alla cassa
    assert mele["category"] == "altro"                                     # categoria fuori lista
    # seconda volta: cache, l'LLM non viene richiamato
    assert gw.normalize_lidl_receipt(raw, "2026-11-21", ["Yogurt greco mirtillo · Delta"]) == out
    assert gw._client.calls == 1
    # un prodotto scansionato in più cambia la risposta possibile: niente cache
    gw.normalize_lidl_receipt(raw, "2026-11-21", ["Yogurt greco mirtillo · Delta", "Skyr"])
    assert gw._client.calls == 2


# --- endpoint ---------------------------------------------------------------

class _FakeGateway:
    def __init__(self, items):
        self.items = items
        self.known_seen = None

    def normalize_lidl_receipt(self, raw_items, receipt_date, known_products=None):
        self.known_seen = known_products
        return [dict(i) for i in self.items]


@pytest.fixture
def lidl_api(monkeypatch, db_session_for_lidl):
    """Lidl Plus finto: 2 scontrini, il token ruota a ogni rinnovo."""
    state = {"refresh_calls": [], "n": 0}

    def refresh(token):
        state["refresh_calls"].append(token)
        state["n"] += 1
        return "access", f"rotated-{state['n']}"

    tickets = [{"id": "OLD", "date": "2026-11-10T10:00:00", "totalAmount": 12.0},
               {"id": "NEW", "date": "2026-11-21T12:28:05", "totalAmount": 43.74}]
    monkeypatch.setattr(lidl, "refresh_access_token", refresh)
    monkeypatch.setattr(lidl, "list_tickets", lambda access: tickets)
    monkeypatch.setattr(lidl, "get_ticket",
                        lambda tid, access: {"id": tid, "date": "2026-11-21T12:28:05",
                                             "htmlPrintedReceipt": HTML})
    monkeypatch.setenv("LIDL_REFRESH_TOKEN", "from-env")
    original = getattr(app.state, "llm_gateway", None)
    state["gw"] = _FakeGateway([
        {"name": "Yogurt greco", "quantity": 150, "unit": "g", "count": 2, "category": "latticini",
         "expiration_date": "2026-12-06", "synonyms": ["YOMO DELT.YOG.GR.MIR"],
         "receipt_name": "YOMO DELT.YOG.GR.MIR", "known_product": None,
         "estimated_nutrition": {"kcal": 75, "protein_g": 8, "carbs_g": 9, "fat_g": 0.2}}])
    app.state.llm_gateway = state["gw"]
    yield state
    app.state.llm_gateway = original


@pytest.fixture
def db_session_for_lidl(setup_database):
    db = setup_database
    db.query(LidlImport).delete()
    db.query(ReceiptProductLink).delete()
    db.query(AppSettings).delete()
    db.commit()
    return db


# Lo Yomo Delta ai mirtilli scansionato col barcode e mangiato come merenda:
# vive solo nello Storico (la confezione non è più in dispensa).
DELTA = {"kcal": 68.0, "protein_g": 7.7, "carbs_g": 8.4, "fat_g": 0.1}


def _eaten_delta(db):
    db.add(ConsumedEntry(
        id=str(uuid.uuid4()), profile_id="aa", date="2026-10-28", meal_type="extra_snack",
        type="extra", override_details={
            "free_text_name": "Yogurt greco mirtillo · Delta",
            "ingredients": [{"name": "Yogurt greco mirtillo · Delta", "qty": 150, "unit": "g",
                             "per_100g": DELTA,
                             "pantry_used": [{"name": "Yogurt greco mirtillo · Delta",
                                              "barcode": "5201037700000"}]}]}))
    db.commit()


def test_known_products_come_from_pantry_and_history(db_session_for_lidl):
    db = db_session_for_lidl
    _eaten_delta(db)
    db.add(PantryItem(id=str(uuid.uuid4()), name="Skyr · Lidl", quantity=1, unit="pz",
                      nutrition={"kcal": 63, "protein_g": 11, "carbs_g": 4, "fat_g": 0.2},
                      barcode="4056489000000", synonyms=[]))
    db.add(PantryItem(id=str(uuid.uuid4()), name="skyr lidl", quantity=1, unit="pz",   # doppione
                      nutrition={"kcal": 63, "protein_g": 11, "carbs_g": 4, "fat_g": 0.2}, synonyms=[]))
    db.commit()
    known = {k["name"]: k for k in collect_known_products(db)}
    assert known["Yogurt greco mirtillo · Delta"]["nutrition"] == DELTA
    assert known["Yogurt greco mirtillo · Delta"]["barcode"] == "5201037700000"
    assert "Skyr · Lidl" in known and "skyr lidl" not in known
    assert not any(k["nutrition"] is None for k in known.values())   # senza valori: esclusi


def test_ai_recognised_scanned_product_gets_label_values(client, lidl_api, db_session_for_lidl):
    db = db_session_for_lidl
    _eaten_delta(db)
    known = collect_known_products(db)
    idx = [k["name"] for k in known].index("Yogurt greco mirtillo · Delta")
    lidl_api["gw"].items[0]["known_product"] = idx
    d = client.post("/pantry/sync-lidl").json()
    assert "Yogurt greco mirtillo · Delta" in lidl_api["gw"].known_seen   # l'AI li ha ricevuti
    it = d["items"][0]
    assert it["match"] == idx and it["match_from"] == "ai"
    assert it["name"] == "Yogurt greco mirtillo · Delta"
    assert it["nutrition"]["fat_g"] == 0.1 and it["nutrition"]["source"] == "etichetta"
    assert it["ai_nutrition"]["kcal"] == 75          # la stima resta, per poterci tornare


def test_unknown_product_gets_ai_estimate_not_nothing(client, lidl_api, db_session_for_lidl):
    it = client.post("/pantry/sync-lidl").json()["items"][0]
    assert it["match"] is None
    assert it["nutrition"] == {"kcal": 75, "protein_g": 8, "carbs_g": 9, "fat_g": 0.2, "source": "stima"}


def _confirm(client, tid, **item):
    body = {"name": "Yogurt greco mirtillo · Delta", "quantity": 150, "unit": "g", "count": 1,
            "receipt_name": "YOMO DELT.YOG.GR.MIR", "nutrition": dict(DELTA, source="etichetta"),
            "barcode": "5201037700000", "linked": True}
    body.update(item)
    return client.post("/pantry/sync-lidl/confirm", json={"ticket_id": tid, "items": [body]})


def test_confirmed_link_is_remembered_for_next_receipt(client, lidl_api, db_session_for_lidl):
    db = db_session_for_lidl
    assert _confirm(client, "NEW").status_code == 200
    db.expire_all()
    row = db.query(PantryItem).filter(PantryItem.name == "Yogurt greco mirtillo · Delta").one()
    assert row.nutrition["fat_g"] == 0.1 and row.barcode == "5201037700000"
    # scontrino successivo: l'AI non lo riconosce (known None) ma l'abbinamento c'è
    it = client.post("/pantry/sync-lidl").json()["items"][0]
    assert it["match_from"] == "ricordato"
    assert it["nutrition"]["kcal"] == 68 and it["name"] == "Yogurt greco mirtillo · Delta"


def test_choosing_estimate_forgets_the_link(client, lidl_api, db_session_for_lidl):
    db = db_session_for_lidl
    _confirm(client, "NEW")
    _confirm(client, "OLD", name="Yogurt greco Yomo Delta ai mirtilli", barcode=None, linked=False,
             nutrition={"kcal": 75, "protein_g": 8, "carbs_g": 9, "fat_g": 0.2, "source": "stima"})
    db.expire_all()
    assert db.query(ReceiptProductLink).count() == 0


def test_preview_writes_nothing_and_saves_rotated_token(client, lidl_api, db_session_for_lidl):
    db = db_session_for_lidl
    before = db.query(PantryItem).count()
    r = client.post("/pantry/sync-lidl")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ticket"]["id"] == "NEW"                     # il più recente per primo
    assert [t["id"] for t in d["pending"]] == ["OLD"]
    assert d["items"][0]["name"] == "Yogurt greco"
    db.expire_all()
    assert db.query(PantryItem).count() == before
    assert db.query(AppSettings).first().lidl_refresh_token == "rotated-1"
    # il rinnovo successivo usa il token ruotato, non quello (ormai morto) dell'env
    client.post("/pantry/sync-lidl")
    assert lidl_api["refresh_calls"] == ["from-env", "rotated-1"]


def test_confirm_one_row_per_package_then_not_proposed_again(client, lidl_api, db_session_for_lidl):
    db = db_session_for_lidl
    before = db.query(PantryItem).count()
    body = {"ticket_id": "NEW", "receipt_date": "2026-11-21", "total_amount": 43.74,
            "items": [{"name": "Yogurt greco", "quantity": 150, "unit": "g", "count": 2,
                       "category": "latticini", "expiration_date": "2026-12-06",
                       "synonyms": ["YOMO DELT.YOG.GR.MIR"]}]}
    r = client.post("/pantry/sync-lidl/confirm", json=body)
    assert r.status_code == 200 and r.json()["created"] == 2
    db.expire_all()
    rows = db.query(PantryItem).filter(PantryItem.name == "Yogurt greco").all()
    assert len(rows) == 2 and all(p.quantity == 150 and p.unit == "g" for p in rows)
    assert db.query(PantryItem).count() == before + 2
    # due volte lo stesso scontrino: rifiutato, niente doppioni
    assert client.post("/pantry/sync-lidl/confirm", json=body).status_code == 409
    assert db.query(PantryItem).count() == before + 2
    # la prossima sincronizzazione propone l'altro
    d = client.post("/pantry/sync-lidl").json()
    assert d["ticket"]["id"] == "OLD" and d["pending"] == []


def test_skip_then_nothing_left(client, lidl_api, db_session_for_lidl):
    for tid in ("NEW", "OLD"):
        assert client.post("/pantry/sync-lidl/skip", json={"ticket_id": tid}).status_code == 200
    d = client.post("/pantry/sync-lidl").json()
    assert d["ticket"] is None


def test_missing_token_asks_to_connect(client, monkeypatch, db_session_for_lidl):
    monkeypatch.delenv("LIDL_REFRESH_TOKEN", raising=False)
    r = client.post("/pantry/sync-lidl")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "lidl_not_configured"
    assert client.post("/pantry/lidl/token", json={"refresh_token": " abc "}).status_code == 200
    assert client.get("/pantry/lidl/status").json()["configured"] is True


def test_expired_token_is_reported_as_auth_error(client, monkeypatch, db_session_for_lidl):
    def boom(token):
        raise lidl.LidlAuthError("Token Lidl Plus non valido")
    monkeypatch.setattr(lidl, "refresh_access_token", boom)
    monkeypatch.setenv("LIDL_REFRESH_TOKEN", "dead")
    r = client.post("/pantry/sync-lidl")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "lidl_auth"
