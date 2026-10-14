import pytest

# Use fixtures from conftest.py
# client: TestClient (FastAPI test client)
# setup_database: fixture to create/drop test database

def test_create_pantry_item(client, setup_database):
    response = client.post(
        "/pantry/items",
        json={"name": "Flour", "quantity": 1, "unit": "kg"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Flour"
    assert data["quantity"] == 1.0
    assert data["unit"] == "kg"
    assert "id" in data

def test_read_pantry_items(client, setup_database):
    response = client.get("/pantry/items")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4 # Expect 4 items seeded by setup_database
    seeded_names = {"Pasta", "Pomodoro", "Pasta Sfoglia", "Ricotta"}
    retrieved_names = {item["name"] for item in data}
    assert seeded_names == retrieved_names

def test_update_pantry_item(client, setup_database):
    create_response = client.post(
        "/pantry/items",
        json={"name": "Milk", "quantity": 1, "unit": "l"},
    )
    item_id = create_response.json()["id"]

    update_response = client.put(
        f"/pantry/items/{item_id}",
        json={"name": "Almond Milk", "quantity": 0.5, "unit": "l"},
    )
    assert update_response.status_code == 200
    data = update_response.json()
    assert data["name"] == "Almond Milk"
    assert data["quantity"] == 0.5

def test_delete_pantry_item(client, setup_database):
    create_response = client.post(
        "/pantry/items",
        json={"name": "Eggs", "quantity": 12, "unit": "pcs"},
    )
    item_id = create_response.json()["id"]

    # Delete the item
    delete_response = client.delete(f"/pantry/items/{item_id}")
    assert delete_response.status_code == 200

    # Verify it's gone
    get_response = client.get(f"/pantry/items/{item_id}")
    assert get_response.status_code == 404


def test_pantry_min_quantity_and_low_stock(client, setup_database):
    r = client.post("/pantry/items", json={"name": "Olio", "quantity": 50, "unit": "ml", "min_quantity": 200})
    assert r.status_code == 200 and r.json()["min_quantity"] == 200
    low = client.get("/pantry/low-stock").json()
    assert any(i["name"] == "Olio" for i in low)
    # un item sopra soglia non deve comparire
    client.post("/pantry/items", json={"name": "Riso", "quantity": 1000, "unit": "g", "min_quantity": 300})
    low2 = client.get("/pantry/low-stock").json()
    assert not any(i["name"] == "Riso" for i in low2)
