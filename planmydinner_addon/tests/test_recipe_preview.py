"""Anteprima nutrizionale + diagnostica di una ricetta in bozza."""
from planmydinner_addon.nutrition import analyze_recipe


def _ing(name, fg, grams):
    return {"name": name, "food_group": fg,
            "quantities": {"persona_a": {"qty": grams, "unit": "g", "grams_equiv": grams}}}


def test_analyze_flags_missing_grams_and_unknown():
    content = [
        _ing("Pasta", "carboidrati", 80),        # ok
        _ing("Pollo", "proteina", 0),             # senza grammi
        _ing("Ingrediente Misterioso", "altro", 50),  # sconosciuto, niente LLM
    ]
    res = analyze_recipe(content, "persona_a")
    issues = {i["ingredient"]: i["issue"] for i in res["issues"]}
    assert issues["Pollo"] == "no_grams"
    assert issues["Ingrediente Misterioso"] == "unknown"
    assert res["nutrition"] is not None            # la pasta è comunque conteggiata
    assert "no_added_fat" in res["warnings"]        # nessun olio nella bozza


def test_analyze_no_warning_when_oil_present():
    content = [
        _ing("Pasta", "carboidrati", 80),
        _ing("Olio extravergine d'oliva", "condimenti", 10),
    ]
    res = analyze_recipe(content, "persona_a")
    assert "no_added_fat" not in res["warnings"]
    assert not res["issues"]


def test_preview_endpoint(client, setup_database):
    content = [
        _ing("Pasta", "carboidrati", 80),
        _ing("Pomodoro", "verdura", 200),
    ]
    r = client.post("/recipes/preview-nutrition",
                    json={"content": content, "profile_id": "persona_a"})
    assert r.status_code == 200, r.text
    prof = r.json()["by_profile"]["persona_a"]
    assert prof["nutrition"]["kcal"] > 0
    assert "no_added_fat" in prof["warnings"]       # bozza senza olio
