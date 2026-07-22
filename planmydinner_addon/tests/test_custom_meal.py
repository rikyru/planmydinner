"""POST /planner/set-custom-meal deve creare una vera Recipe (visibile in Ricette),
non un CandidateRecipe interno, e riusare la stessa riga per nomi ripetuti."""
from datetime import date, timedelta

from planmydinner_addon.database import CandidateRecipe, GeneratedWeeklyPlan, Recipe

TODAY = date(2026, 2, 24)  # freeze_time in conftest


def _ensure_profiles(db):
    from planmydinner_addon.database import UserProfile
    if not db.query(UserProfile).filter(UserProfile.id == "persona_a").first():
        db.add(UserProfile(id="persona_a", name="Alice", allergies=[], excluded_foods=[],
                           preferences=[], equipment=[]))
    if not db.query(UserProfile).filter(UserProfile.id == "persona_b").first():
        db.add(UserProfile(id="persona_b", name="Bob", allergies=[], excluded_foods=[],
                           preferences=[], equipment=[]))
    db.commit()


def _make_plan(db, profile_id="persona_a"):
    _ensure_profiles(db)
    start = TODAY - timedelta(days=TODAY.weekday())
    db.add(GeneratedWeeklyPlan(
        id="plan-custom-meal-test", profile_id_A=profile_id, profile_id_B="persona_b",
        week_start_date=start.isoformat(), generated_at=start.isoformat(),
        daily_plans=[{
            "date": (start + timedelta(days=i)).isoformat(),
            "meals": [
                {"meal_type": "pranzo", "items": []},
                {"meal_type": "cena", "items": []},
            ],
        } for i in range(7)],
    ))
    db.commit()


def _body(title="Piadina con manzo"):
    return {
        "title": title, "protein_name": "manzo", "protein_grams": 150,
        "carb_name": "piadina", "carb_grams": 100,
        "veg_name": "insalata", "veg_grams": 80, "notes": "",
    }


class TestSetCustomMeal:
    def test_creates_real_recipe_visible_in_recipes_list(self, client, setup_database):
        _make_plan(setup_database)
        resp = client.post("/planner/set-custom-meal", params={
            "profile_id_A": "persona_a", "profile_id_B": "persona_b",
            "meal_type": "cena", "current_date": TODAY.isoformat(),
        }, json=_body())
        assert resp.status_code == 200
        recipe_id = resp.json()["recipe_id"]

        # E' una vera Recipe (tabella recipes), non un CandidateRecipe interno
        assert setup_database.query(Recipe).filter(Recipe.id == recipe_id).first() is not None
        assert setup_database.query(CandidateRecipe).filter(CandidateRecipe.id == recipe_id).first() is None

        # Compare nella lista ricette, taggata come personale
        names = {r["name"]: r for r in client.get("/recipes/").json()}
        assert "Piadina con manzo" in names
        assert names["Piadina con manzo"]["tags"]["manual"] == ["true"]

    def test_resubmitting_same_name_updates_instead_of_duplicating(self, client, setup_database):
        _make_plan(setup_database)
        resp1 = client.post("/planner/set-custom-meal", params={
            "profile_id_A": "persona_a", "profile_id_B": "persona_b",
            "meal_type": "pranzo", "current_date": TODAY.isoformat(),
        }, json=_body())
        recipe_id_1 = resp1.json()["recipe_id"]

        # Stesso nome (case diverso), grammi diversi: deve aggiornare la stessa riga
        resp2 = client.post("/planner/set-custom-meal", params={
            "profile_id_A": "persona_a", "profile_id_B": "persona_b",
            "meal_type": "cena", "current_date": TODAY.isoformat(),
        }, json=_body(title="PIADINA con manzo"))
        recipe_id_2 = resp2.json()["recipe_id"]

        assert recipe_id_1 == recipe_id_2
        all_recipes = client.get("/recipes/").json()
        matching = [r for r in all_recipes if r["name"].lower() == "piadina con manzo"]
        assert len(matching) == 1

    def test_applies_to_the_requested_slot(self, client, setup_database):
        _make_plan(setup_database)
        resp = client.post("/planner/set-custom-meal", params={
            "profile_id_A": "persona_a", "profile_id_B": "persona_b",
            "meal_type": "cena", "current_date": TODAY.isoformat(),
        }, json=_body())
        recipe_id = resp.json()["recipe_id"]

        plan = setup_database.query(GeneratedWeeklyPlan).filter(
            GeneratedWeeklyPlan.id == "plan-custom-meal-test").first()
        setup_database.refresh(plan)
        today_entry = next(d for d in plan.daily_plans if d["date"] == TODAY.isoformat())
        cena = next(m for m in today_entry["meals"] if m["meal_type"] == "cena")
        assert cena["items"][0]["recipe_id"] == recipe_id
