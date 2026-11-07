"""Transactional Outbox -> Airflow dispatcher.

A claim is committed before network I/O. Failure to ACK a successful trigger
is recoverable because the DagRun id is deterministic and the Airflow adapter
verifies existing runs after a 409. Delivery is at-least-once; execution is
protected by Stage-2 operation leases and terminal-state checks.
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select
from app.db.session import SessionLocal
from app.models import OutboxEvent, PolicyOperation, OperationEvent
from app.adapters.airflow_adapter import AirflowClient

log = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


def _utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _claim(factory, worker_id: str):
    now = _now()
    with factory.begin() as db:
        event = db.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.event_type == 'policy.operation.requested')
            .where(OutboxEvent.next_retry_at <= now)
            .where(or_(OutboxEvent.dispatch_status == 'pending',
                       (OutboxEvent.dispatch_status == 'dispatching') &
                       (OutboxEvent.lease_until < now)))
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if event is None:
            return None
        op = db.get(PolicyOperation, event.operation_id)
        if op is None:
            raise RuntimeError('Orphan outbox: foreign key violation')
        event.dispatch_status = 'dispatching'
        event.lease_owner = worker_id
        event.lease_until = now + timedelta(seconds=120)
        event.attempts = (event.attempts or 0) + 1
        return (event.id, event.operation_id, op.status, event.attempts)


def _ack(factory, *, event_id: str, worker_id: str, operation_id: str,
         run_id: str | None):
    with factory.begin() as db:
        event = db.get(OutboxEvent, event_id)
        if event is None or event.lease_owner != worker_id or event.dispatch_status != 'dispatching':
            raise RuntimeError('Outbox claim lost before acknowledgment')
        op = db.get(PolicyOperation, operation_id)
        if run_id is not None:
            if op.airflow_run_id and op.airflow_run_id != run_id:
                raise RuntimeError('Airflow run id differs from committed one')
            op.airflow_run_id = run_id
            # A very fast Airflow task may have finished first; never regress a
            # terminal status to queued, nor overwrite running/verifying.
            if op.status == 'pending':
                op.status = 'queued'
            db.add(OperationEvent(
                id=str(uuid4()), operation_id=op.id, event_type='operation.dispatched',
                step_name='dispatch', attempt_no=event.attempts,
                details={'airflow_run_id': run_id},
            ))
        event.dispatch_status = 'delivered'
        event.delivered_at = _now()
        event.lease_owner = None
        event.lease_until = None


def _retry(factory, *, event_id: str, worker_id: str, attempt: int):
    with factory.begin() as db:
        event = db.get(OutboxEvent, event_id)
        if event is None or event.dispatch_status != 'dispatching' or event.lease_owner != worker_id:
            return
        event.dispatch_status = 'pending'
        event.lease_owner = None
        event.lease_until = None
        event.next_retry_at = _now() + timedelta(seconds=min(300, 2 ** min(attempt, 8)))


def dispatch_once(*, session_factory=None, client=None) -> bool:
    """Claim/process one event. False if nothing was ready. Do not leak secrets."""
    factory = session_factory or SessionLocal
    worker_id = str(uuid4())
    claimed = _claim(factory, worker_id)
    if claimed is None:
        return False
    event_id, operation_id, op_status, attempt = claimed
    try:
        if op_status in {'succeeded', 'failed', 'rejected', 'unresolved'}:
            # Manual/terminal operations must not be re-triggered by dispatch.
            _ack(factory, event_id=event_id, worker_id=worker_id,
                 operation_id=operation_id, run_id=None)
        else:
            run_id = (client or AirflowClient()).trigger(operation_id)
            _ack(factory, event_id=event_id, worker_id=worker_id,
                 operation_id=operation_id, run_id=run_id)
        log.info('outbox acknowledged operation=%s', operation_id)
    except Exception as exc:
        log.warning('outbox delivery failed operation=%s type=%s', operation_id, type(exc).__name__)
        _retry(factory, event_id=event_id, worker_id=worker_id, attempt=attempt)
    return True
