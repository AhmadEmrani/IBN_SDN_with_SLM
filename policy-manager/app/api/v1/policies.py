from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.policy import PolicyRecord
from app.schemas.policy import PolicyInput
from app.services.compiler import compile_policy
from app.services.policy_service import create_policy, delete_policy, present
from app.adapters import ryu_adapter as ryu

router = APIRouter(prefix="/api/v1/policies", tags=["Policies"])

@router.post("/validate")
def validate(policy: PolicyInput):
    return {"valid": True, "normalized_policy": policy.model_dump(mode="json")}

@router.post("/compile")
def compile_preview(policy: PolicyInput):
    # Preview only; cookie 1 is a placeholder and is never installed.
    return {"flows": compile_policy(policy, 1), "dry_run": True}

@router.post("", status_code=201)
def create(policy: PolicyInput, db: Session = Depends(get_db)):
    try:
        return create_policy(db, policy)
    except ryu.RyuError as exc:
        raise HTTPException(503, detail=str(exc)) from exc

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
        observed = sum(ryu.flow_present(f) for f in record.compiled_flows)
    except ryu.RyuError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    return {"id": policy_id, "stored_status": record.status,
            "expected": len(record.compiled_flows) if record.status != "deleted" else 0,
            "observed": observed,
            "in_sync": (observed == (0 if record.status == "deleted" else len(record.compiled_flows)))}

@router.delete("/{policy_id}")
def delete(policy_id: str, db: Session = Depends(get_db)):
    record = db.get(PolicyRecord, policy_id)
    if record is None:
        raise HTTPException(404, detail="Policy not found")
    if record.status == "deleted":
        return present(record)
    return delete_policy(db, record)
