"""
Arricchimento mirato del catalogo.

La monotonia del piano non nasce solo dalla logica di rotazione: se il piano
nutrizionale ammette fagioli, piselli, farro e quinoa ma nessuna ricetta li usa,
il planner e' costretto a ripetere i pochi ingredienti che ha. Questi test
coprono il calcolo dei "buchi" e la generazione delle ricette che li chiudono.
"""
import uuid

import pytest

from planmydinner_addon.database import CandidateRecipe, PlanRules, Recipe, UserProfile
from planmydinner_addon.planner import PlannerEngine


def _qty(g):
    return {"qty": float(g), "unit": "g", "grams_equiv": float(g)}


def _recipe_data(name, protein_name, protein_fg, carb_name):
    return {
        "name": name, "description": "", "is_composed_dish": False,
        "content": [
            {"name": carb_name, "food_group": "carboidrati",
             "quantities": {"aa": _qty(80), "bb": _qty(80)}},
            {"name": protein_name, "food_group": protein_fg,
             "quantities": {"aa": _qty(150), "bb": _qty(150)}},
            {"name": "verdure", "food_group": "verdure",
             "quantities": {"aa": _qty(150), "bb": _qty(150)}},
        ],
        "steps": [], "total_time_minutes": 25, "difficulty": "facile",
        "tags": {"mood": ["normale"], "cooking_methods": ["tegame"], "cleanup": ["facile"]},
    }


@pytest.fixture
def catalogo_incompleto(setup_database):
    """Il piano ammette molti ingredienti, il catalogo ne usa due."""
    db = setup_database
    db.add(UserProfile(id="aa", name="A", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.add(UserProfile(id="bb", name="B", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.add(PlanRules(
        id=str(uuid.uuid4()), profile_id="aa", imported_at="2026-03-01",
        carb_target={"pranzo": 80.0, "cena": 80.0},
        protein_target={"pranzo": 150.0, "cena": 130.0},
        carb_options={"cena": [
            {"name": "pane comune", "quantity": 100, "unit": "g"},
            {"name": "farro", "quantity": 80, "unit": "g"},
            {"name": "quinoa", "quantity": 70, "unit": "g"},
            # frammento dal parser del PDF: niente grammatura, va ignorato
            "secche - bollite",
        ]},
        protein_options={"cena": [
            {"name": "ceci secchi - bolliti", "quantity": 120, "unit": "g"},
            {"name": "fagioli Borlotti freschi - bolliti", "quantity": 200, "unit": "g"},
            {"name": "piselli freschi - cotti in padella", "quantity": 150, "unit": "g"},
            "alta qualita' - sgrassato",
        ]},
        frequency_targets={"legumi": {"min": 2, "max": 5}},
        free_meal_quota=2,
    ))
    db.add(CandidateRecipe(id=str(uuid.uuid4()), status="approved",
                           recipe_data=_recipe_data("Zuppa di ceci", "ceci cotti", "legumi", "pane")))
    db.commit()
    return db


class TestCatalogGaps:
    def test_trova_gli_ingredienti_scoperti(self, catalogo_incompleto):
        p = PlannerEngine(catalogo_incompleto)
        rules = p._get_latest_plan_rules("aa")

        gaps = p.catalog_gaps(rules)

        mancanti = {x["name"] for x in gaps["missing_proteins"]}
        assert "fagioli Borlotti freschi - bolliti" in mancanti
        assert "piselli freschi - cotti in padella" in mancanti
        # i ceci ci sono gia', anche se scritti in modo diverso nella ricetta
        assert not any("ceci" in n.lower() for n in mancanti)

    def test_ignora_i_frammenti_del_parser(self, catalogo_incompleto):
        """Il parser del PDF spezza certe voci: i pezzi senza grammatura non sono
        ingredienti veri e chiedere una ricetta su di essi non ha senso."""
        p = PlannerEngine(catalogo_incompleto)
        rules = p._get_latest_plan_rules("aa")

        gaps = p.catalog_gaps(rules)

        nomi = {x["name"] for x in gaps["proteins"] + gaps["carbs"]}
        assert "secche - bollite" not in nomi
        assert "alta qualita' - sgrassato" not in nomi

    def test_i_carboidrati_scoperti(self, catalogo_incompleto):
        p = PlannerEngine(catalogo_incompleto)
        gaps = p.catalog_gaps(p._get_latest_plan_rules("aa"))

        mancanti = {x["name"] for x in gaps["missing_carbs"]}
        assert mancanti == {"farro", "quinoa"}, mancanti

    def test_endpoint(self, client, catalogo_incompleto):
        resp = client.get("/planner/catalog-gaps", params={"profile_id_A": "aa"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["carbs_total"] == 3 and data["carbs_covered"] == 1
        assert "farro" in data["missing_carbs"]

    def test_endpoint_404_senza_piano(self, client, catalogo_incompleto):
        resp = client.get("/planner/catalog-gaps", params={"profile_id_A": "sconosciuto"})
        assert resp.status_code == 404


class TestEnrichCatalog:
    def test_senza_llm_non_inventa_nulla(self, catalogo_incompleto):
        p = PlannerEngine(catalogo_incompleto)  # nessun gateway
        result = p.enrich_catalog(p._get_latest_plan_rules("aa"), "aa", "bb", limit=3)
        assert result["created"] == []
        assert result["skipped"]

    def test_crea_ricette_vere_per_i_buchi(self, catalogo_incompleto, monkeypatch):
        """Le ricette generate devono essere Recipe (visibili e modificabili in
        Ricette), non CandidateRecipe nascoste, e portare la categoria proteica
        giusta — altrimenti sfuggono ai limiti di rotazione."""
        db = catalogo_incompleto
        p = PlannerEngine(db)
        p.llm_gateway = object()  # basta che non sia None

        creati = []

        def finto_llm(meal_plan_A, *a, **kw):
            protein = next(i for i in meal_plan_A.items if i.food_group == "proteina")
            carb = next(i for i in meal_plan_A.items if i.food_group == "carboidrati")
            nome = f"Piatto di {protein.item_name} con {carb.item_name}"
            cid = str(uuid.uuid4())
            db.add(CandidateRecipe(
                id=cid, status="draft_structured",
                recipe_data=_recipe_data(nome, protein.item_name, "proteina", carb.item_name),
            ))
            db.commit()
            creati.append(nome)
            return type("R", (), {"recipe_id": cid, "name": nome})()

        monkeypatch.setattr(p, "_generate_llm_recipe_suggestion", finto_llm)

        result = p.enrich_catalog(p._get_latest_plan_rules("aa"), "aa", "bb", limit=2)

        assert len(result["created"]) == 2
        for info in result["created"]:
            rec = db.query(Recipe).filter(Recipe.id == info["id"]).first()
            assert rec is not None, "la ricetta deve essere una Recipe, non una candidate"
            assert "true" in (rec.tags or {}).get("ai", [])
            groups = {i["food_group"] for i in rec.content}
            assert "proteina" not in groups, "food_group proteico non specializzato"
        # nessuna candidate orfana: farebbe un doppione nel pool
        assert db.query(CandidateRecipe).filter(CandidateRecipe.status == "draft_structured").count() == 0

    def test_chiude_davvero_i_buchi(self, catalogo_incompleto, monkeypatch):
        db = catalogo_incompleto
        p = PlannerEngine(db)
        p.llm_gateway = object()

        def finto_llm(meal_plan_A, *a, **kw):
            protein = next(i for i in meal_plan_A.items if i.food_group == "proteina")
            carb = next(i for i in meal_plan_A.items if i.food_group == "carboidrati")
            cid = str(uuid.uuid4())
            db.add(CandidateRecipe(
                id=cid, status="draft_structured",
                recipe_data=_recipe_data(f"X {protein.item_name}", protein.item_name,
                                         "proteina", carb.item_name),
            ))
            db.commit()
            return type("R", (), {"recipe_id": cid, "name": f"X {protein.item_name}"})()

        monkeypatch.setattr(p, "_generate_llm_recipe_suggestion", finto_llm)
        rules = p._get_latest_plan_rules("aa")
        prima = len(p.catalog_gaps(rules)["missing_proteins"])

        p.enrich_catalog(rules, "aa", "bb", limit=5)

        dopo = len(p.catalog_gaps(rules)["missing_proteins"])
        assert dopo < prima, f"buchi invariati: {prima} -> {dopo}"

    def test_limit_fuori_range(self, client, catalogo_incompleto):
        resp = client.post("/planner/enrich-catalog", params={"profile_id_A": "aa", "limit": 99})
        assert resp.status_code == 422


class TestDedupe:
    def test_trova_i_doppioni(self, catalogo_incompleto):
        db = catalogo_incompleto
        for _ in range(2):
            db.add(CandidateRecipe(id=str(uuid.uuid4()), status="approved",
                                   recipe_data=_recipe_data("Zuppa di ceci", "ceci cotti", "legumi", "pane")))
        db.commit()

        dupes = PlannerEngine(db).find_duplicate_recipes()
        assert any(d["name"] == "Zuppa di ceci" and d["count"] == 3 for d in dupes), dupes

    def test_non_cancella_una_ricetta_usata_dal_piano(self, client, catalogo_incompleto):
        """Cancellare la copia puntata da un piano salvato lascerebbe uno slot che
        rimanda a una ricetta inesistente."""
        from planmydinner_addon.database import GeneratedWeeklyPlan
        db = catalogo_incompleto
        ids = []
        for _ in range(2):
            cid = str(uuid.uuid4())
            ids.append(cid)
            db.add(CandidateRecipe(id=cid, status="approved",
                                   recipe_data=_recipe_data("Zuppa di ceci", "ceci cotti", "legumi", "pane")))
        db.commit()
        # il piano punta alla SECONDA copia, che quindi va conservata
        db.add(GeneratedWeeklyPlan(
            id=str(uuid.uuid4()), profile_id_A="aa", profile_id_B="bb",
            week_start_date="2026-03-02", generated_at="2026-03-02",
            daily_plans=[{"date": "2026-03-02", "meals": [
                {"meal_type": "cena", "items": [{
                    "item_name": "Zuppa di ceci", "food_group": "recipe", "quantity": 1,
                    "unit": "recipe", "is_estimated_unit": False, "alternatives": [],
                    "recipe_id": ids[1],
                }]},
            ]}],
        ))
        db.commit()

        resp = client.post("/planner/dedupe-catalog", params={"profile_id_A": "aa", "apply": "true"})

        assert resp.status_code == 200
        rimossi = {r["id"] for r in resp.json()["removed"]}
        assert ids[1] not in rimossi, "cancellata la copia usata dal piano"
        db.expire_all()
        assert db.query(CandidateRecipe).filter(CandidateRecipe.id == ids[1]).first() is not None

    def test_dry_run_non_cancella(self, client, catalogo_incompleto):
        db = catalogo_incompleto
        db.add(CandidateRecipe(id=str(uuid.uuid4()), status="approved",
                               recipe_data=_recipe_data("Zuppa di ceci", "ceci cotti", "legumi", "pane")))
        db.commit()
        prima = db.query(CandidateRecipe).count()

        resp = client.post("/planner/dedupe-catalog", params={"profile_id_A": "aa"})

        assert resp.status_code == 200
        assert resp.json()["removable"], "il dry-run deve dire cosa toglierebbe"
        assert db.query(CandidateRecipe).count() == prima

    def test_apply_tiene_una_copia(self, client, catalogo_incompleto):
        db = catalogo_incompleto
        for _ in range(2):
            db.add(CandidateRecipe(id=str(uuid.uuid4()), status="approved",
                                   recipe_data=_recipe_data("Zuppa di ceci", "ceci cotti", "legumi", "pane")))
        db.commit()

        resp = client.post("/planner/dedupe-catalog", params={"profile_id_A": "aa", "apply": "true"})

        assert resp.status_code == 200
        assert len(resp.json()["removed"]) == 2
        db.expire_all()
        rimaste = [r for r in PlannerEngine(db)._get_all_recipes() if r.name == "Zuppa di ceci"]
        assert len(rimaste) == 1


class TestCategoriaProteica:
    def test_deduce_la_categoria_dall_ingrediente_se_l_opzione_non_basta(self, catalogo_incompleto):
        """L'opzione del piano si chiama "pesci di mare (media)" e non e'
        riconoscibile; l'ingrediente scelto dall'AI ("filetti di branzino") si'.
        Senza categoria specifica la ricetta sfuggirebbe ai limiti di rotazione."""
        db = catalogo_incompleto
        p = PlannerEngine(db)
        cid = str(uuid.uuid4())
        db.add(CandidateRecipe(
            id=cid, status="draft_structured",
            recipe_data=_recipe_data("Branzino al forno", "filetti di branzino", "proteina", "patate"),
        ))
        db.commit()

        rec = p._promote_candidate_to_recipe(cid, protein_food_group="proteina")

        assert rec is not None
        gruppi = {i["food_group"] for i in rec.content}
        assert "pesce" in gruppi, gruppi

    def test_pesci_al_plurale_e_riconosciuto(self):
        assert PlannerEngine._infer_protein_fg("pesci di mare (media)") == "pesce"
