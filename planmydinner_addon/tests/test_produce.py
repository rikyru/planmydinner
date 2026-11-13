from planmydinner_addon.produce import classify, content_produce, items_produce


def test_classify_by_group_and_name():
    assert classify("Banana", "altro") == "fruit"                 # gruppo generico: vale il nome
    assert classify("Fagiolini", "verdure") == "veg"
    assert classify("Mela", "frutta") == "fruit"
    assert classify("Insalata mista", "altro") == "veg"
    assert classify("Yogurt greco mirtillo · Delta", "altro") is None   # non è frutta
    assert classify("Patate al forno", "verdure") is None              # patate: no
    assert classify("Ceci", "legumi") is None
    assert classify("Pasta al pomodoro", "carboidrati") is None
    assert classify("Succo d'arancia", "frutta") is None


def test_content_and_items_grams():
    content = [
        {"name": "Zucchine", "food_group": "verdure", "quantities": {"p": {"qty": 200, "unit": "g", "grams_equiv": 200}}},
        {"name": "Pollo", "food_group": "carne_bianca", "quantities": {"p": {"qty": 150, "unit": "g", "grams_equiv": 150}}},
        {"name": "Kiwi", "food_group": "altro", "quantities": {"p": {"qty": 100, "unit": "g", "grams_equiv": 100}}},
    ]
    assert content_produce(content, "p") == {"veg_g": 200, "fruit_g": 100}
    assert items_produce([{"name": "Mela", "qty": 180}, {"name": "Crackers", "qty": 30}]) == {"veg_g": 0, "fruit_g": 180}
