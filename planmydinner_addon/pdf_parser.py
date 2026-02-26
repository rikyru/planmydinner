import logging
import re
import uuid
from datetime import date
from typing import Dict, List, Any, Optional

from pdfminer.high_level import extract_text
import tabula
import pandas as pd

from . import schemas
from .database import SessionLocal, UnitConversion, RotationRule

from .llm_gateway import LLMGateway

_LOGGER = logging.getLogger(__name__)

class PDFParsingError(Exception):
    """Custom exception for PDF parsing errors."""
    pass

# Define a common list of units to make the regex more readable and maintainable
UNITS = [
    "g", "ml", "fette", "cucchiaio", "cucchiaino", "tazza", "bicchiere",
    "vasetto", "lattina", "porzione", "porzioni", "pz", "piatto"
]
UNITS_REGEX_PATTERN = "|".join(sorted(UNITS, key=len, reverse=True)) # Sort by length to avoid partial matches


class UnitConverter:
    """Handles unit conversions using a database lookup."""

    def __init__(self, db_session: SessionLocal):
        self.db = db_session
        self.conversions: Dict[str, schemas.UnitConversion] = {}
        self._load_conversions()

    def _load_conversions(self):
        """Load unit conversion rates from the database."""
        db_conversions = self.db.query(UnitConversion).all()
        for conv in db_conversions:
            _LOGGER.debug(f"Loading conversion for unit '{conv.unit}': grams_equiv={conv.grams_equivalent}, ml_equiv={conv.ml_equivalent}")
            self.conversions[conv.unit.lower()] = schemas.UnitConversion(
                unit=conv.unit,
                grams_equivalent=conv.grams_equivalent,
                ml_equivalent=conv.ml_equivalent
            )

    def convert_to_grams(self, quantity: float, unit: str) -> Optional[float]:
        """Convert a quantity to grams if a conversion is known."""
        unit_lower = unit.lower()
        if unit_lower in self.conversions and self.conversions[unit_lower].grams_equivalent is not None:
            return quantity * self.conversions[unit_lower].grams_equivalent
        return None

    def convert_to_ml(self, quantity: float, unit: str) -> Optional[float]:
        """Convert a quantity to milliliters if a conversion is known."""
        unit_lower = unit.lower()
        if unit_lower in self.conversions and self.conversions[unit_lower].ml_equivalent is not None:
            return quantity * self.conversions[unit_lower].ml_equivalent
        return None


class PDFParser:
    """
    Parses a PDF meal plan and extracts structured data.
    This version includes placeholders for template loading and more advanced parsing.
    """
    def __init__(self, db: SessionLocal, llm_gateway: Optional[LLMGateway] = None):
        self.unit_converter = UnitConverter(db)
        self.llm_gateway = llm_gateway
        self.parsing_templates: Dict[str, Any] = self._load_parsing_templates()

    def get_food_group_for_item(self, item_name: str) -> str:
        """
        Determines food group for a given item name, using LLM if available.
        """
        if self.llm_gateway:
            category = self.llm_gateway.get_food_group_for_item(item_name)
            if category:
                return category
            _LOGGER.warning(f"LLM classification failed for '{item_name}', falling back to keyword search.")

        # Fallback to keyword-based search
        item_lower = item_name.lower()
        
        vegetables = [
            "verdure", "insalata", "pomodoro", "cetriolo", "carota", "peperone", 
            "cipolla", "aglio", "melanzana", "zucchina", "spinaci", "broccoli", 
            "cavolfiore", "finocchi", "sedano", "asparagi", "funghi", "radicchio",
            "barbabietola", "zucca"
        ]

        if "pasta" in item_lower or "riso" in item_lower or "pane" in item_lower or "patate" in item_lower:
            return "carboidrati"
        
        if "pollo" in item_lower or "tacchino" in item_lower or "manzo" in item_lower or "maiale" in item_lower or \
           "pesce" in item_lower or "salmone" in item_lower or "tonno" in item_lower or "uova" in item_lower or \
           "lenticchie" in item_lower or "ceci" in item_lower or "fagioli" in item_lower or "legumi" in item_lower or "tofu" in item_lower:
            return "proteine"
            
        if "olio" in item_lower or "burro" in item_lower or "frutta secca" in item_lower or "noci" in item_lower or "mandorle" in item_lower:
            return "grassi"
            
        if "mela" in item_lower or "banana" in item_lower or "arancia" in item_lower or "fragole" in item_lower or "frutta" in item_lower:
            return "frutta"
            
        if any(veg in item_lower for veg in vegetables):
            return "verdure"
            
        return "altro" # Default fallback

    def _load_parsing_templates(self) -> Dict[str, Any]:
        """
        Placeholder: Load PDF parsing templates.
        These templates would define regex patterns, table structures, and keyword lists
        to guide the extraction process for a specific nutritionist's PDF layout.
        """
        # In a real scenario, this would load from JSON/YAML files in 'pdf/templates'
        return {
            "default": {
                "section_starters": {
                    "grammature": r"GRAMMATURE\s*(.*?)(?=(?:METODI|GIORNO|FREQUENZE|COLAZIONE|SPUNTINO|PRANZO|MERENDA|CENA|DURANTE LA GIORNATA|$))",
                    "colazione": r"COLAZIONE\s*(.*?)(?=(?:SPUNTINO|PRANZO|MERENDA|CENA|DURANTE LA GIORNATA|$))",
                    "pranzo": r"PRANZO\s*(.*?)(?=(?:SPUNTINO|COLAZIONE|MERENDA|CENA|DURANTE LA GIORNATA|$))",
                    "cena": r"CENA\s*(.*?)(?=(?:SPUNTINO|COLAZIONE|PRANZO|MERENDA|DURANTE LA GIORNATA|$))",
                    "rotation_rules": r"FREQUENZE SETTIMANALI\s*(.*?)(?=(?:METODI|GIORNO|COLAZIONE|SPUNTINO|PRANZO|MERENDA|CENA|DURANTE LA GIORNATA|$))"
                },
                # Regex to capture item name and the FINAL quantity and unit, ignoring intermediate descriptions.
                "item_regex": r"^\s*(.*?)\s.*?\s*(\d+[,.]?\d*)\s*(" + UNITS_REGEX_PATTERN + r")\s*$",
                "unit_conversions_override_regex": r"([\w\sàèéìòùÀÈÉÌÒÙ]+)\s*\((\d+)\s*(g|ml)\)",
                # Regex to capture weekly frequencies like "- uova: 2-4 volte" or "- carne rossa: 1 volta"
                "rotation_regex": r"-\s*([\w\s]+):\s*(\d+)(?:-(\d+))?\s*volt[ae]"
            }
        }

    def _extract_text_content(self, pdf_path: str) -> str:
        """Extracts all text content from the PDF."""
        return extract_text(pdf_path)

    def _extract_tables_content(self, pdf_path: str) -> List[pd.DataFrame]:
        """Extracts tables from the PDF using tabula-py."""
        try:
            tables = tabula.read_pdf(pdf_path, pages="all", multiple_tables=True, pandas_options={'header': None})
            return [df for df in tables if not df.empty]
        except Exception as e:
            _LOGGER.warning(f"Could not extract tables from PDF: {e}")
            return []

    def parse_pdf(self, pdf_path: str, profile_id: str, template_name: str = "default") -> schemas.StructuredMealPlan:
        """
        Parses a PDF meal plan for a specific profile and returns a StructuredMealPlan.
        """
        _LOGGER.debug("--- Starting PDF Parsing ---")
        text_content = self._extract_text_content(pdf_path)
        _LOGGER.debug(f"Extracted Text Content:\n---\n{text_content}\n---")

        # tables_content = self._extract_tables_content(pdf_path) # Not used in MVP parsing logic
        
        template = self.parsing_templates.get(template_name)
        if not template:
            raise PDFParsingError(f"Parsing template '{template_name}' not found.")

        # --- Extract Rotation Rules ---
        rotation_rules: List[schemas.RotationRuleCreate] = []
        rotation_section_match = re.search(template["section_starters"]["rotation_rules"], text_content, re.IGNORECASE | re.DOTALL)
        if rotation_section_match:
            rules_text = rotation_section_match.group(1)
            _LOGGER.debug(f"Found Rotation Rules Section:\n---\n{rules_text}\n---")
            for line in rules_text.split('\n'):
                rule_match = re.search(template["rotation_regex"], line, re.IGNORECASE)
                if rule_match:
                    food_item = rule_match.group(1).strip()
                    val1_str = rule_match.group(2)
                    val2_str = rule_match.group(3)

                    min_val, max_val = None, None
                    if val2_str: # Range like "2-4"
                        min_val = int(val1_str)
                        max_val = int(val2_str)
                    elif val1_str: # Single value like "1"
                        max_val = int(val1_str)
                    
                    if min_val is not None or max_val is not None:
                        rotation_rules.append(schemas.RotationRuleCreate(
                            food_group_or_item=food_item,
                            max_per_week=max_val,
                            min_per_week=min_val,
                            is_hard_constraint=True 
                        ))
                        _LOGGER.debug(f"Parsed Rule: {food_item}, Min: {min_val}, Max: {max_val}")
        else:
            _LOGGER.debug("Rotation Rules section not found.")
        
        # --- Extract Daily Plans (simplified) ---
        daily_plans: List[schemas.DailyPlannedMeals] = []
        
        plan_date_str = date.today().isoformat() # Placeholder date, ideally derived from PDF or user input

        # Always create PlannedMeal objects, even if items list is empty
        pranzo_items = self._parse_meal_section(text_content, template["section_starters"]["pranzo"], template["item_regex"], "pranzo")
        pranzo_meal = schemas.PlannedMeal(meal_type="pranzo", items=pranzo_items)

        cena_items = self._parse_meal_section(text_content, template["section_starters"]["cena"], template["item_regex"], "cena")
        cena_meal = schemas.PlannedMeal(meal_type="cena", items=cena_items)

        meals_for_day = [pranzo_meal, cena_meal] # Always include both for structure
        
        daily_plans.append(schemas.DailyPlannedMeals(date=plan_date_str, meals=meals_for_day))
        _LOGGER.debug(f"Parsed {len(pranzo_items)} items for Pranzo.")
        _LOGGER.debug(f"Parsed {len(cena_items)} items for Cena.")

        # --- Construct StructuredMealPlan ---
        return schemas.StructuredMealPlan(
            id=str(uuid.uuid4()), # Generate a plan ID
            profile_id=profile_id,
            start_date=plan_date_str, # This needs to be correctly parsed from PDF
            rotation_rules=rotation_rules,
            allowed_cooking_methods=["vapore", "tegame", "forno"], # Placeholder, should be parsed from PDF
            daily_plans=daily_plans
        )

    def _parse_meal_section(self, text: str, section_regex: str, item_regex: str, meal_type: str) -> List[schemas.PlannedItem]:
        """
        Parses a specific meal section (e.g., "PRANZO") from the extracted text
        and returns a list of PlannedItems.
        It now handles alternatives and free vegetable notes for 'cena'.
        """
        _LOGGER.debug(f"--- Parsing Meal Section: {meal_type.upper()} ---")
        items: List[schemas.PlannedItem] = []
        notes_lines = []
        last_item = None
        in_alternatives_block = False

        section_match = re.search(section_regex, text, re.IGNORECASE | re.DOTALL)
        if not section_match:
            _LOGGER.debug(f"Meal section '{meal_type.upper()}' not found using regex: {section_regex}")
            return items

        section_content = section_match.group(1).strip()
        _LOGGER.debug(f"Found Meal Section Content:\n---\n{section_content}\n---")
        all_item_names = set()

        for line in section_content.split('\n'):
            line = line.strip()
            _LOGGER.debug(f"Processing line: '{line}'")
            if not line:
                in_alternatives_block = False # Reset on empty line
                continue

            # Check for alternative marker
            if re.match(r'^(alternative|alternativa):$', line, re.IGNORECASE):
                _LOGGER.debug("Found 'alternative' marker.")
                in_alternatives_block = True
                continue

            item_match = re.search(item_regex, line, re.IGNORECASE)
            if item_match:
                item_name = item_match.group(1).strip()
                
                # Skip entries that are likely not real food items
                if item_name.isdigit() or len(item_name) < 2:
                    _LOGGER.debug(f"Skipping likely malformed item name: '{item_name}'")
                    continue

                quantity_str = item_match.group(2).replace(' e 1/2', '.5').replace(',', '.')
                quantity = float(quantity_str)
                unit = item_match.group(3).strip()

                grams_equiv = self.unit_converter.convert_to_grams(quantity, unit)
                ml_equiv = self.unit_converter.convert_to_ml(quantity, unit)
                _LOGGER.debug(f"Parsing item '{item_name}' (unit: {unit}): grams_equiv={grams_equiv}, ml_equiv={ml_equiv}")
                
                is_estimated = False
                if not (grams_equiv or ml_equiv) and unit.lower() not in ["g", "ml"]:
                    is_estimated = True 

                parsed_item = schemas.PlannedItem(
                    item_name=item_name,
                    food_group=self.get_food_group_for_item(item_name),
                    quantity=quantity,
                    unit=unit,
                    is_estimated_unit=is_estimated,
                    alternatives=[] 
                )

                if in_alternatives_block and last_item:
                    last_item.alternatives.append(parsed_item)
                    _LOGGER.debug(f"Added '{item_name}' as alternative to '{last_item.item_name}'.")
                else:
                    items.append(parsed_item)
                    all_item_names.add(item_name.lower())
                    last_item = parsed_item
                    in_alternatives_block = False # An item line resets the alternative block unless it's inside one
            else:
                notes_lines.append(line)
                _LOGGER.debug(f"Could not parse item line: '{line}' with regex '{item_regex}' in meal section.")

        # Handle "idee piatti" for CENA
        if meal_type.lower() == 'cena' and notes_lines:
            note_text = " ".join(notes_lines)
            # Simple word extraction, could be improved with NLP
            words = re.split(r'\s|[,.;()]', note_text)
            for word in words:
                word = word.strip().lower()
                if not word or len(word) < 3: # Also skip very short words
                    continue
                
                # Check if the word is a vegetable and not already a planned item
                food_group = self.get_food_group_for_item(word)
                if food_group == 'verdure' and word not in all_item_names:
                    _LOGGER.debug(f"Found free vegetable '{word}' in cena notes.")
                    items.append(schemas.PlannedItem(
                        item_name=word,
                        food_group='verdure',
                        quantity=0, # Free item
                        unit='g', # Default unit
                        is_estimated_unit=True,
                        alternatives=[],
                        shopping_list_quantity=200.0 # Default estimated quantity for shopping list
                    ))
                    all_item_names.add(word) # Avoid adding duplicates

        return items
