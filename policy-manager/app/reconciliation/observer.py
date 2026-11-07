"""Pure OpenFlow comparison. Never performs network writes or database IO.

Ryu's match field normalization is shared with Stage 3's verification logic.
Only known deployed cookies are used for classifying unexpected rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from app.adapters.ryu_adapter import _normalize_match


class InvalidObservation(ValueError):
    """An invalid response must be UNKNOWN, never interpreted as an absent rule."""


def signature(flow: dict) -> dict:
    """Comparable OpenFlow identity + actions (ignores volatile counters/duration)."""
    if not isinstance(flow, dict) or not isinstance(flow.get("match"), dict):
        raise InvalidObservation("Flow or match is not an object")
    if "actions" not in flow or not isinstance(flow["actions"], list):
        raise InvalidObservation("Flow is missing a valid actions list")
    try:
        normalized = _normalize_match(flow["match"])
        # Older Ryu responses may use tp_src/tp_dst instead of TCP/UDP names.
        # Resolve only when the IP protocol is explicit (no guessing).
        proto = normalized.get("ip_proto")
        if proto in (6, 17):
            prefix = "tcp" if proto == 6 else "udp"
            for suffix in ("src", "dst"):
                legacy = f"transport_{suffix}"
                canonical = f"{prefix}_{suffix}"
                if legacy in normalized and canonical not in normalized:
                    normalized[canonical] = normalized.pop(legacy)
        match = {k: str(v) if not isinstance(v, int) else v
                 for k, v in normalized.items()}
        return {
            "cookie": int(flow.get("cookie", 0)),
            "table_id": int(flow["table_id"]),
            "priority": int(flow["priority"]),
            "match": match,
            "actions": flow["actions"],
        }
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise InvalidObservation(f"Invalid OpenFlow field: {exc}") from exc


def _match_key(sig: dict) -> tuple:
    return tuple(sorted(sig["match"].items()))


def _same_rule(expected: dict, actual: dict) -> bool:
    return (expected["cookie"] == actual["cookie"]
            and _match_key(expected) == _match_key(actual))


@dataclass(frozen=True)
class Difference:
    classification: str  # healthy | missing | modified
    observed: dict | None
    observed_index: int | None


def compare(expected: dict, observed: list[dict], used: set[int] | None = None) -> Difference:
    """Different match with the same cookie is NOT guessed to be this rule."""
    want = signature(expected)
    used = used or set()
    candidates = [(idx, actual) for idx, actual in enumerate(observed)
                  if idx not in used and _same_rule(want, actual)]
    # Prioritize exact location (table, priority) over a moved/modified rule.
    candidates.sort(key=lambda x: (x[1]["table_id"] != want["table_id"],
                                   x[1]["priority"] != want["priority"]))
    if not candidates:
        return Difference("missing", None, None)
    idx, actual = candidates[0]
    is_healthy = (want["table_id"] == actual["table_id"]
                  and want["priority"] == actual["priority"]
                  and want["actions"] == actual["actions"])
    return Difference("healthy" if is_healthy else "modified", actual, idx)


def extra_finding_key(dpid: int, actual: dict) -> str:
    payload = json.dumps(actual, sort_keys=True, separators=(",", ":"), default=str)
    return f"extra:{dpid}:{sha256(payload.encode()).hexdigest()}"
