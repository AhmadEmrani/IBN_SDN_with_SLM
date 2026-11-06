"""Atomic unit of work: operation + initial audit event + outbox event.

Stage 1 makes this repository available to the next implementation step but
DOES NOT wire it to the public v0.1 endpoints. The caller must put Policy and
PolicyRevision inserts (when needed) in the SAME DB transaction and commit it.
Concurrent inserts are protected by the DB unique constraint; stage-2 service
will translate an IntegrityError into a lookup/replay or HTTP 409.
"""
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.fingerprint import sha256_json
from app.models.event import OperationEvent
from app.models.operation import PolicyOperation
from app.models.outbox import OutboxEvent


class IdempotencyPayloadMismatch(ValueError):
    """The same identity/key was reused with a different request payload."""


@dataclass(frozen=True)
class StagedOperation:
    operation: PolicyOperation
    created: bool


def stage_operation(
    db: Session,
    *,
    policy_id: str,
    operation_type: str,
    requester_id: str,
    idempotency_key: str,
    request_payload: dict,
    requested_revision_id: str | None = None,
    base_revision_id: str | None = None,
    request_hash: str | None = None,
) -> StagedOperation:
    """Stage records in an existing transaction; never commit here.

    Use it inside ``with SessionLocal.begin() as db:``. The policy row must
    exist in this transaction. An outer service must handle a racing
    IntegrityError by rolling back and re-reading the existing operation.
    """
    if not requester_id or not idempotency_key:
        raise ValueError("requester_id and idempotency_key are required")

    request_hash = request_hash or sha256_json({"operation_type": operation_type, "policy_id": policy_id, "payload": request_payload,
                                                "requested_revision_id": requested_revision_id, "base_revision_id": base_revision_id})
    existing = db.scalar(select(PolicyOperation).where(
        PolicyOperation.requester_id == requester_id,
        PolicyOperation.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyPayloadMismatch("Idempotency key has a different request payload")
        return StagedOperation(existing, False)

    
    op_id = str(uuid4())

    operation = PolicyOperation(
        id=op_id,
        policy_id=policy_id,
        operation_type=operation_type,
        requested_revision_id=requested_revision_id,
        base_revision_id=base_revision_id,
        requester_id=requester_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status="pending",
        attempt_count=0,
    )

    # STEP 1: Insert parent operation first.
    # flush() does NOT commit the transaction.
    db.add(operation)
    db.flush()

    # STEP 2: Insert dependent records.
    event = OperationEvent(
        id=str(uuid4()),
        operation_id=op_id,
        event_type="operation.submitted",
        step_name="submit",
        attempt_no=1,
        details={"operation_type": operation_type},
    )

    outbox = OutboxEvent(
        id=str(uuid4()),
        operation_id=op_id,
        event_type="policy.operation.requested",
        payload={"operation_id": op_id},
        dispatch_status="pending",
        attempts=0,
    )

    db.add_all([event, outbox])
    db.flush()

    return StagedOperation(operation, True)

