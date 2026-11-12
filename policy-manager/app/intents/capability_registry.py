"""Single fail-closed capability catalog shared by routing, retrieval, and intent APIs.

The operator-owned JSON controls *declared readiness*, not authorization to deploy.
Only capabilities with an implemented local preview handler may be enabled.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "contracts/intent-v1/capabilities.json"
KNOWN_CAPABILITIES = frozenset({"firewall", "rate_limit", "load_profile"})
IMPLEMENTED_PREVIEW_HANDLERS = frozenset({"firewall"})


class CapabilityConfigurationError(ValueError):
    """Operator configuration is missing, inconsistent, or unsafe."""


class CapabilityUnavailable(ValueError):
    """A caller requested an unknown or not-yet-enabled capability."""


def read_catalog(path: Path = REGISTRY_PATH) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise CapabilityConfigurationError("capability_registry_unavailable") from exc
    if not isinstance(raw, dict) or raw.get("contract_version") != "1.0":
        raise CapabilityConfigurationError("unsupported_capability_registry_version")
    entries = raw.get("capabilities")
    if not isinstance(entries, list) or not entries:
        raise CapabilityConfigurationError("invalid_capability_registry")
    catalog: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise CapabilityConfigurationError("invalid_capability_entry")
        name = entry.get("id")
        if not isinstance(name, str) or name not in KNOWN_CAPABILITIES or name in catalog:
            raise CapabilityConfigurationError("unknown_or_duplicate_capability")
        if type(entry.get("enabled")) is not bool:
            raise CapabilityConfigurationError("invalid_enabled_flag")
        if entry["enabled"]:
            # Never equate an enabled flag with a working adapter / backend.
            if name not in IMPLEMENTED_PREVIEW_HANDLERS:
                raise CapabilityConfigurationError("enabled_capability_has_no_preview_handler")
            if not all(isinstance(entry.get(k), str) and entry[k]
                       for k in ("prompt", "proposal_schema", "backend_schema_version")):
                raise CapabilityConfigurationError("enabled_capability_missing_contract")
        catalog[name] = entry
    if set(catalog) != KNOWN_CAPABILITIES:
        raise CapabilityConfigurationError("capability_registry_incomplete")
    return catalog


def require_enabled(capability: str, *, path: Path = REGISTRY_PATH) -> dict[str, Any]:
    if not isinstance(capability, str):
        raise CapabilityUnavailable("unknown_capability")
    entry = read_catalog(path).get(capability)
    if entry is None:
        raise CapabilityUnavailable("unknown_capability")
    if not entry["enabled"]:
        raise CapabilityUnavailable("capability_disabled")
    return entry


def enabled_map(*, path: Path = REGISTRY_PATH) -> dict[str, bool]:
    return {name: entry["enabled"] for name, entry in read_catalog(path).items()}
