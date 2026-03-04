import uuid
from datetime import date, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db, Recipe, UserProfile, StructuredMealPlan

router = APIRouter(prefix="/seed", tags=["seed"])


def _get_week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _make_daily_plans(start: date) -> list:
    """Genera 7 daily_plans con pranzo/cena diversificati per testare il planner."""
    meal_schedule = [
        # (pranzo_food_group, pranzo_qty, cena_food_group, cena_qty)
        ("carboidrati", 80, "pollo",     150),  # lun: pasta, pollo
        ("carboidrati", 80, "pesce",     150),  # mar: pasta, salmone
        ("legumi",      80, "proteina",  120),  # mer: lenticchie, frittata
        ("carboidrati", 80, "legumi",    150),  # gio: pasta, ceci
        ("carboidrati", 80, "pesce",     120),  # ven: pasta, tonno
        ("legumi",      80, "pollo",     150),  # sab: lenticchie, pollo
        ("carboidrati", 80, "pesce",     150),  # dom: pasta, salmone
    ]
    plans = []
    for i, (pfg, pqty, cfg, cqty) in enumerate(meal_schedule):
        d = start + timedelta(days=i)
        plans.append({
            "date": d.isoformat(),
            "meals": [
                {
                    "meal_type": "pranzo",
                    "items": [{"item_name": pfg, "food_group": pfg, "quantity": pqty, "unit": "g", "is_estimated_unit": False, "alternatives": []}]
                },
                {
                    "meal_type": "cena",
                    "items": [{"item_name": cfg, "food_group": cfg, "quantity": cqty, "unit": "g", "is_estimated_unit": False, "alternatives": []}]
                },
            ]
        })
    return plans

def _qty(v):
    return {"persona_a": {"qty": v, "unit": "g", "grams_equiv": v},
            "persona_b": {"qty": v, "unit": "g", "grams_equiv": v}}


SEED_RECIPES = [
    # ── PRANZO: carboidrati 80g ──────────────────────────────────────────────
    {
        "id": "seed_pasta_pomodoro",
        "name": "Pasta al Pomodoro e Basilico",
        "description": "Classica pasta al pomodoro fresco con basilico e olio extravergine",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "pomodoro", "food_group": "verdure", "quantities": _qty(200)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere la pasta in acqua salata", "Preparare il sugo di pomodoro fresco con basilico", "Unire e servire"],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_pasta_pesto",
        "name": "Trofie al Pesto Genovese",
        "description": "Trofie con pesto di basilico, pinoli e parmigiano",
        "is_composed_dish": False,
        "content": [
            {"name": "trofie", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "pesto", "food_group": "grassi", "quantities": _qty(30)},
            {"name": "fagiolini", "food_group": "verdure", "quantities": _qty(80)},
        ],
        "steps": ["Cuocere trofie e fagiolini insieme", "Scolare e condire con pesto a freddo", "Servire con parmigiano"],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_pasta_norma",
        "name": "Pasta alla Norma",
        "description": "Pasta con melanzane fritte, pomodoro e ricotta salata",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "melanzana", "food_group": "verdure", "quantities": _qty(200)},
            {"name": "pomodoro", "food_group": "verdure", "quantities": _qty(150)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Friggere le melanzane a cubetti", "Preparare sugo di pomodoro", "Cuocere la pasta e unire tutto", "Grattugiare ricotta salata"],
        "total_time_minutes": 35,
        "difficulty": "media",
        "tags": {"mood": ["confort"], "cleanup": ["media"], "cooking_methods": ["tegame", "forno"]},
    },
    {
        "id": "seed_spaghetti_aglio_olio",
        "name": "Spaghetti Aglio, Olio e Peperoncino",
        "description": "Spaghetti saltati con aglio dorato, olio e un pizzico di peperoncino",
        "is_composed_dish": False,
        "content": [
            {"name": "spaghetti", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "aglio", "food_group": "verdure", "quantities": _qty(15)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(20)},
        ],
        "steps": ["Cuocere gli spaghetti al dente", "Dorare l'aglio in olio con peperoncino", "Saltare la pasta nel condimento"],
        "total_time_minutes": 15,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_pasta_broccoli",
        "name": "Pasta con Broccoli e Acciughe",
        "description": "Pasta con broccoli saltati, acciughe e mollica tostata",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "broccoli", "food_group": "verdure", "quantities": _qty(200)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Cuocere broccoli in acqua salata", "Cuocere la pasta nella stessa acqua", "Saltare con olio e acciughe"],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_riso_verdure",
        "name": "Riso Saltato con Verdure di Stagione",
        "description": "Riso basmati saltato con zucchine, carote e sesamo",
        "is_composed_dish": False,
        "content": [
            {"name": "riso", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "zucchina", "food_group": "verdure", "quantities": _qty(150)},
            {"name": "carota", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere il riso", "Saltare le verdure in padella a fuoco vivo", "Unire riso e verdure, insaporire con salsa di soia"],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_risotto_funghi",
        "name": "Risotto ai Funghi Porcini",
        "description": "Risotto cremoso con funghi porcini secchi e parmigiano",
        "is_composed_dish": False,
        "content": [
            {"name": "riso", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "funghi porcini", "food_group": "verdure", "quantities": _qty(150)},
            {"name": "cipolla", "food_group": "verdure", "quantities": _qty(30)},
            {"name": "burro", "food_group": "grassi", "quantities": _qty(20)},
        ],
        "steps": ["Soffriggere cipolla con burro", "Tostare il riso", "Aggiungere funghi e brodo a mestoli", "Mantecare con burro e parmigiano"],
        "total_time_minutes": 40,
        "difficulty": "media",
        "tags": {"mood": ["confort"], "cleanup": ["media"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_risotto_zucca",
        "name": "Risotto alla Zucca e Speck",
        "description": "Risotto autunnale con zucca mantecata e speck croccante",
        "is_composed_dish": False,
        "content": [
            {"name": "riso", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "zucca", "food_group": "verdure", "quantities": _qty(200)},
            {"name": "burro", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Cuocere la zucca a vapore e frullare", "Preparare il risotto base", "Mantecare con purea di zucca", "Aggiungere speck croccante"],
        "total_time_minutes": 45,
        "difficulty": "media",
        "tags": {"mood": ["confort"], "cleanup": ["media"], "cooking_methods": ["tegame", "vapore"]},
    },
    {
        "id": "seed_farro_verdure",
        "name": "Insalata Tiepida di Farro",
        "description": "Farro con pomodorini, rucola, olive e feta",
        "is_composed_dish": False,
        "content": [
            {"name": "farro", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "pomodoro", "food_group": "verdure", "quantities": _qty(150)},
            {"name": "rucola", "food_group": "verdure", "quantities": _qty(50)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere il farro in acqua salata", "Tagliare i pomodorini", "Condire il farro tiepido con verdure e olio"],
        "total_time_minutes": 30,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_orzo_pomodorini",
        "name": "Orzo Freddo con Pomodorini e Basilico",
        "description": "Insalata di orzo perlato con pomodorini, mozzarella e basilico",
        "is_composed_dish": False,
        "content": [
            {"name": "orzo perlato", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "pomodorini", "food_group": "verdure", "quantities": _qty(150)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere l'orzo e raffreddare", "Tagliare i pomodorini", "Condire con olio, basilico e sale"],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    # ── PRANZO: legumi 80g ──────────────────────────────────────────────────
    {
        "id": "seed_lenticchie_zucca",
        "name": "Zuppa di Lenticchie Rosse e Zucca",
        "description": "Zuppa vellutata di lenticchie rosse e zucca con curry",
        "is_composed_dish": False,
        "content": [
            {"name": "lenticchie", "food_group": "legumi", "quantities": _qty(80)},
            {"name": "zucca", "food_group": "verdure", "quantities": _qty(200)},
            {"name": "cipolla", "food_group": "verdure", "quantities": _qty(50)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Soffriggere cipolla con curry", "Aggiungere zucca, lenticchie e brodo", "Cuocere 25 minuti e frullare"],
        "total_time_minutes": 35,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_pasta_legumi",
        "name": "Pasta e Fagioli Borlotti",
        "description": "Pasta mista con fagioli borlotti in brodo saporito",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(60)},
            {"name": "fagioli", "food_group": "legumi", "quantities": _qty(120)},
            {"name": "cipolla", "food_group": "verdure", "quantities": _qty(50)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Soffriggere cipolla, sedano e carota", "Aggiungere fagioli e brodo", "Unire la pasta e cuocere al dente"],
        "total_time_minutes": 35,
        "difficulty": "media",
        "tags": {"mood": ["confort"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_minestrone",
        "name": "Minestrone di Verdure con Cannellini",
        "description": "Minestrone ricco con verdure di stagione e fagioli cannellini",
        "is_composed_dish": False,
        "content": [
            {"name": "fagioli cannellini", "food_group": "legumi", "quantities": _qty(80)},
            {"name": "patate", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "carota", "food_group": "verdure", "quantities": _qty(80)},
            {"name": "zucchina", "food_group": "verdure", "quantities": _qty(80)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Tagliare tutte le verdure a cubetti", "Rosolare con olio e aglio", "Aggiungere brodo e cuocere 30 minuti"],
        "total_time_minutes": 40,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    # ── CENA: pollo / tacchino (carne_bianca) ──────────────────────────────
    {
        "id": "seed_pollo_tegame",
        "name": "Petto di Pollo al Rosmarino",
        "description": "Petti di pollo dorati in tegame con rosmarino e vino bianco",
        "is_composed_dish": False,
        "content": [
            {"name": "pollo", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "aglio", "food_group": "verdure", "quantities": _qty(10)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Rosolare il pollo a fuoco alto", "Aggiungere aglio, rosmarino e vino bianco", "Cuocere coperto 15 minuti"],
        "total_time_minutes": 30,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["media"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_pollo_limone",
        "name": "Pollo al Limone con Capperi",
        "description": "Scaloppine di pollo con salsa al limone, capperi e prezzemolo",
        "is_composed_dish": False,
        "content": [
            {"name": "pollo", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "limone", "food_group": "verdure", "quantities": _qty(30)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Infarinare leggermente le scaloppine", "Rosolare in olio caldo", "Sfumare con succo di limone e aggiungere capperi"],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_tacchino_forno",
        "name": "Fesa di Tacchino al Forno",
        "description": "Fesa di tacchino marinata alle erbe, cotta al forno con pomodorini",
        "is_composed_dish": False,
        "content": [
            {"name": "tacchino", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "pomodorini", "food_group": "verdure", "quantities": _qty(120)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Marinare il tacchino con erbe e olio", "Sistemare in teglia con pomodorini", "Cuocere in forno a 180° per 30 minuti"],
        "total_time_minutes": 45,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["media"], "cooking_methods": ["forno"]},
    },
    {
        "id": "seed_pollo_curry",
        "name": "Pollo al Curry con Latte di Cocco",
        "description": "Bocconcini di pollo in salsa di curry e latte di cocco con riso basmati",
        "is_composed_dish": False,
        "content": [
            {"name": "pollo", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "cipolla", "food_group": "verdure", "quantities": _qty(50)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Rosolare cipolla con curry", "Aggiungere pollo a bocconcini", "Versare latte di cocco e cuocere 20 minuti"],
        "total_time_minutes": 35,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["media"], "cooking_methods": ["tegame"]},
    },
    # ── CENA: pesce ────────────────────────────────────────────────────────
    {
        "id": "seed_salmone_vapore",
        "name": "Salmone al Vapore con Spinaci",
        "description": "Filetto di salmone al vapore con limone, servito su letto di spinaci",
        "is_composed_dish": False,
        "content": [
            {"name": "salmone", "food_group": "pesce", "quantities": _qty(150)},
            {"name": "spinaci", "food_group": "verdure", "quantities": _qty(150)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere il salmone a vapore 12 minuti", "Saltare gli spinaci con aglio", "Servire il salmone sugli spinaci con limone"],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["vapore"]},
    },
    {
        "id": "seed_insalata_tonno",
        "name": "Insalata Nizzarda di Tonno",
        "description": "Tonno in scatola di qualità con insalata, pomodorini, olive e uovo sodo",
        "is_composed_dish": False,
        "content": [
            {"name": "tonno", "food_group": "pesce", "quantities": _qty(120)},
            {"name": "insalata", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "pomodorini", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Lavare e comporre l'insalata", "Aggiungere tonno, pomodorini e olive", "Condire con olio e limone"],
        "total_time_minutes": 10,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["crudo"]},
    },
    {
        "id": "seed_merluzzo_forno",
        "name": "Merluzzo al Forno con Olive e Capperi",
        "description": "Filetto di merluzzo al forno alla mediterranea con olive nere e capperi",
        "is_composed_dish": False,
        "content": [
            {"name": "merluzzo", "food_group": "pesce", "quantities": _qty(150)},
            {"name": "pomodoro", "food_group": "verdure", "quantities": _qty(150)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Sistemare il merluzzo in teglia", "Coprire con pomodoro, olive e capperi", "Cuocere in forno a 180° per 20 minuti"],
        "total_time_minutes": 30,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["forno"]},
    },
    {
        "id": "seed_branzino_cartoccio",
        "name": "Branzino al Cartoccio con Verdure",
        "description": "Branzino intero cotto al cartoccio con zucchine, carote e erbe aromatiche",
        "is_composed_dish": False,
        "content": [
            {"name": "branzino", "food_group": "pesce", "quantities": _qty(150)},
            {"name": "zucchina", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Preparare il cartoccio con carta da forno", "Inserire il branzino con verdure e erbe", "Cuocere in forno a 200° per 25 minuti"],
        "total_time_minutes": 35,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["forno"]},
    },
    {
        "id": "seed_gamberetti_padella",
        "name": "Gamberetti in Padella con Aglio e Limone",
        "description": "Gamberetti saltati a fuoco vivo con aglio, prezzemolo e scorza di limone",
        "is_composed_dish": False,
        "content": [
            {"name": "gamberetti", "food_group": "pesce", "quantities": _qty(150)},
            {"name": "aglio", "food_group": "verdure", "quantities": _qty(10)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Scaldare olio con aglio", "Aggiungere gamberetti e saltare a fuoco alto 3 minuti", "Finire con prezzemolo e limone"],
        "total_time_minutes": 15,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    # ── CENA: carne rossa ──────────────────────────────────────────────────
    {
        "id": "seed_bistecca_ferri",
        "name": "Bistecca ai Ferri con Rucola",
        "description": "Controfiletto ai ferri con insalata di rucola, grana a scaglie e limone",
        "is_composed_dish": False,
        "content": [
            {"name": "manzo", "food_group": "carne_rossa", "quantities": _qty(150)},
            {"name": "rucola", "food_group": "verdure", "quantities": _qty(80)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Portare la bistecca a temperatura ambiente", "Cuocere ai ferri 3 minuti per lato", "Servire su letto di rucola con olio e limone"],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["ferri"]},
    },
    {
        "id": "seed_polpette_sugo",
        "name": "Polpette di Manzo al Sugo",
        "description": "Polpette di manzo macinato in sugo di pomodoro fresco con basilico",
        "is_composed_dish": False,
        "content": [
            {"name": "manzo macinato", "food_group": "carne_rossa", "quantities": _qty(150)},
            {"name": "pomodoro", "food_group": "verdure", "quantities": _qty(200)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Formare le polpette con macinato, uovo e parmigiano", "Rosolare in padella", "Finire la cottura nel sugo di pomodoro 20 minuti"],
        "total_time_minutes": 40,
        "difficulty": "media",
        "tags": {"mood": ["confort"], "cleanup": ["media"], "cooking_methods": ["tegame"]},
    },
    # ── CENA: legumi (proteina serale) ────────────────────────────────────
    {
        "id": "seed_zuppa_ceci",
        "name": "Zuppa di Ceci al Rosmarino",
        "description": "Zuppa densa di ceci con rosmarino, olio a crudo e crostini",
        "is_composed_dish": False,
        "content": [
            {"name": "ceci", "food_group": "legumi", "quantities": _qty(150)},
            {"name": "aglio", "food_group": "verdure", "quantities": _qty(10)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Soffriggere aglio in olio con rosmarino", "Aggiungere ceci e brodo", "Cuocere 20 minuti, frullare parzialmente e servire"],
        "total_time_minutes": 30,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_lenticchie_salsiccia",
        "name": "Lenticchie con Verdure Grigliate",
        "description": "Lenticchie verdi stufate con carote, sedano e un filo di olio nuovo",
        "is_composed_dish": False,
        "content": [
            {"name": "lenticchie verdi", "food_group": "legumi", "quantities": _qty(150)},
            {"name": "carota", "food_group": "verdure", "quantities": _qty(80)},
            {"name": "sedano", "food_group": "verdure", "quantities": _qty(50)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Soffriggere sedano e carota", "Aggiungere lenticchie e brodo", "Cuocere 35 minuti a fuoco lento"],
        "total_time_minutes": 45,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    # ── CENA: uova / proteina ─────────────────────────────────────────────
    {
        "id": "seed_frittata_verdure",
        "name": "Frittata di Zucchine e Peperoni",
        "description": "Frittata alta con zucchine, peperoni colorati e erba cipollina",
        "is_composed_dish": False,
        "content": [
            {"name": "uova", "food_group": "proteina", "quantities": _qty(120)},
            {"name": "zucchina", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "peperone", "food_group": "verdure", "quantities": _qty(80)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Saltare le verdure", "Sbattere le uova con sale e erba cipollina", "Cuocere in padella antiaderente 5 min per lato"],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_uova_camicia",
        "name": "Uova in Camicia su Crema di Piselli",
        "description": "Uova pochéed servite su vellutata di piselli freschi e menta",
        "is_composed_dish": False,
        "content": [
            {"name": "uova", "food_group": "proteina", "quantities": _qty(120)},
            {"name": "piselli", "food_group": "verdure", "quantities": _qty(150)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Frullare i piselli con brodo e menta", "Portare a ebollizione acqua acidulata", "Cuocere le uova in camicia 3 minuti e servire sulla crema"],
        "total_time_minutes": 20,
        "difficulty": "media",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    # ── PIATTI COMPOSTI: pollo + carbo (varietà di carbo) ─────────────────
    {
        "id": "seed_comp_pollo_pasta",
        "name": "Pasta al Ragù Bianco di Pollo",
        "description": "Pasta corta con ragù leggero di pollo macinato, sedano, carota e vino bianco",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "pollo", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "carota", "food_group": "verdure", "quantities": _qty(60)},
            {"name": "sedano", "food_group": "verdure", "quantities": _qty(40)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Tritare pollo con sedano e carota", "Rosolare in tegame con olio", "Unire vino bianco e cuocere 20 min", "Condire la pasta al dente"],
        "total_time_minutes": 35,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["media"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_pollo_riso",
        "name": "Riso con Pollo alle Erbe e Limone",
        "description": "Riso basmati con bocconcini di pollo saltati con erbe aromatiche e scorza di limone",
        "is_composed_dish": False,
        "content": [
            {"name": "riso", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "pollo", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "zucchina", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere il riso basmati", "Saltare il pollo a bocconcini con erbe e limone", "Unire e servire caldo"],
        "total_time_minutes": 30,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_pollo_farro",
        "name": "Farro con Pollo Arrostito e Verdure",
        "description": "Farro perlato con straccetti di pollo arrostito, peperoni grigliati e basilico",
        "is_composed_dish": False,
        "content": [
            {"name": "farro", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "pollo", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "peperone", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere il farro in acqua salata", "Grigliare il pollo e tagliare a straccetti", "Grigliare i peperoni", "Unire tutto con olio e basilico"],
        "total_time_minutes": 40,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["media"], "cooking_methods": ["forno", "tegame"]},
    },
    {
        "id": "seed_comp_tacchino_patate",
        "name": "Tacchino al Forno con Patate e Rosmarino",
        "description": "Fesa di tacchino e patate al forno con rosmarino, aglio e olio extravergine",
        "is_composed_dish": False,
        "content": [
            {"name": "patate", "food_group": "carboidrati", "quantities": _qty(180)},
            {"name": "tacchino", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "aglio", "food_group": "verdure", "quantities": _qty(15)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Tagliare patate a spicchi e condire", "Sistemare tacchino e patate in teglia", "Cuocere a 190° per 40 minuti"],
        "total_time_minutes": 55,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["facile"], "cooking_methods": ["forno"]},
    },
    {
        "id": "seed_comp_pollo_couscous",
        "name": "Couscous con Pollo alle Spezie",
        "description": "Couscous con bocconcini di pollo marinati con curcuma, cumino e coriandolo",
        "is_composed_dish": False,
        "content": [
            {"name": "couscous", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "pollo", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "peperone", "food_group": "verdure", "quantities": _qty(80)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Idratare il couscous con brodo caldo", "Marinare il pollo con spezie e saltare in tegame", "Unire couscous e pollo, servire con coriandolo"],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["etnico"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_tacchino_pasta",
        "name": "Pasta con Tacchino e Pomodorini",
        "description": "Pasta con straccetti di tacchino, pomodorini ciliegino e basilico fresco",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "tacchino", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "pomodorino", "food_group": "verdure", "quantities": _qty(120)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Saltare il tacchino a straccetti in olio", "Aggiungere pomodorini e cuocere 5 min", "Condire la pasta al dente con il sugo"],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_tacchino_riso",
        "name": "Riso con Tacchino al Limone",
        "description": "Riso basmati con bocconcini di tacchino al limone e capperi",
        "is_composed_dish": False,
        "content": [
            {"name": "riso", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "tacchino", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "zucchina", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere il riso basmati", "Saltare il tacchino con succo di limone e capperi", "Impiattare unendo riso e tacchino"],
        "total_time_minutes": 30,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_tacchino_farro",
        "name": "Farro con Tacchino e Verdure Grigliate",
        "description": "Farro perlato con fesa di tacchino grigliata e verdure miste",
        "is_composed_dish": False,
        "content": [
            {"name": "farro", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "tacchino", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "melanzana", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere il farro", "Grigliare il tacchino a fette", "Grigliare le verdure", "Unire e condire"],
        "total_time_minutes": 40,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["media"], "cooking_methods": ["griglia"]},
    },
    {
        "id": "seed_comp_tacchino_couscous",
        "name": "Couscous con Tacchino Aromatico",
        "description": "Couscous integrale con tacchino al forno con erbe aromatiche mediterranee",
        "is_composed_dish": False,
        "content": [
            {"name": "couscous", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "tacchino", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "pomodoro", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Idratare il couscous", "Cuocere il tacchino in padella con erbe", "Unire e servire caldo"],
        "total_time_minutes": 30,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_pollo_patate",
        "name": "Pollo con Patate alle Erbe",
        "description": "Pollo in padella con dadini di patate, rosmarino e aglio",
        "is_composed_dish": False,
        "content": [
            {"name": "patate", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "pollo", "food_group": "pollo", "quantities": _qty(150)},
            {"name": "cipolla", "food_group": "verdure", "quantities": _qty(60)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Tagliare patate a dadini piccoli", "Rosolare il pollo con aglio e rosmarino", "Aggiungere le patate e cuocere 20 min"],
        "total_time_minutes": 35,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["media"], "cooking_methods": ["tegame"]},
    },
    # ── PIATTI COMPOSTI: pesce + carbo ────────────────────────────────────
    {
        "id": "seed_comp_salmone_pasta",
        "name": "Pasta al Salmone e Zucchine",
        "description": "Penne con salmone fresco, zucchine trifolate e pomodorini",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "salmone", "food_group": "pesce", "quantities": _qty(150)},
            {"name": "zucchina", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Saltare le zucchine in olio", "Aggiungere salmone a cubetti e cuocere 5 min", "Mantecare con la pasta al dente"],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_tonno_pasta",
        "name": "Pasta al Tonno e Capperi",
        "description": "Spaghetti con tonno in olio, capperi, olive e pomodorini",
        "is_composed_dish": False,
        "content": [
            {"name": "spaghetti", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "tonno", "food_group": "pesce", "quantities": _qty(120)},
            {"name": "pomodorini", "food_group": "verdure", "quantities": _qty(120)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Scolare e sgranare il tonno", "Rosolare pomodorini con olio e capperi", "Unire tonno e pasta"],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_gamberi_riso",
        "name": "Riso con Gamberi e Piselli",
        "description": "Riso vialone nano mantecato con gamberi saltati e piselli freschi",
        "is_composed_dish": False,
        "content": [
            {"name": "riso", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "gamberetti", "food_group": "pesce", "quantities": _qty(150)},
            {"name": "piselli", "food_group": "verdure", "quantities": _qty(80)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere il riso al vapore", "Saltare gamberi e piselli con aglio", "Unire e servire con prezzemolo"],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_merluzzo_patate",
        "name": "Merluzzo e Patate al Forno",
        "description": "Filetto di merluzzo su letto di patate a fette con olive e pomodoro",
        "is_composed_dish": False,
        "content": [
            {"name": "patate", "food_group": "carboidrati", "quantities": _qty(180)},
            {"name": "merluzzo", "food_group": "pesce", "quantities": _qty(150)},
            {"name": "pomodoro", "food_group": "verdure", "quantities": _qty(100)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Affettare le patate e stendere in teglia", "Appoggiare il merluzzo sopra con pomodoro", "Cuocere a 180° per 30 minuti"],
        "total_time_minutes": 40,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["forno"]},
    },
    # ── PIATTI COMPOSTI: legumi + carbo ───────────────────────────────────
    {
        "id": "seed_comp_ceci_pasta",
        "name": "Pasta e Ceci al Rosmarino",
        "description": "Pasta mista con ceci in brodo aromatico al rosmarino e aglio",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "ceci", "food_group": "legumi", "quantities": _qty(150)},
            {"name": "aglio", "food_group": "verdure", "quantities": _qty(10)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(15)},
        ],
        "steps": ["Soffriggere aglio con rosmarino", "Aggiungere ceci e brodo", "Unire pasta e cuocere al dente in brodo"],
        "total_time_minutes": 30,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_lenticchie_riso",
        "name": "Riso e Lenticchie al Curry",
        "description": "Riso integrale con lenticchie rosse, cipolla caramellata e spezie curry",
        "is_composed_dish": False,
        "content": [
            {"name": "riso", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "lenticchie", "food_group": "legumi", "quantities": _qty(150)},
            {"name": "cipolla", "food_group": "verdure", "quantities": _qty(80)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Caramellare la cipolla in olio", "Aggiungere lenticchie, curry e brodo", "Unire il riso cotto e amalgamare"],
        "total_time_minutes": 35,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    # ── PIATTI COMPOSTI: carne rossa + carbo ──────────────────────────────
    {
        "id": "seed_comp_manzo_pasta",
        "name": "Pasta alla Bolognese",
        "description": "Tagliatelle con ragù di manzo macinato, pomodoro, sedano e carota",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "manzo macinato", "food_group": "carne_rossa", "quantities": _qty(150)},
            {"name": "pomodoro", "food_group": "verdure", "quantities": _qty(150)},
            {"name": "cipolla", "food_group": "verdure", "quantities": _qty(40)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Soffriggere cipolla, carota, sedano", "Aggiungere manzo e rosolare", "Aggiungere pomodoro e cuocere 40 min", "Condire le tagliatelle al dente"],
        "total_time_minutes": 60,
        "difficulty": "media",
        "tags": {"mood": ["confort"], "cleanup": ["media"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_manzo_patate",
        "name": "Spezzatino di Manzo con Patate",
        "description": "Bocconcini di manzo in umido con patate a cubetti, carota e vino rosso",
        "is_composed_dish": False,
        "content": [
            {"name": "patate", "food_group": "carboidrati", "quantities": _qty(200)},
            {"name": "manzo", "food_group": "carne_rossa", "quantities": _qty(150)},
            {"name": "carota", "food_group": "verdure", "quantities": _qty(80)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Rosolare i bocconcini di manzo", "Aggiungere verdure e vino rosso", "Cuocere a fuoco lento 50 min", "Aggiungere le patate negli ultimi 20 min"],
        "total_time_minutes": 75,
        "difficulty": "media",
        "tags": {"mood": ["confort"], "cleanup": ["media"], "cooking_methods": ["tegame"]},
    },
    # ── PIATTI COMPOSTI: uova + carbo ─────────────────────────────────────
    {
        "id": "seed_comp_uova_pasta",
        "name": "Pasta con Uova Strapazzate e Asparagi",
        "description": "Pasta corta con uova strapazzate morbide, asparagi saltati e parmigiano",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "uova", "food_group": "proteina", "quantities": _qty(120)},
            {"name": "asparagi", "food_group": "verdure", "quantities": _qty(120)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere gli asparagi in padella", "Strapazzare le uova morbide a fuoco basso", "Mantecare con la pasta e parmigiano"],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_comp_uova_riso",
        "name": "Riso Saltato con Uova e Verdure",
        "description": "Riso basmati saltato in padella con uova strapazzate, piselli e salsa di soia",
        "is_composed_dish": False,
        "content": [
            {"name": "riso", "food_group": "carboidrati", "quantities": _qty(80)},
            {"name": "uova", "food_group": "proteina", "quantities": _qty(120)},
            {"name": "piselli", "food_group": "verdure", "quantities": _qty(80)},
            {"name": "olio", "food_group": "grassi", "quantities": _qty(10)},
        ],
        "steps": ["Cuocere il riso e raffreddare", "Saltare in wok con olio a fuoco vivo", "Aggiungere uova e piselli, saltare 3 min"],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
]


@router.post("/recipes", status_code=201)
def seed_recipes(db: Session = Depends(get_db)):
    """
    Insert seed recipes into the database. Skips already-existing recipes (by ID).
    """
    created = 0
    skipped = 0
    for recipe_data in SEED_RECIPES:
        existing = db.query(Recipe).filter(Recipe.id == recipe_data["id"]).first()
        if existing:
            skipped += 1
            continue
        db_recipe = Recipe(
            id=recipe_data["id"],
            name=recipe_data["name"],
            description=recipe_data["description"],
            is_composed_dish=recipe_data["is_composed_dish"],
            content=recipe_data["content"],
            steps=recipe_data["steps"],
            total_time_minutes=recipe_data["total_time_minutes"],
            difficulty=recipe_data["difficulty"],
            tags=recipe_data["tags"],
        )
        db.add(db_recipe)
        created += 1
    db.commit()
    return {"created": created, "skipped": skipped}


@router.post("", status_code=201)
def seed_all(db: Session = Depends(get_db)):
    """
    Seed completo: crea profili, piano pasti settimanale e ricette.
    Idempotente: salta le entità già esistenti.
    """
    result = {}

    # --- Profili ---
    profiles_created = 0
    for profile_data in [
        {"id": "persona_a", "name": "Marco", "allergies": [], "excluded_foods": [], "preferences": [], "equipment": []},
        {"id": "persona_b", "name": "Sara",  "allergies": [], "excluded_foods": [], "preferences": [], "equipment": []},
    ]:
        if not db.query(UserProfile).filter(UserProfile.id == profile_data["id"]).first():
            db.add(UserProfile(**profile_data))
            profiles_created += 1
    db.commit()
    result["profiles_created"] = profiles_created

    # --- Piano pasti (settimana corrente) ---
    week_start = _get_week_start(date.today())
    plan_id = f"seed_plan_{week_start.isoformat()}"
    if not db.query(StructuredMealPlan).filter(StructuredMealPlan.id == plan_id).first():
        db.add(StructuredMealPlan(
            id=plan_id,
            profile_id="persona_a",
            start_date=week_start.isoformat(),
            rotation_rules=[],
            allowed_cooking_methods=[],
            daily_plans=_make_daily_plans(week_start),
        ))
        db.commit()
        result["meal_plan_created"] = plan_id
    else:
        result["meal_plan_skipped"] = plan_id

    # --- Ricette ---
    recipes_created = 0
    recipes_skipped = 0
    for recipe_data in SEED_RECIPES:
        if db.query(Recipe).filter(Recipe.id == recipe_data["id"]).first():
            recipes_skipped += 1
            continue
        db.add(Recipe(
            id=recipe_data["id"],
            name=recipe_data["name"],
            description=recipe_data["description"],
            is_composed_dish=recipe_data["is_composed_dish"],
            content=recipe_data["content"],
            steps=recipe_data["steps"],
            total_time_minutes=recipe_data["total_time_minutes"],
            difficulty=recipe_data["difficulty"],
            tags=recipe_data["tags"],
        ))
        recipes_created += 1
    db.commit()
    result["recipes_created"] = recipes_created
    result["recipes_skipped"] = recipes_skipped

    return result
