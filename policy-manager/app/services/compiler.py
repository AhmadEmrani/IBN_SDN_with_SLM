from ipaddress import ip_network
from app.schemas.policy import PolicyInput

# Reserve priorities 1000-1999 for firewall flows; MAC-learning uses priority 1.
# This compiler is deterministic for a given policy + cookie.
def compile_policy(policy: PolicyInput, cookie: int) -> list[dict]:
    m = policy.match
    endpoints = [(m.source.value, m.destination.value)]
    if m.direction == "bidirectional" and m.source.value != m.destination.value:
        endpoints.append((m.destination.value, m.source.value))
    flows = []
    for dpid in policy.scope.switches:
        for src, dst in endpoints:
            protocol_fields = {"any": {}, "tcp": {"ip_proto": 6}, "udp": {"ip_proto": 17}, "icmp": {"ip_proto": 1}}[m.protocol]
            src_ports = m.source_ports or [None]
            dst_ports = m.destination_ports or [None]
            for sport in src_ports:
                for dport in dst_ports:
                    match = {"eth_type": 0x0800, "ipv4_src": src, "ipv4_dst": dst, **protocol_fields}
                    if sport is not None:
                        match[f"{m.protocol}_src"] = sport
                    if dport is not None:
                        match[f"{m.protocol}_dst"] = dport
                    flows.append({"dpid": int(dpid), "cookie": cookie,
                                  "table_id": 0, "priority": 1000 + policy.policy.priority,
                                  "match": match, "actions": []})
    if len(flows) > 256:
        raise ValueError("Policy expands to more than 256 flows")
    return flows
