import pytest

# client / setup_database fixtures come from conftest.py


def test_shopping_checks_persist(client, setup_database):
    sd = "2026-02-19"
    # starts empty
    r = client.get("/shopping-list/checks", params={"start_date": sd})
    assert r.status_code == 200 and r.json()["checked"] == []
    # add (normalized to lowercase)
    r = client.post("/shopping-list/checks", json={"start_date": sd, "item_key": "Latte"})
    assert r.status_code == 200
    assert client.get("/shopping-list/checks", params={"start_date": sd}).json()["checked"] == ["latte"]
    # idempotent
    client.post("/shopping-list/checks", json={"start_date": sd, "item_key": "latte"})
    assert client.get("/shopping-list/checks", params={"start_date": sd}).json()["checked"] == ["latte"]
    # another week is isolated
    assert client.get("/shopping-list/checks", params={"start_date": "2026-03-01"}).json()["checked"] == []
    # delete one
    client.delete("/shopping-list/checks", params={"start_date": sd, "item_key": "latte"})
    assert client.get("/shopping-list/checks", params={"start_date": sd}).json()["checked"] == []
    # clear all
    client.post("/shopping-list/checks", json={"start_date": sd, "item_key": "pane"})
    client.post("/shopping-list/checks", json={"start_date": sd, "item_key": "uova"})
    client.post("/shopping-list/checks/clear", params={"start_date": sd})
    assert client.get("/shopping-list/checks", params={"start_date": sd}).json()["checked"] == []
