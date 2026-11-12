"""Read-only intent-to-policy preview, with explicit injected dependencies."""
from __future__ import annotations
from uuid import uuid4
import httpx
from fastapi import HTTPException
from app.intents.requests import DryRunRequest, TranslateRequest
from app.intents.adapter import IntentContractError
from app.intents.capability_preview import build_preview
from app.intents.context_provider import ContextUnavailable

async def execute_dry_run(request: DryRunRequest, client: httpx.AsyncClient, *,
                          translate_fn, context_fn) -> dict:
    # Reuse 5D.2 end-to-end inference and strict model-result validation.
    translation = await translate_fn(
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
        **({"routing": translation["routing"]} if "routing" in translation else {}),
        **({"reason_code": translation["reason_code"]} if "reason_code" in translation else {}),
        **({"clarification": translation["clarification"]} if "clarification" in translation else {}),
    }
    # A non-ready inference cannot yield a policy, and should not need inventory.
    if status != "ready":
        return basic

    try:
        context, context_source, allow_fixture = context_fn(request.network_id)
    except ContextUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": str(exc)}) from exc

    try:
        # Server-owned ID: never accept an LLM-generated or client-supplied intent ID.
        intent_id = "dryrun-" + uuid4().hex[:16]
        preview = build_preview(
            translation["model_result"], context=context, network_id=request.network_id,
            intent_id=intent_id, allow_fixture=allow_fixture,
        )
    except (IntentContractError, ValueError) as exc:
        # Never return an unvalidated/generated policy on failure.
        raise HTTPException(status_code=422, detail={"code": "policy_dry_run_rejected"}) from exc

    return {
        **basic,
        "policy_validated": True,
        "policy": preview["policy"],
        "compiled_flows": preview["compiled_flows"],
        "context_source": context_source,
    }

