"""Public Intent API request contracts; backward-compatible with Stage 5."""
from pydantic import BaseModel, ConfigDict, Field

class RouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


class TranslateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    capability: str | None = None  # Omitted => BGE capability routing; explicit remains supported.
    top_k: int = Field(default=3, ge=1, le=10)


class DryRunRequest(TranslateRequest):
    network_id: str = Field(min_length=1, max_length=100)

