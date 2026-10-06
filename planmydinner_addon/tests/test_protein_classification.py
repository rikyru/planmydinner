"""La categoria proteica di una ricetta si deduce dal nome quando il
food_group è generico ("proteina") — così le ricette importate rientrano
nelle quote del piano (pesce/carne_rossa/… invece di restare 'proteina')."""
import pytest

from planmydinner_addon import schemas
from planmydinner_addon.planner import PlannerEngine


def _recipe(protein_name, fg="proteina"):
    return schemas.Recipe.model_validate({
        "id": "x", "name": "t", "is_composed_dish": False,
        "content": [
            {"name": protein_name, "food_group": fg,
             "quantities": {"persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150}}},
            {"name": "Pane", "food_group": "carboidrati",
             "quantities": {"persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80}}},
        ],
        "steps": [], "total_time_minutes": 20, "difficulty": "facile", "tags": {},
    })


@pytest.mark.parametrize("name,expected", [
    ("Merluzzo", "pesce"),
    ("Salmone", "pesce"),
    ("Gamberetti", "pesce"),
    ("Manzo", "carne_rossa"),
    ("Bresaola", "carne_rossa"),
    ("Petto di pollo", "carne_bianca"),
    ("Lenticchie", "legumi"),
    ("Uova", "uova"),
    ("Mozzarella", "formaggio"),
])
def test_protein_cat_inferred_from_name_when_generic(setup_database, name, expected):
    assert PlannerEngine(setup_database)._recipe_protein_cat(_recipe(name)) == expected


def test_specific_food_group_wins(setup_database):
    # se il food_group è già specifico, resta quello
    assert PlannerEngine(setup_database)._recipe_protein_cat(_recipe("qualcosa", fg="pesce")) == "pesce"
