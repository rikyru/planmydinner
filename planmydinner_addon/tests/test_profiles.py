import pytest

# Use fixtures from conftest.py
# client: TestClient (FastAPI test client)
# setup_database: fixture to create/drop test database

def test_create_user_profile(client, setup_database):
    response = client.post(
        "/profiles/",
        json={"id": "persona_a", "name": "Mario Rossi"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "persona_a"
    assert data["name"] == "Mario Rossi"
    assert "allergies" in data


def test_create_existing_user_profile(client, setup_database):
    client.post(
        "/profiles/",
        json={"id": "persona_a", "name": "Mario Rossi"},
    )
    response = client.post(
        "/profiles/",
        json={"id": "persona_a", "name": "Mario Bianchi"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Profile with this ID already exists"}


def test_read_user_profile(client, setup_database):
    client.post(
        "/profiles/",
        json={"id": "persona_a", "name": "Mario Rossi"},
    )
    response = client.get("/profiles/persona_a")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "persona_a"
    assert data["name"] == "Mario Rossi"


def test_read_non_existent_user_profile(client, setup_database):
    response = client.get("/profiles/persona_z")
    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found"}


def test_read_user_profiles(client, setup_database):
    client.post("/profiles/", json={"id": "persona_a", "name": "Mario"})
    client.post("/profiles/", json={"id": "persona_b", "name": "Luisa"})
    response = client.get("/profiles/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "Mario"
    assert data[1]["name"] == "Luisa"


def test_update_user_profile(client, setup_database):
    client.post("/profiles/", json={"id": "persona_a", "name": "Mario"})
    response = client.put(
        "/profiles/persona_a",
        json={"id": "persona_a", "name": "Mario Verdi", "allergies": ["nuts"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Mario Verdi"
    assert data["allergies"] == ["nuts"]


def test_delete_user_profile(client, setup_database):
    client.post("/profiles/", json={"id": "persona_a", "name": "Mario"})
    
    # Delete the profile
    delete_response = client.delete("/profiles/persona_a")
    assert delete_response.status_code == 200
    
    # Verify it's gone
    get_response = client.get("/profiles/persona_a")
    assert get_response.status_code == 404
