"""Stage 4C: one safe automatic attempt per confirmed, fresh MISSING episode.

The Stage 4A observer remains the sole evidence producer. Stage 4B is the only
OpenFlow writer. Its PostgreSQL reservation and lease guards are reused here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time

from sqlalchemy import select

from app.adapters import ryu_adapter as ryu
from app.db.session import SessionLocal
from app.models import PolicyOperation, ReconciliationFinding
from app.reconciliation.repair import RepairRefused, apply

logger = logging.getLogger(__name__)
AUTO_REQUESTER = 'system:reconciler:auto'


def _utc(timestamp: datetime) -> datetime:
    return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)


def auto_heal_once(*, session_factory=None, adapter=ryu, sleep=time.sleep,
                   now: datetime | None = None, max_age_seconds: int = 45) -> dict | None:
    """Try at most one eligible flow per cycle, with no retry per finding episode.

    The unique (requester_id, idempotency_key) constraint is the durable guard
    against a second automatic attempt, including across container restarts.
    A refused preflight without a staged operation can be rechecked next cycle.
    """
    factory = session_factory or SessionLocal
    now = now or datetime.now(timezone.utc)
    with factory() as db:
        findings = db.scalars(select(ReconciliationFinding).where(
            ReconciliationFinding.kind == 'missing',
            ReconciliationFinding.confirmed_at.is_not(None),
            ReconciliationFinding.resolved_at.is_(None),
            ReconciliationFinding.consecutive_count >= 2,
        ).order_by(ReconciliationFinding.first_seen_at)).all()
        candidates = []
        for finding in findings:
            if _utc(now) - _utc(finding.last_seen_at) > timedelta(seconds=max_age_seconds):
                continue
            key = f'auto:{finding.id}'
            previous = db.scalar(select(PolicyOperation.id).where(
                PolicyOperation.requester_id == AUTO_REQUESTER,
                PolicyOperation.idempotency_key == key).limit(1))
            if previous is None:
                candidates.append((finding.id, key))

    # Do not keep any DB transaction open while Stage 4B performs Ryu IO.
    for finding_id, key in candidates:
        try:
            result = apply(finding_id, session_factory=factory, adapter=adapter,
                           sleep=sleep, requester_id=AUTO_REQUESTER,
                           idempotency_key=key)
        except RepairRefused as exc:
            # E.g., a concurrent Update/Delete, or an ambiguous Ryu flow slot.
            logger.warning('Auto-heal safely refused finding=%s reason=%s', finding_id, exc)
            return {'finding_id': finding_id, 'status': 'refused',
                    'reason': str(exc), 'operation_id': None}
        outcome = {'finding_id': finding_id, 'status': result.status,
                   'reason': result.reason, 'operation_id': result.operation_id}
        if result.status == 'unresolved':
            logger.error('Auto-heal UNRESOLVED; do not replay operation=%s', result.operation_id)
        return outcome  # At most one staged repair operation per cycle.
    return None
