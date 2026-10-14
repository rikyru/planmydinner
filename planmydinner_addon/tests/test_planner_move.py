from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from planmydinner_addon.database import GeneratedWeeklyPlan

# same sqlite file the app/tests use (see conftest)
_ENG = create_engine("sqlite:///./test.db", connect_args={"check_same_thread": False})
_S = sessionmaker(bind=_ENG)


def test_move_meal_swaps_slots(client, setup_database):
    s = _S()
    s.add(GeneratedWeeklyPlan(
        id="gwp_move", profile_id_A="persona_a", profile_id_B="persona_b",
        week_start_date="2026-02-23", generated_at="2026-02-23",
        daily_plans=[{"date": "2026-02-24", "meals": [
            {"meal_type": "pranzo", "items": [{"item_name": "Riso", "recipe_id": "rA"}]},
            {"meal_type": "cena", "items": [{"item_name": "Zuppa", "recipe_id": "rB"}]},
        ]}]))
    s.commit(); s.close()

    r = client.post("/planner/move-meal", json={
        "profile_id_A": "persona_a", "profile_id_B": "persona_b",
        "from_date": "2026-02-24", "from_meal": "pranzo",
        "to_date": "2026-02-24", "to_meal": "cena"})
    assert r.status_code == 200 and r.json()["moved"] is True

    s2 = _S()
    p = s2.query(GeneratedWeeklyPlan).filter_by(id="gwp_move").first()
    meals = {m["meal_type"]: m["items"] for m in p.daily_plans[0]["meals"]}
    s2.close()
    assert meals["pranzo"][0]["recipe_id"] == "rB"   # swapped
    assert meals["cena"][0]["recipe_id"] == "rA"
