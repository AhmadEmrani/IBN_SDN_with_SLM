"""HTTP boundary for read-only policy previews."""
from __future__ import annotations
import httpx
from fastapi import APIRouter
from app.intents.requests import DryRunRequest, TranslateRequest
from app.intents.orchestrator_api import translate
from app.intents.context_provider import get_trusted_context
from app.intents.dry_run_service import execute_dry_run

router = APIRouter()

async def dry_run(request: DryRunRequest, client: httpx.AsyncClient) -> dict:
    return await execute_dry_run(request, client,
                                 translate_fn=translate,
                                 context_fn=get_trusted_context)

@router.post("/v1/intents/dry-run")
async def dry_run_endpoint(request: DryRunRequest):
    async with httpx.AsyncClient() as client:
        return await dry_run(request, client)
