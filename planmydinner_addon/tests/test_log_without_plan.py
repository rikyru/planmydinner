"""
Registrare pasti senza un piano generato, e generazione che NON distrugge
quanto già registrato.

1. Registrare un pasto (mensa/foto, libero, personalizzato, non mangiato) in una
   settimana senza piano crea uno scheletro vuoto che ospita lo slot.
2. Generando poi il piano, gli slot già registrati restano intatti e la
   generazione riempie solo i rimanenti.
"""
import uuid
from datetime import date, timedelta

import pytest

from planmydinner_addon.database import (
    CandidateRecipe, GeneratedWeeklyPlan, PlanRules, UserProfile,
)

TODAY = date(2026, 2, 24)  # freeze_time in conftest (martedì)
MONDAY = TODAY - timedelta(days=TODAY.weekday())


def _qty(g):
    return {"qty": float(g), "unit": "g", "grams_equiv": float(g)}


def _recipe(name, protein_name, protein_fg, carb_name="pane"):
    return {
        "name": name, "description": "", "is_composed_dish": False,
        "content": [
            {"name": carb_name, "food_group": "carboidrati",
             "quantities": {"aa": _qty(80), "bb": _qty(80)}},
            {"name": protein_name, "food_group": protein_fg,
             "quantities": {"aa": _qty(150), "bb": _qty(150)}},
        ],
        "steps": [], "total_time_minutes": 25, "difficulty": "facile",
        "tags": {"mood": ["normale"], "cooking_methods": ["tegame"], "cleanup": ["facile"]},
    }


@pytest.fixture
def planless_db(setup_database):
    """Due profili e un catalogo utilizzabile, ma NESSUN piano generato."""
    db = setup_database
    db.add(UserProfile(id="aa", name="A", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.add(UserProfile(id="bb", name="B", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.add(PlanRules(
        id=str(uuid.uuid4()), profile_id="aa", imported_at="2026-02-20",
        carb_target={"pranzo": 80.0, "cena": 80.0},
        protein_target={"pranzo": 150.0, "cena": 150.0},
        carb_options={"pranzo": ["pane"], "cena": ["pane"]},
        protein_options={"pranzo": ["pollo"], "cena": ["pollo"]},
        frequency_targets={
            "carne_bianca": {"min": 0, "max": 7},
            "legumi": {"min": 0, "max": 7},
            "pesce": {"min": 0, "max": 7},
        },
        free_meal_quota=2,
    ))
    for name, prot, fg in [
        ("Pollo uno", "pollo uno", "carne_bianca"),
        ("Pollo due", "pollo due", "carne_bianca"),
        ("Ceci", "ceci", "legumi"),
        ("Lenticchie", "lenticchie", "legumi"),
        ("Salmone", "salmone", "pesce"),
        ("Merluzzo", "merluzzo", "pesce"),
    ]:
        db.add(CandidateRecipe(id=str(uuid.uuid4()), status="approved",
                               recipe_data=_recipe(name, prot, fg)))
    db.commit()
    assert db.query(GeneratedWeeklyPlan).count() == 0
    return db


def _plan_for(db, profile_id="aa"):
    return db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == profile_id
    ).order_by(GeneratedWeeklyPlan.generated_at.desc()).first()


def _slot(db, iso, meal_type, profile_id="aa"):
    plan = _plan_for(db, profile_id)
    if not plan:
        return None
    day = next((d for d in plan.daily_plans if d["date"] == iso), None)
    if not day:
        return None
    meal = next((m for m in day.get("meals", []) if m["meal_type"] == meal_type), None)
    items = (meal or {}).get("items") or []
    return items[0] if items else None


class TestLoggingWithoutPlan:
    def test_mensa_meal_creates_empty_plan(self, client, planless_db):
        db = planless_db
        resp = client.post("/consumed-entries/mensa", json={
            "profile_id": "aa", "date": TODAY.isoformat(), "meal_type": "pranzo",
            "name": "Insalatona della mensa",
            "ingredients": [{"name": "pasta", "food_group": "carboidrati", "grams": 80}],
        })
        assert resp.status_code == 200

        db.expire_all()
        plan = _plan_for(db)
        assert plan is not None, "doveva essere creato uno scheletro di piano"
        assert plan.week_start_date == MONDAY.isoformat()
        assert len(plan.daily_plans) == 7

        item = _slot(db, TODAY.isoformat(), "pranzo")
        assert item["food_group"] == "mensa"
        assert "Insalatona della mensa" in item["item_name"]
        # gli altri slot restano vuoti, pronti per la generazione
        assert _slot(db, TODAY.isoformat(), "cena") is None

    def test_free_meal_without_plan(self, client, planless_db):
        db = planless_db
        resp = client.post(
            "/planner/free-meal",
            params={"profile_id_A": "aa", "profile_id_B": "bb",
                    "meal_type": "cena", "current_date": TODAY.isoformat()},
            json={"title": "Pizza con gli amici", "notes": ""},
        )
        assert resp.status_code == 200
        db.expire_all()
        item = _slot(db, TODAY.isoformat(), "cena")
        assert item["food_group"] == "free_meal"
        assert item["item_name"] == "Pizza con gli amici"

    def test_not_eaten_without_plan(self, client, planless_db):
        db = planless_db
        resp = client.post("/planner/not-eaten", params={
            "profile_id_A": "aa", "profile_id_B": "bb",
            "meal_type": "pranzo", "current_date": TODAY.isoformat(),
        })
        assert resp.status_code == 200
        db.expire_all()
        assert _slot(db, TODAY.isoformat(), "pranzo")["food_group"] == "not_eaten"

    def test_custom_meal_without_plan(self, client, planless_db):
        db = planless_db
        resp = client.post(
            "/planner/set-custom-meal",
            params={"profile_id_A": "aa", "profile_id_B": "bb",
                    "meal_type": "cena", "current_date": TODAY.isoformat()},
            json={"title": "Piadina di manzo", "protein_name": "manzo", "protein_grams": 150,
                  "carb_name": "piadina", "carb_grams": 80},
        )
        assert resp.status_code == 200
        db.expire_all()
        assert _slot(db, TODAY.isoformat(), "cena")["item_name"] == "Piadina di manzo"

    def test_logged_meal_counts_in_summary(self, client, planless_db):
        """Senza piano il pasto registrato restava fuori da /integration/summary."""
        client.post("/consumed-entries/mensa", json={
            "profile_id": "aa", "date": TODAY.isoformat(), "meal_type": "pranzo",
            "name": "Pasta e ceci", "ingredients": [
                {"name": "pasta", "food_group": "carboidrati", "grams": 80},
                {"name": "ceci", "food_group": "legumi", "grams": 100},
            ],
        })
        resp = client.get("/integration/summary", params={
            "profile_id": "aa", "start_date": MONDAY.isoformat(),
            "end_date": (MONDAY + timedelta(days=6)).isoformat(),
        })
        assert resp.status_code == 200
        day = next(d for d in resp.json()["days"] if d["date"] == TODAY.isoformat())
        assert day["nutrition"] is not None
        assert day["nutrition"]["kcal"] > 0


class TestGenerationKeepsLoggedMeals:
    def _log_a_bit(self, client):
        """Registra: mensa lunedì pranzo, libero lunedì cena, non mangiato martedì pranzo."""
        client.post("/consumed-entries/mensa", json={
            "profile_id": "aa", "date": MONDAY.isoformat(), "meal_type": "pranzo",
            "name": "Vassoio mensa",
            "ingredients": [{"name": "pasta", "food_group": "carboidrati", "grams": 80}],
        })
        client.post(
            "/planner/free-meal",
            params={"profile_id_A": "aa", "profile_id_B": "bb",
                    "meal_type": "cena", "current_date": MONDAY.isoformat()},
            json={"title": "Sushi", "notes": ""},
        )
        client.post("/planner/not-eaten", params={
            "profile_id_A": "aa", "profile_id_B": "bb",
            "meal_type": "pranzo", "current_date": (MONDAY + timedelta(days=1)).isoformat(),
        })

    def test_generation_preserves_logged_and_fills_the_rest(self, client, planless_db):
        db = planless_db
        self._log_a_bit(client)

        resp = client.post("/planner/generate-week", params={
            "profile_id_A": "aa", "profile_id_B": "bb",
            "current_date": MONDAY.isoformat(), "ai_mode": "off",
        })
        assert resp.status_code == 200
        db.expire_all()

        # I tre slot registrati sono intatti...
        mensa = _slot(db, MONDAY.isoformat(), "pranzo")
        assert mensa["food_group"] == "mensa" and "Vassoio mensa" in mensa["item_name"]
        libero = _slot(db, MONDAY.isoformat(), "cena")
        assert libero["food_group"] == "free_meal" and libero["item_name"] == "Sushi"
        saltato = _slot(db, (MONDAY + timedelta(days=1)).isoformat(), "pranzo")
        assert saltato["food_group"] == "not_eaten"

        # ...e gli altri slot sono stati riempiti dalla generazione
        filled = _slot(db, (MONDAY + timedelta(days=1)).isoformat(), "cena")
        assert filled is not None and filled["food_group"] == "recipe"
        for i in range(2, 7):
            iso = (MONDAY + timedelta(days=i)).isoformat()
            assert _slot(db, iso, "pranzo") is not None, f"{iso} pranzo vuoto"
            assert _slot(db, iso, "cena") is not None, f"{iso} cena vuoto"

    def test_slot_with_consumed_entry_is_preserved(self, client, planless_db):
        """Anche un pasto del piano segnato come mangiato non va rigenerato."""
        db = planless_db
        client.post("/planner/generate-week", params={
            "profile_id_A": "aa", "profile_id_B": "bb",
            "current_date": MONDAY.isoformat(), "ai_mode": "off",
        })
        db.expire_all()
        original = _slot(db, MONDAY.isoformat(), "pranzo")
        assert original is not None

        client.post("/consumed-entries/", json={
            "profile_id": "aa", "date": MONDAY.isoformat(), "meal_type": "pranzo",
            "type": "planned", "consumed_recipe_id": original["recipe_id"],
        })

        client.post("/planner/generate-week", params={
            "profile_id_A": "aa", "profile_id_B": "bb",
            "current_date": MONDAY.isoformat(), "ai_mode": "off",
        })
        db.expire_all()
        assert _slot(db, MONDAY.isoformat(), "pranzo")["recipe_id"] == original["recipe_id"]

    def test_keep_logged_false_regenerates_everything(self, client, planless_db):
        db = planless_db
        self._log_a_bit(client)
        resp = client.post("/planner/generate-week", params={
            "profile_id_A": "aa", "profile_id_B": "bb",
            "current_date": MONDAY.isoformat(), "ai_mode": "off",
            "keep_logged": "false",
        })
        assert resp.status_code == 200
        db.expire_all()
        assert _slot(db, MONDAY.isoformat(), "pranzo")["food_group"] == "recipe"
        assert _slot(db, MONDAY.isoformat(), "cena")["food_group"] == "recipe"

    def test_logged_days_outside_new_window_survive(self, client, planless_db):
        """Registro lunedì/martedì, poi genero una settimana che parte da mercoledì:
        i giorni registrati fuori finestra non devono sparire."""
        db = planless_db
        self._log_a_bit(client)
        wednesday = MONDAY + timedelta(days=2)

        resp = client.post("/planner/generate-week", params={
            "profile_id_A": "aa", "profile_id_B": "bb",
            "current_date": wednesday.isoformat(), "ai_mode": "off",
        })
        assert resp.status_code == 200
        db.expire_all()

        resp = client.get("/planner/plan-for-date", params={
            "profile_id_A": "aa", "target_date": MONDAY.isoformat(),
        })
        assert resp.status_code == 200
        plan = resp.json()
        assert plan is not None, "il piano con i pasti registrati è stato cancellato"
        monday_day = next(d for d in plan["daily_plans"] if d["date"] == MONDAY.isoformat())
        groups = {m["meal_type"]: (m["items"] or [{}])[0].get("food_group") for m in monday_day["meals"]}
        assert groups["pranzo"] == "mensa"
        assert groups["cena"] == "free_meal"


class TestRegenerateDayKeepsLogged:
    def test_regenerate_day_does_not_wipe_logged_meal(self, client, planless_db):
        db = planless_db
        client.post("/consumed-entries/mensa", json={
            "profile_id": "aa", "date": TODAY.isoformat(), "meal_type": "pranzo",
            "name": "Vassoio mensa",
            "ingredients": [{"name": "pasta", "food_group": "carboidrati", "grams": 80}],
        })
        resp = client.post("/planner/regenerate-day", params={
            "profile_id_A": "aa", "profile_id_B": "bb", "current_date": TODAY.isoformat(),
        })
        assert resp.status_code == 200
        db.expire_all()
        item = _slot(db, TODAY.isoformat(), "pranzo")
        assert item["food_group"] == "mensa" and "Vassoio mensa" in item["item_name"]
        # la cena, non registrata, viene invece proposta
        assert _slot(db, TODAY.isoformat(), "cena") is not None
