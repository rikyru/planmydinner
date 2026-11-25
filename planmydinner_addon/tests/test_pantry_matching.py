"""Quando un ingrediente "è" un prodotto della dispensa, e cosa ne segue:
suggerimenti per i prodotti in scadenza, spesa già mangiata, barcode che
corregge una stima."""
import uuid
from datetime import date, timedelta

import pytest

from planmydinner_addon.api import pantry as pantry_api
from planmydinner_addon.database import ConsumedEntry, PantryItem, ReceiptProductLink, Recipe
from planmydinner_addon.pantry_use import same_food
from planmydinner_addon.planner import PlannerEngine

TODAY = date(2026, 2, 24)   # freeze_time in conftest
POLPO = "Tentacoli Di Polpo · Gastronomia Di Mare by Lidl"


@pytest.mark.parametrize("ingredient,pantry,expected", [
    # il bug: "di" in comune bastava
    ("petto di pollo", POLPO, False),
    ("Pesto di zucchine", POLPO, False),
    ("polpo", POLPO, True),
    ("tentacoli di polpo", POLPO, True),
    # i gusti dopo "al"/"a base di" non sono il cibo
    ("latte", "Cioccolato al latte", False),
    ("mandorle", "Bevanda biologica a base di mandorla", False),
    # tagli, singolare/plurale, marchio
    ("merluzzo", "Filetti di merluzzo MSC in porzioni", True),
    ("filetti di tonno", "Filetti di merluzzo MSC in porzioni", False),
    ("zucchina", "Zucchine", True),
    ("Pesto di zucchine", "Zucchine", True),
    ("yogurt", "Delta yogurt greco autentico · Delta", True),
    ("mozzarella", "mozzarella di bufala", True),
    ("pane", "Panettone", False),
])
def test_same_food(ingredient, pantry, expected):
    assert same_food(ingredient, pantry) is expected


def test_planner_pantry_bonus_uses_the_same_rule():
    item = type("P", (), {"name": POLPO})()
    assert PlannerEngine._pantry_matches("polpo", [item])
    assert not PlannerEngine._pantry_matches("Pesto di zucchine", [item])


def _add(db, name, days, **kw):
    db.add(PantryItem(id=str(uuid.uuid4()), name=name, quantity=kw.pop("quantity", 100), unit="g",
                      expiration_date=(TODAY + timedelta(days=days)).isoformat(), synonyms=[], **kw))


def _recipe(db, rid, name, ingredients):
    db.add(Recipe(id=rid, name=name, description="", is_composed_dish=False, steps=[],
                  content=[{"name": n, "food_group": "altro",
                            "quantities": {"persona_a": {"qty": 100, "unit": "g", "grams_equiv": 100}}}
                           for n in ingredients],
                  total_time_minutes=10, difficulty="facile", tags={}))


def test_expiring_recipes_no_longer_put_octopus_everywhere(client, setup_database):
    db = setup_database
    _recipe(db, "pesto_zucchine", "Pasta al pesto di zucchine", ["Pasta", "Pesto di zucchine"])
    _recipe(db, "polpo_patate", "Polpo e patate", ["Polpo", "Patate"])
    _add(db, POLPO, 1)
    db.commit()
    recipes = {r["name"]: r["uses"] for r in client.get("/pantry/expiring-recipes").json()["recipes"]}
    assert recipes.get("Polpo e patate") == [POLPO]
    assert "Pasta al pesto di zucchine" not in recipes


def test_expiring_recipes_rank_by_urgency_and_skip_expired(client, setup_database):
    db = setup_database
    _recipe(db, "polpo_patate", "Polpo e patate", ["Polpo", "Patate"])
    _recipe(db, "zucchine_trifolate", "Zucchine trifolate", ["Zucchine"])
    _add(db, "Zucchine", 0)          # scadono oggi
    _add(db, "Patate", 5)
    _add(db, POLPO, -1)              # scaduto ieri: niente ricette, va controllato
    _add(db, "Zucchine", 2)          # seconda confezione
    db.commit()
    d = client.get("/pantry/expiring-recipes").json()
    names = [r["name"] for r in d["recipes"]]
    assert names.index("Zucchine trifolate") < names.index("Polpo e patate")   # oggi prima di 5 giorni
    polpo = next(r for r in d["recipes"] if r["name"] == "Polpo e patate")
    assert polpo["uses"] == ["Patate"]                                         # lo scaduto non conta
    zucchine = next(e for e in d["expiring"] if e["name"] == "Zucchine")
    assert zucchine["count"] == 2 and zucchine["days"] == 0                    # una voce per prodotto
    assert next(e for e in d["expiring"] if e["name"] == POLPO)["days"] == -1


def test_meals_eaten_after_the_receipt_are_found(setup_database):
    db = setup_database
    _recipe(db, "polpo_hummus", "Tentacoli di polpo su hummus", ["Tentacoli di polpo", "Hummus"])
    for pid in ("aa", "bb"):         # stesso pranzo per i due profili: una volta sola
        db.add(ConsumedEntry(id=str(uuid.uuid4()), profile_id=pid, date="2026-02-22",
                             meal_type="pranzo", type="planned", consumed_recipe_id="polpo_hummus"))
    db.add(ConsumedEntry(id=str(uuid.uuid4()), profile_id="aa", date="2026-02-20",   # prima della spesa
                         meal_type="cena", type="planned", consumed_recipe_id="polpo_hummus"))
    db.commit()
    meals = pantry_api._meals_since(db, "2026-02-21")
    item = {"name": "Tentacoli di polpo", "ai_name": "Tentacoli di polpo"}
    found, grams = pantry_api._eaten_in(meals, item)
    assert found == [{"date": "2026-02-22", "meal_type": "pranzo", "name": "Tentacoli di polpo su hummus"}]
    assert grams == 200                       # 100 g a testa, due profili; la cena del 20 non conta
    assert pantry_api._eaten_in(meals, {"name": "Zucchine"}) == ([], 0)
    assert pantry_api._meals_since(db, TODAY.isoformat()) == []    # scontrino di oggi: niente


def test_preview_unticks_only_what_was_finished(client, setup_database, monkeypatch):
    """Polpo 250 g finito (mangiati 200+): fuori. Zucchine 750 g, usati 200: dentro."""
    from planmydinner_addon import lidl
    from planmydinner_addon.main import app
    db = setup_database
    _recipe(db, "polpo_zucchine", "Polpo e zucchine", ["Tentacoli di polpo", "Zucchine"])
    for pid in ("aa", "bb"):
        db.add(ConsumedEntry(id=str(uuid.uuid4()), profile_id=pid, date="2026-02-22",
                             meal_type="pranzo", type="planned", consumed_recipe_id="polpo_zucchine"))
    db.commit()
    monkeypatch.setenv("LIDL_REFRESH_TOKEN", "t")
    monkeypatch.setattr(lidl, "refresh_access_token", lambda t: ("a", "t"))
    monkeypatch.setattr(lidl, "list_tickets", lambda a: [{"id": "T", "date": "2026-02-21T10:00:00"}])
    monkeypatch.setattr(lidl, "get_ticket", lambda tid, a: {"date": "2026-02-21T10:00:00",
                                                            "htmlPrintedReceipt": ""})

    class GW:
        def normalize_lidl_receipt(self, raw, d, known=None):
            return [{"name": n, "quantity": q, "unit": "g", "count": 1, "category": "altro",
                     "synonyms": [], "receipt_name": n.upper(), "known_product": None,
                     "estimated_nutrition": None} for n, q in (("Tentacoli di polpo", 250),
                                                               ("Zucchine", 750))]
    monkeypatch.setattr(app.state, "llm_gateway", GW())
    items = {i["name"]: i for i in client.post("/pantry/sync-lidl").json()["items"]}
    assert items["Tentacoli di polpo"]["eaten_all"] is True
    assert items["Zucchine"]["eaten_all"] is False and items["Zucchine"]["eaten_grams"] == 200


DELTA_CAFFE = {"kcal": 70.0, "protein_g": 7.5, "carbs_g": 9.0, "fat_g": 0.1}


def test_barcode_finds_estimated_product_and_updates_it(client, setup_database, monkeypatch):
    db = setup_database
    est = {"kcal": 105, "protein_g": 6.5, "carbs_g": 14, "fat_g": 2.8, "source": "stima"}
    for _ in range(2):
        db.add(PantryItem(id=str(uuid.uuid4()), name="Yogurt greco Yomo Delta al caffè", quantity=150,
                          unit="g", nutrition=est, synonyms=["YOMO DELT.YOG.GR.CAF", "Yogurt greco"]))
    db.add(PantryItem(id=str(uuid.uuid4()), name="Yogurt greco mirtillo · Delta", quantity=150, unit="g",
                      synonyms=[], nutrition={"kcal": 68, "protein_g": 7.7, "carbs_g": 8.4,
                                              "fat_g": 0.1, "source": "etichetta"}))
    db.commit()
    monkeypatch.setattr(pantry_api, "lookup_barcode", lambda code: {
        "found": True, "barcode": code, "name": "Yogurt greco caffè", "brands": "Delta",
        "nutrition": DELTA_CAFFE})
    res = client.get("/pantry/barcode/5201037799999").json()
    matches = res["estimated_matches"]
    assert [(m["name"], m["count"]) for m in matches] == [("Yogurt greco Yomo Delta al caffè", 2)]

    r = client.post(f"/pantry/items/{matches[0]['id']}/label-values",
                    json={"nutrition": DELTA_CAFFE, "barcode": "5201037799999",
                          "name": "Yogurt greco caffè · Delta"})
    assert r.status_code == 200 and r.json()["updated"] == 2
    db.expire_all()
    rows = db.query(PantryItem).filter(PantryItem.name == "Yogurt greco caffè · Delta").all()
    assert len(rows) == 2
    assert all(p.nutrition["fat_g"] == 0.1 and p.nutrition["source"] == "etichetta"
               and p.barcode == "5201037799999" for p in rows)
    # il prossimo scontrino con "YOMO DELT.YOG.GR.CAF" prende questi valori
    link = db.query(ReceiptProductLink).filter_by(receipt_name="YOMO DELT.YOG.GR.CAF").one()
    assert link.product_name == "Yogurt greco caffè · Delta" and link.nutrition["kcal"] == 70
    # ora ha l'etichetta: una nuova scansione non lo propone più
    assert client.get("/pantry/barcode/5201037799999").json()["estimated_matches"] == []
