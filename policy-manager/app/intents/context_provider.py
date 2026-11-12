"""Stage 5D.3: explicitly lab-only trusted context source.

Never use untrusted client/model-provided inventory. Runtime discovery is not
implemented in this stage. Keep the runtime path fail-closed until it exists.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAB_FIXTURE = PROJECT_ROOT / "data/intents/stage5a/network-context.json"


class ContextUnavailable(ValueError):
    """No authorized inventory for this network."""


def get_trusted_context(network_id: str) -> tuple[dict, str, bool]:
    """Return (context, provenance, allow_fixture), never from request data.

    The server operator must explicitly set LLNET_DRY_RUN_CONTEXT_MODE=fixture.
    No environment setting in this stage enables production inventory.
    """
    if not isinstance(network_id, str) or not network_id:
        raise ContextUnavailable("network_id_required")
    if os.getenv("LLNET_DRY_RUN_CONTEXT_MODE", "disabled") != "fixture":
        raise ContextUnavailable("trusted_runtime_context_unavailable")
    try:
        context = json.loads(LAB_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContextUnavailable("lab_fixture_unavailable") from exc
    if context.get("fixture_only") is not True or context.get("network_id") != network_id:
        raise ContextUnavailable("lab_fixture_network_mismatch")
    return context, "lab_fixture", True
