"""Read-side policy routes; never mutate OVS or PostgreSQL."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import PolicyRecord, PolicyOperation, FlowDeployment
from app.adapters import ryu_adapter as ryu

router = APIRouter(prefix='/policies', tags=['Policy Queries'])


def _present(row: PolicyRecord):
    return {
        'id': row.id, 'revision': row.revision, 'definition': row.definition,
        'status': row.status, 'last_error': row.last_error,
        'desired_state': row.desired_state,
        'applied_state': row.applied_state,
        'desired_revision_id': row.desired_revision_id,
        'applied_revision_id': row.applied_revision_id,
        'installed_flows_expected': len(row.compiled_flows or []) if row.applied_revision_id else 0,
        'created_at': row.created_at, 'updated_at': row.updated_at,
    }


@router.get('')
def list_policies(db: Session = Depends(get_db)):
    return [_present(row) for row in db.scalars(select(PolicyRecord).order_by(PolicyRecord.created_at))]


@router.get('/{policy_id}')
def get_policy(policy_id: str, db: Session = Depends(get_db)):
    row = db.get(PolicyRecord, policy_id)
    if row is None:
        raise HTTPException(404, detail='Policy not found')
    return _present(row)


@router.get('/{policy_id}/status')
def status(policy_id: str, db: Session = Depends(get_db)):
    row = db.get(PolicyRecord, policy_id)
    if row is None:
        raise HTTPException(404, detail='Policy not found')
    pending = db.scalars(select(PolicyOperation).where(
        PolicyOperation.policy_id == policy_id,
        PolicyOperation.status.in_(['pending', 'queued', 'running', 'verifying', 'unresolved']),
    )).all()
    if pending:
        return {'id': policy_id, 'in_sync': None, 'reason': 'operation_pending_or_unresolved',
                'pending_operation_ids': [op.id for op in pending],
                'desired_state': row.desired_state, 'applied_state': row.applied_state}
    if row.applied_state == 'unknown':
        return {'id': policy_id, 'in_sync': None, 'reason': 'actual_state_unknown',
                'desired_state': row.desired_state, 'applied_state': row.applied_state}
    expected = row.compiled_flows if row.desired_state == 'enabled' else []
    try:
        # Count currently observed relevant flows, including unexpected stale
        # rules for disabled/deleted policies.
        observed = sum(bool(ryu.flow_present(flow)) for flow in (row.compiled_flows or []))
    except ryu.RyuError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    return {'id': policy_id, 'expected': len(expected), 'observed': observed,
            'in_sync': observed == len(expected), 'desired_state': row.desired_state,
            'applied_state': row.applied_state}


@router.get('/{policy_id}/deployments')
def deployments(policy_id: str, db: Session = Depends(get_db)):
    if db.get(PolicyRecord, policy_id) is None:
        raise HTTPException(404, detail='Policy not found')
    rows = db.scalars(select(FlowDeployment).where(
        FlowDeployment.policy_id == policy_id
    ).order_by(FlowDeployment.revision_id, FlowDeployment.dpid, FlowDeployment.flow_index)).all()
    return [{
        'id': r.id, 'revision_id': r.revision_id, 'dpid': r.dpid,
        'cookie': r.cookie, 'flow_spec': r.flow_spec,
        'deployment_status': r.deployment_status,
        'last_observed_at': r.last_observed_at,
    } for r in rows]
