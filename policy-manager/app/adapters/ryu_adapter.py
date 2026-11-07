import httpx
import ipaddress
from app.config import RYU_URL

class RyuError(RuntimeError):
    pass

def _post(path: str, payload: dict):
    try:
        with httpx.Client(timeout=4.0) as client:
            response = client.post(RYU_URL + path, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RyuError(str(exc)) from exc

def switches() -> set[int]:
    try:
        with httpx.Client(timeout=4.0) as client:
            response = client.get(RYU_URL + "/stats/switches")
            response.raise_for_status()
            return {int(v) for v in response.json()}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise RyuError(str(exc)) from exc

def observed_flows(dpid: int) -> list[dict]:
    try:
        with httpx.Client(timeout=4.0) as client:
            response = client.get(f"{RYU_URL}/stats/flow/{dpid}")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get(str(dpid)), list):
                raise RyuError("Malformed flow-stats response (missing switch or flow list)")
            return data[str(dpid)]
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise RyuError(str(exc)) from exc

def add_flow(flow: dict):
    _post("/stats/flowentry/add", flow)

def delete_flow(flow: dict):
    _post("/stats/flowentry/delete_strict", {
        "dpid": flow["dpid"], "table_id": flow["table_id"],
        "priority": flow["priority"], "match": flow["match"],
        "cookie": flow["cookie"], "cookie_mask": 0xFFFFFFFFFFFFFFFF
    })

FIELD_ALIASES = {
    "dl_type": "eth_type", "nw_src": "ipv4_src",
    "nw_dst": "ipv4_dst", "nw_proto": "ip_proto",
    "tp_src": "transport_src", "tp_dst": "transport_dst",
}


def _normalize_match(match: dict) -> dict:
    normalized = {}
    for key, value in match.items():
        canonical_key = FIELD_ALIASES.get(key, key)
        if canonical_key in ("ipv4_src", "ipv4_dst"):
            normalized[canonical_key] = ipaddress.ip_network(str(value), strict=False)
        elif canonical_key in (
            "eth_type", "ip_proto", "tcp_src", "tcp_dst", "udp_src", "udp_dst",
            "transport_src", "transport_dst", "in_port"
        ):
            normalized[canonical_key] = int(value)
        else:
            normalized[canonical_key] = value
    return normalized


def flow_present(expected: dict) -> bool:
    expected_match = _normalize_match(expected["match"])
    for observed in observed_flows(expected["dpid"]):
        if int(observed.get("cookie", -1)) != int(expected["cookie"]):
            continue
        if int(observed.get("priority", -1)) != int(expected["priority"]):
            continue
        if int(observed.get("table_id", -1)) != int(expected["table_id"]):
            continue
        actual_match = _normalize_match(observed.get("match", {}))
        if not all(key in actual_match and actual_match[key] == value for key, value in expected_match.items()):
            continue
        if expected.get("actions") == []:
            if observed.get("actions") != []:
                continue
        return True
    return False
