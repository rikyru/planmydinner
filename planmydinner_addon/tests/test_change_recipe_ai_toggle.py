"""
/planner/change-recipe deve proporre prima le ricette del catalogo (default,
nessuna chiamata AI) e generare opzioni AI aggiuntive solo su richiesta
esplicita (use_llm_fill=true), usate dal pulsante "Proponi N con AI".
"""
from datetime import date
from unittest.mock import patch

from planmydinner_addon import schemas
from planmydinner_addon.planner import PlannerEngine


def _fake_llm_option(suffix="1"):
    return schemas.ChangeRecipeOption(
        option_id=f"ai-opt-{suffix}",
        recipe_id=f"ai-recipe-{suffix}",
        name=f"Ricetta AI {suffix}",
        total_time_minutes=25,
        difficulty="facile",
        cleanup_score="facile",
        key_ingredients=["ingrediente"],
        divergence_strategy="llm_generated",
        divergence_details="generata dall'AI",
    )


class TestChangeRecipeDefaultIsCatalogOnly:
    def test_default_call_never_returns_ai_options(self, client, planner_seeded_database):
        # Anche con un LLM che risponderebbe con successo, la chiamata di default
        # (nessun use_llm_fill) non deve includerlo: solo catalogo.
        with patch.object(PlannerEngine, "_generate_llm_recipe_suggestion", return_value=_fake_llm_option()):
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
        options = response.json()
        assert options, "il catalogo del fixture deve produrre almeno un'opzione"
        assert all(o["divergence_strategy"] != "llm_generated" for o in options)

    def test_use_llm_fill_true_adds_ai_options(self, client, planner_seeded_database):
        with patch.object(PlannerEngine, "_generate_llm_recipe_suggestion", return_value=_fake_llm_option()):
            response = client.post(
                "/planner/change-recipe",
                params={
                    "profile_id_A": "persona_a",
                    "profile_id_B": "persona_b",
                    "meal_type": "cena",
                    "current_date": date.today().isoformat(),
                    "max_time_minutes": 150,
                    "use_llm_fill": "true",
                    "target_count": 10,
                },
            )
        assert response.status_code == 200
        options = response.json()
        assert any(o["divergence_strategy"] == "llm_generated" for o in options)

    def test_empty_catalog_still_falls_back_to_ai(self, client, planner_seeded_database):
        # Rete di sicurezza: se il catalogo non produce nulla (qui grazie a un
        # tempo massimo irraggiungibile), l'AI scatta anche a use_llm_fill=False.
        with patch.object(PlannerEngine, "_generate_llm_recipe_suggestion", return_value=_fake_llm_option()):
            response = client.post(
                "/planner/change-recipe",
                params={
                    "profile_id_A": "persona_a",
                    "profile_id_B": "persona_b",
                    "meal_type": "cena",
                    "current_date": date.today().isoformat(),
                    "max_time_minutes": 1,
                },
            )
        assert response.status_code == 200
        options = response.json()
        assert any(o["divergence_strategy"] == "llm_generated" for o in options)
