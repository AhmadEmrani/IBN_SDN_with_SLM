"""Stage 4B: explicitly triggered, fail-closed repair of ONE confirmed missing flow.

No Airflow, no automatic polling repair, no deletes. The existing operation and
scope-reservation tables serialize changes with the Stage 2/3 lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.adapters import ryu_adapter as ryu
from app.db.session import SessionLocal
from app.domain.fingerprint import sha256_json
from app.models import (FlowDeployment, OperationEvent, PolicyOperation, PolicyRecord,
                        ReconciliationFinding, ScopeReservation)
from app.reconciliation.observer import InvalidObservation, signature
from app.reconciliation.service import BUSY_STATUSES, _stable
from app.schemas.policy import PolicyInput
from app.services.execution_service import _claim, _set_verifying


class RepairRefused(RuntimeError):
    """No network mutation is permitted for this finding/current state."""


@dataclass(frozen=True)
class RepairResult:
    status: str  # eligible | succeeded | failed | unresolved
    reason: str
    operation_id: str | None = None


def _now():
    return datetime.now(timezone.utc)


def _candidate(db, finding_id: str, *, lock: bool = False) -> tuple:
    find_query = select(ReconciliationFinding).where(ReconciliationFinding.id == finding_id)
    if lock:
        # Lock policy FIRST, like policy submission. The finding itself is checked
        # under the same short transaction before reserving the switch.
        pid = db.scalar(select(ReconciliationFinding.policy_id).where(
            ReconciliationFinding.id == finding_id))
        if not pid:
            raise RepairRefused('Unknown finding or missing policy owner')
        policy = db.scalar(select(PolicyRecord).where(PolicyRecord.id == pid).with_for_update())
        find_query = find_query.with_for_update()
    else:
        policy = None
    finding = db.scalar(find_query)
    if not finding or finding.kind != 'missing' or finding.confirmed_at is None or finding.resolved_at is not None:
        raise RepairRefused('Finding is not an open, confirmed MISSING finding')
    if finding.consecutive_count < 2 or not finding.deployment_id or not finding.policy_id:
        raise RepairRefused('Missing evidence is not confirmed in two valid observations')
    policy = policy or db.get(PolicyRecord, finding.policy_id)
    row = db.get(FlowDeployment, finding.deployment_id)
    if not policy or not row or row.policy_id != policy.id or row.dpid != finding.dpid:
        raise RepairRefused('Finding does not match its deployment owner')
    if not (_stable(policy) and policy.desired_state == 'enabled'
            and row.revision_id == policy.applied_revision_id
            and policy.applied_revision_id == policy.desired_revision_id):
        raise RepairRefused('Policy is not stable/enabled on its committed revision')
    snapshot = row.observed_snapshot or {}
    if snapshot.get('classification') != 'missing' or not snapshot.get('confirmed'):
        raise RepairRefused('Latest observer evidence is not confirmed MISSING')
    if row.deployment_status != 'missing':
        raise RepairRefused('Deployment is not marked missing')
    spec = row.flow_spec
    if (not isinstance(spec, dict) or spec.get('actions') != []
            or int(spec.get('dpid', -1)) != int(row.dpid)
            or int(spec.get('cookie', -1)) != int(row.cookie)
            or int(policy.cookie) != int(row.cookie)):
        raise RepairRefused('Only registered, missing DROP flows are supported')
    scope = PolicyInput.model_validate(policy.definition).scope
    if int(row.dpid) not in {int(d) for d in scope.switches}:
        raise RepairRefused('Deployment switch is not in the committed policy scope')
    busy = db.scalar(select(PolicyOperation.id).where(
        PolicyOperation.policy_id == policy.id,
        PolicyOperation.status.in_(BUSY_STATUSES)).limit(1))
    if busy:
        raise RepairRefused('Policy has a pending, running, or unresolved operation')
    reserved = db.scalar(select(ScopeReservation.operation_id).where(
        ScopeReservation.dpid == row.dpid).limit(1))
    if reserved:
        raise RepairRefused('Switch is reserved by an existing operation')
    known = db.scalars(select(FlowDeployment).where(
        FlowDeployment.policy_id == policy.id,
        FlowDeployment.revision_id == policy.applied_revision_id,
        FlowDeployment.dpid == row.dpid)).all()
    return policy, row, finding, scope.network_id, [r.flow_spec for r in known]


def _network_check(adapter, row_spec: dict, known_specs: list[dict]) -> str:
    """Fresh preflight/verification. Never overwrite a modified or foreign rule."""
    dpid = int(row_spec['dpid'])
    if dpid not in {int(v) for v in adapter.switches()}:
        raise RepairRefused('Switch is not connected; observation is UNKNOWN')
    raw = adapter.observed_flows(dpid)
    if not isinstance(raw, list):
        raise RepairRefused('Invalid flow stats; observation is UNKNOWN')
    actual = [signature(item) for item in raw]
    want = signature(row_spec)
    known = [signature(spec) for spec in known_specs]
    # A foreign or modified rule with the same match, table and priority may
    # be overwritten by an OF ADD. Never write into this ambiguous slot.
    for item in actual:
        same_slot = (item['table_id'] == want['table_id']
                     and item['priority'] == want['priority']
                     and item['match'] == want['match'])
        if same_slot and item != want:
            raise RepairRefused('Modified/foreign flow occupies the exact OpenFlow slot')
        if item['cookie'] == want['cookie'] and item not in known:
            raise RepairRefused('Unexpected flow with the policy cookie')
    return 'already_present' if want in actual else 'missing'


def check(finding_id: str, *, session_factory=None, adapter=ryu) -> RepairResult:
    """Read-only preflight for an operator; does NOT reserve or write anything."""
    factory = session_factory or SessionLocal
    with factory() as db:
        _, row, _, _, known = _candidate(db, finding_id)
        state = _network_check(adapter, row.flow_spec, known)
    return RepairResult('eligible' if state == 'missing' else 'already_present', state)


def _stage(factory, finding_id: str) -> str:
    try:
        with factory.begin() as db:
            policy, row, finding, network_id, _ = _candidate(db, finding_id, lock=True)
            op_id = str(uuid4())
            op = PolicyOperation(
                id=op_id, policy_id=policy.id, operation_type='reconcile',
                requested_revision_id=policy.applied_revision_id,
                base_revision_id=policy.applied_revision_id,
                requester_id='system:reconciler',
                idempotency_key=f'{finding.id}:{uuid4().hex}',
                request_hash=sha256_json({'finding': finding.id, 'revision': policy.applied_revision_id}),
                status='pending', requested_state='enabled', base_desired_state='enabled',
            )
            db.add(op)
            db.flush()  # ensure FK target before the reservation/event
            db.add(ScopeReservation(network_id=network_id, dpid=row.dpid, operation_id=op_id))
            db.add(OperationEvent(
                id=str(uuid4()), operation_id=op_id, event_type='operation.staged',
                step_name='repair', attempt_no=1,
                details={'finding_id': finding.id, 'deployment_id': row.id, 'dpid': row.dpid},
            ))
            db.flush()
        return op_id
    except IntegrityError as exc:
        raise RepairRefused('Switch reservation changed concurrently; repair refused') from exc


def _load_plan(factory, operation_id: str, finding_id: str, token: str) -> tuple:
    with factory() as db:
        op = db.get(PolicyOperation, operation_id)
        if not op or op.runner_token != token or op.operation_type != 'reconcile':
            raise RepairRefused('Repair operation has lost ownership')
        policy = db.get(PolicyRecord, op.policy_id)
        finding = db.get(ReconciliationFinding, finding_id)
        row = db.get(FlowDeployment, finding.deployment_id) if finding else None
        if (not policy or not finding or not row
                or finding.policy_id != policy.id or row.revision_id != op.requested_revision_id
                or not _stable(policy) or policy.desired_state != 'enabled'
                or policy.applied_revision_id != op.requested_revision_id):
            raise RepairRefused('Policy, finding or revision changed after reservation')
        reserved = db.scalar(select(ScopeReservation.operation_id).where(
            ScopeReservation.dpid == row.dpid).limit(1))
        if reserved != operation_id:
            raise RepairRefused('Repair does not own the switch reservation')
        known = db.scalars(select(FlowDeployment.flow_spec).where(
            FlowDeployment.policy_id == policy.id,
            FlowDeployment.revision_id == op.requested_revision_id,
            FlowDeployment.dpid == row.dpid)).all()
        return row.flow_spec, known


def _finish(factory, *, operation_id: str, finding_id: str, token: str,
            status: str, code: str | None, detail: str, changed: bool):
    with factory.begin() as db:
        op = db.scalar(select(PolicyOperation).where(
            PolicyOperation.id == operation_id).with_for_update())
        if op is None or op.runner_token != token:
            raise RepairRefused('Cannot finalize without the original worker token')
        policy = db.scalar(select(PolicyRecord).where(
            PolicyRecord.id == op.policy_id).with_for_update())
        finding = db.get(ReconciliationFinding, finding_id)
        row = db.get(FlowDeployment, finding.deployment_id) if finding else None
        if not policy or not row or not finding:
            raise RepairRefused('Repair evidence disappeared during finalize')
        if status == 'succeeded' and (not _stable(policy) or policy.desired_state != 'enabled'
                or policy.applied_revision_id != op.requested_revision_id):
            status, code, detail = 'unresolved', 'STATE_CHANGED', 'Policy changed during repair'
        op.status = status
        op.error_code = code
        op.error_message = detail if status != 'succeeded' else None
        op.runner_token = None
        op.lease_until = None
        if status != 'unresolved':
            op.finished_at = _now()
            db.execute(delete(ScopeReservation).where(ScopeReservation.operation_id == op.id))
        if status == 'succeeded':
            now = _now()
            row.deployment_status = 'installed'
            row.last_observed_at = now
            row.observed_snapshot = {'classification': 'healthy', 'confirmed': True,
                                     'observed': signature(row.flow_spec),
                                     'source': 'repair_post_verify'}
            finding.resolved_at = now
            finding.evidence = {**(finding.evidence or {}), 'repair_operation_id': op.id,
                                'repair_result': detail}
        if status == 'unresolved':
            # Keep the switch reserved. Never allow blind replay after ambiguous IO.
            policy.applied_state = 'unknown'
            row.deployment_status = 'unknown'
        db.add(OperationEvent(
            id=str(uuid4()), operation_id=op.id, event_type=f'operation.{status}',
            step_name='repair', attempt_no=op.attempt_count or 1,
            details={'finding_id': finding_id, 'changed': changed,
                     'error_code': code, 'result': detail[:500]},
        ))
    return RepairResult(status, detail, operation_id)


def apply(finding_id: str, *, session_factory=None, adapter=ryu, sleep=time.sleep) -> RepairResult:
    """Single explicit operator action. No automatic or repeated repair."""
    factory = session_factory or SessionLocal
    operation_id = _stage(factory, finding_id)
    token, _ = _claim(factory, operation_id)
    if token is None:
        raise RepairRefused('Could not claim new repair operation')
    changed = False
    try:
        flow, known = _load_plan(factory, operation_id, finding_id, token)
        state = _network_check(adapter, flow, known)
        if state == 'already_present':
            return _finish(factory, operation_id=operation_id, finding_id=finding_id,
                           token=token, status='succeeded', code=None,
                           detail='already_present_no_write', changed=False)
        # From this point any exception could be AFTER an OpenFlow side effect.
        changed = True
        adapter.add_flow(flow)
        _set_verifying(factory, operation_id, token)
        for attempt in range(6):
            try:
                after = _network_check(adapter, flow, known)
                if after == 'already_present':
                    break
            except (ryu.RyuError, InvalidObservation, RepairRefused, ValueError, TypeError):
                # A post-write read error is not proof the Flow was absent.
                after = 'unknown'
            if attempt != 5:
                sleep(0.25)
        else:
            raise RepairRefused('OpenFlow ADD was not positively verified')
        return _finish(factory, operation_id=operation_id, finding_id=finding_id,
                       token=token, status='succeeded', code=None,
                       detail='flow_restored_and_verified', changed=True)
    except Exception as exc:
        status = 'unresolved' if changed else 'failed'
        return _finish(factory, operation_id=operation_id, finding_id=finding_id,
                       token=token, status=status,
                       code='REPAIR_AMBIGUOUS' if changed else 'REPAIR_PREFLIGHT_REFUSED',
                       detail=f'{type(exc).__name__}: {exc}'[:1000], changed=changed)
