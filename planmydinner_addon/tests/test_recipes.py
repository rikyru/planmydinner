import pytest

# Use fixtures from conftest.py
# client: TestClient (FastAPI test client)
# setup_database: fixture to create/drop test database

def get_sample_recipe_data(recipe_id: str = "recipe_001"):
    return {
        "id": recipe_id,
        "name": "Pasta al Pesto",
        "description": "Una classica pasta al pesto genovese.",
        "is_composed_dish": False,
        "content": [
            {
                "name": "Pasta",
                "food_group": "carboidrati",
                "quantities": {
                    "persona_a": {"qty": 100, "unit": "g", "grams_equiv": 100},
                    "persona_b": {"qty": 80, "unit": "g", "grams_equiv": 80},
                },
            },
            {
                "name": "Pesto",
                "food_group": "grassi",
                "quantities": {
                    "persona_a": {"qty": 50, "unit": "g", "grams_equiv": 50},
                    "persona_b": {"qty": 40, "unit": "g", "grams_equiv": 40},
                },
            },
        ],
        "steps": ["Cuocere la pasta.", "Condire con pesto."],
        "total_time_minutes": 15,
        "difficulty": "facile",
        "tags": {
            "mood": ["quick"],
            "cleanup": ["low_mess"],
            "cooking_methods": ["bollitura"],
            "other": ["vegetariano"],
        },
    }


def test_create_recipe(client, setup_database):
    recipe_data = get_sample_recipe_data()
    response = client.post("/recipes/", json=recipe_data)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "recipe_001"
    assert data["name"] == "Pasta al Pesto"
    assert len(data["content"]) == 2
    assert data["difficulty"] == "facile"


def test_create_existing_recipe(client, setup_database):
    recipe_data = get_sample_recipe_data()
    client.post("/recipes/", json=recipe_data)
    response = client.post("/recipes/", json=recipe_data)
    assert response.status_code == 400
    assert response.json() == {"detail": "Recipe with this ID already exists"}


def test_read_recipe(client, setup_database):
    recipe_data = get_sample_recipe_data()
    client.post("/recipes/", json=recipe_data)
    response = client.get(f"/recipes/{recipe_data['id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == recipe_data["id"]
    assert data["name"] == recipe_data["name"]


def test_read_non_existent_recipe(client, setup_database):
    response = client.get("/recipes/non_existent_id")
    assert response.status_code == 404
    assert response.json() == {"detail": "Recipe not found"}


def test_read_all_recipes(client, setup_database):
    recipe_data1 = get_sample_recipe_data("recipe_001")
    recipe_data2 = get_sample_recipe_data("recipe_002")
    recipe_data2["name"] = "Risotto ai Funghi"

    client.post("/recipes/", json=recipe_data1)
    client.post("/recipes/", json=recipe_data2)

    response = client.get("/recipes/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3 # 1 from setup_database + 2 added in this test
    all_recipe_names = {item["name"] for item in data}
    assert "Pasta al Pomodoro" in all_recipe_names
    assert "Pasta al Pesto" in all_recipe_names
    assert "Risotto ai Funghi" in all_recipe_names


def test_update_recipe(client, setup_database):
    recipe_data = get_sample_recipe_data()
    client.post("/recipes/", json=recipe_data)

    updated_data = recipe_data.copy()
    updated_data["total_time_minutes"] = 20
    updated_data["difficulty"] = "media"

    response = client.put(f"/recipes/{recipe_data['id']}", json=updated_data)
    assert response.status_code == 200
    data = response.json()
    assert data["total_time_minutes"] == 20
    assert data["difficulty"] == "media"


def test_delete_recipe(client, setup_database):
    recipe_data = get_sample_recipe_data()
    client.post("/recipes/", json=recipe_data)

    delete_response = client.delete(f"/recipes/{recipe_data['id']}")
    assert delete_response.status_code == 200

    get_response = client.get(f"/recipes/{recipe_data['id']}")
    assert get_response.status_code == 404