"""
Cambio di un singolo componente del pasto (carbo / proteina / verdura).

Due cose che non funzionavano: l'endpoint pretendeva un vecchio StructuredMealPlan
importato, quindi con le sole PlanRules (il caso normale) rispondeva 404 e i tre
bottoni non facevano nulla; e la variante scelta restava una bozza invisibile,
persa dopo quella sera invece di diventare una ricetta riproponibile.
"""
import uuid
from datetime import date

import pytest

from planmydinner_addon.database import (
    CandidateRecipe, GeneratedWeeklyPlan, PlanRules, Recipe, UserProfile,
)
from planmydinner_addon.planner import PlannerEngine

GIORNO = date(2026, 3, 2)  # lunedì


def _qty(g):
    return {"qty": float(g), "unit": "g", "grams_equiv": float(g)}


def _recipe_data(name="Ceci con pane e pomodorini"):
    return {
        "name": name, "description": "", "is_composed_dish": False,
        "content": [
            {"name": "pane", "food_group": "carboidrati",
             "quantities": {"aa": _qty(90), "bb": _qty(90)}},
            {"name": "ceci bolliti", "food_group": "legumi",
             "quantities": {"aa": _qty(120), "bb": _qty(120)}},
            {"name": "pomodorini", "food_group": "verdure",
             "quantities": {"aa": _qty(150), "bb": _qty(150)}},
        ],
        "steps": [], "total_time_minutes": 20, "difficulty": "facile",
        "tags": {"mood": ["normale"], "cooking_methods": ["tegame"], "cleanup": ["facile"]},
    }


@pytest.fixture
def piano_con_regole(setup_database):
    """Profili + PlanRules (nessuno StructuredMealPlan legacy) + un piano salvato."""
    db = setup_database
    db.add(UserProfile(id="aa", name="A", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.add(UserProfile(id="bb", name="B", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.add(PlanRules(
        id=str(uuid.uuid4()), profile_id="aa", imported_at="2026-03-01",
        carb_target={"pranzo": 80.0, "cena": 80.0},
        protein_target={"pranzo": 150.0, "cena": 130.0},
        carb_options={"cena": [
            {"name": "riso", "quantity": 80, "unit": "g"},
            {"name": "patate", "quantity": 300, "unit": "g"},
            {"name": "pane comune", "quantity": 100, "unit": "g"},
        ]},
        protein_options={"cena": [
            {"name": "ceci secchi - bolliti", "quantity": 120, "unit": "g"},
            {"name": "petto di pollo", "quantity": 130, "unit": "g"},
            {"name": "lenticchie", "quantity": 150, "unit": "g"},
            "secche - bollite",          # frammento orfano del parser PDF
        ]},
        frequency_targets={"legumi": {"min": 1, "max": 4}},
        free_meal_quota=2,
    ))
    rid = str(uuid.uuid4())
    db.add(CandidateRecipe(id=rid, status="approved", recipe_data=_recipe_data()))
    db.add(GeneratedWeeklyPlan(
        id=str(uuid.uuid4()), profile_id_A="aa", profile_id_B="bb",
        week_start_date=GIORNO.isoformat(), generated_at=GIORNO.isoformat(),
        daily_plans=[{
            "date": GIORNO.isoformat(),
            "meals": [
                {"meal_type": "pranzo", "items": []},
                {"meal_type": "cena", "items": [{
                    "item_name": "Ceci con pane e pomodorini", "food_group": "recipe",
                    "quantity": 1, "unit": "recipe", "is_estimated_unit": False,
                    "alternatives": [], "recipe_id": rid,
                }]},
            ],
        }],
    ))
    db.commit()
    return db, rid


class TestEndpointSenzaPianoLegacy:
    def test_funziona_con_le_sole_plan_rules(self, client, piano_con_regole):
        """Era il bug: con le PlanRules ma senza StructuredMealPlan rispondeva 404."""
        db, rid = piano_con_regole
        for componente in ("carb", "protein", "veg"):
            resp = client.post("/planner/change-component", params={
                "profile_id_A": "aa", "profile_id_B": "bb", "meal_type": "cena",
                "current_date": GIORNO.isoformat(), "recipe_id": rid, "component": componente,
            })
            assert resp.status_code == 200, f"{componente}: {resp.status_code} {resp.text[:120]}"
            assert resp.json(), f"{componente}: nessuna alternativa"

    def test_404_senza_nessun_piano(self, client, piano_con_regole):
        resp = client.post("/planner/change-component", params={
            "profile_id_A": "sconosciuto", "profile_id_B": "bb", "meal_type": "cena",
            "current_date": GIORNO.isoformat(), "recipe_id": "x", "component": "carb",
        })
        assert resp.status_code == 404


class TestAlternativeDalPiano:
    def test_ogni_alternativa_usa_la_sua_grammatura(self, piano_con_regole):
        """80 g di riso e 300 g di patate non sono intercambiabili a parità di peso."""
        db, rid = piano_con_regole
        p = PlannerEngine(db)
        rules = p._get_latest_plan_rules("aa")
        meal = p._rules_to_component_options(rules, "cena")

        opts = p.get_component_alternatives(
            rid, "carb", meal, p._get_user_profile("aa"), p._get_user_profile("bb"),
        )

        grammi = {}
        for o in opts:
            ingr, _ = p._get_recipe_content(o.recipe_id)
            for i in ingr:
                fg = i.food_group if not isinstance(i, dict) else i["food_group"]
                if fg == "carboidrati":
                    nome = i.name if not isinstance(i, dict) else i["name"]
                    q = next(iter((i.quantities if not isinstance(i, dict) else i["quantities"]).values()))
                    grammi[nome.lower()] = float(q.grams_equiv if not isinstance(q, dict) else q["grams_equiv"])
        assert grammi.get("riso") == 80
        assert grammi.get("patate") == 300

    def test_scarta_i_frammenti_del_parser(self, piano_con_regole):
        """"secche - bollite" e' un pezzo orfano: proporlo darebbe un piatto di "Secche"."""
        db, rid = piano_con_regole
        p = PlannerEngine(db)
        meal = p._rules_to_component_options(p._get_latest_plan_rules("aa"), "cena")

        nomi = [i.item_name.lower() for i in meal.items]
        assert not any(n.startswith("secche") for n in nomi), nomi

    def test_le_proteine_sono_quelle_del_piano(self, piano_con_regole):
        db, rid = piano_con_regole
        p = PlannerEngine(db)
        meal = p._rules_to_component_options(p._get_latest_plan_rules("aa"), "cena")

        proteine = {i.item_name.lower() for i in meal.items if i.food_group == "proteina"}
        assert "petto di pollo" in proteine
        assert "lenticchie" in proteine


class TestNomeDelPiatto:
    def test_usa_la_verdura_vera_non_una_a_caso(self):
        """Il nome prometteva radicchio mentre nel piatto c'erano pomodorini."""
        content = [
            {"name": "ceci", "food_group": "legumi"},
            {"name": "farro", "food_group": "carboidrati"},
            {"name": "pomodorini", "food_group": "verdure"},
        ]
        assert PlannerEngine._make_display_name(content) == "Ceci con farro e pomodorini"

    def test_verdura_generica_usa_il_catalogo(self):
        content = [
            {"name": "ceci", "food_group": "legumi"},
            {"name": "farro", "food_group": "carboidrati"},
            {"name": "verdure", "food_group": "verdure"},
        ]
        nome = PlannerEngine._make_display_name(content)
        assert nome.startswith("Ceci con farro e ")
        assert "verdure" not in nome.lower()


class TestPastoAdattatoDiventaRicetta:
    def _prima_alternativa(self, p, rid, componente="carb"):
        meal = p._rules_to_component_options(p._get_latest_plan_rules("aa"), "cena")
        opts = p.get_component_alternatives(
            rid, componente, meal, p._get_user_profile("aa"), p._get_user_profile("bb"),
        )
        assert opts
        return opts[0]

    def test_applicare_una_variante_crea_una_ricetta_vera(self, piano_con_regole):
        db, rid = piano_con_regole
        p = PlannerEngine(db)
        scelta = self._prima_alternativa(p, rid)

        assert p.apply_recipe_to_plan("aa", "bb", "cena", GIORNO, scelta.recipe_id)

        db.expire_all()
        nuova = db.query(Recipe).filter(Recipe.name == scelta.name).first()
        assert nuova is not None, "la variante doveva diventare una Recipe"
        assert "true" in (nuova.tags or {}).get("adattata", [])
        # la bozza non deve restare: sarebbe un doppione nel pool
        assert db.query(CandidateRecipe).filter(CandidateRecipe.id == scelta.recipe_id).first() is None

    def test_lo_slot_punta_alla_ricetta_salvata(self, piano_con_regole):
        db, rid = piano_con_regole
        p = PlannerEngine(db)
        scelta = self._prima_alternativa(p, rid)

        p.apply_recipe_to_plan("aa", "bb", "cena", GIORNO, scelta.recipe_id)

        db.expire_all()
        nuova = db.query(Recipe).filter(Recipe.name == scelta.name).first()
        plan = db.query(GeneratedWeeklyPlan).filter(GeneratedWeeklyPlan.profile_id_A == "aa").first()
        cena = next(m for m in plan.daily_plans[0]["meals"] if m["meal_type"] == "cena")
        assert cena["items"][0]["recipe_id"] == nuova.id

    def test_e_riproponibile_dal_planner(self, piano_con_regole):
        db, rid = piano_con_regole
        p = PlannerEngine(db)
        scelta = self._prima_alternativa(p, rid)

        p.apply_recipe_to_plan("aa", "bb", "cena", GIORNO, scelta.recipe_id)

        db.expire_all()
        nuova = db.query(Recipe).filter(Recipe.name == scelta.name).first()
        assert any(r.id == nuova.id for r in PlannerEngine(db)._get_all_recipes())

    def test_applicarla_due_volte_non_crea_doppioni(self, piano_con_regole):
        db, rid = piano_con_regole
        p = PlannerEngine(db)
        prima = self._prima_alternativa(p, rid)
        p.apply_recipe_to_plan("aa", "bb", "cena", GIORNO, prima.recipe_id)
        db.expire_all()

        # stessa variante richiesta di nuovo: nuova bozza, stesso nome
        seconda = self._prima_alternativa(p, rid)
        p.apply_recipe_to_plan("aa", "bb", "cena", GIORNO, seconda.recipe_id)

        db.expire_all()
        omonime = db.query(Recipe).filter(Recipe.name == prima.name).all()
        assert len(omonime) == 1, f"{len(omonime)} copie della stessa ricetta"

    def test_un_pasto_da_foto_non_diventa_una_ricetta(self, piano_con_regole):
        """I pasti fotografati hanno il loro catalogo: non vanno trasformati in
        ricette da cucinare solo perche' li si mette nel piano."""
        db, rid = piano_con_regole
        data = _recipe_data("Pasto in mensa")
        data["tags"] = {"mensa": ["true"]}
        cid = str(uuid.uuid4())
        db.add(CandidateRecipe(id=cid, status="draft_structured", recipe_data=data))
        db.commit()

        PlannerEngine(db).apply_recipe_to_plan("aa", "bb", "cena", GIORNO, cid)

        db.expire_all()
        assert db.query(Recipe).filter(Recipe.name == "Pasto in mensa").first() is None
        assert db.query(CandidateRecipe).filter(CandidateRecipe.id == cid).first() is not None

    def test_nessun_piano_per_quella_data_non_esplode(self, piano_con_regole):
        """C'era un NameError nel log del ramo "piano non trovato": sollevava
        un'eccezione invece di restituire False."""
        db, rid = piano_con_regole
        assert PlannerEngine(db).apply_recipe_to_plan(
            "aa", "bb", "cena", date(2027, 1, 1), rid,
        ) is False


class TestIngredienteScrittoAMano:
    """Le alternative proposte vengono dal piano, ma non sempre c'e' quello che
    si ha in casa: si deve poter scrivere "bresaola"."""

    def _chiama(self, client, nome, componente="protein", grammi=None):
        return client.post("/planner/custom-component", params={
            "profile_id_A": "aa", "profile_id_B": "bb", "meal_type": "cena",
            "recipe_id": self.rid, "component": componente,
        }, json={"name": nome, "grams": grammi})

    @pytest.fixture(autouse=True)
    def _setup(self, piano_con_regole):
        self.db, self.rid = piano_con_regole

    def test_crea_la_variante_con_l_ingrediente_scritto(self, client):
        resp = self._chiama(client, "bresaola")

        assert resp.status_code == 200, resp.text
        opzione = resp.json()
        assert "bresaola" in opzione["name"].lower()
        assert opzione["key_ingredients"] == ["bresaola"]

    def test_la_categoria_e_dedotta_dal_nome(self, client):
        """Senza categoria specifica la ricetta sfuggirebbe ai limiti di rotazione."""
        resp = self._chiama(client, "bresaola")
        p = PlannerEngine(self.db)

        assert p._get_main_protein_category(resp.json()["recipe_id"]) == "carne_rossa"

    def test_usa_le_grammature_del_piano_se_non_specificate(self, client):
        resp = self._chiama(client, "bresaola")
        ingr, _ = PlannerEngine(self.db)._get_recipe_content(resp.json()["recipe_id"])

        bres = next(i for i in ingr if (i.name if not isinstance(i, dict) else i["name"]) == "bresaola")
        q = next(iter((bres.quantities if not isinstance(bres, dict) else bres["quantities"]).values()))
        grammi = float(q.grams_equiv if not isinstance(q, dict) else q["grams_equiv"])
        assert grammi == 130, "doveva usare protein_target della cena"

    def test_grammi_espliciti(self, client):
        resp = self._chiama(client, "bresaola", grammi=90)
        ingr, _ = PlannerEngine(self.db)._get_recipe_content(resp.json()["recipe_id"])

        bres = next(i for i in ingr if (i.name if not isinstance(i, dict) else i["name"]) == "bresaola")
        q = next(iter((bres.quantities if not isinstance(bres, dict) else bres["quantities"]).values()))
        assert float(q.grams_equiv if not isinstance(q, dict) else q["grams_equiv"]) == 90

    def test_conserva_gli_altri_componenti(self, client):
        resp = self._chiama(client, "bresaola")
        ingr, _ = PlannerEngine(self.db)._get_recipe_content(resp.json()["recipe_id"])

        nomi = {(i.name if not isinstance(i, dict) else i["name"]).lower() for i in ingr}
        assert "pane" in nomi and "pomodorini" in nomi
        assert "ceci bolliti" not in nomi, "la proteina vecchia doveva sparire"

    def test_funziona_anche_per_carbo_e_verdura(self, client):
        for componente, atteso in (("carb", "focaccia"), ("veg", "cicoria")):
            resp = self._chiama(client, atteso, componente=componente)
            assert resp.status_code == 200, f"{componente}: {resp.text[:120]}"
            assert atteso in resp.json()["name"].lower()

    def test_applicandola_diventa_una_ricetta_riproponibile(self, client):
        opzione = self._chiama(client, "bresaola").json()

        applica = client.post("/planner/apply-recipe-option", params={
            "profile_id_A": "aa", "profile_id_B": "bb", "meal_type": "cena",
            "current_date": GIORNO.isoformat(), "recipe_id": opzione["recipe_id"],
        })

        assert applica.status_code == 200
        self.db.expire_all()
        salvata = self.db.query(Recipe).filter(Recipe.name == opzione["name"]).first()
        assert salvata is not None
        assert "true" in (salvata.tags or {}).get("adattata", [])

    @pytest.mark.parametrize("nome,grammi,atteso", [
        ("", None, 422),
        ("   ", None, 422),
        ("x" * 81, None, 422),
        ("bresaola", 0, 422),
        ("bresaola", 5000, 422),
    ])
    def test_input_non_validi(self, client, nome, grammi, atteso):
        assert self._chiama(client, nome, grammi=grammi).status_code == atteso

    def test_componente_sconosciuto(self, client):
        assert self._chiama(client, "bresaola", componente="dolce").status_code == 422

    def test_ricetta_inesistente(self, client):
        resp = client.post("/planner/custom-component", params={
            "profile_id_A": "aa", "profile_id_B": "bb", "meal_type": "cena",
            "recipe_id": "non-esiste", "component": "protein",
        }, json={"name": "bresaola"})
        assert resp.status_code == 404
