import pytest
from datetime import date

# Use fixtures from conftest.py
# client: TestClient (FastAPI test client)
# setup_database: fixture to create/drop test database

def test_mark_meal_as_consumed_planned(client, setup_database):
    # First, create a user profile to link to
    client.post("/profiles/", json={"id": "persona_a", "name": "Test User"})
    
    today = date.today().isoformat()
    response = client.post(
        f"/consumed-entries/mark-planned?profile_id=persona_a&meal_date={today}&meal_type=pranzo&recipe_id=pasta_pomodoro_recipe"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["profile_id"] == "persona_a"
    assert data["date"] == today
    assert data["meal_type"] == "pranzo"
    assert data["type"] == "planned"
    assert data["consumed_recipe_id"] == "pasta_pomodoro_recipe"
    assert data["override_details"] is None

def test_mark_meal_as_consumed_override_simple(client, setup_database):
    client.post("/profiles/", json={"id": "persona_b", "name": "Test User 2"})
    
    today = date.today().isoformat()
    override_data = {
        "free_text_name": "Panino al bar"
    }
    
    response = client.post(
        f"/consumed-entries/override?profile_id=persona_b&meal_date={today}&meal_type=cena",
        json=override_data,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["profile_id"] == "persona_b"
    assert data["type"] == "override"
    assert data["override_details"]["free_text_name"] == "Panino al bar"
    assert data["override_details"]["ingredients"] is None

def test_mark_meal_as_consumed_override_structured(client, setup_database):
    client.post("/profiles/", json={"id": "persona_a", "name": "Test User"})
    
    today = date.today().isoformat()
    override_data = {
        "free_text_name": "Torta salata",
        "ingredients": [
            {"name": "pasta sfoglia", "qty": 1, "unit": "rotolo"},
            {"name": "ricotta", "qty": 250, "unit": "g"},
        ],
        "notes": "Fatta in casa"
    }

    response = client.post(
        f"/consumed-entries/override?profile_id=persona_a&meal_date={today}&meal_type=cena",
        json=override_data,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "override"
    assert data["override_details"]["free_text_name"] == "Torta salata"
    assert len(data["override_details"]["ingredients"]) == 2
    assert data["override_details"]["notes"] == "Fatta in casa"

def test_read_consumed_entries(client, setup_database):
    client.post("/profiles/", json={"id": "persona_a", "name": "Test User"})
    today = date.today().isoformat()

    client.post(f"/consumed-entries/mark-planned?profile_id=persona_a&meal_date={today}&meal_type=pranzo&recipe_id=recipe_001")
    client.post(f"/consumed-entries/override?profile_id=persona_a&meal_date={today}&meal_type=cena", json={"free_text_name": "Pizza"})
    
    response = client.get(f"/consumed-entries/?profile_id=persona_a&start_date={today}&end_date={today}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["type"] == "planned"
    assert data[1]["type"] == "override"

def test_mark_planned_consumes_from_pantry(client, setup_database):
    # Ensure recipe and pantry items are seeded by setup_database fixture
    # User profile for persona_a is assumed to be created by other tests or fixture
    client.post("/profiles/", json={"id": "persona_a", "name": "Test User"})

    # Check initial pantry state for "Pasta" and "Pomodoro"
    pantry_items_response = client.get("/pantry/items")
    initial_pasta_qty = next(item["quantity"] for item in pantry_items_response.json() if item["name"] == "Pasta")
    initial_pomodoro_qty = next(item["quantity"] for item in pantry_items_response.json() if item["name"] == "Pomodoro")

    assert initial_pasta_qty == 500.0
    assert initial_pomodoro_qty == 400.0

    # Mark "Pasta al Pomodoro" as consumed for persona_a
    # The recipe_id "pasta_pomodoro_recipe" was seeded in conftest.py
    today = date.today().isoformat()
    response = client.post(
        f"/consumed-entries/mark-planned?profile_id=persona_a&meal_date={today}&meal_type=pranzo&recipe_id=pasta_pomodoro_recipe"
    )
    assert response.status_code == 200

    # Check updated pantry state
    pantry_items_after_consumption = client.get("/pantry/items")
    current_pasta_qty = next(item["quantity"] for item in pantry_items_after_consumption.json() if item["name"] == "Pasta")
    current_pomodoro_qty = next(item["quantity"] for item in pantry_items_after_consumption.json() if item["name"] == "Pomodoro")

    assert current_pasta_qty == (initial_pasta_qty - 100) # 100g consumed for persona_a
    assert current_pomodoro_qty == (initial_pomodoro_qty - 200) # 200g consumed for persona_a

def test_mark_override_consumes_from_pantry(client, setup_database):
    # User profile for persona_a is assumed to be created by other tests or fixture
    client.post("/profiles/", json={"id": "persona_a", "name": "Test User"})

    # Check initial pantry state for "Pasta Sfoglia" and "Ricotta"
    pantry_items_response = client.get("/pantry/items")
    initial_sfoglia_qty = next(item["quantity"] for item in pantry_items_response.json() if item["name"] == "Pasta Sfoglia")
    initial_ricotta_qty = next(item["quantity"] for item in pantry_items_response.json() if item["name"] == "Ricotta")

    assert initial_sfoglia_qty == 2.0
    assert initial_ricotta_qty == 500.0

    today = date.today().isoformat()
    override_data = {
        "free_text_name": "Torta salata",
        "ingredients": [
            {"name": "pasta sfoglia", "qty": 1, "unit": "rotolo"},
            {"name": "ricotta", "qty": 250, "unit": "g"},
        ],
        "notes": "Fatta in casa"
    }

    response = client.post(
        f"/consumed-entries/override?profile_id=persona_a&meal_date={today}&meal_type=cena",
        json=override_data,
    )
    assert response.status_code == 200

    # Check updated pantry state
    pantry_items_after_consumption = client.get("/pantry/items")
    current_sfoglia_qty = next(item["quantity"] for item in pantry_items_after_consumption.json() if item["name"] == "Pasta Sfoglia")
    current_ricotta_qty = next(item["quantity"] for item in pantry_items_after_consumption.json() if item["name"] == "Ricotta")

    assert current_sfoglia_qty == (initial_sfoglia_qty - 1)
    assert current_ricotta_qty == (initial_ricotta_qty - 250)