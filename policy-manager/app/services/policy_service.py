import secrets
import time
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.policy import PolicyRecord
from app.schemas.policy import PolicyInput
from app.services.compiler import compile_policy
from app.services.conflict_detector import potential_conflict
from app.adapters import ryu_adapter as ryu

# 16-bit LL prefix + 47 random bits: unique cookie per policy, within signed BIGINT.
def new_cookie():
    return (0x4C4C << 47) | secrets.randbits(47)

def present(record: PolicyRecord):
    return {"id": record.id, "revision": record.revision, "definition": record.definition,
            "status": record.status, "last_error": record.last_error,
            "installed_flows_expected": len(record.compiled_flows),
            "created_at": record.created_at, "updated_at": record.updated_at}

def ensure_no_conflict(db: Session, input_policy: PolicyInput):
    for existing in db.scalars(select(PolicyRecord).where(PolicyRecord.status != "deleted")):
        other = PolicyInput.model_validate(existing.definition)
        if potential_conflict(input_policy, other):
            raise HTTPException(409, detail=f"Potential policy overlap with {existing.id}")

def create_policy(db: Session, original: PolicyInput):
    ensure_no_conflict(db, original)
    pid = original.policy.id or f"FW-{uuid.uuid4().hex[:12]}"
    if db.get(PolicyRecord, pid):
        raise HTTPException(409, detail="Policy ID already exists")
    # Server owns authoritative identity.
    policy = original.model_copy(deep=True)
    policy.policy.id = pid
    flows = compile_policy(policy, new_cookie())
    if not set(f["dpid"] for f in flows).issubset(ryu.switches()):
        raise HTTPException(503, detail="Target switch not connected to Ryu")
    record = PolicyRecord(id=pid, cookie=flows[0]["cookie"],
                          definition=policy.model_dump(mode="json"), compiled_flows=flows, status="applying")
    db.add(record)
    db.commit()
    db.refresh(record)
    try:
        for flow in flows:
            ryu.add_flow(flow)
        # REST response is not an installation acknowledgement; check switch flow table.
        for attempt in range(5):
            if all(ryu.flow_present(flow) for flow in flows):
                break
            time.sleep(0.25)
        else:
            raise ryu.RyuError("Flow(s) not observed in Ryu flow stats after install")
        record.status = "active"
        record.last_error = None
    except ryu.RyuError as exc:
        record.status = "failed"
        record.last_error = str(exc)[:2000]
        # Best-effort cleanup. If it fails, record remains failed for later repair.
        for flow in flows:
            try:
                ryu.delete_flow(flow)
            except ryu.RyuError:
                pass
    db.commit()
    db.refresh(record)
    return present(record)

def delete_policy(db: Session, record: PolicyRecord):
    record.status = "deleting"
    db.commit()
    try:
        for flow in record.compiled_flows:
            ryu.delete_flow(flow)
        for attempt in range(5):
            if not any(ryu.flow_present(flow) for flow in record.compiled_flows):
                break
            time.sleep(0.25)
        else:
            raise ryu.RyuError("Some flow(s) still present after deletion")
        record.status = "deleted"
        record.last_error = None
    except ryu.RyuError as exc:
        record.status = "failed_delete"
        record.last_error = str(exc)[:2000]
    db.commit()
    db.refresh(record)
    return present(record)
