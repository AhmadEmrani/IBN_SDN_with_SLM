"""HTTP-independent transactional submission of desired policy operations.

A successful submission NEVER accesses Ryu.  It atomically inserts the operation,
its initial audit event, an outbox envelope and scope reservations.  Until the
worker completes, the PolicyRecord's committed desired state is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4, uuid5, NAMESPACE_URL

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.domain.fingerprint import sha256_json
from app.models import PolicyRecord, PolicyOperation, PolicyRevision, FlowDeployment
from app.models.scope_reservation import ScopeReservation
from app.repositories.operation_repository import stage_operation, IdempotencyPayloadMismatch
from app.schemas.policy import PolicyInput
from app.services.compiler import compile_policy
from app.services.conflict_detector import potential_conflict
from app.domain.cookies import new_cookie
import logging


logger = logging.getLogger(__name__)


class SubmissionError(ValueError):
    def __init__(self, message: str, http_status: int = 409):
        self.http_status = http_status
        super().__init__(message)


@dataclass(frozen=True)
class Submitted:
    policy_id: str
    operation_id: str
    status: str
    created: bool

    def as_dict(self):
        return {
            'policy_id': self.policy_id, 'operation_id': self.operation_id,
            'status': self.status,
            'status_url': f'/api/v1/operations/{self.operation_id}',
            'created': self.created,
        }


def _fingerprint(kind: str, target: str | None, payload: dict, expected_revision: int | None) -> str:
    return sha256_json({'operation_type': kind, 'route_target': target,
                        'payload': payload, 'expected_revision': expected_revision})


def _replay(db, *, requester: str, key: str, fingerprint: str):
    op = db.scalar(select(PolicyOperation).where(
        PolicyOperation.requester_id == requester, PolicyOperation.idempotency_key == key
    ))
    if op is None:
        return None
    if op.request_hash != fingerprint:
        raise SubmissionError('Idempotency-Key reused with a different request payload', 409)
    return Submitted(op.policy_id, op.id, op.status, False)


def _reserve(db, *, operation_id: str, scope_pairs: set[tuple[str, int]]):
    if not scope_pairs:
        raise SubmissionError('Missing switch scope', 422)
    for net, dpid in sorted(scope_pairs):
        db.add(ScopeReservation(network_id=net, dpid=dpid, operation_id=operation_id))
    db.flush()  # composite primary key also serializes concurrent submissions


def _scope_from_policy(policy: PolicyInput) -> set[tuple[str, int]]:
    return {(policy.scope.network_id, int(dpid)) for dpid in policy.scope.switches}


def _check_conflict(db, candidate: PolicyInput, *, exclude_id: str | None = None):
    # Conservative v0.2: any overlapping enabled rules are rejected, including
    # duplicate DENY rules.  Disabled and logically deleted policies are ignored.
    rows = db.scalars(select(PolicyRecord).where(
        PolicyRecord.desired_state == 'enabled', PolicyRecord.id != (exclude_id or '')
    )).all()
    for existing in rows:
        if existing.status == 'deleted':
            continue
        try:
            other = PolicyInput.model_validate(existing.definition)
        except ValueError:
            # Do not silently authorize a new overlap when legacy data is corrupt.
            raise SubmissionError(f'Existing policy {existing.id} is invalid; inspect before continuing')
        if potential_conflict(candidate, other):
            raise SubmissionError(f'Overlapping enabled policy: {existing.id}')


def _store_flows(db, *, record: PolicyRecord, revision: PolicyRevision, flows: list[dict]):
    indices = {}
    for flow in flows:
        dpid = int(flow['dpid'])
        index = indices.get(dpid, 0)
        indices[dpid] = index + 1
        db.add(FlowDeployment(
            id=str(uuid4()), policy_id=record.id, revision_id=revision.id,
            dpid=dpid, flow_index=index, cookie=int(flow['cookie']),
            flow_spec=flow, flow_hash=sha256_json(flow), deployment_status='unknown',
        ))


def _create_inner(db, policy: PolicyInput, *, requester: str, key: str, fp: str):
    replay = _replay(db, requester=requester, key=key, fingerprint=fp)
    if replay:
        return replay
    requested_id = policy.policy.id
    pid = requested_id or f'FW-{uuid5(NAMESPACE_URL, requester + "|" + key).hex[:12]}'
    if db.get(PolicyRecord, pid):
        raise SubmissionError(f'Policy already exists: {pid}')
    # The supplied definition is not altered in-place.
    canonical = policy.model_copy(deep=True)
    canonical.policy.id = pid
    cookie = new_cookie()
    flows = compile_policy(canonical, cookie)
    record = PolicyRecord(
        id=pid, revision=1, cookie=cookie,
        definition=canonical.model_dump(mode='json'), compiled_flows=[],
        status='pending', desired_state='disabled', applied_state='unknown',
    )
    db.add(record)
    db.flush()
    rev = PolicyRevision(
        id=str(uuid4()), policy_id=pid, revision_no=1,
        definition=canonical.model_dump(mode='json'),
        definition_hash=sha256_json(canonical.model_dump(mode='json')),
        source=canonical.metadata.source, intent_id=canonical.metadata.intent_id,
    )
    db.add(rev)
    db.flush()
    # Definition may exist while committed enforcement is disabled/pending.
    record.desired_revision_id = rev.id
    staged = stage_operation(
        db, policy_id=pid, operation_type='create', requester_id=requester,
        idempotency_key=key, request_payload=policy.model_dump(mode='json'),
        requested_revision_id=rev.id, request_hash=fp,
    )
    staged.operation.requested_state = 'enabled'
    staged.operation.base_desired_state = None
    _reserve(db, operation_id=staged.operation.id, scope_pairs=_scope_from_policy(canonical))
    _check_conflict(db, canonical, exclude_id=pid)
    _store_flows(db, record=record, revision=rev, flows=flows)
    return Submitted(pid, staged.operation.id, staged.operation.status, True)


def _change_inner(db, *, kind: str, policy_id: str, policy: PolicyInput | None,
                  expected_revision: int | None, requester: str, key: str, fp: str):
    replay = _replay(db, requester=requester, key=key, fingerprint=fp)
    if replay:
        return replay
    # row lock prevents same-policy races; scope reservation prevents different
    # policies on the same switch from executing simultaneously.
    record = db.scalar(select(PolicyRecord).where(PolicyRecord.id == policy_id).with_for_update())
    if record is None:
        raise SubmissionError('Policy not found', 404)
    if record.desired_state == 'deleted' or record.status == 'deleted':
        raise SubmissionError('Policy has been deleted')
    if kind == 'update':
        if expected_revision is None:
            raise SubmissionError('If-Match revision header required', 428)
        if record.revision != expected_revision:
            raise SubmissionError('Revision mismatch (If-Match)', 412)
        if policy is None:
            raise SubmissionError('Update body required', 422)
        if policy.policy.id not in (None, policy_id):
            raise SubmissionError('Body policy.id must match route policy_id', 422)
    if kind == 'enable' and record.desired_state == 'enabled':
        raise SubmissionError('Policy already enabled')
    if kind == 'disable' and record.desired_state == 'disabled':
        raise SubmissionError('Policy already disabled')

    old_def = PolicyInput.model_validate(record.definition)
    candidate = policy.model_copy(deep=True) if policy is not None else old_def
    candidate.policy.id = policy_id
    if kind in {'update', 'enable'}:
        _check_conflict(db, candidate, exclude_id=policy_id)
    target_scope = _scope_from_policy(candidate) | _scope_from_policy(old_def)
    current_revision = record.desired_revision_id
    new_rev = None
    if kind == 'update':
        normalized = candidate.model_dump(mode='json')
        if sha256_json(normalized) == sha256_json(old_def.model_dump(mode='json')):
            raise SubmissionError('New definition is identical to current definition')
        revision_cookie = new_cookie()  # distinct ownership for every revision
        flows = compile_policy(candidate, revision_cookie)
        latest_revision = db.scalar(select(func.max(PolicyRevision.revision_no)).where(PolicyRevision.policy_id == policy_id)) or 0
        new_rev = PolicyRevision(
            id=str(uuid4()), policy_id=policy_id, revision_no=latest_revision + 1,
            definition=normalized, definition_hash=sha256_json(normalized),
            source=candidate.metadata.source, intent_id=candidate.metadata.intent_id,
        )
        db.add(new_rev)
        db.flush()
        _store_flows(db, record=record, revision=new_rev, flows=flows)
    requested_revision = new_rev.id if new_rev is not None else current_revision
    if not requested_revision:
        raise SubmissionError('Policy has no revision; repair foundation records before changing')
    staged = stage_operation(
        db, policy_id=policy_id, operation_type=kind, requester_id=requester,
        idempotency_key=key,
        request_payload=(policy.model_dump(mode='json') if policy is not None else {}),
        requested_revision_id=requested_revision, base_revision_id=record.applied_revision_id,
        request_hash=fp,
    )
    staged.operation.base_desired_state = record.desired_state
    staged.operation.requested_state = ('enabled' if kind in {'enable','update'} and record.desired_state == 'enabled'
                                        else 'enabled' if kind == 'enable'
                                        else 'disabled' if kind == 'disable'
                                        else 'deleted' if kind == 'delete'
                                        else record.desired_state)
    _reserve(db, operation_id=staged.operation.id, scope_pairs=target_scope)
    return Submitted(policy_id, staged.operation.id, staged.operation.status, True)


def submit(kind: str, *, requester: str, key: str, policy_id: str | None = None,
           policy: PolicyInput | None = None, expected_revision: int | None = None,
           session_factory=None) -> Submitted:
    if kind not in {'create', 'update', 'enable', 'disable', 'delete'}:
        raise SubmissionError('Unsupported operation type', 422)
    if not (requester and key) or len(requester) > 128 or len(key) > 160:
        raise SubmissionError('Valid requester and Idempotency-Key required', 422)
    if kind == 'create' and policy is None:
        raise SubmissionError('Policy body required', 422)
    if kind != 'create' and not policy_id:
        raise SubmissionError('Target policy id required', 422)
    payload = policy.model_dump(mode='json') if policy is not None else {}
    fp = _fingerprint(kind, policy_id, payload, expected_revision)
    factory = session_factory or SessionLocal
    try:
        with factory.begin() as db:
            if kind == 'create':
                return _create_inner(db, policy, requester=requester, key=key, fp=fp)
            return _change_inner(db, kind=kind, policy_id=policy_id, policy=policy,
                                 expected_revision=expected_revision, requester=requester,
                                 key=key, fp=fp)
    except IdempotencyPayloadMismatch as e:
        raise SubmissionError(str(e)) from e
    
    except IntegrityError as e:
        # PostgreSQL diagnostic details, without logging request data.
        original = e.orig
        sqlstate = getattr(original, "sqlstate", None)
        diag = getattr(original, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        message = getattr(original, "diag", None)
        primary_message = getattr(message, "message_primary", None)

        logger.error(
            "Policy submission database error: "
            "sqlstate=%s constraint=%s message=%s",
            sqlstate,
            constraint,
            primary_message,
        )

        # The transaction has already rolled back.
        # Check whether another concurrent request created the
        # same operation successfully.
        with factory() as db:
            replay = _replay(
                db,
                requester=requester,
                key=key,
                fingerprint=fp,
            )
            if replay:
                return replay

        raise SubmissionError(
            "Policy submission violated a database constraint"
        ) from e

