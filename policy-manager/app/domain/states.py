"""Canonical lifecycle vocabulary. DB columns use these string values.

State transitions and the execution engine arrive in v0.2 stage 2.
"""
from enum import StrEnum


class DesiredState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    DELETED = "deleted"


class OperationType(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    ENABLE = "enable"
    DISABLE = "disable"
    DELETE = "delete"
    RECONCILE = "reconcile"


class OperationStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    UNRESOLVED = "unresolved"


class DeploymentStatus(StrEnum):
    INSTALLED = "installed"
    ABSENT = "absent"
    PARTIAL = "partial"
    DRIFTED = "drifted"
    UNKNOWN = "unknown"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    DELIVERED = "delivered"
