from planmydinner_addon.api.balance import week_payload


def test_week_payload_keeps_only_eaten_days_and_meals():
    summary = {"targets": {"kcal": 1900}, "days": [
        {"date": "2026-11-10", "nutrition": {"kcal": 1800, "protein_g": 120, "carbs_g": 200, "fat_g": 55},
         "routine_items": ["Colazione: Latte e muesli", "Dopo cena: Frutta"],
         "produce": {"veg_g": 150, "fruit_g": 220},
         "extras": [{"name": "Merenda extra", "description": "mela"}],
         "meals": {"cena": {"consumed": True, "ingredients": [{"name": "Zucchine", "grams": 150.4}]},
                   "pranzo": {"consumed": False, "ingredients": [{"name": "Pasta", "grams": 80}]}}},
        {"date": "2026-11-11", "nutrition": None},
        {"date": "2026-11-12", "nutrition": {"kcal": 1}, "future": True},
    ]}
    routine = {"dopo_cena": {"name": "Frutta", "content": [
        {"name": "Mela", "quantities": {"p": {"qty": 150, "grams_equiv": 150}}}]}}
    w = week_payload(summary, routine, "p")
    assert w["composizione_pasti_fissi"] == {"Frutta": ["Mela 150 g"]}
    assert len(w["giorni"]) == 1
    g = w["giorni"][0]
    assert g["cena"] == ["Zucchine 150 g"] and "pranzo" not in g
    assert g["frutta_g"] == 220 and g["extra"] == ["mela"]
