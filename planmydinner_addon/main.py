from contextlib import asynccontextmanager
from fastapi import FastAPI
from database import create_db_and_tables # Relative import

# Explicitly import routers with relative paths
from api import profiles as profiles_router
from api import pantry as pantry_router
from api import consumption as consumption_router
from api import recipes as recipes_router
from api import _import as import_router
from api import planner as planner_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Actions to perform on application startup and shutdown.
    """
    print("Starting up...")
    create_db_and_tables()
    yield
    print("Shutting down...")

app = FastAPI(title="Plan My Dinner API", lifespan=lifespan)

app.include_router(profiles_router.router)
app.include_router(pantry_router.router)
app.include_router(consumption_router.router)
app.include_router(recipes_router.router)
app.include_router(import_router.router)
app.include_router(planner_router.router)

@app.get("/")
async def root():
    """Root endpoint to check if the API is running."""
    return {"message": "Plan My Dinner Add-on is running!"}