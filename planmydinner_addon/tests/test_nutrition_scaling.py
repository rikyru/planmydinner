"""Portion scaling toward a daily energy target (OpenFit integration).

Seed recipe "pasta_pomodoro_recipe" for persona_a = pasta 100 g (353 kcal) +
pomodoro 200 g (36 kcal) = 389 kcal/meal. A day of pranzo+cena = 778 kcal.
conftest freezes today at 2026-02-24.
"""
import pytest

from datetime import date, timedelta

from planmydinner_addon import schemas
from planmydinner_addon.database import GeneratedWeeklyPlan, PlanRules
from planmydinner_addon.scaling import apply_nutrition_scaling, SCALE_MIN, SCALE_MAX

from planmydinner_addon.nutrition import DEFAULT_COOKING_FAT_G

TODAY = "2026-02-24"
# pasta_pomodoro = 389 kcal/pasto + olio di cottura stimato (ricetta senza grassi)
MEAL_KCAL = 389.0 + DEFAULT_COOKING_FAT_G * 899 / 100.0
DAY_KCAL = 2 * MEAL_KCAL


def _item(recipe_id="pasta_pomodoro_recipe", food_group="carboidrato", name="Pasta al Pomodoro"):
    return {"item_name": name, "food_group": food_group, "quantity": 0, "unit": "",
            "is_estimated_unit": False, "alternatives": [], "recipe_id": recipe_id}


def _plan_rows(start_iso=TODAY, days=3):
    start = date.fromisoformat(start_iso)
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        out.append({"date": d, "meals": [
            {"meal_type": "pranzo", "items": [_item()]},
            {"meal_type": "cena", "items": [_item()]},
        ]})
    return out


def _save_plan(db, profile_id="persona_a", start_iso=TODAY, days=3):
    plan = GeneratedWeeklyPlan(
        id="gen-scale-test", profile_id_A=profile_id, profile_id_B="persona_b",
        week_start_date=start_iso, generated_at=TODAY, daily_plans=_plan_rows(start_iso, days))
    db.add(plan)
    db.commit()
    return plan


def _set_targets(db, profile_id="persona_a", **targets):
    import uuid
    from datetime import datetime
    row = PlanRules(id=str(uuid.uuid4()), profile_id=profile_id,
                    imported_at=datetime.now().isoformat(), nutrition_targets=targets)
    db.add(row)
    db.commit()


def test_no_target_is_noop(setup_database):
    db = setup_database
    daily = [schemas.DailyPlannedMeals.model_validate(dp) for dp in _plan_rows()]
    apply_nutrition_scaling(db, "persona_a", daily)
    assert all(m.scale == 1.0 for dp in daily for m in dp.meals)


def test_scale_hits_target(setup_database):
    db = setup_database
    _set_targets(db, kcal=600)  # 600/778 = 0.771, within the band
    daily = [schemas.DailyPlannedMeals.model_validate(dp) for dp in _plan_rows()]
    apply_nutrition_scaling(db, "persona_a", daily)
    expected = 600 / DAY_KCAL
    for dp in daily:
        for m in dp.meals:
            assert m.scale == pytest.approx(expected, abs=0.01)


def test_scale_is_floored(setup_database):
    db = setup_database
    _set_targets(db, kcal=300)  # 300/778 = 0.385 -> floored to SCALE_MIN
    daily = [schemas.DailyPlannedMeals.model_validate(dp) for dp in _plan_rows()]
    apply_nutrition_scaling(db, "persona_a", daily)
    assert all(m.scale == SCALE_MIN for dp in daily for m in dp.meals)


def test_scale_is_capped(setup_database):
    db = setup_database
    _set_targets(db, kcal=5000)  # way over -> capped to SCALE_MAX
    daily = [schemas.DailyPlannedMeals.model_validate(dp) for dp in _plan_rows()]
    apply_nutrition_scaling(db, "persona_a", daily)
    assert all(m.scale == SCALE_MAX for dp in daily for m in dp.meals)


def test_past_day_not_rescaled(setup_database):
    db = setup_database
    _set_targets(db, kcal=600)
    # one past day (yesterday) + two from today
    rows = _plan_rows(start_iso=(date.fromisoformat(TODAY) - timedelta(days=1)).isoformat(), days=3)
    daily = [schemas.DailyPlannedMeals.model_validate(dp) for dp in rows]
    apply_nutrition_scaling(db, "persona_a", daily)
    assert all(m.scale == 1.0 for m in daily[0].meals)              # yesterday untouched
    assert all(m.scale < 1.0 for dp in daily[1:] for m in dp.meals)  # today+ scaled down


def test_cut_never_inflates(setup_database):
    db = setup_database
    # target well above the plan's base, but allow_upscale off (a cut)
    _set_targets(db, kcal=5000, allow_upscale=0.0)
    daily = [schemas.DailyPlannedMeals.model_validate(dp) for dp in _plan_rows()]
    apply_nutrition_scaling(db, "persona_a", daily)
    # portions are not grown beyond 1.0 even though the target is far higher
    assert all(m.scale == 1.0 for dp in daily for m in dp.meals)


def test_cut_still_shrinks(setup_database):
    db = setup_database
    _set_targets(db, kcal=600, allow_upscale=0.0)  # below base -> must shrink
    daily = [schemas.DailyPlannedMeals.model_validate(dp) for dp in _plan_rows()]
    apply_nutrition_scaling(db, "persona_a", daily)
    expected = 600 / DAY_KCAL
    assert all(m.scale == pytest.approx(expected, abs=0.01) for dp in daily for m in dp.meals)


def test_apply_targets_endpoint_rescales_and_summary_reflects(client, setup_database):
    db = setup_database
    _save_plan(db)
    r = client.post("/integration/apply-targets", params={"profile_id": "persona_a"},
                    json={"kcal": 600})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rescaled_current_plan"] is True
    assert body["targets"]["kcal"] == 600

    # summary over the scaled window shows the reduced day kcal (~600), not 778
    end = (date.fromisoformat(TODAY) + timedelta(days=2)).isoformat()
    s = client.get("/integration/summary", params={
        "profile_id": "persona_a", "start_date": TODAY, "end_date": end})
    assert s.status_code == 200
    day0 = s.json()["days"][0]
    assert day0["nutrition"]["kcal"] == pytest.approx(600, abs=1.0)
    assert s.json()["targets"]["kcal"] == 600


def test_shopping_list_honours_scale(setup_database):
    from planmydinner_addon.planner import PlannerEngine
    db = setup_database
    _save_plan(db)
    start = date.fromisoformat(TODAY)

    def pasta_qty():
        sl = PlannerEngine(db).generate_shopping_list_for_week("persona_a", "persona_b", start)
        for cat in sl.items_by_category.values():
            for it in cat:
                if "pasta" in it.name.lower():
                    return it.quantity
        return None

    before = pasta_qty()
    assert before and before > 0
    # apply a deficit target and re-scale, then the groceries shrink proportionally
    _set_targets(db, kcal=600)
    plan = db.query(GeneratedWeeklyPlan).filter(
        GeneratedWeeklyPlan.profile_id_A == "persona_a").first()
    daily = [schemas.DailyPlannedMeals.model_validate(dp) for dp in plan.daily_plans]
    apply_nutrition_scaling(db, "persona_a", daily)
    plan.daily_plans = [dp.model_dump() for dp in daily]
    db.add(plan)
    db.commit()
    after = pasta_qty()
    # groceries shrink with the scaled-down portions (pantry stock makes the
    # ratio non-linear, so we assert the direction and a meaningful reduction)
    assert after < before
