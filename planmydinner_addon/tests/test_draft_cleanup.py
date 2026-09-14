"""
Pulizia delle bozze di ricetta mai scelte.

Ogni apertura del menu "cambia carbo/proteina/verdura" crea una ventina di
CandidateRecipe draft_structured, e le scartate restavano nel database per
sempre. Questi test fissano cosa si puo' buttare e soprattutto cosa NON si
tocca: una bozza appena proposta (l'utente ha il menu aperto), una usata da un
piano o da un pasto registrato, i pasti da foto, i pasti fissi.
"""
import uuid
from datetime import date, datetime, timedelta

import pytest

from planmydinner_addon.database import (
    CandidateRecipe, ConsumedEntry, GeneratedWeeklyPlan, PlanRules, UserProfile,
)
from planmydinner_addon.planner import PlannerEngine

GIORNO = date(2026, 3, 2)


def _qty(g):
    return {"qty": float(g), "unit": "g", "grams_equiv": float(g)}


def _data(name="Variante", tags=None):
    return {
        "name": name, "description": "", "is_composed_dish": False,
        "content": [
            {"name": "pane", "food_group": "carboidrati", "quantities": {"aa": _qty(90)}},
            {"name": "ceci", "food_group": "legumi", "quantities": {"aa": _qty(120)}},
        ],
        "steps": [], "total_time_minutes": 20, "difficulty": "facile",
        "tags": tags if tags is not None else {"mood": ["normale"]},
    }


def _vecchia():
    return (datetime.now() - timedelta(days=30)).isoformat()


def _adesso():
    return datetime.now().isoformat()


@pytest.fixture
def db_bozze(setup_database):
    db = setup_database
    db.add(UserProfile(id="aa", name="A", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.commit()
    return db


def _aggiungi(db, **kwargs):
    cid = kwargs.pop("id", None) or str(uuid.uuid4())
    cand = CandidateRecipe(id=cid, status=kwargs.pop("status", "draft_structured"),
                           recipe_data=kwargs.pop("recipe_data", _data()), **kwargs)
    db.add(cand)
    db.commit()
    return cid


class TestCosaVieneRimosso:
    def test_rimuove_una_bozza_vecchia_e_mai_scelta(self, db_bozze):
        cid = _aggiungi(db_bozze, created_at=_vecchia())

        stats = PlannerEngine(db_bozze).cleanup_orphan_drafts()

        assert stats["removed"] == 1
        assert db_bozze.query(CandidateRecipe).filter(CandidateRecipe.id == cid).first() is None

    def test_una_bozza_senza_data_e_considerata_vecchia(self, db_bozze):
        """Le bozze esistenti prima di questa colonna vengono da sessioni passate."""
        cid = _aggiungi(db_bozze, created_at=_vecchia())
        # simula una riga scritta prima che la colonna esistesse
        db_bozze.query(CandidateRecipe).filter(CandidateRecipe.id == cid).update(
            {"created_at": None}
        )
        db_bozze.commit()

        PlannerEngine(db_bozze).cleanup_orphan_drafts()

        assert db_bozze.query(CandidateRecipe).filter(CandidateRecipe.id == cid).first() is None

    def test_dry_run_conta_soltanto(self, db_bozze):
        cid = _aggiungi(db_bozze, created_at=_vecchia())

        stats = PlannerEngine(db_bozze).cleanup_orphan_drafts(dry_run=True)

        assert stats["removed"] == 1
        assert db_bozze.query(CandidateRecipe).filter(CandidateRecipe.id == cid).first() is not None


class TestCosaNonSiTocca:
    def test_una_bozza_appena_creata_resta(self, db_bozze):
        """Mentre l'utente guarda le alternative quelle bozze esistono gia': se
        sparissero, sceglierne una fallirebbe."""
        cid = _aggiungi(db_bozze, created_at=_adesso())

        PlannerEngine(db_bozze).cleanup_orphan_drafts()

        assert db_bozze.query(CandidateRecipe).filter(CandidateRecipe.id == cid).first() is not None

    def test_una_bozza_usata_dal_piano_resta(self, db_bozze):
        cid = _aggiungi(db_bozze, created_at=_vecchia())
        db_bozze.add(GeneratedWeeklyPlan(
            id=str(uuid.uuid4()), profile_id_A="aa", profile_id_B="bb",
            week_start_date=GIORNO.isoformat(), generated_at=GIORNO.isoformat(),
            daily_plans=[{"date": GIORNO.isoformat(), "meals": [
                {"meal_type": "cena", "items": [{
                    "item_name": "Variante", "food_group": "recipe", "quantity": 1,
                    "unit": "recipe", "is_estimated_unit": False, "alternatives": [],
                    "recipe_id": cid,
                }]},
            ]}],
        ))
        db_bozze.commit()

        PlannerEngine(db_bozze).cleanup_orphan_drafts()

        assert db_bozze.query(CandidateRecipe).filter(CandidateRecipe.id == cid).first() is not None

    def test_una_bozza_gia_mangiata_resta(self, db_bozze):
        cid = _aggiungi(db_bozze, created_at=_vecchia())
        db_bozze.add(ConsumedEntry(
            id=str(uuid.uuid4()), profile_id="aa", date=GIORNO.isoformat(),
            meal_type="cena", type="planned", consumed_recipe_id=cid,
        ))
        db_bozze.commit()

        PlannerEngine(db_bozze).cleanup_orphan_drafts()

        assert db_bozze.query(CandidateRecipe).filter(CandidateRecipe.id == cid).first() is not None

    @pytest.mark.parametrize("tag", ["mensa", "routine", "free_meal_estimate"])
    def test_i_cataloghi_speciali_restano(self, db_bozze, tag):
        """Pasti da foto, pasti fissi e stime dei pasti liberi vivono come bozze:
        non sono scarti di un menu di alternative."""
        cid = _aggiungi(db_bozze, created_at=_vecchia(),
                        recipe_data=_data(tags={tag: ["true"]}))

        PlannerEngine(db_bozze).cleanup_orphan_drafts()

        assert db_bozze.query(CandidateRecipe).filter(CandidateRecipe.id == cid).first() is not None

    def test_una_candidate_approvata_resta(self, db_bozze):
        cid = _aggiungi(db_bozze, status="approved", created_at=_vecchia())

        PlannerEngine(db_bozze).cleanup_orphan_drafts()

        assert db_bozze.query(CandidateRecipe).filter(CandidateRecipe.id == cid).first() is not None

    def test_una_bozza_gia_usata_resta(self, db_bozze):
        cid = _aggiungi(db_bozze, created_at=_vecchia(), usage_count=2)

        PlannerEngine(db_bozze).cleanup_orphan_drafts()

        assert db_bozze.query(CandidateRecipe).filter(CandidateRecipe.id == cid).first() is not None

    def test_una_bozza_nata_da_un_pasto_registrato_resta(self, db_bozze):
        cid = _aggiungi(db_bozze, created_at=_vecchia(), origin_override_id="entry-1")

        PlannerEngine(db_bozze).cleanup_orphan_drafts()

        assert db_bozze.query(CandidateRecipe).filter(CandidateRecipe.id == cid).first() is not None


class TestAutomatismo:
    def test_le_nuove_alternative_portano_via_le_vecchie(self, db_bozze):
        """La pulizia scatta dove nasce la spazzatura, senza un lavoro periodico."""
        db = db_bozze
        vecchia = _aggiungi(db, created_at=_vecchia())
        db.add(PlanRules(
            id=str(uuid.uuid4()), profile_id="aa", imported_at="2026-03-01",
            carb_target={"cena": 80.0}, protein_target={"cena": 130.0},
            carb_options={"cena": [{"name": "riso", "quantity": 80, "unit": "g"}]},
            protein_options={"cena": [{"name": "petto di pollo", "quantity": 130, "unit": "g"}]},
            frequency_targets={"legumi": {"min": 1, "max": 4}}, free_meal_quota=2,
        ))
        base = _aggiungi(db, status="approved", created_at=_adesso(),
                         recipe_data=_data("Base"))
        db.commit()

        p = PlannerEngine(db)
        meal = p._rules_to_component_options(p._get_latest_plan_rules("aa"), "cena")
        p.get_component_alternatives(base, "carb", meal, p._get_user_profile("aa"),
                                     p._get_user_profile("aa"))

        assert db.query(CandidateRecipe).filter(CandidateRecipe.id == vecchia).first() is None, \
            "la bozza vecchia doveva essere rimossa"
        # e le alternative appena create sono ancora li'
        assert db.query(CandidateRecipe).filter(
            CandidateRecipe.status == "draft_structured"
        ).count() > 0

    def test_endpoint(self, client, db_bozze):
        _aggiungi(db_bozze, created_at=_vecchia())

        conta = client.post("/planner/cleanup-drafts", params={"apply": "false"})
        assert conta.status_code == 200
        assert conta.json()["removed"] == 1

        applica = client.post("/planner/cleanup-drafts")
        assert applica.status_code == 200
        assert applica.json()["removed"] == 1
        assert db_bozze.query(CandidateRecipe).count() == 0
