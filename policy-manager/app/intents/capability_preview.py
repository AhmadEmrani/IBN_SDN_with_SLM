"""Pure capability dispatch for intent previews. No DB, HTTP actuation, or network IO.

The output is a *candidate artifact*; never a deployment authorization.
Stage 6 capabilities must implement their own preview builders before activation.
"""
from __future__ import annotations

from typing import Any, Callable

from app.intents.adapter import adapt_model_result, IntentContractError
from app.intents.capability_registry import require_enabled, CapabilityUnavailable
from app.schemas.policy import PolicyInput
from app.services.compiler import compile_policy


class PreviewNotSupported(ValueError):
    pass


def _firewall_preview(result: dict, *, context: dict, network_id: str,
                      intent_id: str, allow_fixture: bool) -> dict[str, Any]:
    converted = adapt_model_result(result, context=context, network_id=network_id,
                                   intent_id=intent_id, allow_fixture=allow_fixture)
    if converted["status"] != "ready" or converted["policy"] is None:
        raise IntentContractError("unexpected_converter_status")
    policy = PolicyInput.model_validate(converted["policy"])
    return {"policy": policy.model_dump(mode="json"),
            "compiled_flows": compile_policy(policy, cookie=1)}


# Capability-specific preview handlers. Future load_profile output is a workload,
# not necessarily a PolicyInput or an OpenFlow flow list.
PREVIEW_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "firewall": _firewall_preview,
}


def build_preview(result: dict, *, context: dict, network_id: str,
                  intent_id: str, allow_fixture: bool = False) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("status") != "ready":
        raise PreviewNotSupported("model_result_not_ready")
    capability = result.get("capability")
    try:
        require_enabled(capability)
    except CapabilityUnavailable as exc:
        raise PreviewNotSupported(str(exc)) from exc
    handler = PREVIEW_HANDLERS.get(capability)
    if handler is None:
        raise PreviewNotSupported("capability_preview_unavailable")
    return handler(result, context=context, network_id=network_id,
                   intent_id=intent_id, allow_fixture=allow_fixture)
