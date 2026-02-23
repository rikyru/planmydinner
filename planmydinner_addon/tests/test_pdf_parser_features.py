import pytest
from unittest.mock import MagicMock, patch
from planmydinner_addon.pdf_parser import PDFParser, UnitConverter
from planmydinner_addon import schemas
from datetime import date

@pytest.fixture
def db_session_mock():
    db = MagicMock()
    db.query.return_value.all.return_value = [] # No unit conversions for simplicity
    return db

@pytest.fixture
def mock_unit_converter(db_session_mock):
    # Mock the unit converter to avoid db calls and to control food group mapping
    converter = UnitConverter(db_session_mock)
    original_get_food_group = converter.get_food_group_for_item
    def get_food_group_mock(item_name):
        if 'pane' in item_name: return 'carboidrati'
        if 'pollo' in item_name: return 'proteine'
        if 'insalata' in item_name: return 'verdure'
        if 'pomodori' in item_name: return 'verdure'
        return original_get_food_group(item_name)
    
    converter.get_food_group_for_item = get_food_group_mock
    converter.convert_to_grams = MagicMock(return_value=100.0)
    converter.convert_to_ml = MagicMock(return_value=100.0)
    return converter

def test_parse_alternatives(db_session_mock, mock_unit_converter):
    """Test that alternatives are correctly parsed and nested."""
    parser = PDFParser(db_session_mock)
    parser.unit_converter = mock_unit_converter
    
    fake_pdf_text = """
    PRANZO
    Pane di segale 50 g
    Alternative:
    Pane integrale 50 g
    Gnocchi di patate 150 g
    """
    
    with patch.object(parser, '_extract_text_content', return_value=fake_pdf_text):
        plan = parser.parse_pdf("fake.pdf", "test_profile")
        
    pranzo_meal = next(m for m in plan.daily_plans[0].meals if m.meal_type == 'pranzo')
    assert len(pranzo_meal.items) == 1
    main_item = pranzo_meal.items[0]
    assert main_item.item_name == "Pane di segale"
    assert len(main_item.alternatives) == 2
    assert main_item.alternatives[0].item_name == "Pane integrale"
    assert main_item.alternatives[1].item_name == "Gnocchi di patate"

def test_parse_free_vegetables_in_cena(db_session_mock, mock_unit_converter):
    """Test that vegetables mentioned in notes for CENA are added as free items."""
    parser = PDFParser(db_session_mock)
    parser.unit_converter = mock_unit_converter

    fake_pdf_text = """
    CENA
    Petto di pollo 150 g
    Accompagnare con insalata e pomodori.
    """

    with patch.object(parser, '_extract_text_content', return_value=fake_pdf_text):
        plan = parser.parse_pdf("fake.pdf", "test_profile")

    cena_meal = next(m for m in plan.daily_plans[0].meals if m.meal_type == 'cena')
    assert len(cena_meal.items) == 3 # Pollo, insalata, pomodori
    
    pollo = next(i for i in cena_meal.items if i.item_name == 'Petto di pollo')
    assert pollo.quantity == 150

    insalata = next(i for i in cena_meal.items if i.item_name == 'insalata')
    assert insalata.quantity == 0
    assert insalata.food_group == 'verdure'
    assert insalata.is_estimated_unit is True
    assert insalata.shopping_list_quantity == 200.0

    pomodori = next(i for i in cena_meal.items if i.item_name == 'pomodori')
    assert pomodori.quantity == 0
    assert pomodori.food_group == 'verdure'

def test_no_free_vegetables_in_pranzo(db_session_mock, mock_unit_converter):
    """Test that vegetables in notes are NOT added for PRANZO."""
    parser = PDFParser(db_session_mock)
    parser.unit_converter = mock_unit_converter

    fake_pdf_text = """
    PRANZO
    Pasta al pesto 80g
    Aggiungere pomodorini a piacere.
    """

    with patch.object(parser, '_extract_text_content', return_value=fake_pdf_text):
        plan = parser.parse_pdf("fake.pdf", "test_profile")

    pranzo_meal = next(m for m in plan.daily_plans[0].meals if m.meal_type == 'pranzo')
    # Should only contain "Pasta al pesto"
    assert len(pranzo_meal.items) == 1
    assert pranzo_meal.items[0].item_name == "Pasta al pesto"
