import pytest
from datetime import date
from unittest.mock import patch, mock_open
from io import BytesIO # Required for mocking file content

# Use fixtures from conftest.py
# client: TestClient (FastAPI test client)
# setup_database: fixture to create/drop test database

from pdf_parser import PDFParser, PDFParsingError
import schemas
from database import UnitConversion # Import directly

# Define the mock content once
MOCK_PRANZO_CENA_PDF_CONTENT = """
GRAMMATURE
METODI DI COTTURA: vapore, tegame
FREQUENZE SETTIMANALI:
uova: max 2/settimana, min 1/settimana
carne rossa: max 1/settimana, min 0/settimana

COLAZIONE
PRANZO
Riso integrale 80 g
Salmone 150 g
Olio EVO 1 cucchiaio
Verdure miste 1 piatto

CENA
Zuppa di legumi 300 ml
Pane integrale 50 g
Frutta 1 porzione
"""

MOCK_EMPTY_SECTIONS_PDF_CONTENT = """
PRANZO
Riso 100 g

CENA
"""

@pytest.fixture(scope="function")
def seeded_parser_database(setup_database):
    # This fixture uses the setup_database fixture and adds specific seed data for the parser
    db_session = setup_database # setup_database yields a session
    
    db_session.commit()
    return db_session


# Patch the methods of the PDFParser instance directly
@patch.object(PDFParser, "_extract_tables_content", return_value=[])
@patch.object(PDFParser, "_extract_text_content")
def test_pdf_parser_extracts_and_structures_data(mock_extract_text_content, mock_extract_tables_content, seeded_parser_database):
    db_session = seeded_parser_database
    
    mock_extract_text_content.return_value = MOCK_PRANZO_CENA_PDF_CONTENT

    parser = PDFParser(db_session)
    pdf_path = "/tmp/test.pdf" # Path is irrelevant as methods are mocked
    profile_id = "persona_test"
    
    structured_plan = parser.parse_pdf(pdf_path, profile_id)

    assert structured_plan.profile_id == profile_id
    assert len(structured_plan.daily_plans) == 1
    assert structured_plan.daily_plans[0].date == date.today() # Placeholder
    assert len(structured_plan.daily_plans[0].meals) == 2

    # Test Pranzo
    pranzo = structured_plan.daily_plans[0].meals[0]
    assert pranzo.meal_type == "pranzo"
    assert len(pranzo.items) == 4
    assert pranzo.items[0].item_name == "Riso integrale"
    assert pranzo.items[0].quantity == 80
    assert pranzo.items[0].unit == "g"
    assert pranzo.items[0].food_group == "carboidrati"

    assert pranzo.items[1].item_name == "Salmone"
    assert pranzo.items[1].quantity == 150
    assert pranzo.items[1].unit == "g"
    assert pranzo.items[1].food_group == "proteine"

    assert pranzo.items[2].item_name == "Olio EVO"
    assert pranzo.items[2].quantity == 1
    assert pranzo.items[2].unit == "cucchiaio"
    assert pranzo.items[2].food_group == "grassi"
    assert pranzo.items[2].is_estimated_unit == False 

    assert pranzo.items[3].item_name == "Verdure miste"
    assert pranzo.items[3].quantity == 1
    assert pranzo.items[3].unit == "piatto"
    assert pranzo.items[3].food_group == "verdure"
    assert pranzo.items[3].is_estimated_unit == False 

    # Test Cena
    cena = structured_plan.daily_plans[0].meals[1]
    assert cena.meal_type == "cena"
    assert len(cena.items) == 3
    assert cena.items[0].item_name == "Zuppa di legumi"
    assert cena.items[0].quantity == 300
    assert cena.items[0].unit == "ml"
    assert cena.items[0].food_group == "proteine"

    assert cena.items[1].item_name == "Pane integrale"
    assert cena.items[1].quantity == 50
    assert cena.items[1].unit == "g"
    assert cena.items[1].food_group == "carboidrati"

    assert cena.items[2].item_name == "Frutta"
    assert cena.items[2].quantity == 1
    assert cena.items[2].unit == "porzione"
    assert cena.items[2].food_group == "frutta"
    assert cena.items[2].is_estimated_unit == False 


@patch.object(PDFParser, "_extract_tables_content", return_value=[])
@patch.object(PDFParser, "_extract_text_content")
def test_pdf_parser_handles_empty_sections(mock_extract_text_content, mock_extract_tables_content, seeded_parser_database):
    db_session = seeded_parser_database
    
    mock_extract_text_content.return_value = MOCK_EMPTY_SECTIONS_PDF_CONTENT

    parser = PDFParser(db_session)
    structured_plan = parser.parse_pdf("/tmp/test.pdf", "persona_test")
    
    assert structured_plan.profile_id == "persona_test"
    assert len(structured_plan.daily_plans) == 1
    assert len(structured_plan.daily_plans[0].meals) == 2 
    
    assert structured_plan.daily_plans[0].meals[0].meal_type == "pranzo"
    assert len(structured_plan.daily_plans[0].meals[0].items) == 1
    assert structured_plan.daily_plans[0].meals[1].meal_type == "cena"
    assert len(structured_plan.daily_plans[0].meals[1].items) == 0 # Cena is empty

@patch.object(PDFParser, "_extract_tables_content", return_value=[])
@patch.object(PDFParser, "_extract_text_content")
def test_pdf_parser_raises_error_for_unknown_template(mock_extract_text_content, mock_extract_tables_content, seeded_parser_database):
    db_session = seeded_parser_database
    
    mock_extract_text_content.return_value = ""
    
    parser = PDFParser(db_session)
    with pytest.raises(PDFParsingError, match="Parsing template 'unknown' not found."):
        parser.parse_pdf("/tmp/test.pdf", "persona_test", template_name="unknown")