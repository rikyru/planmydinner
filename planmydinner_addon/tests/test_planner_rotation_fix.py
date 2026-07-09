"""
Replica lo scenario del server di casa (2026-07-09):
- ricette con food_group generico "proteina" (pollo/vitellone/salmone...)
- nessuna ricetta per le categorie uova/formaggio richieste dal piano
- LLM non disponibile

Il piano generato deve comunque rispettare le frequency_targets:
carne_bianca max 2, carne_rossa max 1, uova min 2, formaggio min 2, legumi 3-5.
"""
import uuid
from datetime import date

import pytest

from planmydinner_addon.database import CandidateRecipe, PlanRules, UserProfile
from planmydinner_addon.planner import PlannerEngine
from planmydinner_addon import schemas

START = date(2026, 3, 2)  # lunedì (freeze_time in conftest è 2026-02-24)

# Frequency targets identici al piano importato sul server
FREQ_TARGETS = {
    "uova": {"min": 2, "max": 4},
    "carne_rossa": {"min": 0, "max": 1},
    "carne_bianca": {"min": 2, "max": 2},
    "legumi": {"min": 3, "max": 5},
    "formaggio": {"min": 2, "max": 2},
}


def _qty(g):
    return {"qty": float(g), "unit": "g", "grams_equiv": float(g)}


def _recipe(name, protein_name, protein_fg, carb_name="pane"):
    """Ricetta stile server: proteina con food_group GENERICO + carbo + verdure."""
    return {
        "name": name,
        "description": "",
        "is_composed_dish": False,
        "content": [
            {"name": carb_name, "food_group": "carboidrati",
             "quantities": {"riccardo": _qty(80), "cristiana": _qty(80)}},
            {"name": protein_name, "food_group": protein_fg,
             "quantities": {"riccardo": _qty(150), "cristiana": _qty(150)}},
            {"name": "verdure", "food_group": "verdure",
             "quantities": {"riccardo": _qty(150), "cristiana": _qty(150)}},
        ],
        "steps": [],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cooking_methods": ["tegame"], "cleanup": ["facile"]},
    }


@pytest.fixture
def server_like_db(setup_database):
    db = setup_database
    # Le ricette seed del conftest non servono: il pool sotto replica il server
    db.add(UserProfile(id="riccardo", name="Riccardo", allergies=[], excluded_foods=[],
                       preferences=[], equipment=[]))
    db.add(UserProfile(id="cristiana", name="Cristiana", allergies=[], excluded_foods=[],
                       preferences=[], equipment=[]))
    db.add(PlanRules(
        id=str(uuid.uuid4()),
        profile_id="riccardo",
        imported_at="2026-03-01",
        carb_target={"pranzo": 80.0, "cena": 80.0},
        protein_target={"pranzo": 150.0, "cena": 150.0},
        carb_options={"pranzo": ["pane", "pasta di semola"], "cena": ["pane", "pasta di semola"]},
        protein_options={"pranzo": ["pollo", "vitellone"], "cena": ["pollo", "vitellone"]},
        frequency_targets=FREQ_TARGETS,
        free_meal_quota=2,
    ))
    # Pool come sul server: food_group generico "proteina", niente uova/formaggio
    pool = [
        _recipe("Petto di pollo con pane", "petto di pollo", "proteina", "pane"),
        _recipe("Pollo sovracoscio con pasta", "pollo - sovracoscio - senza pelle", "proteina", "pasta di semola"),
        _recipe("Fesa di tacchino con pane", "fesa di tacchino", "proteina", "pane"),
        _recipe("Tacchino alla griglia con pasta", "tacchino", "proteina", "pasta di semola"),
        _recipe("Vitellone magro con pane", "vitellone tagli magri", "proteina", "pane"),
        _recipe("Salmone con pasta", "salmone", "proteina", "pasta di semola"),
        _recipe("Merluzzo con pane", "merluzzo", "proteina", "pane"),
        _recipe("Ceci con pane tostato", "ceci cotti", "legumi", "pane"),
        _recipe("Pasta e fagioli", "fagioli borlotti", "legumi", "pasta di semola"),
        _recipe("Lenticchie con pane", "lenticchie", "legumi", "pane"),
        _recipe("Piselli con pasta", "piselli freschi", "legumi", "pasta di semola"),
    ]
    for data in pool:
        db.add(CandidateRecipe(id=str(uuid.uuid4()), status="approved", recipe_data=data))
    db.commit()
    return db


def _category_counts(planner, weekly_plan):
    counts = {}
    for day in weekly_plan:
        for meal in day.meals:
            for item in meal.items:
                if item.recipe_id:
                    cat = planner._get_main_protein_category(item.recipe_id)
                    if cat:
                        counts[cat] = counts.get(cat, 0) + 1
    return counts


class TestRotationFix:
    def test_infer_protein_fg(self):
        assert PlannerEngine._infer_protein_fg("Vitellone Tagli Magri", "proteina") == "carne_rossa"
        assert PlannerEngine._infer_protein_fg("petto di pollo", "proteina") == "carne_bianca"
        assert PlannerEngine._infer_protein_fg("uova strapazzate", "proteine") == "uova"
        assert PlannerEngine._infer_protein_fg("mozzarella", "proteina") == "latticini"
        # food_group già specifico: non viene toccato
        assert PlannerEngine._infer_protein_fg("qualsiasi", "legumi") == "legumi"
        # nessuna keyword: resta generico
        assert PlannerEngine._infer_protein_fg("seitan speciale", "proteina") == "proteina"

    def test_get_all_recipes_normalizes_generic_protein(self, server_like_db):
        planner = PlannerEngine(server_like_db)
        by_name = {r.name: r for r in planner._get_all_recipes()}
        rec = by_name["Vitellone magro con pane"]
        fgs = {i.food_group for i in rec.content}
        assert "carne_rossa" in fgs and "proteina" not in fgs
        rec = by_name["Petto di pollo con pane"]
        assert "carne_bianca" in {i.food_group for i in rec.content}

    def test_fingerprint_includes_white_meat(self, server_like_db):
        planner = PlannerEngine(server_like_db)
        by_name = {r.name: r for r in planner._get_all_recipes()}
        fp = PlannerEngine._recipe_fingerprint(by_name["Fesa di tacchino con pane"])
        assert "fesa di tacchino" in fp and "pane" in fp

    def test_rules_to_planned_meal_respects_target(self, server_like_db):
        planner = PlannerEngine(server_like_db)
        rules = planner._get_latest_plan_rules("riccardo")
        # target uova: il piano non ha opzioni uova → usa il default di categoria
        meal = planner._rules_to_planned_meal(rules, "pranzo", "uova")
        protein = next(i for i in meal.items if i.food_group not in ("carboidrati",))
        assert protein.food_group == "uova"
        assert "uova" in protein.item_name.lower()
        # target carne_rossa: sceglie l'opzione del piano giusta (vitellone, non pollo)
        meal = planner._rules_to_planned_meal(rules, "pranzo", "carne_rossa")
        protein = next(i for i in meal.items if i.food_group == "carne_rossa")
        assert "vitellone" in protein.item_name.lower()

    def test_category_coverage_creates_templates_without_llm(self, server_like_db):
        planner = PlannerEngine(server_like_db)  # nessun LLM gateway
        rules = planner._get_latest_plan_rules("riccardo")
        planner._ensure_category_coverage(rules, "riccardo", "cristiana")
        cats = {planner._recipe_protein_cat(r) for r in planner._get_all_recipes()}
        assert "uova" in cats
        assert "formaggio" in cats
        # idempotente: rilanciare non crea altri template
        n = len(planner._get_all_recipes())
        planner._ensure_category_coverage(rules, "riccardo", "cristiana")
        assert len(planner._get_all_recipes()) == n

    def test_weekly_plan_respects_frequency_targets(self, server_like_db):
        planner = PlannerEngine(server_like_db)  # LLM spento, come sul server
        weekly_plan = planner.generate_weekly_plan("riccardo", "cristiana", START)
        assert weekly_plan, "piano non generato"

        counts = _category_counts(planner, weekly_plan)
        filled = sum(counts.values())
        assert filled >= 12, f"troppi slot vuoti: {counts}"

        assert counts.get("carne_bianca", 0) <= 2, f"carne_bianca oltre il max: {counts}"
        assert counts.get("carne_rossa", 0) <= 1, f"carne_rossa oltre il max: {counts}"
        assert counts.get("uova", 0) >= 2, f"uova sotto il min: {counts}"
        assert counts.get("formaggio", 0) >= 2, f"formaggio sotto il min: {counts}"
        assert counts.get("legumi", 0) >= 3, f"legumi sotto il min: {counts}"

    def test_no_same_protein_category_pranzo_and_cena(self, server_like_db):
        planner = PlannerEngine(server_like_db)
        weekly_plan = planner.generate_weekly_plan("riccardo", "cristiana", START)
        for day in weekly_plan:
            cats = []
            for meal in day.meals:
                for item in meal.items:
                    if item.recipe_id:
                        cat = planner._get_main_protein_category(item.recipe_id)
                        if cat:
                            cats.append(cat)
            dupes = [c for c in set(cats) if cats.count(c) > 1]
            assert not dupes, f"{day.date}: stessa categoria pranzo e cena: {dupes}"
