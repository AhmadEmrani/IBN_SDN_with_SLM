"""Single explicit FastAPI assembly for Intent endpoints."""
from fastapi import FastAPI
from app.intents.orchestrator_api import router as intent_routes
from app.intents.dry_run_api import router as preview_routes

app = FastAPI(title="LLNet Intent API", version="0.5f")
app.include_router(intent_routes)
app.include_router(preview_routes)
