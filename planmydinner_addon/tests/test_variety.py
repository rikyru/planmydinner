"""
Varietà del piano generato.

Su una settimana di sole cene la monotonia si vede subito: legumi due sere di
fila, gli stessi ceci due volte, il pane come unico carboidrato. Questi test
fissano le regole che la evitano — e distinguono la monotonia dovuta alla
logica (da correggere) da quella dovuta a un catalogo povero (che nessun
filtro può inventare).
"""
import uuid
from datetime import date, timedelta

import pytest

from planmydinner_addon.database import CandidateRecipe, PlanRules, UserProfile
from planmydinner_addon.planner import PlannerEngine

MONDAY = date(2026, 3, 2)
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


def _qty(g):
    return {"qty": float(g), "unit": "g", "grams_equiv": float(g)}


def _recipe(name, protein_name, protein_fg, carb_name="pane"):
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


class TestNomiLeggibili:
    """I nomi importati dal piano nutrizionale arrivano in forma da tabella
    alimentare e come nomi di piatto sono illeggibili."""

    @pytest.mark.parametrize("grezzo,atteso", [
        ("uova di gallina - intero", "uova di gallina"),
        ("ceci secchi - bolliti", "ceci"),
        # trattino attaccato alla parola (errore di battitura nel piano importato)
        ("fagioli Cannellini secchi- bolliti", "fagioli Cannellini"),
        ("pollo - sovracoscio - senza pelle", "pollo"),
        ("vitellone tagli magri", "vitellone"),
        ("tonno sott'olio - sgocciolato", "tonno sott'olio"),
        ("pasta di semola", "pasta di semola"),
        ("mozzarella", "mozzarella"),
    ])
    def test_pulisce_i_qualificatori(self, grezzo, atteso):
        assert PlannerEngine._pretty_ingredient_name(grezzo) == atteso

    def test_nome_del_piatto_non_e_in_title_case(self):
        content = [
            {"name": "uova di gallina - intero", "food_group": "uova"},
            {"name": "pasta di semola", "food_group": "carboidrati"},
        ]
        nome = PlannerEngine._make_display_name(content)
        assert nome == "Uova di gallina con pasta di semola"


class TestChiaveDiRotazione:
    """Varianti dello stesso alimento devono contare come lo stesso ingrediente."""

    @pytest.mark.parametrize("a,b", [
        ("ceci cotti", "ceci secchi - bolliti"),
        ("Ceci", "ceci"),
        ("pane tostato", "pane"),
        ("pane (mollica)", "pane per tramezzini"),
        ("patate al forno", "patate"),
    ])
    def test_varianti_stessa_chiave(self, a, b):
        assert PlannerEngine._rotation_key(a) == PlannerEngine._rotation_key(b)

    @pytest.mark.parametrize("a,b", [
        ("ceci", "lenticchie"),
        ("pane", "pasta"),
        ("pasta", "pasta sfoglia"),   # impasti diversi, non lo stesso alimento
        ("riso", "ravioli"),
    ])
    def test_alimenti_diversi_chiavi_diverse(self, a, b):
        assert PlannerEngine._rotation_key(a) != PlannerEngine._rotation_key(b)


class TestSequenzaProteica:
    def test_mai_la_stessa_categoria_in_slot_consecutivi(self):
        """Legumi lunedì sera e martedì sera si somigliano anche con ricette diverse."""
        freq = {"legumi": {"min": 3, "max": 5}, "uova": {"min": 2, "max": 4},
                "carne_bianca": {"min": 2, "max": 2}, "formaggio": {"min": 2, "max": 2}}
        slot_plan = [(d, "cena") for d in range(7)] + [(5, "pranzo"), (6, "pranzo")]
        slot_plan.sort()

        seq = PlannerEngine._build_protein_sequence(freq, slot_plan=slot_plan)

        ordered = [seq[s] for s in slot_plan]
        consecutivi = [
            (a, b) for a, b in zip(ordered, ordered[1:]) if a is not None and a == b
        ]
        assert not consecutivi, f"categoria ripetuta in slot consecutivi: {consecutivi}"

    def test_minimi_rispettati_quando_ci_stanno(self):
        """Se i minimi entrano negli slot disponibili sono la volontà del
        nutrizionista e vanno rispettati tali e quali."""
        freq = {"legumi": {"min": 3, "max": 5}, "uova": {"min": 2, "max": 4},
                "carne_bianca": {"min": 2, "max": 2}, "formaggio": {"min": 2, "max": 2}}
        slot_plan = sorted([(d, "cena") for d in range(7)] + [(5, "pranzo"), (6, "pranzo")])

        seq = PlannerEngine._build_protein_sequence(freq, slot_plan=slot_plan)

        from collections import Counter
        conteggio = Counter(c for c in seq.values() if c)
        for cat, tgt in freq.items():
            assert conteggio[cat] >= tgt["min"], f"{cat}: {conteggio[cat]} < min {tgt['min']}"
            assert conteggio[cat] <= tgt["max"], f"{cat}: {conteggio[cat]} > max {tgt['max']}"

    def test_minimi_riproporzionati_quando_non_ci_stanno(self):
        """Con pochi slot generati, pretendere i minimi di una settimana intera
        vincolerebbe ogni singolo slot e renderebbe il piano monotono."""
        freq = {"legumi": {"min": 3, "max": 5}, "uova": {"min": 2, "max": 4},
                "carne_bianca": {"min": 2, "max": 2}, "formaggio": {"min": 2, "max": 2}}
        slot_plan = [(d, "cena") for d in range(4)]  # 4 slot, minimi = 9

        seq = PlannerEngine._build_protein_sequence(freq, slot_plan=slot_plan)

        categorie = [c for c in seq.values() if c]
        assert len(categorie) == 4
        # Con soli 4 slot nessuna categoria deve monopolizzare la settimana
        from collections import Counter
        assert max(Counter(categorie).values()) <= 2

    def test_gli_slot_liberi_non_vanno_tutti_alla_categoria_col_tetto_piu_alto(self):
        """Dopo i minimi, il criterio e' la categoria usata MENO, non quella con
        piu' spazio residuo: altrimenti legumi (max 5) e uova (max 4) si prendono
        tutto e le altre non compaiono."""
        freq = {"legumi": {"min": 0, "max": 5}, "uova": {"min": 0, "max": 4},
                "carne_bianca": {"min": 0, "max": 3}, "pesce": {"min": 0, "max": 3}}
        slot_plan = [(d, "cena") for d in range(7)]

        seq = PlannerEngine._build_protein_sequence(freq, slot_plan=slot_plan)

        from collections import Counter
        conteggio = Counter(c for c in seq.values() if c)
        assert len(conteggio) >= 4, f"solo {len(conteggio)} categorie usate: {dict(conteggio)}"
        assert max(conteggio.values()) - min(conteggio.values()) <= 1

    def test_i_pasti_gia_registrati_contano_nel_budget(self):
        freq = {"legumi": {"min": 2, "max": 3}, "uova": {"min": 0, "max": 3},
                "carne_bianca": {"min": 0, "max": 3}}
        slot_plan = [(d, "cena") for d in range(4)]

        seq = PlannerEngine._build_protein_sequence(
            freq, slot_plan=slot_plan, initial_counts={"legumi": 3},
        )
        assert "legumi" not in [c for c in seq.values() if c], "legumi era già al massimo"


@pytest.fixture
def catalogo_vario(setup_database):
    """Due ingredienti per categoria: la varietà è possibile, se la logica la cerca."""
    db = setup_database
    db.add(UserProfile(id="aa", name="A", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.add(UserProfile(id="bb", name="B", allergies=[], excluded_foods=[], preferences=[], equipment=[]))
    db.add(PlanRules(
        id=str(uuid.uuid4()), profile_id="aa", imported_at="2026-03-01",
        carb_target={"pranzo": 80.0, "cena": 80.0},
        protein_target={"pranzo": 150.0, "cena": 150.0},
        carb_options={"pranzo": ["pane"], "cena": ["pane"]},
        protein_options={"pranzo": ["ceci"], "cena": ["ceci"]},
        frequency_targets={"legumi": {"min": 2, "max": 4}, "pesce": {"min": 2, "max": 4}},
        free_meal_quota=2,
        generation_slots={"pranzo": [], "cena": ALL_DAYS},
    ))
    pool = [
        _recipe("Zuppa di ceci", "ceci secchi - bolliti", "legumi", "pane"),
        _recipe("Insalata di ceci", "ceci cotti", "legumi", "pane tostato"),
        _recipe("Polpette di lenticchie", "lenticchie", "legumi", "riso"),
        _recipe("Lenticchie in umido", "lenticchie secche", "legumi", "patate"),
        _recipe("Salmone al forno", "salmone", "pesce", "pasta"),
        _recipe("Pasta al salmone", "salmone affumicato", "pesce", "pasta di semola"),
        _recipe("Merluzzo in padella", "merluzzo", "pesce", "couscous"),
        _recipe("Merluzzo gratinato", "merluzzo surgelato", "pesce", "quinoa"),
    ]
    for data in pool:
        db.add(CandidateRecipe(id=str(uuid.uuid4()), status="approved", recipe_data=data))
    db.commit()
    return db


class TestVarietaNelPianoGenerato:
    def test_non_ripete_lo_stesso_ingrediente_se_esiste_alternativa(self, catalogo_vario):
        """Ceci e lenticchie sono entrambi legumi: due slot di legumi devono usarli
        entrambi, non i ceci due volte con nomi diversi."""
        p = PlannerEngine(catalogo_vario)
        week = p.generate_weekly_plan("aa", "bb", MONDAY)

        items = []
        for day in week:
            for meal in day.meals:
                if meal.items and meal.items[0].recipe_id:
                    items.append(p._get_main_protein_item(meal.items[0].recipe_id))
        usati = [i for i in items if i]
        assert len(set(usati)) >= 4, f"pochi ingredienti distinti: {usati}"

    def test_nessuna_ricetta_ripetuta_nella_settimana(self, catalogo_vario):
        p = PlannerEngine(catalogo_vario)
        week = p.generate_weekly_plan("aa", "bb", MONDAY)
        ids = [m.items[0].recipe_id for d in week for m in d.meals if m.items]
        assert len(ids) == len(set(ids)), "ricetta ripetuta nella stessa settimana"
