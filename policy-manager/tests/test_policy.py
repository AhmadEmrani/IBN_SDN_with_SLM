import pytest
from pydantic import ValidationError
from app.schemas.policy import PolicyInput
from app.services.compiler import compile_policy
from app.services.conflict_detector import potential_conflict

BASE = {
  "schema_version": "1.0", "policy": {"name": "block-1", "type": "firewall"},
  "scope": {"network_id": "mininet-lab", "switches": ["1"]},
  "match": {"source": {"type": "ipv4", "value": "10.0.0.1/32"},
            "destination": {"type": "ipv4", "value": "10.0.0.3/32"},
            "direction": "bidirectional", "protocol": "any"},
  "action": {"type": "deny"}}

def test_compile_bidirectional():
    flows = compile_policy(PolicyInput.model_validate(BASE), 100)
    assert len(flows) == 2
    assert all(f["actions"] == [] and f["cookie"] == 100 for f in flows)

def test_reject_invalid_port_protocol():
    p = {**BASE, "match": {**BASE["match"], "destination_ports": [80]}}
    with pytest.raises(ValidationError):
        PolicyInput.model_validate(p)

def test_conflict_overlap():
    a = PolicyInput.model_validate(BASE)
    p = {**BASE, "match": {**BASE["match"], "source": {"type": "ipv4", "value": "10.0.0.0/24"}}}
    assert potential_conflict(a, PolicyInput.model_validate(p))
