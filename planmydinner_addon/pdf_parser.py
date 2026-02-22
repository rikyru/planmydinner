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

    def get_food_group_for_item(self, item_name: str) -> str:
        """
        Placeholder: Determine food group for a given item name.
        In a real implementation, this would use a lookup table, LLM, or more sophisticated logic.
        """
        item_lower = item_name.lower()
        if "pasta" in item_lower or "riso" in item_lower or "pane" in item_lower:
            return "carboidrati"
        # Added 'legumi' to proteins as they are a primary source of protein
        if "pollo" in item_lower or "salmone" in item_lower or "uova" in item_lower or "lenticchie" in item_lower or "legumi" in item_lower:
            return "proteine"
        if "olio" in item_lower or "burro" in item_lower:
            return "grassi"
        if "mela" in item_lower or "banana" in item_lower or "frutta" in item_lower: # Added "frutta"
            return "frutta"
        if "broccoli" in item_lower or "carote" in item_lower or "verdure" in item_lower:
            return "verdure"
        return "altro" # Default fallback


class PDFParser:
    """
    Parses a PDF meal plan and extracts structured data.
    This version includes placeholders for template loading and more advanced parsing.
    """
    def __init__(self, db: SessionLocal):
        self.unit_converter = UnitConverter(db)
        self.parsing_templates: Dict[str, Any] = self._load_parsing_templates()

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
                # Refined item regex with correct matching for all units
                "item_regex": r"^\s*(.+?)(?=\s*\d+[,.]?\d*\s*(?:" + UNITS_REGEX_PATTERN + r"))\s*(\d+[,.]?\d*)\s*(" + UNITS_REGEX_PATTERN + r")\s*$",
                "unit_conversions_override_regex": r"([\w\sàèéìòùÀÈÉÌÒÙ]+)\s*\((\d+)\s*(g|ml)\)",
                "rotation_regex": r"([\w\sàèéìòùÀÈÉÌÒÙ\s]+):\s*(?:max\s*(\d+)/settimana)?(?:,\s*min\s*(\d+)/settimana)?" # Allow optional max/min
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
        text_content = self._extract_text_content(pdf_path)
        tables_content = self._extract_tables_content(pdf_path) # Not used in MVP parsing logic
        
        template = self.parsing_templates.get(template_name)
        if not template:
            raise PDFParsingError(f"Parsing template '{template_name}' not found.")

        # --- Extract Rotation Rules ---
        rotation_rules: List[schemas.RotationRuleCreate] = []
        rotation_section_match = re.search(template["section_starters"]["rotation_rules"], text_content, re.IGNORECASE | re.DOTALL)
        if rotation_section_match:
            rules_text = rotation_section_match.group(1)
            for line in rules_text.split('\n'):
                rule_match = re.search(template["rotation_regex"], line, re.IGNORECASE)
                if rule_match:
                    food_item = rule_match.group(1).strip()
                    max_val_str = rule_match.group(2)
                    min_val_str = rule_match.group(3)
                    
                    max_val = int(max_val_str) if max_val_str else None
                    min_val = int(min_val_str) if min_val_str else None

                    rotation_rules.append(schemas.RotationRuleCreate(
                        food_group_or_item=food_item,
                        max_per_week=max_val,
                        min_per_week=min_val,
                        is_hard_constraint=True # Default to hard for MVP, can be refined later
                    ))
        
        # --- Extract Daily Plans (simplified) ---
        daily_plans: List[schemas.DailyPlannedMeals] = []
        
        plan_date_str = date.today().isoformat() # Placeholder date, ideally derived from PDF or user input

        # Always create PlannedMeal objects, even if items list is empty
        pranzo_items = self._parse_meal_section(text_content, template["section_starters"]["pranzo"], template["item_regex"])
        pranzo_meal = schemas.PlannedMeal(meal_type="pranzo", items=pranzo_items)

        cena_items = self._parse_meal_section(text_content, template["section_starters"]["cena"], template["item_regex"])
        cena_meal = schemas.PlannedMeal(meal_type="cena", items=cena_items)

        meals_for_day = [pranzo_meal, cena_meal] # Always include both for structure
        
        daily_plans.append(schemas.DailyPlannedMeals(date=plan_date_str, meals=meals_for_day))

        # --- Construct StructuredMealPlan ---
        return schemas.StructuredMealPlan(
            id=str(uuid.uuid4()), # Generate a plan ID
            profile_id=profile_id,
            start_date=plan_date_str, # This needs to be correctly parsed from PDF
            rotation_rules=rotation_rules,
            allowed_cooking_methods=["vapore", "tegame", "forno"], # Placeholder, should be parsed from PDF
            daily_plans=daily_plans
        )

    def _parse_meal_section(self, text: str, section_regex: str, item_regex: str) -> List[schemas.PlannedItem]:
        """
        Parses a specific meal section (e.g., "PRANZO") from the extracted text
        and returns a list of PlannedItems.
        """
        items: List[schemas.PlannedItem] = []
        section_match = re.search(section_regex, text, re.IGNORECASE | re.DOTALL)
        if section_match:
            section_content = section_match.group(1).strip()
            # Process content line by line
            for line in section_content.split('\n'):
                line = line.strip()
                if not line:
                    continue # Skip empty lines

                item_match = re.search(item_regex, line, re.IGNORECASE)
                if item_match:
                    item_name = item_match.group(1).strip()
                    quantity = float(item_match.group(2).replace(',', '.'))
                    unit = item_match.group(3).strip()

                    grams_equiv = self.unit_converter.convert_to_grams(quantity, unit)
                    ml_equiv = self.unit_converter.convert_to_ml(quantity, unit)
                    _LOGGER.debug(f"Parsing item '{item_name}' (unit: {unit}): grams_equiv={grams_equiv}, ml_equiv={ml_equiv}")
                    
                    is_estimated = False
                    if not (grams_equiv or ml_equiv) and unit.lower() not in ["g", "ml"]:
                        is_estimated = True 

                    items.append(schemas.PlannedItem(
                        item_name=item_name,
                        food_group=self.unit_converter.get_food_group_for_item(item_name),
                        quantity=quantity,
                        unit=unit,
                        is_estimated_unit=is_estimated,
                        alternatives=[] 
                    ))
                else:
                    _LOGGER.debug(f"Could not parse item line: '{line}' with regex '{item_regex}' in meal section.")
        return items
