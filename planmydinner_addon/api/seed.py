from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db, Recipe

router = APIRouter(prefix="/seed", tags=["seed"])

SEED_RECIPES = [
    {
        "id": "seed_pasta_pomodoro",
        "name": "Pasta al Pomodoro",
        "description": "Classica pasta al pomodoro con basilico fresco",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": {
                "persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80},
                "persona_b": {"qty": 80, "unit": "g", "grams_equiv": 80},
            }},
            {"name": "pomodoro", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 200, "unit": "g", "grams_equiv": 200},
                "persona_b": {"qty": 200, "unit": "g", "grams_equiv": 200},
            }},
            {"name": "olio", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 10, "unit": "g", "grams_equiv": 10},
                "persona_b": {"qty": 10, "unit": "g", "grams_equiv": 10},
            }},
        ],
        "steps": ["Cuocere la pasta in acqua salata", "Preparare il sugo di pomodoro", "Unire e servire con basilico"],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_riso_verdure",
        "name": "Riso con Verdure",
        "description": "Riso saltato con verdure di stagione",
        "is_composed_dish": False,
        "content": [
            {"name": "riso", "food_group": "carboidrati", "quantities": {
                "persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80},
                "persona_b": {"qty": 80, "unit": "g", "grams_equiv": 80},
            }},
            {"name": "zucchina", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150},
                "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150},
            }},
            {"name": "carota", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 100, "unit": "g", "grams_equiv": 100},
                "persona_b": {"qty": 100, "unit": "g", "grams_equiv": 100},
            }},
            {"name": "olio", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 10, "unit": "g", "grams_equiv": 10},
                "persona_b": {"qty": 10, "unit": "g", "grams_equiv": 10},
            }},
        ],
        "steps": ["Cuocere il riso", "Saltare le verdure in padella", "Unire riso e verdure"],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_pollo_tegame",
        "name": "Pollo in Tegame",
        "description": "Petti di pollo con aglio, rosmarino e vino bianco",
        "is_composed_dish": False,
        "content": [
            {"name": "pollo", "food_group": "pollo", "quantities": {
                "persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150},
                "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150},
            }},
            {"name": "aglio", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 10, "unit": "g", "grams_equiv": 10},
                "persona_b": {"qty": 10, "unit": "g", "grams_equiv": 10},
            }},
            {"name": "olio", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 15, "unit": "g", "grams_equiv": 15},
                "persona_b": {"qty": 15, "unit": "g", "grams_equiv": 15},
            }},
        ],
        "steps": ["Rosolare il pollo in tegame", "Aggiungere aglio e rosmarino", "Sfumare con vino bianco e cuocere"],
        "total_time_minutes": 30,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["media"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_salmone_vapore",
        "name": "Salmone al Vapore",
        "description": "Filetto di salmone al vapore con limone e erbe",
        "is_composed_dish": False,
        "content": [
            {"name": "salmone", "food_group": "pesce", "quantities": {
                "persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150},
                "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150},
            }},
            {"name": "spinaci", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 100, "unit": "g", "grams_equiv": 100},
                "persona_b": {"qty": 100, "unit": "g", "grams_equiv": 100},
            }},
            {"name": "olio", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 10, "unit": "g", "grams_equiv": 10},
                "persona_b": {"qty": 10, "unit": "g", "grams_equiv": 10},
            }},
        ],
        "steps": ["Preparare il cestello vapore", "Cuocere il salmone a vapore 12 minuti", "Condire con limone e olio"],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["vapore"]},
    },
    {
        "id": "seed_lenticchie_zucca",
        "name": "Zuppa di Lenticchie e Zucca",
        "description": "Zuppa calda di lenticchie rosse e zucca",
        "is_composed_dish": False,
        "content": [
            {"name": "lenticchie", "food_group": "legumi", "quantities": {
                "persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80},
                "persona_b": {"qty": 80, "unit": "g", "grams_equiv": 80},
            }},
            {"name": "zucca", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 200, "unit": "g", "grams_equiv": 200},
                "persona_b": {"qty": 200, "unit": "g", "grams_equiv": 200},
            }},
            {"name": "cipolla", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50},
                "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50},
            }},
            {"name": "olio", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 10, "unit": "g", "grams_equiv": 10},
                "persona_b": {"qty": 10, "unit": "g", "grams_equiv": 10},
            }},
        ],
        "steps": ["Soffriggere cipolla", "Aggiungere zucca e lenticchie", "Cuocere 30 minuti con brodo"],
        "total_time_minutes": 40,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_frittata_verdure",
        "name": "Frittata di Verdure",
        "description": "Frittata con zucchine, peperoni e cipolla",
        "is_composed_dish": False,
        "content": [
            {"name": "uova", "food_group": "proteina", "quantities": {
                "persona_a": {"qty": 120, "unit": "g", "grams_equiv": 120},
                "persona_b": {"qty": 120, "unit": "g", "grams_equiv": 120},
            }},
            {"name": "zucchina", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 100, "unit": "g", "grams_equiv": 100},
                "persona_b": {"qty": 100, "unit": "g", "grams_equiv": 100},
            }},
            {"name": "peperone", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80},
                "persona_b": {"qty": 80, "unit": "g", "grams_equiv": 80},
            }},
            {"name": "olio", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 10, "unit": "g", "grams_equiv": 10},
                "persona_b": {"qty": 10, "unit": "g", "grams_equiv": 10},
            }},
        ],
        "steps": ["Saltare le verdure", "Sbattere le uova e unire", "Cuocere in padella antiaderente"],
        "total_time_minutes": 20,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_pasta_legumi",
        "name": "Pasta e Fagioli",
        "description": "Pasta con fagioli borlotti in brodo",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": {
                "persona_a": {"qty": 60, "unit": "g", "grams_equiv": 60},
                "persona_b": {"qty": 60, "unit": "g", "grams_equiv": 60},
            }},
            {"name": "fagioli", "food_group": "legumi", "quantities": {
                "persona_a": {"qty": 120, "unit": "g", "grams_equiv": 120},
                "persona_b": {"qty": 120, "unit": "g", "grams_equiv": 120},
            }},
            {"name": "cipolla", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50},
                "persona_b": {"qty": 50, "unit": "g", "grams_equiv": 50},
            }},
            {"name": "olio", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 15, "unit": "g", "grams_equiv": 15},
                "persona_b": {"qty": 15, "unit": "g", "grams_equiv": 15},
            }},
        ],
        "steps": ["Soffriggere cipolla e aglio", "Aggiungere fagioli e brodo", "Unire la pasta e cuocere"],
        "total_time_minutes": 35,
        "difficulty": "media",
        "tags": {"mood": ["confort"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_insalata_tonno",
        "name": "Insalata di Tonno",
        "description": "Insalata fresca con tonno, pomodorini e cetrioli",
        "is_composed_dish": False,
        "content": [
            {"name": "tonno", "food_group": "pesce", "quantities": {
                "persona_a": {"qty": 120, "unit": "g", "grams_equiv": 120},
                "persona_b": {"qty": 120, "unit": "g", "grams_equiv": 120},
            }},
            {"name": "insalata", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 100, "unit": "g", "grams_equiv": 100},
                "persona_b": {"qty": 100, "unit": "g", "grams_equiv": 100},
            }},
            {"name": "pomodoro", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 100, "unit": "g", "grams_equiv": 100},
                "persona_b": {"qty": 100, "unit": "g", "grams_equiv": 100},
            }},
            {"name": "olio", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 10, "unit": "g", "grams_equiv": 10},
                "persona_b": {"qty": 10, "unit": "g", "grams_equiv": 10},
            }},
        ],
        "steps": ["Lavare e tagliare le verdure", "Scolare il tonno", "Unire e condire"],
        "total_time_minutes": 10,
        "difficulty": "facile",
        "tags": {"mood": ["leggero"], "cleanup": ["facile"], "cooking_methods": ["crudo"]},
    },
    {
        "id": "seed_risotto_funghi",
        "name": "Risotto ai Funghi",
        "description": "Risotto cremoso con funghi champignon e parmigiano",
        "is_composed_dish": False,
        "content": [
            {"name": "riso", "food_group": "carboidrati", "quantities": {
                "persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80},
                "persona_b": {"qty": 80, "unit": "g", "grams_equiv": 80},
            }},
            {"name": "fungo", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150},
                "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150},
            }},
            {"name": "cipolla", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 30, "unit": "g", "grams_equiv": 30},
                "persona_b": {"qty": 30, "unit": "g", "grams_equiv": 30},
            }},
            {"name": "burro", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 20, "unit": "g", "grams_equiv": 20},
                "persona_b": {"qty": 20, "unit": "g", "grams_equiv": 20},
            }},
        ],
        "steps": ["Soffriggere cipolla con burro", "Tostare il riso", "Aggiungere funghi e brodo a mestoli", "Mantecare"],
        "total_time_minutes": 40,
        "difficulty": "media",
        "tags": {"mood": ["confort"], "cleanup": ["media"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_tacchino_forno",
        "name": "Tacchino al Forno",
        "description": "Fetta di tacchino al forno con patate e rosmarino",
        "is_composed_dish": False,
        "content": [
            {"name": "tacchino", "food_group": "pollo", "quantities": {
                "persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150},
                "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150},
            }},
            {"name": "patate", "food_group": "carboidrati", "quantities": {
                "persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150},
                "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150},
            }},
            {"name": "olio", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 15, "unit": "g", "grams_equiv": 15},
                "persona_b": {"qty": 15, "unit": "g", "grams_equiv": 15},
            }},
        ],
        "steps": ["Tagliare patate e condire", "Sistemare tacchino e patate in teglia", "Cuocere in forno 35 minuti a 180°"],
        "total_time_minutes": 50,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["media"], "cooking_methods": ["forno"]},
    },
    {
        "id": "seed_zuppa_ceci",
        "name": "Zuppa di Ceci",
        "description": "Zuppa di ceci con rosmarino e olio a crudo",
        "is_composed_dish": False,
        "content": [
            {"name": "ceci", "food_group": "legumi", "quantities": {
                "persona_a": {"qty": 150, "unit": "g", "grams_equiv": 150},
                "persona_b": {"qty": 150, "unit": "g", "grams_equiv": 150},
            }},
            {"name": "aglio", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 10, "unit": "g", "grams_equiv": 10},
                "persona_b": {"qty": 10, "unit": "g", "grams_equiv": 10},
            }},
            {"name": "olio", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 15, "unit": "g", "grams_equiv": 15},
                "persona_b": {"qty": 15, "unit": "g", "grams_equiv": 15},
            }},
        ],
        "steps": ["Soffriggere aglio in olio", "Aggiungere ceci e brodo", "Cuocere 20 minuti e frullare parzialmente"],
        "total_time_minutes": 30,
        "difficulty": "facile",
        "tags": {"mood": ["confort"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
    },
    {
        "id": "seed_pasta_broccoli",
        "name": "Pasta con Broccoli",
        "description": "Pasta con broccoli saltati in padella con aglio e olio",
        "is_composed_dish": False,
        "content": [
            {"name": "pasta", "food_group": "carboidrati", "quantities": {
                "persona_a": {"qty": 80, "unit": "g", "grams_equiv": 80},
                "persona_b": {"qty": 80, "unit": "g", "grams_equiv": 80},
            }},
            {"name": "broccoli", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 200, "unit": "g", "grams_equiv": 200},
                "persona_b": {"qty": 200, "unit": "g", "grams_equiv": 200},
            }},
            {"name": "aglio", "food_group": "verdure", "quantities": {
                "persona_a": {"qty": 10, "unit": "g", "grams_equiv": 10},
                "persona_b": {"qty": 10, "unit": "g", "grams_equiv": 10},
            }},
            {"name": "olio", "food_group": "grassi", "quantities": {
                "persona_a": {"qty": 15, "unit": "g", "grams_equiv": 15},
                "persona_b": {"qty": 15, "unit": "g", "grams_equiv": 15},
            }},
        ],
        "steps": ["Bollire i broccoli", "Cuocere la pasta", "Saltare broccoli con aglio e olio, unire pasta"],
        "total_time_minutes": 25,
        "difficulty": "facile",
        "tags": {"mood": ["normale"], "cleanup": ["facile"], "cooking_methods": ["tegame"]},
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
