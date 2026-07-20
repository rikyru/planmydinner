"""
Regressione per l'incidente del 2026-07-19: GET /planner/weekly-plan generava e
salvava un piano su cache-miss, e il salvataggio cancellava (per finestra
sovrapposta) qualunque piano esistente coprisse la stessa settimana — inclusi
tutti i pasti mensa/liberi registrati dall'utente. La GET deve essere di sola
lettura: mai generare, mai salvare, mai cancellare piani esistenti.
"""
from datetime import date

import pytest

from planmydinner_addon.database import GeneratedWeeklyPlan

MONDAY = "2026-02-23"  # lunedì della settimana di freeze_time (2026-02-24)
SUNDAY = "2026-03-01"


def _seed_plan(db, start_date=MONDAY, marker="Marker utente non deve sparire"):
    plan = GeneratedWeeklyPlan(
        id="existing-plan",
        profile_id_A="persona_a",
        profile_id_B="persona_b",
        week_start_date=start_date,
        generated_at=start_date,
        daily_plans=[{
            "date": start_date,
            "meals": [{"meal_type": "pranzo", "items": [{
                "item_name": marker, "food_group": "mensa", "quantity": 1,
                "unit": "recipe", "is_estimated_unit": False, "alternatives": [],
                "recipe_id": "some-id",
            }]}],
        }],
    )
    db.add(plan)
    db.commit()


class TestWeeklyPlanIsReadOnly:
    def test_exact_match_returns_stored_plan_untouched(self, client, setup_database):
        _seed_plan(setup_database)
        resp = client.get("/planner/weekly-plan", params={
            "profile_id_A": "persona_a", "profile_id_B": "persona_b", "start_date": MONDAY,
        })
        assert resp.status_code == 200
        assert resp.json()[0]["meals"][0]["items"][0]["item_name"] == "Marker utente non deve sparire"
        assert setup_database.query(GeneratedWeeklyPlan).count() == 1

    def test_non_aligned_date_does_not_wipe_existing_plan(self, client, setup_database):
        """Lo scenario esatto dell'incidente: si naviga a una data che ricade
        nella finestra di un piano esistente ma non ne è lo start_date esatto
        (es. una domenica dentro la settimana). Prima: 404 → auto-generate →
        _save_generated_plan cancellava il piano esistente per overlap."""
        db = setup_database
        _seed_plan(db)
        mid_week_sunday = SUNDAY  # ultimo giorno della finestra lunedì-based, non è lo start esatto

        resp = client.get("/planner/weekly-plan", params={
            "profile_id_A": "persona_a", "profile_id_B": "persona_b",
            "start_date": mid_week_sunday,
        })
        # Deve restituire il piano esistente che copre quella data, non generarne uno nuovo
        assert resp.status_code == 200
        assert resp.json()[0]["meals"][0]["items"][0]["item_name"] == "Marker utente non deve sparire"

        # Il piano originale deve esistere ancora, intatto, nessun piano nuovo creato
        plans = db.query(GeneratedWeeklyPlan).all()
        assert len(plans) == 1
        assert plans[0].id == "existing-plan"
        assert plans[0].week_start_date == MONDAY

    def test_no_covering_plan_returns_404_without_generating(self, client, setup_database):
        db = setup_database
        resp = client.get("/planner/weekly-plan", params={
            "profile_id_A": "persona_a", "profile_id_B": "persona_b", "start_date": "2026-05-01",
        })
        assert resp.status_code == 404
        # Nessun piano creato come effetto collaterale della GET
        assert db.query(GeneratedWeeklyPlan).count() == 0
