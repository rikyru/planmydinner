import logging
import os
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
                 timeout: int = 30):
        self.provider = provider.lower()
        self.api_key = api_key if api_key else os.getenv(f"{provider.upper()}_API_KEY")
        self.base_url = base_url if base_url else os.getenv(f"{provider.upper()}_BASE_URL")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self._client = None
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
            "Estimate reasonable quantities for the provided profile IDs. "
            f"The profile IDs are: {', '.join(profile_ids)}. "
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

