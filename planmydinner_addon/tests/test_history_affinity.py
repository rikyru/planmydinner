"""La generazione pesca dal repertorio reale: boost di affinità storica."""
import uuid
from datetime import date, timedelta

from planmydinner_addon import schemas
from planmydinner_addon.database import ConsumedEntry, Recipe
from planmydinner_addon.planner import PlannerEngine

TODAY = date(2026, 2, 24)  # freeze_time in conftest
RID = "pasta_pomodoro_recipe"  # seeded in setup_database


def _seed_consumed(db, recipe_id, days_ago, profile="persona_a"):
    for n in days_ago:
        db.add(ConsumedEntry(
            id=str(uuid.uuid4()), profile_id=profile,
            date=(TODAY - timedelta(days=n)).isoformat(),
            meal_type="cena", type="planned", consumed_recipe_id=recipe_id))
    db.commit()


def test_affinity_counts_and_recency(setup_database):
    db = setup_database
    _seed_consumed(db, RID, [2, 40])          # una recente, una vecchia
    m = PlannerEngine(db)._history_affinity_map(["persona_a"], TODAY)
    assert RID in m
    assert m[RID] > 1.0                        # due consumi, peso totale > 1
    # un consumo di ieri pesa più di uno vecchio
    only_recent = PlannerEngine(db)._history_affinity_map(["persona_a"], TODAY, days_back=56)
    assert only_recent[RID] == m[RID]


def test_affinity_ignores_future_and_old(setup_database):
    db = setup_database
    _seed_consumed(db, RID, [200])             # oltre la finestra 56g
    m = PlannerEngine(db)._history_affinity_map(["persona_a"], TODAY)
    assert RID not in m


def test_scoring_boosts_affine_recipe(setup_database):
    db = setup_database
    rec = db.query(Recipe).filter(Recipe.id == RID).first()
    r = schemas.Recipe.model_validate(rec)
    p = PlannerEngine(db)
    base = p._score_soft_constraints(r, [], {}, TODAY, [], [])
    p._affinity = {RID: 4.0}                    # mangiata spesso
    boosted = p._score_soft_constraints(r, [], {}, TODAY, [], [])
    assert boosted - base > 0.5                 # boost ben oltre il jitter ±0.05
