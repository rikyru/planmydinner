"""
Generazione focalizzata sulle cene.

Chi pranza in mensa non vuole che il piano gli riempia i pranzi lavorativi: quegli
slot devono restare vuoti da compilare a mano, e il budget settimanale delle
proteine va distribuito solo sui pasti generati davvero. In compenso il pool da cui
pescare si allarga ai pasti importati da foto (già mangiati e mappati), esclusi
quelli della mensa.
"""
import uuid
from datetime import date, timedelta

import pytest

from planmydinner_addon.database import (
    CandidateRecipe, ConsumedEntry, GeneratedWeeklyPlan, PlanRules, UserProfile,
)
from planmydinner_addon.planner import (
    PlannerEngine, generation_slots_for, photo_meal_plan_eligible,
)

MONDAY = date(2026, 3, 2)  # lunedì (freeze_time in conftest è 2026-02-24)
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
WEEKEND = [5, 6]


def _qty(g):
    return {"qty": float(g), "unit": "g", "grams_equiv": float(g)}


def _recipe(name, protein_name, protein_fg, carb_name="pane"):
    return {
        "name": name,
        "description": "",
        "is_composed_dish": False,
        "content": [
            {"name": carb_name, "food_group": "carboidrati",
             "quantities": {"aa": _qty(80), "bb": _qty(80)}},
            {"name": protein_name, "food_group": protein_fg,
             "quantities": {"aa": _qty(150), "bb": _qty(150)}},
            {"name": "verdure", "food_group": "verdure",
             "quantities": {"aa": _qty(150), "bb": _qty(150)}},
        ],
        "steps": [],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cooking_methods": ["tegame"], "cleanup": ["facile"]},
    }


def _photo_meal(name, protein_name="pollo arrosto", plan_eligible=None, profile="aa"):
    """Pasto importato da foto: CandidateRecipe draft_structured con tag mensa."""
    data = {
        "name": name,
        "description": "Pasto mensa (mappato da foto)",
        "is_composed_dish": False,
        "content": [
            {"name": "pane pita", "food_group": "carboidrato",
             "quantities": {profile: _qty(80)}},
            {"name": protein_name, "food_group": "proteina",
             "quantities": {profile: _qty(150)}},
            {"name": "insalata", "food_group": "verdura",
             "quantities": {profile: _qty(100)}},
        ],
        "steps": [],
        "total_time_minutes": 0,
        "difficulty": "sconosciuto",
        "tags": {"mensa": ["true"]},
    }
    if plan_eligible is not None:
        data["plan_eligible"] = plan_eligible
    return data


def _item(recipe_id, name="Ricetta", food_group="recipe"):
    return {
        "item_name": name, "food_group": food_group, "quantity": 1, "unit": "recipe",
        "is_estimated_unit": False, "alternatives": [], "recipe_id": recipe_id,
    }


def _add_rules(db, generation_slots=None, frequency_targets=None):
    db.add(PlanRules(
        id=str(uuid.uuid4()), profile_id="aa", imported_at="2026-03-01",
        carb_target={"pranzo": 80.0, "cena": 80.0},
        protein_target={"pranzo": 150.0, "cena": 150.0},
        carb_options={"pranzo": ["pane"], "cena": ["pane"]},
        protein_options={"pranzo": ["pollo"], "cena": ["pollo"]},
        frequency_targets=frequency_targets or {
            "carne_bianca": {"min": 0, "max": 2},
            "legumi": {"min": 0, "max": 12},
            "pesce": {"min": 0, "max": 12},
        },
        free_meal_quota=2,
        generation_slots=generation_slots,
    ))
    db.commit()


@pytest.fixture
def dinner_db(setup_database):
    """Profili + pool ampio di ricette; le PlanRules le aggiunge ogni test."""
    db = setup_database
    db.add(UserProfile(id="aa", name="A", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.add(UserProfile(id="bb", name="B", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    ids = {}
    pool = [
        ("pollo1", _recipe("Pollo uno", "pollo uno", "carne_bianca")),
        ("pollo2", _recipe("Pollo due", "pollo due", "carne_bianca")),
        ("legumi1", _recipe("Legumi uno", "ceci", "legumi", carb_name="pane")),
        ("legumi2", _recipe("Legumi due", "lenticchie", "legumi", carb_name="riso")),
        ("legumi3", _recipe("Legumi tre", "fagioli", "legumi", carb_name="farro")),
        ("legumi4", _recipe("Legumi quattro", "piselli", "legumi", carb_name="orzo")),
        ("pesce1", _recipe("Pesce uno", "pesce uno", "pesce", carb_name="pane")),
        ("pesce2", _recipe("Pesce due", "pesce due", "pesce", carb_name="riso")),
        ("pesce3", _recipe("Pesce tre", "pesce tre", "pesce", carb_name="farro")),
        ("pesce4", _recipe("Pesce quattro", "pesce quattro", "pesce", carb_name="orzo")),
    ]
    for key, data in pool:
        cid = str(uuid.uuid4())
        db.add(CandidateRecipe(id=cid, status="approved", recipe_data=data))
        ids[key] = cid
    db.commit()
    return db, ids


def _slots_by_meal(week, meal_type):
    """meal_type -> lista di (data, items) nell'ordine del piano."""
    out = []
    for day in week:
        meal = next((m for m in day.meals if m.meal_type == meal_type), None)
        out.append((day.date, meal.items if meal else None))
    return out


class TestGenerationSlotsConfig:
    def test_default_is_everything(self):
        assert generation_slots_for(None) == {"pranzo": ALL_DAYS, "cena": ALL_DAYS}

    def test_reads_configured_days(self, dinner_db):
        db, _ = dinner_db
        _add_rules(db, generation_slots={"pranzo": WEEKEND, "cena": ALL_DAYS})
        rules = PlannerEngine(db)._get_latest_plan_rules("aa")
        assert generation_slots_for(rules) == {"pranzo": WEEKEND, "cena": ALL_DAYS}

    def test_ignores_out_of_range_and_junk(self, dinner_db):
        db, _ = dinner_db
        _add_rules(db, generation_slots={"pranzo": [1, 9, -3, "lun"], "cena": "tutti"})
        rules = PlannerEngine(db)._get_latest_plan_rules("aa")
        slots = generation_slots_for(rules)
        assert slots["pranzo"] == [1]
        # Valore illeggibile: si torna al default, non a "non generare nulla"
        assert slots["cena"] == ALL_DAYS

    def test_missing_meal_type_defaults_to_all_days(self, dinner_db):
        db, _ = dinner_db
        _add_rules(db, generation_slots={"cena": ALL_DAYS})
        rules = PlannerEngine(db)._get_latest_plan_rules("aa")
        assert generation_slots_for(rules)["pranzo"] == ALL_DAYS


class TestDinnerOnlyGeneration:
    def test_weekday_lunches_stay_empty(self, dinner_db):
        db, ids = dinner_db
        _add_rules(db, generation_slots={"pranzo": WEEKEND, "cena": ALL_DAYS})

        week = PlannerEngine(db).generate_weekly_plan("aa", "bb", MONDAY)

        assert len(week) == 7
        for i, (day_iso, items) in enumerate(_slots_by_meal(week, "pranzo")):
            weekday = (MONDAY + timedelta(days=i)).weekday()
            if weekday in WEEKEND:
                assert items, f"il pranzo del weekend ({day_iso}) doveva essere generato"
            else:
                assert items == [], f"il pranzo di {day_iso} doveva restare vuoto"
        for day_iso, items in _slots_by_meal(week, "cena"):
            assert items, f"la cena di {day_iso} doveva essere generata"

    def test_empty_lunch_slot_is_still_present(self, dinner_db):
        """Lo slot vuoto deve esistere: la UI ci appende sopra la registrazione."""
        db, _ = dinner_db
        _add_rules(db, generation_slots={"pranzo": [], "cena": ALL_DAYS})

        week = PlannerEngine(db).generate_weekly_plan("aa", "bb", MONDAY)
        for day in week:
            assert {m.meal_type for m in day.meals} == {"pranzo", "cena"}

    def test_weekly_protein_budget_spread_over_generated_slots_only(self, dinner_db):
        """Le sole cene: carne_bianca resta entro il max settimanale (2), non 2 ogni
        mezza settimana perché la sequenza è stata calcolata su 14 slot."""
        db, ids = dinner_db
        _add_rules(db, generation_slots={"pranzo": [], "cena": ALL_DAYS})

        planner = PlannerEngine(db)
        week = planner.generate_weekly_plan("aa", "bb", MONDAY)

        cats = []
        for _day_iso, items in _slots_by_meal(week, "cena"):
            assert items
            cats.append(planner._get_main_protein_category(items[0].recipe_id))
        assert cats.count("carne_bianca") <= 2

    def test_dinners_do_not_repeat_the_same_recipe(self, dinner_db):
        db, _ = dinner_db
        _add_rules(db, generation_slots={"pranzo": [], "cena": ALL_DAYS})

        week = PlannerEngine(db).generate_weekly_plan("aa", "bb", MONDAY)
        recipe_ids = [items[0].recipe_id for _d, items in _slots_by_meal(week, "cena") if items]
        assert len(set(recipe_ids)) == len(recipe_ids), "cene ripetute nella stessa settimana"

    def test_locked_lunch_survives_on_a_non_generated_day(self, dinner_db):
        """Il pranzo in mensa già registrato resta nel piano anche se i pranzi
        non vengono generati."""
        db, ids = dinner_db
        _add_rules(db, generation_slots={"pranzo": [], "cena": ALL_DAYS})
        locked = {MONDAY.isoformat(): {"pranzo": _item(ids["pollo1"], "🍱 Insalatona", "mensa")}}

        week = PlannerEngine(db).generate_weekly_plan("aa", "bb", MONDAY, locked_slots=locked)

        monday = next(d for d in week if d.date == MONDAY.isoformat())
        pranzo = next(m for m in monday.meals if m.meal_type == "pranzo")
        assert pranzo.items and pranzo.items[0].item_name == "🍱 Insalatona"

    def test_logged_lunches_consume_the_weekly_budget_before_generation(self, dinner_db):
        """Due pranzi carne_bianca già registrati (di cui uno a fine settimana):
        le cene non devono aggiungerne altri, il massimo è 2."""
        db, ids = dinner_db
        _add_rules(db, generation_slots={"pranzo": [], "cena": ALL_DAYS})
        locked = {
            (MONDAY + timedelta(days=4)).isoformat(): {"pranzo": _item(ids["pollo1"], "🍱 Pollo", "mensa")},
            (MONDAY + timedelta(days=5)).isoformat(): {"pranzo": _item(ids["pollo2"], "🍱 Pollo", "mensa")},
        }

        planner = PlannerEngine(db)
        week = planner.generate_weekly_plan("aa", "bb", MONDAY, locked_slots=locked)

        dinner_cats = [
            planner._get_main_protein_category(items[0].recipe_id)
            for _d, items in _slots_by_meal(week, "cena") if items
        ]
        assert "carne_bianca" not in dinner_cats, (
            "il budget di carne bianca era già speso nei pranzi registrati"
        )

    def test_full_week_is_still_the_default(self, dinner_db):
        """Senza configurazione il comportamento storico non cambia: 14 slot pieni."""
        db, _ = dinner_db
        _add_rules(db)  # generation_slots = None

        week = PlannerEngine(db).generate_weekly_plan("aa", "bb", MONDAY)
        for day in week:
            for meal in day.meals:
                assert meal.items, f"{day.date} {meal.meal_type} vuoto senza configurazione"


class TestPhotoMealsInPool:
    def test_photo_meal_enters_the_planner_pool(self, dinner_db):
        db, _ = dinner_db
        cid = str(uuid.uuid4())
        db.add(CandidateRecipe(id=cid, status="draft_structured",
                               recipe_data=_photo_meal("Hamburger di fassona con verdure")))
        db.commit()

        names = {r.id for r in PlannerEngine(db)._get_all_recipes()}
        assert cid in names

    def test_mensa_named_photo_meal_is_excluded(self, dinner_db):
        db, _ = dinner_db
        cid = str(uuid.uuid4())
        db.add(CandidateRecipe(id=cid, status="draft_structured",
                               recipe_data=_photo_meal("Pasto mensa - frittata")))
        db.commit()

        assert cid not in {r.id for r in PlannerEngine(db)._get_all_recipes()}

    def test_explicit_flag_wins_over_the_name(self, dinner_db):
        db, _ = dinner_db
        forced_in = str(uuid.uuid4())
        forced_out = str(uuid.uuid4())
        db.add(CandidateRecipe(id=forced_in, status="draft_structured",
                               recipe_data=_photo_meal("Caprese mensa", plan_eligible=True)))
        db.add(CandidateRecipe(id=forced_out, status="draft_structured",
                               recipe_data=_photo_meal("Porridge con latte di mandorla", plan_eligible=False)))
        db.commit()

        pool = {r.id for r in PlannerEngine(db)._get_all_recipes()}
        assert forced_in in pool
        assert forced_out not in pool

    def test_quantities_are_mirrored_to_the_other_profile(self, dinner_db):
        """Il pasto nasce con le quantità di chi ha scattato la foto: senza copia
        l'altro profilo resterebbe senza grammature (né macro né lista spesa)."""
        db, _ = dinner_db
        cid = str(uuid.uuid4())
        db.add(CandidateRecipe(id=cid, status="draft_structured",
                               recipe_data=_photo_meal("Piatto misto con pesce", profile="aa")))
        db.commit()

        rec = next(r for r in PlannerEngine(db)._get_all_recipes() if r.id == cid)
        for ing in rec.content:
            assert "bb" in ing.quantities
            assert ing.quantities["bb"].grams_equiv == ing.quantities["aa"].grams_equiv

    def test_photo_meal_can_be_selected_for_dinner(self, dinner_db):
        """Unica fonte di pesce del catalogo: se la generazione lo sceglie, il pasto
        da foto è a tutti gli effetti materiale per il piano."""
        db, ids = dinner_db
        for key in ("pesce1", "pesce2", "pesce3", "pesce4"):
            db.query(CandidateRecipe).filter(CandidateRecipe.id == ids[key]).delete()
        db.commit()
        cid = str(uuid.uuid4())
        db.add(CandidateRecipe(id=cid, status="draft_structured",
                               recipe_data=_photo_meal("Piatto misto con pesce", protein_name="salmone")))
        db.commit()
        _add_rules(db, generation_slots={"pranzo": [], "cena": ALL_DAYS}, frequency_targets={
            "pesce": {"min": 3, "max": 4},
            "legumi": {"min": 0, "max": 3},
            "carne_bianca": {"min": 0, "max": 1},
        })

        week = PlannerEngine(db).generate_weekly_plan("aa", "bb", MONDAY)
        chosen = {items[0].recipe_id for _d, items in _slots_by_meal(week, "cena") if items}
        assert cid in chosen

    def test_photo_meal_named_mensa_never_reaches_dinner(self, dinner_db):
        db, ids = dinner_db
        for key in ("pesce1", "pesce2", "pesce3", "pesce4"):
            db.query(CandidateRecipe).filter(CandidateRecipe.id == ids[key]).delete()
        db.commit()
        cid = str(uuid.uuid4())
        db.add(CandidateRecipe(id=cid, status="draft_structured",
                               recipe_data=_photo_meal("Pasto mensa insalatona", protein_name="salmone")))
        db.commit()
        _add_rules(db, generation_slots={"pranzo": [], "cena": ALL_DAYS}, frequency_targets={
            "pesce": {"min": 3, "max": 4},
            "legumi": {"min": 0, "max": 3},
            "carne_bianca": {"min": 0, "max": 1},
        })

        week = PlannerEngine(db).generate_weekly_plan("aa", "bb", MONDAY)
        chosen = {items[0].recipe_id for _d, items in _slots_by_meal(week, "cena") if items}
        assert cid not in chosen

    def test_eligibility_helper_defaults(self):
        assert photo_meal_plan_eligible({"name": "Piadina con carote"}) is True
        assert photo_meal_plan_eligible({"name": "Pizza e insalata mensa"}) is False
        assert photo_meal_plan_eligible({"name": "Caprese mensa", "plan_eligible": True}) is True
        assert photo_meal_plan_eligible({"name": "Piadina", "plan_eligible": False}) is False


class TestPhotoMealEndpoints:
    def test_list_exposes_plan_eligible(self, client, dinner_db):
        db, _ = dinner_db
        db.add(CandidateRecipe(id=str(uuid.uuid4()), status="draft_structured",
                               recipe_data=_photo_meal("Torta salata zucchine")))
        db.add(CandidateRecipe(id=str(uuid.uuid4()), status="draft_structured",
                               recipe_data=_photo_meal("Pasto mensa - frittata")))
        db.commit()

        resp = client.get("/consumed-entries/mensa", params={"profile_id": "aa"})
        assert resp.status_code == 200
        by_name = {m["name"]: m["plan_eligible"] for m in resp.json()}
        assert by_name["Torta salata zucchine"] is True
        assert by_name["Pasto mensa - frittata"] is False

    def test_put_toggles_plan_eligible(self, client, dinner_db):
        db, _ = dinner_db
        cid = str(uuid.uuid4())
        db.add(CandidateRecipe(id=cid, status="draft_structured",
                               recipe_data=_photo_meal("Cornetto alla crema")))
        db.commit()

        resp = client.put(f"/consumed-entries/mensa/{cid}", json={
            "name": "Cornetto alla crema",
            "ingredients": [{"name": "cornetto", "food_group": "carboidrato", "grams": 60}],
            "plan_eligible": False,
        })
        assert resp.status_code == 200
        assert resp.json()["plan_eligible"] is False

        db.expire_all()
        assert cid not in {r.id for r in PlannerEngine(db)._get_all_recipes()}

    def test_resaving_a_meal_keeps_the_flag(self, client, dinner_db):
        """Registrare di nuovo lo stesso pasto non deve riportarlo nel piano."""
        db, _ = dinner_db
        cid = str(uuid.uuid4())
        db.add(CandidateRecipe(id=cid, status="draft_structured",
                               recipe_data=_photo_meal("Granita e brioche", plan_eligible=False)))
        db.commit()

        resp = client.post("/consumed-entries/mensa", json={
            "profile_id": "aa", "date": MONDAY.isoformat(), "meal_type": "pranzo",
            "name": "Granita e brioche",
            "ingredients": [{"name": "brioche", "food_group": "carboidrato", "grams": 80}],
            "register_consumption": False,
        })
        assert resp.status_code == 200
        assert resp.json()["recipe_id"] == cid

        db.expire_all()
        listed = client.get("/consumed-entries/mensa", params={"profile_id": "aa"}).json()
        assert next(m for m in listed if m["id"] == cid)["plan_eligible"] is False


class TestGenerationSlotsEndpoint:
    def test_put_persists_and_rules_returns_it(self, client, dinner_db):
        db, _ = dinner_db
        _add_rules(db)

        resp = client.put("/planner/generation-slots", params={"profile_id": "aa"},
                          json={"pranzo": WEEKEND, "cena": ALL_DAYS})
        assert resp.status_code == 200
        assert resp.json()["generation_slots"] == {"pranzo": WEEKEND, "cena": ALL_DAYS}

        rules = client.get("/planner/rules", params={"profile_id_A": "aa"}).json()
        assert rules["plan_rules"]["generation_slots"] == {"pranzo": WEEKEND, "cena": ALL_DAYS}

    def test_creates_rules_when_missing(self, client, dinner_db):
        db, _ = dinner_db
        resp = client.put("/planner/generation-slots", params={"profile_id": "senza-regole"},
                          json={"pranzo": [], "cena": ALL_DAYS})
        assert resp.status_code == 200
        assert db.query(PlanRules).filter(PlanRules.profile_id == "senza-regole").first() is not None

    def test_rejects_invalid_days(self, client, dinner_db):
        db, _ = dinner_db
        _add_rules(db)
        resp = client.put("/planner/generation-slots", params={"profile_id": "aa"},
                          json={"pranzo": [0, 7], "cena": ALL_DAYS})
        assert resp.status_code == 422

    def test_rejects_generating_nothing(self, client, dinner_db):
        db, _ = dinner_db
        _add_rules(db)
        resp = client.put("/planner/generation-slots", params={"profile_id": "aa"},
                          json={"pranzo": [], "cena": []})
        assert resp.status_code == 422


class TestRegenerateDayRespectsSlots:
    def test_ai_day_button_leaves_the_lunch_free(self, client, dinner_db):
        db, ids = dinner_db
        _add_rules(db, generation_slots={"pranzo": WEEKEND, "cena": ALL_DAYS})
        tuesday = MONDAY + timedelta(days=1)

        resp = client.post("/planner/regenerate-day", params={
            "profile_id_A": "aa", "profile_id_B": "bb", "current_date": tuesday.isoformat(),
        })
        assert resp.status_code == 200
        meals = {m["meal_type"]: m["items"] for m in resp.json()["meals"]}
        assert meals["pranzo"] == []
        assert meals["cena"]

    def test_ai_day_button_fills_the_weekend_lunch(self, client, dinner_db):
        db, _ = dinner_db
        _add_rules(db, generation_slots={"pranzo": WEEKEND, "cena": ALL_DAYS})
        saturday = MONDAY + timedelta(days=5)

        resp = client.post("/planner/regenerate-day", params={
            "profile_id_A": "aa", "profile_id_B": "bb", "current_date": saturday.isoformat(),
        })
        assert resp.status_code == 200
        meals = {m["meal_type"]: m["items"] for m in resp.json()["meals"]}
        assert meals["pranzo"]
        assert meals["cena"]


class TestGenerateWeekEndpointWithSlots:
    def test_saved_plan_keeps_the_empty_lunches(self, client, dinner_db):
        db, _ = dinner_db
        _add_rules(db, generation_slots={"pranzo": WEEKEND, "cena": ALL_DAYS})

        resp = client.post("/planner/generate-week", params={
            "profile_id_A": "aa", "profile_id_B": "bb",
            "current_date": MONDAY.isoformat(), "ai_mode": "off",
        })
        assert resp.status_code == 200

        db.expire_all()
        plan = db.query(GeneratedWeeklyPlan).filter(
            GeneratedWeeklyPlan.profile_id_A == "aa"
        ).first()
        for day in plan.daily_plans:
            weekday = date.fromisoformat(day["date"]).weekday()
            meals = {m["meal_type"]: m.get("items") or [] for m in day["meals"]}
            assert meals["cena"], f"cena mancante il {day['date']}"
            if weekday in WEEKEND:
                assert meals["pranzo"], f"pranzo del weekend mancante il {day['date']}"
            else:
                assert meals["pranzo"] == [], f"pranzo di {day['date']} non doveva essere generato"

    def test_registered_lunch_is_kept_by_a_regeneration(self, client, dinner_db):
        """Il pranzo registrato in mensa sopravvive alla rigenerazione della settimana."""
        db, ids = dinner_db
        _add_rules(db, generation_slots={"pranzo": WEEKEND, "cena": ALL_DAYS})
        wednesday = MONDAY + timedelta(days=2)
        db.add(GeneratedWeeklyPlan(
            id=str(uuid.uuid4()), profile_id_A="aa", profile_id_B="bb",
            week_start_date=MONDAY.isoformat(), generated_at=MONDAY.isoformat(),
            daily_plans=[{
                "date": (MONDAY + timedelta(days=i)).isoformat(),
                "meals": [
                    {"meal_type": "pranzo",
                     "items": [_item(ids["pollo1"], "🍱 Insalatona", "mensa")]
                     if i == 2 else []},
                    {"meal_type": "cena", "items": []},
                ],
            } for i in range(7)],
        ))
        db.add(ConsumedEntry(
            id=str(uuid.uuid4()), profile_id="aa", date=wednesday.isoformat(),
            meal_type="pranzo", type="override",
            override_details={"free_text_name": "Insalatona", "notes": "mensa"},
        ))
        db.commit()

        resp = client.post("/planner/generate-week", params={
            "profile_id_A": "aa", "profile_id_B": "bb",
            "current_date": MONDAY.isoformat(), "ai_mode": "off",
        })
        assert resp.status_code == 200
        week = resp.json()
        day = next(d for d in week if d["date"] == wednesday.isoformat())
        pranzo = next(m for m in day["meals"] if m["meal_type"] == "pranzo")
        assert pranzo["items"] and pranzo["items"][0]["item_name"] == "🍱 Insalatona"


class TestAdherenceCountsOnlyRealSlots:
    def test_ungenerated_lunches_do_not_lower_adherence(self, client, dinner_db):
        """Con i pranzi non generati gli slot pianificati sono 7, non 14: contare
        anche le caselle vuote terrebbe l'aderenza sotto al 50% per sempre."""
        db, _ = dinner_db
        _add_rules(db, generation_slots={"pranzo": [], "cena": ALL_DAYS})

        resp = client.post("/planner/generate-week", params={
            "profile_id_A": "aa", "profile_id_B": "bb",
            "current_date": MONDAY.isoformat(), "ai_mode": "off",
        })
        assert resp.status_code == 200

        adherence = client.get("/planner/adherence", params={
            "profile_id_A": "aa",
            "start_date": MONDAY.isoformat(), "days": 7,
        }).json()
        assert adherence["planned_slots"] == 7

    def test_full_week_still_counts_fourteen(self, client, dinner_db):
        db, _ = dinner_db
        _add_rules(db)

        client.post("/planner/generate-week", params={
            "profile_id_A": "aa", "profile_id_B": "bb",
            "current_date": MONDAY.isoformat(), "ai_mode": "off",
        })
        adherence = client.get("/planner/adherence", params={
            "profile_id_A": "aa",
            "start_date": MONDAY.isoformat(), "days": 7,
        }).json()
        assert adherence["planned_slots"] == 14
