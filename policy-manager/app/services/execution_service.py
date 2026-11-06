"""Idempotent operation runner; DB transactions are short and never span Ryu IO.

Stage 2 has a local CLI trigger. In stage 3, Airflow will call these same
services via authenticated internal API steps, NOT duplicate the SDN logic.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, select
from app.db.session import SessionLocal
from app.models import PolicyOperation, PolicyRecord, PolicyRevision, FlowDeployment, OperationEvent, OutboxEvent
from app.models.scope_reservation import ScopeReservation
from app.services.deployment_service import apply_change, DeploymentResult


def _now():
    return datetime.now(timezone.utc)


def _as_utc(value):
    # SQLite test adapter drops timezone info; PostgreSQL timestamptz retains it.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _event(db, op, typ: str, step: str, detail: dict | None = None):
    db.add(OperationEvent(
        id=str(uuid4()), operation_id=op.id, event_type=typ,
        step_name=step, attempt_no=op.attempt_count or 1, details=detail or {},
    ))


class OperationBusy(RuntimeError):
    pass


class OperationNotFound(LookupError):
    pass


def _claim(factory, operation_id: str) -> tuple[str | None, str]:
    token = str(uuid4())
    with factory.begin() as db:
        op = db.scalar(select(PolicyOperation).where(PolicyOperation.id == operation_id).with_for_update())
        if op is None:
            raise OperationNotFound(operation_id)
        if op.status in ('succeeded', 'rejected', 'failed'):
            return None, op.status
        if op.status == 'unresolved':
            raise OperationBusy('Unresolved operation requires reconciliation before replay')
        if op.lease_until and _as_utc(op.lease_until) > _now():
            raise OperationBusy('Operation is currently leased to another worker')
        # After an expired lease and interrupted deployment the effect may be
        # ambiguous. Never blindly retry; leave for independent reconciliation.
        if op.runner_token and op.status in ('running', 'verifying'):
            op.status = 'unresolved'
            op.error_code = 'EXPIRED_WORKER_LEASE'
            op.error_message = 'Worker lease expired; inspect network before retry'
            _event(db, op, 'operation.unresolved', 'claim', {'reason': 'expired_worker_lease'})
            return None, op.status
        if op.status not in ('pending', 'queued'):
            raise OperationBusy(f'Unexpected operation state {op.status}')
        op.status = 'running'
        op.runner_token = token
        op.lease_until = _now() + timedelta(minutes=5)
        op.attempt_count = (op.attempt_count or 0) + 1
        op.started_at = op.started_at or _now()
        _event(db, op, 'operation.started', 'runner')
    return token, 'running'


def _plan(factory, operation_id: str, token: str):
    with factory() as db:
        op = db.get(PolicyOperation, operation_id)
        if op is None or op.runner_token != token:
            raise OperationBusy('Runner token mismatch')
        policy = db.get(PolicyRecord, op.policy_id)
        if policy is None:
            raise RuntimeError('Policy disappeared')
        revision = db.get(PolicyRevision, op.requested_revision_id)
        if revision is None:
            raise RuntimeError('Requested revision missing')
        new_rows = db.scalars(select(FlowDeployment).where(
            FlowDeployment.revision_id == revision.id
        ).order_by(FlowDeployment.dpid, FlowDeployment.flow_index)).all()
        # Legacy committed flows represent the last known active rule set.
        old_flows = list(policy.compiled_flows or []) if policy.desired_state == 'enabled' else []
        new_flows = [r.flow_spec for r in new_rows] if op.requested_state == 'enabled' else []
        # Updating while disabled should not deploy; the new revision will be
        # staged and can be deployed by a later enable operation.
        if op.operation_type == 'update' and policy.desired_state == 'disabled':
            old_flows, new_flows = [], []
        return {
            'old': old_flows, 'new': new_flows, 'active_before': policy.desired_state == 'enabled',
            'revision_id': revision.id, 'operation_type': op.operation_type,
        }


def _set_verifying(factory, operation_id: str, token: str):
    with factory.begin() as db:
        op = db.scalar(select(PolicyOperation).where(PolicyOperation.id == operation_id).with_for_update())
        if op.runner_token != token:
            raise OperationBusy('Worker lease ownership changed')
        op.status = 'verifying'
        op.lease_until = _now() + timedelta(minutes=5)
        _event(db, op, 'operation.verifying', 'verify')


def _finalize(factory, operation_id: str, token: str, result: DeploymentResult):
    with factory.begin() as db:
        op = db.scalar(select(PolicyOperation).where(PolicyOperation.id == operation_id).with_for_update())
        if op is None or op.runner_token != token:
            raise OperationBusy('Cannot finalize without lease ownership')
        policy = db.get(PolicyRecord, op.policy_id)
        revision = db.get(PolicyRevision, op.requested_revision_id)
        if policy is None or revision is None:
            raise RuntimeError('Cannot finalize missing policy or revision')

        op.status = result.status
        op.error_code = result.error_code
        op.error_message = result.detail
        op.runner_token = None
        op.lease_until = None
        if result.status != 'unresolved':
            op.finished_at = _now()
        if result.status == 'succeeded':
            # Commit the desired state only AFTER network-side verification.
            policy.desired_state = op.requested_state
            policy.desired_revision_id = revision.id
            policy.definition = revision.definition
            policy.revision = revision.revision_no
            if op.requested_state == 'enabled':
                new_rows = db.scalars(select(FlowDeployment).where(
                    FlowDeployment.revision_id == revision.id
                )).all()
                new_flows = [row.flow_spec for row in sorted(new_rows, key=lambda r: (r.dpid, r.flow_index))]
                if not new_flows:
                    raise RuntimeError('Enabled policy has no compiled flows')
                policy.compiled_flows = new_flows
                policy.cookie = int(new_flows[0]['cookie'])
                policy.applied_revision_id = revision.id
                policy.applied_state = 'installed'
                policy.status = 'active'
                for row in new_rows:
                    row.deployment_status = 'installed'
                    row.last_observed_at = _now()
                    row.operation_id = op.id
            else:
                if op.operation_type == 'update':
                    # Disabled update updates the definition, not the network.
                    new_rows = db.scalars(select(FlowDeployment).where(
                        FlowDeployment.revision_id == revision.id
                    )).all()
                    policy.compiled_flows = [r.flow_spec for r in new_rows]
                    if new_rows:
                        policy.cookie = new_rows[0].cookie
                policy.applied_revision_id = None
                policy.applied_state = 'absent'
                policy.status = policy.desired_state
            if op.operation_type in ('update', 'disable', 'delete') and op.base_revision_id:
                # Do not overwrite updated same revision for disable/enable.
                if op.operation_type == 'update' or op.requested_state != 'enabled':
                    old_rows = db.scalars(select(FlowDeployment).where(
                        FlowDeployment.revision_id == op.base_revision_id
                    )).all()
                    for row in old_rows:
                        row.deployment_status = 'absent'
                        row.last_observed_at = _now()
            policy.last_error = None
        else:
            # A failed proposed revision never overwrites committed desired state.
            policy.last_error = (result.detail or result.error_code or 'Operation failed')[:2000]
            candidate_rows = db.scalars(select(FlowDeployment).where(
                FlowDeployment.revision_id == revision.id
            )).all()
            previous_rows = db.scalars(select(FlowDeployment).where(
                FlowDeployment.revision_id == op.base_revision_id
            )).all() if op.base_revision_id else []
            if result.status == 'unresolved':
                policy.applied_state = 'unknown'
                for row in {r.id: r for r in candidate_rows + previous_rows}.values():
                    row.deployment_status = 'unknown'
            elif result.compensated is True:
                # Compensation was observed: proposed flows are absent and
                # previously committed flows were restored (when applicable).
                for row in candidate_rows:
                    if op.base_revision_id != revision.id:
                        row.deployment_status = 'absent'
                        row.last_observed_at = _now()
                for row in previous_rows:
                    if policy.desired_state == 'enabled':
                        row.deployment_status = 'installed'
                        row.last_observed_at = _now()
            if result.status == 'failed' and op.operation_type == 'create':
                policy.status = 'failed'

        _event(db, op, 'operation.' + result.status, 'finalize', {
            'error_code': result.error_code,
            'compensated': result.compensated,
            'attempted_network_change': result.attempted_network_change,
        })
        if result.status != 'unresolved':
            db.execute(delete(ScopeReservation).where(ScopeReservation.operation_id == op.id))
            # Local manual execution consumes its outbox record; Airflow's later
            # dispatcher must not start a second run for this completed operation.
            envelope = db.scalar(select(OutboxEvent).where(OutboxEvent.operation_id == op.id))
            if envelope and envelope.dispatch_status == 'pending':
                envelope.dispatch_status = 'delivered'
                envelope.delivered_at = _now()
    return result.status


def run_operation(operation_id: str, *, session_factory=None, adapter=None, sleep=None):
    """Operator-driven stage-2 entrypoint; safe against concurrent workers.

    Until stage 3, pending operations are run explicitly. Never run a partial
    or unresolved operation again without reconciliation.
    """
    factory = session_factory or SessionLocal
    token, status = _claim(factory, operation_id)
    if token is None:
        return status
    try:
        plan = _plan(factory, operation_id, token)
        kw = {}
        if adapter is not None:
            kw['adapter'] = adapter
        if sleep is not None:
            kw['sleep'] = sleep
        outcome = apply_change(
            old_flows=plan['old'], new_flows=plan['new'],
            is_active_before=plan['active_before'],
            on_verifying=lambda: _set_verifying(factory, operation_id, token),
            **kw,
        )
    except Exception as exc:
        # If a worker failed for unexpected reasons after claiming, do not
        # assert that no network side effect occurred.
        outcome = DeploymentResult('unresolved', 'WORKER_EXCEPTION', str(exc)[:1000])
    return _finalize(factory, operation_id, token, outcome)
