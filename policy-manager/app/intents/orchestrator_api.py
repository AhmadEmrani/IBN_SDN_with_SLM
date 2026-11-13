"""Intent HTTP routes. Application logic lives in orchestrator_service."""
from __future__ import annotations
import httpx
from fastapi import APIRouter, FastAPI
from app.intents.requests import RouteRequest, TranslateRequest
from app.intents.orchestrator_service import (
    route_capability, translate, _check_capability, _parse_model_json,
    _validate_result, _compact_phi_messages,
)
router = APIRouter()

@router.get("/health")
def health():
    # Keep the legacy response for existing clients/tests during Stage 5F.
    return {"status": "ok", "mode": "read_only", "stage": "5d4"}

@router.post("/v1/intents/route")
async def route_api(request: RouteRequest):
    async with httpx.AsyncClient() as client:
        return await route_capability(request.text, client)

@router.post("/v1/intents/translate")
async def translate_api(request: TranslateRequest):
    async with httpx.AsyncClient() as client:
        return await translate(request, client)

# Legacy import path remains available for tools that imported this module's app.
app = FastAPI(title="LLNet Intent API", version="0.5f")
app.include_router(router)
