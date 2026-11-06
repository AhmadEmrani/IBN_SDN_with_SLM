"""Explicit public contract, independent of SQLAlchemy models."""
from pydantic import BaseModel


class OperationAccepted(BaseModel):
    policy_id: str
    operation_id: str
    status: str
    status_url: str
    created: bool
