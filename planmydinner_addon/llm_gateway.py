import logging
import os
import json
import hashlib
from typing import Optional, Dict, Any, List

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
                 timeout: int = 180,
                 vision_model: Optional[str] = None):
        self.provider = provider.lower()
        self.api_key = api_key if api_key else os.getenv(f"{provider.upper()}_API_KEY")
        self.base_url = base_url if base_url else os.getenv(f"{provider.upper()}_BASE_URL")
        self.model = model
        self.vision_model = vision_model  # modello dedicato per analisi foto (fallback: model)
        self.temperature = temperature
        self.timeout = timeout
        self._client = None
        self.custom_rules: str = ""   # injected into planner prompt if set
        # --- Cache ---
        self._cache: Dict[str, Any] = {}
        _data_dir = os.getenv("DATA_DIR", ".")
        self._cache_path = os.path.join(_data_dir, "llm_cache.json")
        self._load_cache()
        self._initialize_client()

    def _load_cache(self):
        try:
            if os.path.exists(self._cache_path):
                with open(self._cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                _LOGGER.info(f"LLM cache: {len(self._cache)} voci caricate da disco.")
        except Exception as e:
            _LOGGER.warning(f"Impossibile caricare la LLM cache: {e}")
            self._cache = {}

    def _save_cache(self):
        try:
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False)
        except Exception as e:
            _LOGGER.warning(f"Impossibile salvare la LLM cache: {e}")

    def _cache_key(self, *parts: str) -> str:
        payload = "|".join(str(p) for p in parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def clear_cache(self):
        self._cache = {}
        self._save_cache()
        _LOGGER.info("LLM cache svuotata.")

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
        Result cached permanently (il gruppo alimentare di un ingrediente non cambia).
        """
        cache_key = f"food_group:{item_name.strip().lower()}"
        if cache_key in self._cache:
            _LOGGER.debug(f"LLM cache hit: food_group '{item_name}'")
            return self._cache[cache_key]

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
                    temperature=0.1
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

            if category in food_groups:
                _LOGGER.debug(f"LLM classified '{item_name}' as '{category}'.")
                self._cache[cache_key] = category
                self._save_cache()
                return category
            else:
                _LOGGER.warning(f"LLM returned an unexpected category '{category}' for item '{item_name}'.")
                return None

        except Exception as e:
            _LOGGER.error(f"Error during LLM call for food group classification: {e}")
            return None

    def estimate_meal_from_photo(self, image_b64: str, mime_type: str = "image/jpeg") -> Optional[Dict[str, Any]]:
        """
        Analizza la foto di un pasto (es. vassoio mensa) e restituisce una stima strutturata:
        {"name": str, "ingredients": [{"name": str, "food_group": str, "grams": float}]}.
        Usa vision_model se impostato, altrimenti il modello principale. Nessuna cache
        (ogni foto è diversa).
        """
        if not self._client:
            _LOGGER.error("LLM client not initialized. Cannot analyze meal photo.")
            return None

        model = self.vision_model or self.model
        food_groups = "carboidrati, carne_bianca, carne_rossa, pesce, legumi, uova, latticini, verdure, grassi, frutta, altro"
        task = (
            "Sei un nutrizionista esperto. Analizza la foto di questo pasto (es. vassoio della mensa). "
            "Identifica le portate e per ciascuna stima gli ingredienti principali con i grammi della porzione visibile. "
            f"Per ogni ingrediente scegli il food_group fra: {food_groups}. "
            'Rispondi SOLO con JSON in questa forma esatta: '
            '{"name": "<nome breve del pasto>", "ingredients": '
            '[{"name": "<ingrediente>", "food_group": "<gruppo>", "grams": <numero>}]}. '
            "Se l'immagine non contiene cibo rispondi: {\"name\": null, \"ingredients\": []}."
        )

        try:
            if self.provider == "openai":
                response = self._client.chat.completions.create(
                    model=model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": task},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{mime_type};base64,{image_b64}",
                                "detail": "high",
                            }},
                        ],
                    }],
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content
            elif self.provider == "ollama":
                # Richiede un modello multimodale (es. llava)
                response = self._client.chat(
                    model=model,
                    messages=[{"role": "user", "content": task, "images": [image_b64]}],
                )
                raw = response["message"]["content"]
            else:
                _LOGGER.error(f"Unsupported LLM provider for photo analysis: {self.provider}")
                return None

            data = json.loads(raw)
            if not data.get("name") or not isinstance(data.get("ingredients"), list):
                _LOGGER.warning(f"Photo analysis returned no usable meal: {str(raw)[:200]}")
                return None
            ingredients = []
            for ing in data["ingredients"]:
                try:
                    ingredients.append({
                        "name": str(ing["name"]),
                        "food_group": str(ing.get("food_group") or "altro"),
                        "grams": max(0.0, float(ing.get("grams") or 0)),
                    })
                except (KeyError, TypeError, ValueError):
                    continue
            if not ingredients:
                return None
            _LOGGER.info(f"Photo analysis ({model}): '{data['name']}' con {len(ingredients)} ingredienti")
            return {"name": str(data["name"]), "ingredients": ingredients}
        except Exception as e:
            _LOGGER.error(f"Error during LLM photo analysis: {e}")
            return None

    def estimate_nutrition(self, item_name: str) -> Optional[Dict[str, float]]:
        """
        Stima i valori nutrizionali per 100 g di un ingrediente:
        {"kcal": .., "protein_g": .., "carbs_g": .., "fat_g": ..}.
        Risultato cachato permanentemente (la composizione di un alimento non cambia).
        """
        if not item_name or not item_name.strip():
            return None
        cache_key = f"nutrition:{item_name.strip().lower()}"
        if cache_key in self._cache:
            _LOGGER.debug(f"LLM cache hit: nutrition '{item_name}'")
            return self._cache[cache_key]

        if not self._client:
            _LOGGER.error("LLM client not initialized. Cannot estimate nutrition.")
            return None

        task_description = (
            "You are a food composition expert. Given the name of a food item (in Italian), "
            "estimate its nutritional values PER 100 GRAMS (raw/dry weight for pasta, rice, "
            "cereals and legumes; raw weight otherwise). "
            'Respond ONLY with a JSON object in this exact form: '
            '{"kcal": <number>, "protein_g": <number>, "carbs_g": <number>, "fat_g": <number>}. '
            "No other text."
        )
        messages = [
            {"role": "system", "content": self._get_system_message(task_description)},
            {"role": "user", "content": item_name},
        ]

        try:
            if self.provider == "openai":
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content
            elif self.provider == "ollama":
                response = self._client.chat(model=self.model, messages=messages)
                raw = response["message"]["content"]
            else:
                _LOGGER.error(f"Unsupported LLM provider for nutrition estimation: {self.provider}")
                return None

            data = json.loads(raw)
            values = {k: float(data[k]) for k in ("kcal", "protein_g", "carbs_g", "fat_g")}
            if not (0 <= values["kcal"] <= 950):
                _LOGGER.warning(f"LLM nutrition estimate out of range for '{item_name}': {values}")
                return None
            self._cache[cache_key] = values
            self._save_cache()
            _LOGGER.info(f"LLM estimated nutrition for '{item_name}': {values}")
            return values
        except Exception as e:
            _LOGGER.error(f"Error during LLM nutrition estimation for '{item_name}': {e}")
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

    def generate_structured_meal(self, prompt: str, use_cache: bool = True) -> Optional[str]:
        """
        Chiama il LLM con un prompt nutrizionale e restituisce la stringa raw della risposta.
        Tutta la logica di provider è incapsulata qui.
        Il risultato viene cachato per prompt identici (use_cache=False per forzare una nuova chiamata).
        """
        cache_key = self._cache_key("structured_meal", prompt)
        if use_cache and cache_key in self._cache:
            _LOGGER.info("LLM cache hit: generate_structured_meal")
            return self._cache[cache_key]

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
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content
            elif self.provider == "ollama":
                response = self._client.chat(model=self.model, messages=messages, options={"temperature": self.temperature})
                raw = response["message"]["content"]
            else:
                _LOGGER.error(f"Provider LLM non supportato: {self.provider}")
                return None

            if raw and use_cache:
                self._cache[cache_key] = raw
                self._save_cache()
            return raw
        except Exception as e:
            _LOGGER.error(f"Errore in generate_structured_meal: {e}")
            return None

    def generate_full_week_plan_json(
        self,
        rules_dict: Dict[str, Any],
        profile_id_A: str,
        profile_id_B: str,
        start_date: str,
        custom_rules: str = "",
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        Chiama il LLM UNA SOLA VOLTA per generare l'intero piano settimanale (7 giorni × 2 pasti).
        Restituisce una stringa JSON con la struttura: {"daily_plans": [...]} conforme a DailyPlannedMeals.
        Usato quando llm_generation_mode = "full_week".
        """
        freq_text = ""
        if rules_dict.get("frequency_targets"):
            lines = []
            for cat, tgt in rules_dict["frequency_targets"].items():
                lines.append(f"  - {cat}: min {tgt.get('min',1)}, max {tgt.get('max',3)} volte/settimana")
            freq_text = "\n".join(lines)

        carb_text = json.dumps(rules_dict.get("carb_target", {"pranzo": 80, "cena": 60}), ensure_ascii=False)
        prot_text = json.dumps(rules_dict.get("protein_target", {"pranzo": 150, "cena": 120}), ensure_ascii=False)

        custom_block = ""
        if custom_rules.strip():
            custom_block = f"\nRegole aggiuntive dell'utente:\n{custom_rules}\n"

        prompt = f"""Sei uno chef italiano e pianificatore nutrizionale esperto. Genera un piano settimanale VARIO e CREATIVO per 7 giorni a partire da {start_date}.

Profilo principale: {profile_id_A}, profilo secondario: {profile_id_B}.

Vincoli nutritivi:
- Grammi carboidrati target: {carb_text}
- Grammi proteine target: {prot_text}

Frequenze proteiche settimanali (distribuite su 14 pasti):
{freq_text if freq_text else "  Nessuna frequenza specifica — alterna pollo/tacchino, pesce, carne rossa, legumi, uova, formaggio."}
{custom_block}
REGOLE DI VARIETÀ E CREATIVITÀ:
- Non ripetere la stessa ricetta nella settimana.
- Non usare sempre gli stessi carboidrati: alterna pasta, riso, orzo, farro, patate, pane, quinoa, gnocchi.
- Non usare sempre gli stessi metodi di cottura: alterna forno, tegame, griglia, vapore, saltato, cartoccio.
- Dai nomi specifici e invitanti alle ricette (es. "Salmone al cartoccio con finocchio e agrumi" non "Pesce al forno").
- Ispirati alla cucina italiana regionale: scaloppine, involtini, risotti, zuppe, arrosti, frittate, polpette, insalate di cereali, pasta fredda, carpacci, tartare.
- Varia le verdure: zucchine, melanzane, broccoli, spinaci, cavolo, fagiolini, peperoni, carote, finocchio, radicchio, carciofi.
- Aggiungi aromi e sapori: rosmarino, timo, basilico, origano, zafferano, curcuma, paprika, limone, capperi, olive.
- food_group per le proteine deve essere specifico: "carne_bianca" (pollo/tacchino), "pesce", "carne_rossa", "legumi", "uova", "latticini".

Rispondi SOLO con un JSON valido, senza testo aggiuntivo, con questa struttura esatta:
{{
  "daily_plans": [
    {{
      "date": "YYYY-MM-DD",
      "meals": [
        {{
          "meal_type": "pranzo",
          "recipe_name": "Petto di pollo alle erbe con orzo e zucchine grigliate",
          "difficulty": "facile",
          "total_time_minutes": 30,
          "ingredients": [
            {{"name": "orzo perlato", "food_group": "carboidrati", "grams_{profile_id_A}": 80, "grams_{profile_id_B}": 70}},
            {{"name": "petto di pollo", "food_group": "carne_bianca", "grams_{profile_id_A}": 150, "grams_{profile_id_B}": 130}},
            {{"name": "zucchine", "food_group": "verdure", "grams_{profile_id_A}": 120, "grams_{profile_id_B}": 120}}
          ]
        }},
        {{
          "meal_type": "cena",
          "recipe_name": "Salmone al cartoccio con finocchio e patate",
          "difficulty": "facile",
          "total_time_minutes": 35,
          "ingredients": [
            {{"name": "patate", "food_group": "carboidrati", "grams_{profile_id_A}": 150, "grams_{profile_id_B}": 130}},
            {{"name": "salmone", "food_group": "pesce", "grams_{profile_id_A}": 130, "grams_{profile_id_B}": 120}},
            {{"name": "finocchio", "food_group": "verdure", "grams_{profile_id_A}": 100, "grams_{profile_id_B}": 100}}
          ]
        }}
      ]
    }}
  ]
}}"""

        cache_key = self._cache_key("full_week_plan", profile_id_A, profile_id_B, start_date,
                                    json.dumps(rules_dict, sort_keys=True), custom_rules)
        if use_cache and cache_key in self._cache:
            _LOGGER.info("LLM cache hit: generate_full_week_plan_json")
            return self._cache[cache_key]

        if not self._client:
            _LOGGER.error("LLM client non inizializzato. Impossibile generare piano settimanale.")
            return None

        messages = [
            {"role": "system", "content": "Sei un assistente nutrizionale esperto. Rispondi SOLO con JSON valido, senza testo aggiuntivo."},
            {"role": "user", "content": prompt},
        ]

        try:
            if self.provider == "openai":
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content
            elif self.provider == "ollama":
                response = self._client.chat(model=self.model, messages=messages)
                raw = response["message"]["content"]
            else:
                _LOGGER.error(f"Provider LLM non supportato: {self.provider}")
                return None

            if raw and use_cache:
                self._cache[cache_key] = raw
                self._save_cache()
            return raw
        except Exception as e:
            _LOGGER.error(f"Errore in generate_full_week_plan_json: {e}")
            return None

    def generate_meal_plan_json(self, prompt: str, use_cache: bool = True) -> Optional[str]:
        """
        Chiama il LLM per il parsing di un piano alimentare da testo (usato da import PDF/testo).
        Cachato per prompt identici: se l'utente reimporta lo stesso PDF non paga di nuovo.
        """
        cache_key = self._cache_key("meal_plan", prompt)
        if use_cache and cache_key in self._cache:
            _LOGGER.info("LLM cache hit: generate_meal_plan_json")
            return self._cache[cache_key]

        if not self._client:
            _LOGGER.error("LLM client non inizializzato.")
            return None

        messages = [
            {"role": "system", "content": "Sei un assistente nutrizionale esperto. Rispondi SOLO con JSON valido, senza testo aggiuntivo."},
            {"role": "user", "content": prompt},
        ]

        try:
            if self.provider == "openai":
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content
            elif self.provider == "ollama":
                response = self._client.chat(model=self.model, messages=messages)
                raw = response["message"]["content"]
            else:
                _LOGGER.error(f"Provider LLM non supportato: {self.provider}")
                return None

            if raw and use_cache:
                self._cache[cache_key] = raw
                self._save_cache()
            return raw
        except Exception as e:
            _LOGGER.error(f"Errore in generate_meal_plan_json: {e}")
            return None

