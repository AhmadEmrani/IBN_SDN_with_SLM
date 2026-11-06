"""Policy read-side endpoints: database record and observed switch state."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.policy import PolicyRecord
from app.services.policy_service import present
from app.adapters import ryu_adapter as ryu

router = APIRouter(prefix="/policies")


@router.get("")
def list_policies(db: Session = Depends(get_db)):
    return [present(row) for row in db.scalars(select(PolicyRecord).order_by(PolicyRecord.created_at))]


@router.get("/{policy_id}")
def get_policy(policy_id: str, db: Session = Depends(get_db)):
    record = db.get(PolicyRecord, policy_id)
    if record is None:
        raise HTTPException(404, detail="Policy not found")
    return present(record)


@router.get("/{policy_id}/status")
def status(policy_id: str, db: Session = Depends(get_db)):
    record = db.get(PolicyRecord, policy_id)
    if record is None:
        raise HTTPException(404, detail="Policy not found")
    try:
        observed = sum(ryu.flow_present(flow) for flow in record.compiled_flows)
    except ryu.RyuError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    expected = 0 if record.status == "deleted" else len(record.compiled_flows)
    return {"id": policy_id, "stored_status": record.status,
            "expected": expected, "observed": observed,
            "in_sync": observed == expected}
