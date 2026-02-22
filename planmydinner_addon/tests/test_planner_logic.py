import pytest
from datetime import date
from planmydinner_addon.planner import PlannerEngine

# Fixtures are in conftest.py and test_planner.py

def test_generate_weekly_plan(planner_seeded_database):
    db_session = planner_seeded_database
    planner = PlannerEngine(db_session)

    start_date = date.today()
    weekly_plan = planner.generate_weekly_plan("persona_a", "persona_b", start_date)

    assert len(weekly_plan) == 7
    for day in weekly_plan:
        assert len(day.meals) == 2 # Lunch and dinner
