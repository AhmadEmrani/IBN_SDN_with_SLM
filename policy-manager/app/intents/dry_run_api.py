"""Stage 5D.3: AI -> PolicyInput -> OpenFlow specs, without any actuation.

Reuses the live 5D.2 translation function and the *existing* 5B adapter and
backend compiler. It never imports submission_service, database, Ryu or Airflow.
"""
from __future__ import annotations

from uuid import uuid4

import httpx
from fastapi import HTTPException
from pydantic import Field

from app.intents.adapter import IntentContractError, adapt_model_result
from app.intents.context_provider import ContextUnavailable, get_trusted_context
from app.intents.orchestrator_api import TranslateRequest, app, translate
from app.schemas.policy import PolicyInput
from app.services.compiler import compile_policy


class DryRunRequest(TranslateRequest):
    network_id: str = Field(min_length=1, max_length=100)


async def dry_run(request: DryRunRequest, client: httpx.AsyncClient) -> dict:
    # Reuse 5D.2 end-to-end inference and strict model-result validation.
    translation = await translate(
        TranslateRequest(text=request.text, capability=request.capability, top_k=request.top_k),
        client,
    )
    status = translation["status"]
    basic = {
        "status": status,
        "capability": translation["capability"],
        "model_result": translation["model_result"],
        "retrieved_example_ids": translation["retrieved_example_ids"],
        "model_validated": translation["validated"],
        "policy_validated": False,
        "policy": None,
        "compiled_flows": [],
        "context_source": None,
        "deployment": "not_requested",
    }
    # A non-ready inference cannot yield a policy, and should not need inventory.
    if status != "ready":
        return basic

    try:
        context, context_source, allow_fixture = get_trusted_context(request.network_id)
    except ContextUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": str(exc)}) from exc

    try:
        # Server-owned ID: never accept an LLM-generated or client-supplied intent ID.
        intent_id = "dryrun-" + uuid4().hex[:16]
        converted = adapt_model_result(
            translation["model_result"], context=context, network_id=request.network_id,
            intent_id=intent_id, allow_fixture=allow_fixture,
        )
        if converted["status"] != "ready" or converted["policy"] is None:
            raise IntentContractError("unexpected_converter_status")
        policy = PolicyInput.model_validate(converted["policy"])
        # A preview cookie is never registered or used for deployment.
        flows = compile_policy(policy, cookie=1)
    except (IntentContractError, ValueError) as exc:
        # Never return an unvalidated/generated policy on failure.
        raise HTTPException(status_code=422, detail={"code": "policy_dry_run_rejected"}) from exc

    return {
        **basic,
        "policy_validated": True,
        "policy": policy.model_dump(mode="json"),
        "compiled_flows": flows,
        "context_source": context_source,
    }


@app.post("/v1/intents/dry-run")
async def dry_run_endpoint(request: DryRunRequest):
    async with httpx.AsyncClient() as client:
        return await dry_run(request, client)
