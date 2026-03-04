import logging
import os
import json
from typing import Optional, Dict, Any, List

# Placeholder for actual LLM client imports (e.g., from openai, from ollama)
# from openai import OpenAI
# from ollama import Client as OllamaClient

_LOGGER = logging.getLogger(__name__)

class LLMGateway:
    """
    Manages interactions with Large Language Models (LLMs) for tasks like
    generating structured data from free-text or enhancing existing data.
    Supports configurable LLM providers (e.g., OpenAI, Ollama).
    """

    def __init__(self,
                 provider: str = "ollama",
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 model: str = "llama3",
                 temperature: float = 0.7,
                 timeout: int = 180):
        self.provider = provider.lower()
        self.api_key = api_key if api_key else os.getenv(f"{provider.upper()}_API_KEY")
        self.base_url = base_url if base_url else os.getenv(f"{provider.upper()}_BASE_URL")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self._client = None
        self.custom_rules: str = ""   # injected into planner prompt if set
        self._initialize_client()

    def _initialize_client(self):
        """Initializes the LLM client based on the configured provider."""
        if self.provider == "openai":
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
                _LOGGER.info("Initialized OpenAI client.")
            except ImportError:
                _LOGGER.error("OpenAI library not found. Please install it: pip install openai")
                self._client = None
        elif self.provider == "ollama":
            try:
                from ollama import Client as OllamaClient
                self._client = OllamaClient(host=self.base_url, timeout=self.timeout)
                _LOGGER.info(f"Initialized Ollama client at {self.base_url}.")
            except ImportError:
                _LOGGER.error("Ollama library not found. Please install it: pip install ollama")
                self._client = None
            except Exception as e:
                _LOGGER.error(f"Failed to initialize Ollama client: {e}")
                self._client = None
        else:
            _LOGGER.warning(f"Unsupported LLM provider: {self.provider}. No client initialized.")
        
        if self._client is None:
            _LOGGER.error("LLM client could not be initialized. LLM-powered features will be unavailable.")

    def _get_system_message(self, task_description: str) -> str:
        """Constructs a system message for the LLM based on the task."""
        # This will be refined with more specific instructions for each task
        return f"You are an expert culinary assistant. {task_description}"

    def generate_structured_recipe_from_text(self, free_text_recipe: str, profile_ids: List[str]) -> Optional[Dict[str, Any]]:
        """
        Generates a structured recipe (matching schemas.RecipeCreate) from free-form text.
        """
        if not self._client:
            _LOGGER.error("LLM client not initialized. Cannot generate structured recipe.")
            return None

        task_description = (
            "Given a free-text recipe, extract the following structured JSON data "
            "conforming to the `schemas.RecipeCreate` Pydantic model (ensure all fields are present "
            "and correctly typed, especially `content` and its nested `quantities` for each profile). "
            "For `content`, generate appropriate `RecipeIngredient`s. If `is_composed_dish` is true, "
            "then `content` should be a `ComposedDishContent` object with a list of components. "
            "If `is_composed_dish` is false, `content` should be a list of `RecipeIngredient`s. "
            f"The profile IDs for which quantities should be generated are: {', '.join(profile_ids)}. "
            "When determining quantities, follow these rules: "
            "1. **Vegetables without explicit quantity**: If a vegetable is mentioned without a specific weight or amount (e.g., 'con un contorno di spinaci', 'insalata a piacere'), it's a 'free item'. For these, set the `food_group` to 'verdure' and inside the `quantities` object for each profile, set `qty` to 0 and `unit` to 'g'. "
            "2. **All other ingredients**: Estimate a reasonable quantity based on the recipe context for each profile ID. "
            "For units, use standard Italian units like 'g', 'ml', 'cucchiaio', 'cucchiaino', 'tazza', 'bicchiere', 'porzione', 'pz'. "
            "For `food_group`, categorize ingredients into 'carboidrati', 'proteine', 'grassi', 'verdure', 'frutta', 'latticini', 'altro'. "
            "Set `llm_generated_metadata.source_prompt` to the original free-text. "
            "Respond ONLY with the JSON object, nothing else. Do NOT include any markdown formatting like ```json."
        )
        prompt_template = f"{self._get_system_message(task_description)}\n\nFree-text recipe: {free_text_recipe}"

        messages = [
            {"role": "system", "content": self._get_system_message(task_description)},
            {"role": "user", "content": free_text_recipe}
        ]

        try:
            if self.provider == "openai":
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    response_format={"type": "json_object"}
                )
                json_output = response.choices[0].message.content
            elif self.provider == "ollama":
                # Ollama client API for chat is slightly different, no direct response_format
                response = self._client.chat(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature
                )
                json_output = response['message']['content']
            else:
                _LOGGER.error(f"Unsupported LLM provider for structured generation: {self.provider}")
                return None

            try:
                structured_data = json.loads(json_output)
                # Basic validation against schema (more robust validation might be needed)
                # schemas.RecipeCreate(**structured_data) 
                _LOGGER.info("Successfully generated structured recipe from LLM.")
                return structured_data
            except json.JSONDecodeError as e:
                _LOGGER.error(f"LLM response was not valid JSON: {e}. Response: {json_output}")
                return None
            except Exception as e:
                _LOGGER.error(f"Failed to validate LLM generated data against schema: {e}. Data: {json_output}")
                return None

        except Exception as e:
            _LOGGER.error(f"Error during LLM call for structured recipe generation: {e}")
            return None

    def get_llm_description_for_recipe(self, recipe_name: str, ingredients: List[str]) -> Optional[str]:
        """
        Generates a creative description for a recipe based on its name and key ingredients.
        """
        if not self._client:
            _LOGGER.error("LLM client not initialized. Cannot generate recipe description.")
            return None

        task_description = (
            "You are a creative culinary writer. Write a short, engaging description "
            "for the given recipe, highlighting its key ingredients. "
            "Respond ONLY with the description text, nothing else."
        )
        user_prompt = f"Recipe name: {recipe_name}\nKey ingredients: {', '.join(ingredients)}"
        messages = [
            {"role": "system", "content": self._get_system_message(task_description)},
            {"role": "user", "content": user_prompt}
        ]

        try:
            if self.provider == "openai":
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature
                )
                return response.choices[0].message.content
            elif self.provider == "ollama":
                response = self._client.chat(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature
                )
                return response['message']['content']
            else:
                _LOGGER.error(f"Unsupported LLM provider for description generation: {self.provider}")
                return None
        except Exception as e:
            _LOGGER.error(f"Error during LLM call for recipe description generation: {e}")
            return None

    def get_food_group_for_item(self, item_name: str) -> Optional[str]:
        """
        Classifies a given food item into a predefined food group using the LLM.
        """
        if not self._client:
            _LOGGER.error("LLM client not initialized. Cannot classify food group.")
            return None

        food_groups = ['carboidrati', 'proteine', 'grassi', 'verdure', 'frutta', 'latticini', 'altro']
        task_description = (
            "You are an expert food classifier. Given the name of a food item, classify it into one of the "
            f"following categories: {', '.join(food_groups)}. "
            "Respond ONLY with the category name, nothing else."
        )
        messages = [
            {"role": "system", "content": self._get_system_message(task_description)},
            {"role": "user", "content": item_name}
        ]

        try:
            if self.provider == "openai":
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1 # Low temperature for classification
                )
                category = response.choices[0].message.content.strip().lower()
            elif self.provider == "ollama":
                response = self._client.chat(
                    model=self.model,
                    messages=messages,
                    temperature=0.1
                )
                category = response['message']['content'].strip().lower()
            else:
                _LOGGER.error(f"Unsupported LLM provider for food group classification: {self.provider}")
                return None
            
            # Basic validation to ensure response is one of the expected groups
            if category in food_groups:
                _LOGGER.debug(f"LLM classified '{item_name}' as '{category}'.")
                return category
            else:
                _LOGGER.warning(f"LLM returned an unexpected category '{category}' for item '{item_name}'.")
                return None

        except Exception as e:
            _LOGGER.error(f"Error during LLM call for food group classification: {e}")
            return None

    def generate_recipe_from_constraints(self, constraints: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Generates a new, creative, and complete structured recipe based on a set of constraints.
        """
        if not self._client:
            _LOGGER.error("LLM client not initialized. Cannot generate recipe from constraints.")
            return None

        # Build a detailed prompt from the constraints dictionary
        prompt_lines = ["Please generate a single, creative, and delicious recipe in Italian that adheres to the following constraints."]
        
        profiles_info = constraints.get("profiles", [])
        profile_ids = [p["id"] for p in profiles_info]
        for p_info in profiles_info:
            prompt_lines.append(f"\nFor user '{p_info['id']}':")
            if p_info.get("allergies"):
                prompt_lines.append(f"- Must NOT contain: {', '.join(p_info['allergies'])}")
            if p_info.get("excluded_foods"):
                prompt_lines.append(f"- User dislikes and excludes: {', '.join(p_info['excluded_foods'])}")
        
        meal_info = constraints.get("meal_plan", {})
        prompt_lines.append(f"\nThe recipe should be for '{meal_info.get('meal_type', 'a meal')}' and must strictly match this composition per user:")
        for p_info in profiles_info:
            profile_id = p_info["id"]
            
            # Find the meal plan items relevant for this profile
            # This logic assumes the parent passes a simplified list of targets
            target_foods = meal_info.get(profile_id, [])
            
            food_targets = [f"{item['quantity']}{item['unit']} of {item['food_group']}" for item in target_foods]
            if food_targets:
                prompt_lines.append(f"- For user '{profile_id}', target: {', '.join(food_targets)}.")
            else:
                prompt_lines.append(f"- For user '{profile_id}', no specific targets, be creative but balanced.")

        if constraints.get("recently_used_ingredients"):
            prompt_lines.append(f"\nTo ensure variety, avoid using these recently used ingredients if possible: {', '.join(constraints['recently_used_ingredients'])}")
        if constraints.get("pantry_items_expiring_soon"):
            prompt_lines.append(f"Strongly prefer to incorporate these ingredients from the pantry, as they are expiring soon: {', '.join(constraints['pantry_items_expiring_soon'])}")
        
        prompt_lines.append("\nPlease provide a creative name, a brief description, simple steps, total time, and difficulty.")
        user_prompt = " ".join(prompt_lines)

        profile_ids = [p["id"] for p in profiles_info]

        json_example_recipe = {
            "name": "Esempio Ricetta",
            "description": "Una ricetta di esempio per il test.",
            "is_composed_dish": False,
            "content": [
                {
                    "name": "Ingrediente 1",
                    "food_group": "carboidrati",
                    "quantities": {
                        profile_ids[0]: {"qty": 100, "unit": "g", "grams_equiv": 100},
                        profile_ids[1] if len(profile_ids) > 1 else "dummy_profile_B": {"qty": 120, "unit": "g", "grams_equiv": 120}
                    }
                },
                {
                    "name": "Ingrediente 2",
                    "food_group": "verdure",
                    "quantities": {
                        profile_ids[0]: {"qty": 50, "unit": "g", "grams_equiv": 50},
                        profile_ids[1] if len(profile_ids) > 1 else "dummy_profile_B": {"qty": 60, "unit": "g", "grams_equiv": 60}
                    }
                }
            ],
            "steps": ["Step 1", "Step 2"],
            "total_time_minutes": 30,
            "difficulty": "facile",
            "tags": {"mood": ["test"], "cleanup": ["facile"]}
        }

        task_description = (
            "You are a master chef who creates recipes based on strict dietary and pantry constraints. "
            "Generate a complete recipe in structured JSON format that matches the `schemas.RecipeCreate` model. "
            "The JSON must be perfect. "
            "Here is an example of the desired JSON structure you MUST follow strictly:\n"
            f"```json\n{json.dumps(json_example_recipe, indent=2)}\n```\n"
            "Specifically, `total_time_minutes` MUST be an integer representing the total preparation and cooking time in minutes. "
            "`difficulty` MUST be a lowercase string, chosen from ONLY these exact values: 'facile', 'media', 'difficile', 'sconosciuto'. "
            "`steps` MUST be a JSON array of strings, where each string is a single step of the recipe. "
            "For the `content` field, create a list of `RecipeIngredient` objects. "
            "For each ingredient, specify the `name`, `food_group`, and `quantities`. "
            "The `quantities` object must have a key for each profile ID "
            f"({', '.join(profile_ids)}) with the exact `qty` and `unit` needed to meet their targets. Also calculate the `grams_equiv` for each. "
            "Respond ONLY with the JSON object, nothing else. Do NOT include markdown outside of the JSON block."
        )

        messages = [
            {"role": "system", "content": task_description},
            {"role": "user", "content": user_prompt}
        ]

        _LOGGER.info(f"Generating new recipe with prompt: {user_prompt}")

        try:
            if self.provider == "openai":
                response = self._client.chat.completions.create(model=self.model, messages=messages, temperature=self.temperature, response_format={"type": "json_object"})
                json_output = response.choices[0].message.content
            elif self.provider == "ollama":
                response = self._client.chat(model=self.model, messages=messages, temperature=self.temperature)
                json_output = response['message']['content']
            else:
                _LOGGER.error(f"Unsupported LLM provider for constrained generation: {self.provider}")
                return None

            try:
                structured_data = json.loads(json_output)
                _LOGGER.info("Successfully generated recipe from constraints.")
                return structured_data
            except json.JSONDecodeError as e:
                _LOGGER.error(f"LLM response for constrained recipe was not valid JSON: {e}. Response: {json_output}")
                return None
            except Exception as e:
                _LOGGER.error(f"Failed to validate LLM constrained recipe against schema: {e}. Data: {json_output}")
                return None

        except Exception as e:
            _LOGGER.error(f"Error during LLM call for constrained recipe generation: {e}")
            return None

    def generate_structured_meal(self, prompt: str) -> Optional[str]:
        """
        Chiama il LLM con un prompt nutrizionale e restituisce la stringa raw della risposta.
        Tutta la logica di provider è incapsulata qui.
        """
        if not self._client:
            _LOGGER.error("LLM client non inizializzato. Impossibile generare il pasto.")
            return None

        messages = [
            {
                "role": "system",
                "content": "Sei un assistente nutrizionale esperto. Rispondi SOLO con JSON valido, senza testo aggiuntivo.",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            if self.provider == "openai":
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.4,
                    response_format={"type": "json_object"},
                )
                return response.choices[0].message.content
            elif self.provider == "ollama":
                response = self._client.chat(model=self.model, messages=messages)
                return response["message"]["content"]
            else:
                _LOGGER.error(f"Provider LLM non supportato: {self.provider}")
                return None
        except Exception as e:
            _LOGGER.error(f"Errore in generate_structured_meal: {e}")
            return None

