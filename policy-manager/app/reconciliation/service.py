"""Stage 4A observation loop: GET Ryu -> compare -> persist evidence.

No POST/DELETE to Ryu; no repair, policy revision change, or Airflow trigger.
Network IO is outside database transactions. Before committing evidence, policy
revision and reservation state are checked again to avoid stale observations.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import uuid4

from sqlalchemy import select

from app.adapters import ryu_adapter as ryu
from app.db.session import SessionLocal
from app.models import FlowDeployment, PolicyOperation, PolicyRecord, ReconciliationFinding
from app.models.scope_reservation import ScopeReservation
from app.reconciliation.observer import InvalidObservation, compare, extra_finding_key, signature

logger = logging.getLogger(__name__)
BUSY_STATUSES = ('pending', 'queued', 'running', 'verifying', 'unresolved')
DRIFT_KINDS = ('missing', 'modified', 'extra')


def _policy_signature(p) -> tuple:
    return (p.desired_state, p.applied_state, p.status, p.desired_revision_id,
            p.applied_revision_id, p.revision)


def _stable(p) -> bool:
    if p.desired_state == 'enabled':
        return (p.status == 'active' and p.applied_state == 'installed'
                and p.applied_revision_id is not None
                and p.desired_revision_id == p.applied_revision_id)
    return (p.desired_state in ('disabled', 'deleted') and p.applied_state == 'absent')


def _active(p) -> bool:
    return p.desired_state == 'enabled' and _stable(p)


def _plans(factory) -> list[dict]:
    """Detached read-only plan; never keep an ORM transaction open during Ryu IO."""
    with factory() as db:
        policies = {p.id: p for p in db.scalars(select(PolicyRecord)).all()}
        deployments = db.scalars(select(FlowDeployment)).all()
        busy = set(db.scalars(select(PolicyOperation.policy_id).where(
            PolicyOperation.status.in_(BUSY_STATUSES))).all())
        reserved = set(db.scalars(select(ScopeReservation.dpid)).all())
        groups: dict[int, list] = {}
        for flow in deployments:
            groups.setdefault(int(flow.dpid), []).append(flow)

        plans = []
        for dpid, rows in sorted(groups.items()):
            owner_ids = {row.policy_id for row in rows}
            if dpid in reserved or owner_ids & busy:
                plans.append({'dpid': dpid, 'skipped': True})
                continue
            # Failed/unknown legacy policies do not prevent observing unrelated,
            # stable policies on the same switch. Their cookies remain untrusted.
            safe_owners = {pid for pid in owner_ids
                           if pid in policies and _stable(policies[pid])}
            if not safe_owners:
                plans.append({'dpid': dpid, 'skipped': True})
                continue
            safe_rows = [r for r in rows if r.policy_id in safe_owners]
            expected = [dict(id=r.id, policy_id=r.policy_id,
                             revision_id=r.revision_id, spec=r.flow_spec)
                        for r in safe_rows if (_active(policies[r.policy_id])
                                               and r.revision_id == policies[r.policy_id].applied_revision_id)]
            cookies: dict[int, set[str]] = {}
            for r in safe_rows:
                cookies.setdefault(int(r.cookie), set()).add(r.policy_id)
            plans.append({
                'dpid': dpid, 'skipped': False, 'expected': expected,
                'cookies': cookies,
                'policies': {pid: _policy_signature(policies[pid]) for pid in safe_owners},
            })
        return plans


def _collect(plan: dict, *, adapter, available: set[int] | None, switch_error: str | None):
    if switch_error:
        return {'error': switch_error, 'results': [], 'extras': []}
    if plan['dpid'] not in available:
        return {'error': 'switch_disconnected', 'results': [], 'extras': []}
    try:
        raw = adapter.observed_flows(plan['dpid'])
        if not isinstance(raw, list):
            raise InvalidObservation('Flow-stats payload is not a list')
        # Ignore MAC-learning and other controllers, but validate all known cookies.
        candidates = []
        for item in raw:
            if not isinstance(item, dict):
                raise InvalidObservation('Flow entry is not an object')
            try:
                cookie = int(item.get('cookie', 0))
            except (ValueError, TypeError) as exc:
                raise InvalidObservation('Unparseable flow cookie') from exc
            if cookie in plan['cookies']:
                candidates.append(signature(item))
        results = []
        used = set()
        for row in plan['expected']:
            difference = compare(row['spec'], candidates, used)
            if difference.observed_index is not None:
                used.add(difference.observed_index)
            results.append({**row, 'kind': difference.classification,
                            'observed': difference.observed})
        extras = []
        for idx, actual in enumerate(candidates):
            if idx in used:
                continue
            owners = plan['cookies'][actual['cookie']]
            extras.append({'key': extra_finding_key(plan['dpid'], actual),
                           'policy_id': next(iter(owners)) if len(owners) == 1 else None,
                           'observed': actual})
        return {'error': None, 'results': results, 'extras': extras}
    except (ryu.RyuError, InvalidObservation, KeyError, ValueError, TypeError) as exc:
        return {'error': f'observation_error:{type(exc).__name__}', 'results': [], 'extras': []}


def _open_find(db, *, key: str, kind: str, dpid: int, now: datetime,
               evidence: dict, policy_id=None, deployment_id=None) -> ReconciliationFinding:
    finding = db.scalar(select(ReconciliationFinding).where(
        ReconciliationFinding.finding_key == key,
        ReconciliationFinding.resolved_at.is_(None)).with_for_update())
    if finding is None:
        finding = ReconciliationFinding(
            id=str(uuid4()), finding_key=key, kind=kind, dpid=dpid,
            policy_id=policy_id, deployment_id=deployment_id,
            first_seen_at=now, last_seen_at=now,
            consecutive_count=1, evidence=evidence,
        )
        db.add(finding)
    else:
        finding.consecutive_count += 1
        finding.last_seen_at = now
        finding.evidence = evidence
    if finding.confirmed_at is None and (kind == 'unknown' or finding.consecutive_count >= 2):
        finding.confirmed_at = now
    return finding


def _resolve(db, *, now, kind: str | None = None, deployment_id: str | None = None,
             dpid: int | None = None, except_keys: set[str] | None = None):
    stmt = select(ReconciliationFinding).where(ReconciliationFinding.resolved_at.is_(None))
    if kind is not None:
        stmt = stmt.where(ReconciliationFinding.kind == kind)
    if deployment_id is not None:
        stmt = stmt.where(ReconciliationFinding.deployment_id == deployment_id)
    if dpid is not None:
        stmt = stmt.where(ReconciliationFinding.dpid == dpid)
    for item in db.scalars(stmt.with_for_update()).all():
        if except_keys is None or item.finding_key not in except_keys:
            item.resolved_at = now


def _reset_streaks(db, *, deployment_id: str):
    # Unknown is not proof that a prior drift was resolved. Break the sequence.
    for item in db.scalars(select(ReconciliationFinding).where(
        ReconciliationFinding.deployment_id == deployment_id,
        ReconciliationFinding.resolved_at.is_(None)).with_for_update()):
        item.consecutive_count = 0


def _save(factory, plan: dict, reading: dict, now: datetime) -> dict:
    stats = {'healthy': 0, 'suspected': 0, 'confirmed': 0, 'unknown': 0, 'extra': 0, 'skipped': 0}
    with factory.begin() as db:
        # Lock policy rows briefly. Operation submit/finalize also lock the policy.
        actual_policies = {p.id: p for p in db.scalars(select(PolicyRecord).where(
            PolicyRecord.id.in_(list(plan['policies']))).with_for_update()).all()}
        if any(pid not in actual_policies or _policy_signature(actual_policies[pid]) != sig
               for pid, sig in plan['policies'].items()):
            stats['skipped'] = 1
            return stats
        reservation = db.scalar(select(ScopeReservation.dpid).where(
            ScopeReservation.dpid == plan['dpid']).limit(1))
        busy = db.scalar(select(PolicyOperation.id).where(
            PolicyOperation.policy_id.in_(list(plan['policies'])),
            PolicyOperation.status.in_(BUSY_STATUSES)).limit(1))
        if reservation is not None or busy is not None:
            stats['skipped'] = 1
            return stats
        # All expected flow rows must still be the same immutable revision/spec.
        current = {r.id: r for r in db.scalars(select(FlowDeployment).where(
            FlowDeployment.dpid == plan['dpid'])).all()}
        if any(r['id'] not in current or current[r['id']].revision_id != r['revision_id']
               or current[r['id']].flow_spec != r['spec'] for r in plan['expected']):
            stats['skipped'] = 1
            return stats
        if reading['error']:
            _open_find(db, key=f"unknown:{plan['dpid']}", kind='unknown', dpid=plan['dpid'],
                       now=now, evidence={'reason': reading['error']})
            for r in plan['expected']:
                current_row = current[r['id']]
                current_row.last_observed_at = now
                current_row.observed_snapshot = {'classification': 'unknown',
                                                 'reason': reading['error']}
                current_row.deployment_status = 'unknown'
                _reset_streaks(db, deployment_id=r['id'])
                stats['unknown'] += 1
            if not plan['expected']:
                stats['unknown'] = 1
            return stats
        _resolve(db, now=now, kind='unknown', dpid=plan['dpid'])
        expected_ids = {r['id'] for r in plan['expected']}
        for old in current.values():
            if old.id not in expected_ids and old.policy_id in plan['policies']:
                _resolve(db, now=now, kind='missing', deployment_id=old.id)
                _resolve(db, now=now, kind='modified', deployment_id=old.id)
        for result in reading['results']:
            row = current[result['id']]
            kind = result['kind']
            if kind == 'healthy':
                _resolve(db, now=now, deployment_id=row.id)
                row.deployment_status = 'installed'
                confirmed = True
                stats['healthy'] += 1
            else:
                other = 'modified' if kind == 'missing' else 'missing'
                _resolve(db, now=now, kind=other, deployment_id=row.id)
                finding = _open_find(db, key=f"{kind}:{row.id}", kind=kind,
                                     dpid=plan['dpid'], now=now,
                                     policy_id=row.policy_id, deployment_id=row.id,
                                     evidence={'expected': result['spec'], 'observed': result['observed']})
                confirmed = finding.confirmed_at is not None
                if confirmed:
                    row.deployment_status = kind
                    stats['confirmed'] += 1
                else:
                    stats['suspected'] += 1
            row.last_observed_at = now
            row.observed_snapshot = {'classification': kind, 'confirmed': confirmed,
                                     'observed': result['observed']}
        extra_keys = set()
        for item in reading['extras']:
            extra_keys.add(item['key'])
            finding = _open_find(db, key=item['key'], kind='extra', dpid=plan['dpid'],
                                 policy_id=item['policy_id'], now=now,
                                 evidence={'observed': item['observed']})
            stats['extra'] += int(finding.confirmed_at is not None)
            stats['suspected'] += int(finding.confirmed_at is None)
        _resolve(db, now=now, kind='extra', dpid=plan['dpid'], except_keys=extra_keys)
    return stats


def observe_once(*, session_factory=None, adapter=ryu, now: datetime | None = None) -> dict:
    """One bounded scan: read network and write observation evidence only."""
    factory = session_factory or SessionLocal
    now = now or datetime.now(timezone.utc)
    plans = _plans(factory)
    totals = {'switches': 0, 'healthy': 0, 'suspected': 0, 'confirmed': 0,
              'unknown': 0, 'extra': 0, 'skipped': 0}
    candidates = [p for p in plans if not p['skipped']]
    if not candidates:
        totals['skipped'] = len(plans)
        return totals
    try:
        connected = adapter.switches()
        if not isinstance(connected, (set, list, tuple)):
            raise InvalidObservation('Unexpected switches response')
        connected = {int(dpid) for dpid in connected}
        error = None
    except (ryu.RyuError, InvalidObservation, TypeError, ValueError):
        connected, error = None, 'ryu_unavailable'
    for plan in plans:
        if plan['skipped']:
            totals['skipped'] += 1
            continue
        totals['switches'] += 1
        reading = _collect(plan, adapter=adapter, available=connected, switch_error=error)
        stats = _save(factory, plan, reading, now)
        for key, value in stats.items():
            totals[key] += value
    logger.info('LLNet observation %s', totals)
    return totals
