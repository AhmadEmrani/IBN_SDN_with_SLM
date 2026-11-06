"""Legacy synchronous create/delete endpoints (stage-1 compatibility).

Stage 2 replaces these internals with operation submission / HTTP 202.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.policy import PolicyRecord
from app.schemas.policy import PolicyInput
from app.services.policy_service import create_policy, delete_policy, present
from app.adapters import ryu_adapter as ryu

router = APIRouter(prefix="/policies")


@router.post("", status_code=201)
def create(policy: PolicyInput, db: Session = Depends(get_db)):
    try:
        return create_policy(db, policy)
    except ryu.RyuError as exc:
        raise HTTPException(503, detail=str(exc)) from exc


@router.delete("/{policy_id}")
def delete(policy_id: str, db: Session = Depends(get_db)):
    record = db.get(PolicyRecord, policy_id)
    if record is None:
        raise HTTPException(404, detail="Policy not found")
    if record.status == "deleted":
        return present(record)
    return delete_policy(db, record)
