"""Read-only durable operation and event lookup; mutations live in command modules."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.operation import PolicyOperation
from app.models.event import OperationEvent

router = APIRouter(prefix="/api/v1/operations", tags=["Operations"])


@router.get("/{operation_id}")
def get_operation(operation_id: str, db: Session = Depends(get_db)):
    operation = db.get(PolicyOperation, operation_id)
    if operation is None:
        raise HTTPException(404, detail="Operation not found")
    return {
        "id": operation.id, "policy_id": operation.policy_id,
        "operation_type": operation.operation_type, "status": operation.status,
        "requested_state": operation.requested_state,
        "requested_revision_id": operation.requested_revision_id,
        "base_revision_id": operation.base_revision_id,
        "attempt_count": operation.attempt_count,
        "error_code": operation.error_code, "error_message": operation.error_message,
        "airflow_run_id": operation.airflow_run_id,
        "created_at": operation.created_at,
        "started_at": operation.started_at,
        "finished_at": operation.finished_at,
    }


@router.get("/{operation_id}/events")
def get_operation_events(operation_id: str, db: Session = Depends(get_db)):
    if db.get(PolicyOperation, operation_id) is None:
        raise HTTPException(404, detail="Operation not found")
    rows = db.scalars(
        select(OperationEvent).where(OperationEvent.operation_id == operation_id)
        .order_by(OperationEvent.created_at, OperationEvent.id)
    ).all()
    return [{
        "id": r.id, "event_type": r.event_type, "step_name": r.step_name,
        "attempt_no": r.attempt_no, "details": r.details,
        "evidence_ref": r.evidence_ref, "created_at": r.created_at,
    } for r in rows]
