"""Stage 5B: fail-closed, side-effect-free intent result -> PolicyInput adapter.

No LLM, network discovery, DB writes, or Ryu calls occur here.
Inventory comes from the trusted caller; Stage5A fixture must be explicitly opted into.
"""
from __future__ import annotations

from ipaddress import IPv4Network, ip_network
from pathlib import Path
import json
from typing import Any

from jsonschema import Draft202012Validator
from app.schemas.policy import PolicyInput
from app.services.compiler import compile_policy

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = PROJECT_ROOT / "contracts/intent-v1/model-result.schema.json"
CAPABILITIES_PATH = PROJECT_ROOT / "contracts/intent-v1/capabilities.json"


class IntentContractError(ValueError):
    """Bad or unsafe model output or untrusted context; no policy generated."""


def _schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_context(context: dict[str, Any], network_id: str, *, allow_fixture: bool) -> tuple[dict, list[str], int]:
    if not isinstance(context, dict):
        raise IntentContractError("network context must be a mapping from a trusted source")
    if context.get("fixture_only") is True and not allow_fixture:
        raise IntentContractError("fixture_only inventory cannot be used at runtime")
    if context.get("network_id") != network_id or not isinstance(network_id, str) or not network_id:
        raise IntentContractError("network_id does not match trusted inventory")
    hosts = context.get("hosts")
    switches = context.get("default_switches")
    priority = context.get("default_priority")
    if not isinstance(hosts, dict) or not isinstance(switches, list) or not switches:
        raise IntentContractError("trusted inventory missing hosts or default_switches")
    if not isinstance(priority, int) or isinstance(priority, bool) or not 10 <= priority <= 999:
        raise IntentContractError("invalid trusted default priority")
    if any(not isinstance(x, str) or not x.isdecimal() or int(x) <= 0 for x in switches) or len(set(switches)) != len(switches) or len(switches) > 16:
        raise IntentContractError("invalid trusted default switches")
    known = context.get("switches")
    if not isinstance(known, list) or not set(switches).issubset(set(known)):
        raise IntentContractError("default switch not in trusted inventory")
    return hosts, switches, priority


def _endpoint(value: str, hosts: dict[str, str]) -> str:
    if value == "any":
        return "0.0.0.0/0"
    if value in hosts:
        value = hosts[value]
    else:
        # Unknown symbolic host name must not become a wildcard or guessed IP.
        if not (isinstance(value, str) and ("." in value or "/" in value)):
            raise IntentContractError("unknown_host")
    try:
        net = ip_network(value, strict=False)
    except (ValueError, TypeError) as exc:
        raise IntentContractError("invalid_or_unknown_endpoint") from exc
    if not isinstance(net, IPv4Network):
        raise IntentContractError("unsupported_ipv6")
    return str(net)


def adapt_model_result(result: dict[str, Any], *, context: dict[str, Any], network_id: str,
                       intent_id: str, allow_fixture: bool = False) -> dict[str, Any]:
    """Return a converter response with status, policy or null, and reason_code.

    `ready` is a *proposal*, NEVER an authorization to deploy. Only the trusted
    backend uses context. Caller must supply intent_id (not from model output).
    """
    if not isinstance(result, dict):
        raise IntentContractError("model result must be a JSON object")
    validator = Draft202012Validator(_schema(SCHEMA_PATH))
    errors = list(validator.iter_errors(result))
    if errors:
        raise IntentContractError("model-result schema invalid: " + errors[0].message)
    registry = _schema(CAPABILITIES_PATH)
    enabled = {entry["id"] for entry in registry["capabilities"] if entry.get("enabled")}
    status = result["status"]
    capability = result["capability"]
    if status != "ready":
        return {"status": status, "policy": None, "clarification": result["clarification"],
                "reason_code": result["reason_code"]}
    if capability not in enabled:
        raise IntentContractError("capability_disabled")
    if not isinstance(intent_id, str) or not (1 <= len(intent_id) <= 64):
        raise IntentContractError("trusted intent_id required")
    hosts, switches, priority = _require_context(context, network_id, allow_fixture=allow_fixture)
    p = result["proposal"]
    if p["direction"] == "bidirectional" and (p["source_ports"] is not None or p["destination_ports"] is not None):
        raise IntentContractError("unsupported_bidirectional_ports")
    if p["protocol"] not in ("tcp", "udp") and (p["source_ports"] is not None or p["destination_ports"] is not None):
        raise IntentContractError("ports_require_tcp_or_udp")
    policy_data = {
        "schema_version": "1.0",
        "policy": {"id": None, "name": f"Intent {intent_id}", "description": None,
                   "type": "firewall", "enabled": True, "priority": priority},
        "scope": {"network_id": network_id, "switches": switches},
        "match": {"source": {"type": "ipv4", "value": _endpoint(p["source"], hosts)},
                  "destination": {"type": "ipv4", "value": _endpoint(p["destination"], hosts)},
                  "direction": p["direction"], "protocol": p["protocol"],
                  "source_ports": p["source_ports"], "destination_ports": p["destination_ports"]},
        "action": {"type": "deny", "parameters": {}},
        "constraints": {"start_at": None, "end_at": None},
        "metadata": {"source": "intent_converter", "intent_id": intent_id, "tags": [], "reason": None},
    }
    # Real backend validator + compiler are the final dry-run gates.
    policy = PolicyInput.model_validate(policy_data)
    compile_policy(policy, cookie=1)
    return {"status": "ready", "policy": policy.model_dump(mode="json"),
            "clarification": None, "reason_code": None}
