from __future__ import annotations
from ipaddress import IPv4Network, ip_network
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class PolicyIdentity(StrictModel):
    id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    type: Literal["firewall"]
    enabled: bool = True
    priority: int = Field(default=100, ge=10, le=999)

class Scope(StrictModel):
    network_id: str = Field(min_length=1, max_length=100)
    switches: list[str] = Field(min_length=1, max_length=16)

    @field_validator("switches")
    @classmethod
    def validate_switches(cls, values: list[str]):
        if len(set(values)) != len(values) or any(not v.isdecimal() or int(v) < 1 for v in values):
            raise ValueError("switches must be unique, positive decimal DPIDs")
        return values

class Endpoint(StrictModel):
    type: Literal["ipv4"] = "ipv4"
    value: str

    @field_validator("value")
    @classmethod
    def normalize_cidr(cls, value: str):
        net = ip_network(value, strict=False)
        if not isinstance(net, IPv4Network):
            raise ValueError("IPv4 only in v1")
        return str(net)

class Match(StrictModel):
    source: Endpoint
    destination: Endpoint
    direction: Literal["unidirectional", "bidirectional"] = "unidirectional"
    protocol: Literal["any", "tcp", "udp", "icmp"] = "any"
    source_ports: list[int] | None = None
    destination_ports: list[int] | None = None

    @field_validator("source_ports", "destination_ports")
    @classmethod
    def valid_ports(cls, values):
        if values is not None and (not values or len(values) > 16 or len(set(values)) != len(values) or any(not 1 <= x <= 65535 for x in values)):
            raise ValueError("port lists must contain 1-16 distinct values in 1..65535")
        return values

    @model_validator(mode="after")
    def ports_require_transport(self):
        if (self.source_ports is not None or self.destination_ports is not None) and self.protocol not in ("tcp", "udp"):
            raise ValueError("ports require tcp or udp")
        if self.direction == "bidirectional" and (self.source_ports is not None or self.destination_ports is not None):
            raise ValueError("bidirectional port rules are deferred to a later schema version")
        return self

class Action(StrictModel):
    type: Literal["deny"]
    parameters: dict = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def empty_parameters(cls, value):
        if value:
            raise ValueError("deny does not accept action parameters")
        return value

class Constraints(StrictModel):
    start_at: None = None
    end_at: None = None

class Metadata(StrictModel):
    source: Literal["manual", "intent_converter"] = "manual"
    intent_id: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    reason: str | None = Field(default=None, max_length=1000)

class PolicyInput(StrictModel):
    schema_version: Literal["1.0"]
    policy: PolicyIdentity
    scope: Scope
    match: Match
    action: Action
    constraints: Constraints = Field(default_factory=Constraints)
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="after")
    def supported(self):
        if not self.policy.enabled:
            raise ValueError("v1 create only supports enabled policies; disable via DELETE and recreate later")
        return self
