import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .database import create_db_and_tables # Relative import
from .llm_gateway import LLMGateway # Import LLMGateway

# Explicitly import routers with relative paths
from .api import profiles as profiles_router
from .api import pantry as pantry_router
from .api import consumption as consumption_router
from .api import recipes as recipes_router
from .api import _import as import_router
from .api import planner as planner_router
from .api import shopping_list as shopping_list_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Actions to perform on application startup and shutdown.
    """
    print("Starting up...")
    create_db_and_tables()

    # Initialize LLMGateway
    llm_provider = os.getenv("LLM_PROVIDER", "ollama")
    llm_api_key = os.getenv("LLM_API_KEY")
    llm_base_url = os.getenv("LLM_BASE_URL")
    llm_model = os.getenv("LLM_MODEL", "llama3")
    
    app.state.llm_gateway = LLMGateway(
        provider=llm_provider,
        api_key=llm_api_key,
        base_url=llm_base_url,
        model=llm_model
    )
    
    yield
    print("Shutting down...")

app = FastAPI(title="Plan My Dinner API", lifespan=lifespan)

# Construct the absolute path to the frontend directory
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
app.mount("/ui", StaticFiles(directory=frontend_dir, html=True), name="ui")


app.include_router(profiles_router.router)
app.include_router(pantry_router.router)
app.include_router(consumption_router.router)
app.include_router(recipes_router.router)
app.include_router(import_router.router)
app.include_router(planner_router.router)
app.include_router(shopping_list_router.router)

@app.get("/")
async def root():
    """Root endpoint to check if the API is running."""
    return {"message": "Plan My Dinner Add-on is running!"}