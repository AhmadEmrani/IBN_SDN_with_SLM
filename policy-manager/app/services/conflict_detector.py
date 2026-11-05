from ipaddress import ip_network
from app.schemas.policy import PolicyInput

def _overlap_endpoints(a: PolicyInput, b: PolicyInput) -> bool:
    def pairs(p):
        pairs = [(p.match.source.value, p.match.destination.value)]
        if p.match.direction == "bidirectional":
            pairs.append((p.match.destination.value, p.match.source.value))
        return pairs
    for asrc, adst in pairs(a):
        for bsrc, bdst in pairs(b):
            if ip_network(asrc).overlaps(ip_network(bsrc)) and ip_network(adst).overlaps(ip_network(bdst)):
                return True
    return False

def potential_conflict(a: PolicyInput, b: PolicyInput) -> bool:
    if a.scope.network_id != b.scope.network_id or not (set(a.scope.switches) & set(b.scope.switches)):
        return False
    if a.match.protocol != "any" and b.match.protocol != "any" and a.match.protocol != b.match.protocol:
        return False
    # Fail closed: overlapping IP/protocol scope is conservatively rejected even if ports differ.
    return _overlap_endpoints(a, b)
