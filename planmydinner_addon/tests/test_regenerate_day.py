"""
Rigenerazione AI di un singolo giorno del piano (POST /planner/regenerate-day).

A differenza di "ExtraFantasy" per singolo pasto — che chiama l'LLM senza sapere
nulla del resto della settimana — regenerate_day_with_ai deve ricostruire il
contesto (rotazione proteine/carboidrati, ricette già usate) dagli altri giorni
del piano salvato prima di generare, così la proposta non ripete né supera i
limiti settimanali.
"""
import uuid
from datetime import date, timedelta

import pytest

from planmydinner_addon.database import CandidateRecipe, GeneratedWeeklyPlan, PlanRules, UserProfile
from planmydinner_addon.planner import PlannerEngine

MONDAY = date(2026, 3, 2)  # lunedì (freeze_time in conftest è 2026-02-24)


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


def _item(recipe_id, name="Ricetta"):
    return {
        "item_name": name, "food_group": "recipe", "quantity": 1, "unit": "recipe",
        "is_estimated_unit": False, "alternatives": [], "recipe_id": recipe_id,
    }


@pytest.fixture
def rotation_db(setup_database):
    """Pool con 2 ricette carne_bianca e 4 legumi, limite carne_bianca=2/settimana."""
    db = setup_database
    db.add(UserProfile(id="aa", name="A", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.add(UserProfile(id="bb", name="B", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.add(PlanRules(
        id=str(uuid.uuid4()), profile_id="aa", imported_at="2026-03-01",
        carb_target={"pranzo": 80.0, "cena": 80.0},
        protein_target={"pranzo": 150.0, "cena": 150.0},
        carb_options={"pranzo": ["pane"], "cena": ["pane"]},
        protein_options={"pranzo": ["pollo"], "cena": ["pollo"]},
        frequency_targets={
            "carne_bianca": {"min": 0, "max": 2},
            "legumi": {"min": 0, "max": 12},
            "pesce": {"min": 0, "max": 12},
        },
        free_meal_quota=2,
    ))
    ids = {}
    pool = [
        ("pollo1", _recipe("Pollo uno", "pollo uno", "carne_bianca")),
        ("pollo2", _recipe("Pollo due", "pollo due", "carne_bianca")),
        ("legumi1", _recipe("Legumi uno", "ceci", "legumi")),
        ("legumi2", _recipe("Legumi due", "lenticchie", "legumi")),
        ("legumi3", _recipe("Legumi tre", "fagioli", "legumi")),
        ("legumi4", _recipe("Legumi quattro", "piselli", "legumi")),
        # Terza categoria: senza, pranzo e cena del giorno target non avrebbero
        # alternativa valida (legumi escluso per lo stesso giorno, carne_bianca
        # bloccata dal limite settimanale) e il test non distinguerebbe i due casi.
        ("pesce1", _recipe("Pesce uno", "pesce uno", "pesce")),
        ("pesce2", _recipe("Pesce due", "pesce due", "pesce")),
    ]
    for key, data in pool:
        cid = str(uuid.uuid4())
        db.add(CandidateRecipe(id=cid, status="approved", recipe_data=data))
        ids[key] = cid
    db.commit()
    return db, ids


def _make_week_plan(db, ids, target_date, carne_bianca_ids):
    """
    Crea un piano settimanale salvato dove SOLO gli altri 6 giorni usano
    carne_bianca (esattamente al limite di 2), e il giorno target ha
    provvisoriamente legumi (verrà sovrascritto dalla rigenerazione).
    """
    daily_plans = []
    carne_bianca_slots_left = list(carne_bianca_ids)  # 2 id, usati una volta ciascuno
    for i in range(7):
        d = (MONDAY + timedelta(days=i)).isoformat()
        day_is_target = (MONDAY + timedelta(days=i)) == target_date
        meals = []
        for meal_type in ("pranzo", "cena"):
            if not day_is_target and carne_bianca_slots_left:
                rid = carne_bianca_slots_left.pop(0)
            else:
                rid = ids["legumi1"]
            meals.append({"meal_type": meal_type, "items": [_item(rid)]})
        daily_plans.append({"date": d, "meals": meals})

    plan = GeneratedWeeklyPlan(
        id=str(uuid.uuid4()), profile_id_A="aa", profile_id_B="bb",
        week_start_date=MONDAY.isoformat(), generated_at=MONDAY.isoformat(),
        daily_plans=daily_plans,
    )
    db.add(plan)
    db.commit()
    return plan


class TestRegenerateDayWithAI:
    def test_no_plan_rules_returns_none(self, setup_database):
        planner = PlannerEngine(setup_database)
        assert planner.regenerate_day_with_ai("nessuno", "bb", MONDAY) is None

    def test_no_plan_covering_date_returns_none(self, rotation_db):
        db, ids = rotation_db
        planner = PlannerEngine(db)
        assert planner.regenerate_day_with_ai("aa", "bb", MONDAY) is None

    def test_regenerates_only_target_day(self, rotation_db):
        db, ids = rotation_db
        target_date = MONDAY + timedelta(days=6)  # domenica: non consuma carne_bianca
        _make_week_plan(db, ids, target_date, [ids["pollo1"], ids["pollo2"]])

        planner = PlannerEngine(db)
        before = db.query(GeneratedWeeklyPlan).filter(GeneratedWeeklyPlan.profile_id_A == "aa").first()
        other_days_before = {
            dp["date"]: dp["meals"] for dp in before.daily_plans if dp["date"] != target_date.isoformat()
        }

        result = planner.regenerate_day_with_ai("aa", "bb", target_date)
        assert result is not None
        assert result.date == target_date.isoformat()
        assert len(result.meals) == 2

        db.expire_all()
        after = db.query(GeneratedWeeklyPlan).filter(GeneratedWeeklyPlan.profile_id_A == "aa").first()
        other_days_after = {
            dp["date"]: dp["meals"] for dp in after.daily_plans if dp["date"] != target_date.isoformat()
        }
        assert other_days_after == other_days_before

    def test_respects_weekly_protein_rotation_limit(self, rotation_db):
        """Con carne_bianca già al suo massimo (2) negli altri 6 giorni, il giorno
        rigenerato non deve proporre carne_bianca per nessuno dei due pasti."""
        db, ids = rotation_db
        target_date = MONDAY + timedelta(days=6)
        _make_week_plan(db, ids, target_date, [ids["pollo1"], ids["pollo2"]])

        planner = PlannerEngine(db)
        result = planner.regenerate_day_with_ai("aa", "bb", target_date)
        assert result is not None
        for meal in result.meals:
            recipe_id = meal.items[0].recipe_id
            cat = planner._get_main_protein_category(recipe_id)
            assert cat != "carne_bianca", f"{meal.meal_type} ha proposto carne_bianca oltre il limite settimanale"

    def test_does_not_repeat_recipe_already_used_in_week(self, rotation_db):
        db, ids = rotation_db
        target_date = MONDAY + timedelta(days=6)
        _make_week_plan(db, ids, target_date, [ids["pollo1"], ids["pollo2"]])

        planner = PlannerEngine(db)
        result = planner.regenerate_day_with_ai("aa", "bb", target_date)
        used_elsewhere = {ids["pollo1"], ids["pollo2"], ids["legumi1"]}
        for meal in result.meals:
            assert meal.items[0].recipe_id not in used_elsewhere


class TestRegenerateDayEndpoint:
    def test_endpoint_404_without_plan(self, client, rotation_db):
        db, ids = rotation_db
        resp = client.post("/planner/regenerate-day", params={
            "profile_id_A": "aa", "profile_id_B": "bb", "current_date": MONDAY.isoformat(),
        })
        assert resp.status_code == 404

    def test_endpoint_200_replaces_day(self, client, rotation_db):
        db, ids = rotation_db
        target_date = MONDAY + timedelta(days=6)
        _make_week_plan(db, ids, target_date, [ids["pollo1"], ids["pollo2"]])

        resp = client.post("/planner/regenerate-day", params={
            "profile_id_A": "aa", "profile_id_B": "bb", "current_date": target_date.isoformat(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == target_date.isoformat()
        assert len(data["meals"]) == 2
