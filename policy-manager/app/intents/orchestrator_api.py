"""Stage 5D.2: read-only BGE -> Phi -> ModelResult validation.

This service deliberately imports no policy execution, DB, Airflow, or Ryu code.
The firewall capability is supplied explicitly in 5D.2, not auto-classified.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA = PROJECT_ROOT / "contracts/intent-v1/model-result.schema.json"
REGISTRY = PROJECT_ROOT / "contracts/intent-v1/capabilities.json"

RETRIEVER_URL = os.getenv("LLNET_RETRIEVER_URL", "http://intent-retriever:8092").rstrip("/")
PHI_URL = os.getenv("LLNET_PHI_URL", "http://phi-inference:8093").rstrip("/")
TIMEOUT_SECONDS = float(os.getenv("LLNET_PHI_TIMEOUT_SECONDS", "180"))


class TranslateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    capability: str = "firewall"  # Explicit v1 selection. NO automatic classifier yet.
    top_k: int = Field(default=3, ge=1, le=10)


app = FastAPI(title="LLNet Stage 5D.2 Read-only Intent Orchestrator", version="0.5d2")


@app.get("/health")
def health():
    return {"status": "ok", "mode": "read_only", "stage": "5d2"}


def _check_capability(capability: str) -> None:
    entries = json.loads(REGISTRY.read_text(encoding="utf-8"))["capabilities"]
    found = next((item for item in entries if item["id"] == capability), None)
    if found is None:
        raise HTTPException(status_code=422, detail={"code": "unknown_capability"})
    if not found.get("enabled", False):
        raise HTTPException(status_code=422, detail={"code": "capability_disabled"})


def _parse_model_json(raw: str) -> dict:
    # Reject decoration and multiple objects; no silent JSON repair.
    try:
        value = json.loads(raw.strip())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail={"code": "invalid_model_json"}) from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=502, detail={"code": "model_result_not_object"})
    return value


def _validate_result(result: dict, capability: str) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(result))
    if errors:
        raise HTTPException(status_code=502, detail={"code": "model_contract_violation"})
    if result["status"] == "ready" and result["capability"] != capability:
        raise HTTPException(status_code=502, detail={"code": "capability_mismatch"})
    if result["status"] != "ready" and result["capability"] not in (None, capability):
        raise HTTPException(status_code=502, detail={"code": "capability_mismatch"})


def _compact_phi_messages(messages: list[dict]) -> list[dict]:
    """Remove only the verbose inline schema; the backend keeps validating it.

    Preserve trusted system/capability rules and BGE-selected demonstrations.
    """
    if not messages or messages[0]["role"] != "system":
        raise ValueError("retriever must provide a trusted system message")
    marker = "\n\nOutput schema (JSON):\n"
    system = messages[0]["content"]
    if marker not in system:
        raise ValueError("retriever schema marker missing")
    rules, _, inline_schema = system.partition(marker)
    # Ensure we're dropping the expected JSON schema, not arbitrary text.
    schema = json.loads(inline_schema)
    if not isinstance(schema, dict) or "oneOf" not in schema:
        raise ValueError("unexpected inline schema")
    instruction = (
        "\n\nOutput ONLY one minified JSON object; no prose, no fences, "
        "no schema echo, no second object. Stop immediately after its closing brace. "
        "Keys: contract_version, status, capability, proposal, clarification, reason_code. "
        "For status=ready, proposal keys: source, destination, direction, protocol, "
        "source_ports, destination_ports, action. For non-ready, proposal=null. "
        "Follow the few-shot response structure; never copy the schema into the answer."
    )
    return [{"role": "system", "content": rules + instruction}] + messages[1:]


async def translate(request: TranslateRequest, client: httpx.AsyncClient) -> dict:
    _check_capability(request.capability)
    try:
        retrieved = await client.post(
            RETRIEVER_URL + "/v1/prepare",
            json={"text": request.text, "capability": request.capability, "top_k": request.top_k},
            timeout=45.0,
        )
        retrieved.raise_for_status()
        prepared = retrieved.json()
        messages = prepared["messages"]
        if (prepared.get("capability") != request.capability
                or not isinstance(messages, list) or not messages
                or not all(isinstance(m, dict) and m.get("role") in ("system", "user", "assistant")
                           and isinstance(m.get("content"), str) for m in messages)):
            raise ValueError("retriever returned inconsistent prompt")
        messages = _compact_phi_messages(messages)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=502, detail={"code": "retriever_unavailable_or_invalid"}) from exc

    # This is inference only. Do not call policy APIs, DB, Airflow, Ryu, or OVS.
    try:
        generated = await client.post(
            PHI_URL + "/v1/chat/completions",
            json={
                "messages": messages,
                "temperature": 0,
                "max_tokens": 1024,
                "stream": False,
                # Prevent a second top-level JSON object or schema echo after the answer.
                # Parsing and schema validation below remain fail-closed.
                "stop": ["\n {", "\n{", "\n```"],
                # Do not force llama.cpp JSON grammar for Phi-3.5 GGUF here:
                # certain llama.cpp builds fail sampler initialization (HTTP 400).
                # Fail-closed JSON parsing and schema validation remain mandatory.
            },
            timeout=TIMEOUT_SECONDS,
        )
        generated.raise_for_status()
        payload = generated.json()
        raw_result = payload["choices"][0]["message"]["content"]
        finish_reason = payload["choices"][0].get("finish_reason")
        if not isinstance(raw_result, str):
            raise ValueError("Phi returned non-string")
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail={"code": "phi_unavailable_or_invalid"}) from exc

    if finish_reason == "length":
        raise HTTPException(status_code=502, detail={"code": "phi_output_truncated"})
    result = _parse_model_json(raw_result)
    _validate_result(result, request.capability)
    return {
        "status": result["status"],
        "capability": request.capability,
        "model_result": result,
        "retrieved_example_ids": prepared.get("retrieved_example_ids", []),
        "validated": True,
        "deployment": "not_requested",
    }


@app.post("/v1/intents/translate")
async def translate_api(request: TranslateRequest):
    async with httpx.AsyncClient() as client:
        return await translate(request, client)
