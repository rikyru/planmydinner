"""
Regressione: POST /planner/change-recipe rispondeva 500 quando, nella finestra
anti-ripetizione, esisteva un ConsumedEntry che puntava a una vera Recipe
(tabella recipes, non CandidateRecipe). _filter_hard_constraints interrogava
Recipe direttamente dal DB e leggeva `ing.food_group` su un dict grezzo della
colonna JSON invece che su un RecipeIngredient validato.

Innescato in produzione da: pasto personalizzato -> ora crea una vera Recipe
(fix precedente) -> segnata come consumata -> "Cambia ricetta" nella finestra
anti-ripetizione -> AttributeError: 'dict' object has no attribute 'food_group'.
"""
from datetime import date, timedelta

from planmydinner_addon.database import ConsumedEntry


class TestChangeRecipeWithRecentRealRecipeConsumed:
    def test_does_not_500_when_recent_consumed_entry_points_to_real_recipe(
        self, client, planner_seeded_database
    ):
        db = planner_seeded_database
        # Consumo recente (entro la finestra anti-ripetizione) di una Recipe VERA
        # (non CandidateRecipe) — lo scenario che ha innescato il bug in produzione.
        db.add(ConsumedEntry(
            id="cons_recent_real_recipe",
            profile_id="persona_a",
            date=date.today().isoformat(),
            meal_type="cena",
            type="planned",
            consumed_recipe_id="rec_stufato_maiale",  # Recipe reale nel fixture
        ))
        db.commit()

        response = client.post(
            "/planner/change-recipe",
            params={
                "profile_id_A": "persona_a",
                "profile_id_B": "persona_b",
                "meal_type": "cena",
                "current_date": date.today().isoformat(),
                "max_time_minutes": 150,
            },
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
