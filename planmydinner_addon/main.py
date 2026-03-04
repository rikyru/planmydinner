import os
import mimetypes
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
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
from .api import seed as seed_router
from .api import settings as settings_router

# Fix for Windows MIME types
mimetypes.add_type("application/javascript", ".js")

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
    
    # Build gateway from env vars first
    gw = LLMGateway(
        provider=llm_provider,
        api_key=llm_api_key,
        base_url=llm_base_url,
        model=llm_model
    )

    # Load persisted settings from DB (overrides env vars if present)
    from .database import SessionLocal, AppSettings as _AppSettings
    _db = SessionLocal()
    try:
        _row = _db.query(_AppSettings).filter(_AppSettings.id == 1).first()
        if _row is None:
            # First run: save current env-var config to DB (without API key to avoid .env duplication)
            _row = _AppSettings(
                id=1,
                llm_provider=llm_provider,
                llm_model=llm_model,
                llm_api_key=llm_api_key,
                llm_base_url=llm_base_url,
            )
            _db.add(_row)
            _db.commit()
            _db.refresh(_row)
        else:
            # Subsequent runs: use DB values to (re)init gateway
            gw = LLMGateway(
                provider=_row.llm_provider or llm_provider,
                api_key=_row.llm_api_key or llm_api_key,
                base_url=_row.llm_base_url or llm_base_url,
                model=_row.llm_model or llm_model,
                temperature=_row.llm_temperature or 0.7,
            )
        gw.custom_rules = _row.llm_custom_rules or ""
    finally:
        _db.close()

    app.state.llm_gateway = gw

    yield
    print("Shutting down...")

app = FastAPI(title="Plan My Dinner API", lifespan=lifespan)

# CORS — permette chiamate API da altri client (opzionale in standalone, utile in sviluppo)
_cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(seed_router.router)
app.include_router(settings_router.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/ui")

@app.get("/health")
async def health():
    return {"status": "ok"}