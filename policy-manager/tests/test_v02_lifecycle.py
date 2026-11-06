"""Stage-2 contract tests in a local SQLite emulator.

Runtime uses PostgreSQL; these tests do NOT prove PostgreSQL concurrency.
"""
import copy
import unittest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models import PolicyOperation, PolicyRecord, PolicyRevision, OperationEvent, OutboxEvent
from app.models.scope_reservation import ScopeReservation
from app.schemas.policy import PolicyInput
from app.services.submission_service import submit, SubmissionError
from app.services.execution_service import run_operation, OperationBusy


@compiles(JSONB, 'sqlite')
def _sqlite_jsonb(_type, _compiler, **_kwargs):
    return 'JSON'


def policy(src='10.0.0.1/32', dst='10.0.0.3/32'):
    return PolicyInput.model_validate({
        'schema_version': '1.0', 'policy': {'name': 'test-rule', 'type': 'firewall'},
        'scope': {'network_id': 'mininet-lab', 'switches': ['1']},
        'match': {'source': {'type': 'ipv4', 'value': src},
                  'destination': {'type': 'ipv4', 'value': dst},
                  'direction': 'bidirectional', 'protocol': 'any'},
        'action': {'type': 'deny'},
    })


class FakeRyu:
    def __init__(self):
        self.flows = []
        self.fail_add = False
    def switches(self):
        return {1}
    def add_flow(self, f):
        if self.fail_add:
            raise RuntimeError('injected add failure')
        # OpenFlow ADD can replace an existing identical match/priority.
        self.flows = [x for x in self.flows if not (
            x['dpid'] == f['dpid'] and x['match'] == f['match'] and x['priority'] == f['priority'])]
        self.flows.append(copy.deepcopy(f))
    def delete_flow(self, f):
        self.flows = [x for x in self.flows if not (
            x['cookie'] == f['cookie'] and x['dpid'] == f['dpid']
            and x['priority'] == f['priority'] and x['match'] == f['match'])]
    def flow_present(self, f):
        return any(x == f for x in self.flows)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite+pysqlite:///:memory:',
            connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.ryu = FakeRyu()

    def tearDown(self):
        self.engine.dispose()

    def submit(self, kind, *, key, policy_id=None, definition=None, expected_revision=None):
        return submit(kind, requester='client-test', key=key,
                      policy_id=policy_id, policy=definition, expected_revision=expected_revision,
                      session_factory=self.factory)

    def execute(self, result):
        return run_operation(result.operation_id, session_factory=self.factory,
                             adapter=self.ryu, sleep=lambda _: None)

    def count(self, model):
        with self.factory() as db:
            return db.scalar(select(func.count()).select_from(model))

    def test_create_is_atomic_pending_and_outbox(self):
        op = self.submit('create', key='key1', definition=policy())
        self.assertEqual('pending', op.status)
        self.assertEqual(0, len(self.ryu.flows))
        self.assertEqual(1, self.count(PolicyOperation))
        self.assertEqual(1, self.count(OutboxEvent))
        self.assertEqual(1, self.count(ScopeReservation))
        self.assertEqual(1, self.count(PolicyRevision))
        with self.factory() as db:
            r = db.get(PolicyRecord, op.policy_id)
            self.assertEqual('disabled', r.desired_state) # committed state, not proposed
            self.assertIsNotNone(r.desired_revision_id)

    def test_create_execute_and_repeat_idempotent(self):
        op = self.submit('create', key='key1', definition=policy())
        repeat = self.submit('create', key='key1', definition=policy())
        self.assertFalse(repeat.created)
        self.assertEqual(op.operation_id, repeat.operation_id)
        self.assertEqual('succeeded', self.execute(op))
        self.assertEqual(2, len(self.ryu.flows))
        self.assertEqual('succeeded', self.execute(op))
        with self.factory() as db:
            p = db.get(PolicyRecord, op.policy_id)
            self.assertEqual('enabled', p.desired_state)
            self.assertEqual('installed', p.applied_state)
            o = db.get(PolicyOperation, op.operation_id)
            self.assertEqual('succeeded', o.status)
            self.assertEqual('delivered', db.scalars(select(OutboxEvent)).first().dispatch_status)
        self.assertEqual(0, self.count(ScopeReservation))
        self.assertGreaterEqual(self.count(OperationEvent), 2)

    def test_same_key_changed_payload_rejected(self):
        self.submit('create', key='key1', definition=policy())
        with self.assertRaises(SubmissionError) as ctx:
            self.submit('create', key='key1', definition=policy(dst='10.0.0.2/32'))
        self.assertEqual(409, ctx.exception.http_status)
        self.assertEqual(1, self.count(PolicyRecord))

    def test_overlapping_pending_operations_scope_locked(self):
        self.submit('create', key='key1', definition=policy())
        with self.assertRaises(SubmissionError) as ctx:
            self.submit('create', key='key2', definition=policy(dst='10.0.0.2/32'))
        self.assertEqual(409, ctx.exception.http_status)
        self.assertEqual(1, self.count(PolicyRecord))

    def test_failure_is_compensated_and_logged(self):
        op = self.submit('create', key='key1', definition=policy())
        self.ryu.fail_add = True
        self.assertEqual('failed', self.execute(op))
        self.assertEqual(0, self.count(ScopeReservation))
        with self.factory() as db:
            p = db.get(PolicyRecord, op.policy_id)
            self.assertIsNotNone(p.desired_revision_id)
            o = db.get(PolicyOperation, op.operation_id)
            self.assertEqual('DEPLOY_COMPENSATED', o.error_code)

    def test_create_disable_enable_delete(self):
        created = self.submit('create', key='key1', definition=policy())
        self.assertEqual('succeeded', self.execute(created))
        disabled = self.submit('disable', key='key2', policy_id=created.policy_id)
        self.assertEqual('succeeded', self.execute(disabled))
        self.assertEqual(0, len(self.ryu.flows))
        enabled = self.submit('enable', key='key3', policy_id=created.policy_id)
        self.assertEqual('succeeded', self.execute(enabled))
        self.assertEqual(2, len(self.ryu.flows))
        deleted = self.submit('delete', key='key4', policy_id=created.policy_id)
        self.assertEqual('succeeded', self.execute(deleted))
        self.assertEqual(0, len(self.ryu.flows))
        with self.factory() as db:
            p = db.get(PolicyRecord, created.policy_id)
            self.assertEqual('deleted', p.desired_state)
            self.assertEqual('absent', p.applied_state)

    def test_update_revision_and_if_match(self):
        created = self.submit('create', key='key1', definition=policy())
        self.assertEqual('succeeded', self.execute(created))
        with self.assertRaises(SubmissionError) as ctx:
            self.submit('update', key='bad', policy_id=created.policy_id,
                        definition=policy(dst='10.0.0.2/32'), expected_revision=2)
        self.assertEqual(412, ctx.exception.http_status)
        updated = self.submit('update', key='good', policy_id=created.policy_id,
                              definition=policy(dst='10.0.0.2/32'), expected_revision=1)
        self.assertEqual('succeeded', self.execute(updated))
        self.assertEqual(2, len(self.ryu.flows))
        with self.factory() as db:
            p = db.get(PolicyRecord, created.policy_id)
            self.assertEqual(2, p.revision)
            self.assertEqual('10.0.0.2/32', p.definition['match']['destination']['value'])

    def test_replay_terminal_operation_has_no_effect(self):
        created = self.submit('create', key='key1', definition=policy())
        self.execute(created)
        count = len(self.ryu.flows)
        self.assertEqual('succeeded', self.execute(created))
        self.assertEqual(count, len(self.ryu.flows))

    def test_manual_worker_lease_protects_concurrency(self):
        created = self.submit('create', key='key1', definition=policy())
        with self.factory.begin() as db:
            op = db.get(PolicyOperation, created.operation_id)
            from datetime import datetime, timedelta, timezone
            op.runner_token = 'someone-else'
            op.lease_until = datetime.now(timezone.utc) + timedelta(minutes=3)
        with self.assertRaises(OperationBusy):
            self.execute(created)


    def test_active_overlap_rejected_without_creating_new_policy(self):
        created = self.submit('create', key='a', definition=policy())
        self.execute(created)
        with self.assertRaises(SubmissionError) as ctx:
            self.submit('create', key='b', definition=policy())
        self.assertEqual(409, ctx.exception.http_status)
        self.assertEqual(1, self.count(PolicyRecord))

    def test_failed_update_does_not_overwrite_committed_revision(self):
        created = self.submit('create', key='a', definition=policy())
        self.execute(created)
        updated = self.submit('update', key='b', policy_id=created.policy_id,
                              definition=policy(dst='10.0.0.2/32'), expected_revision=1)
        self.ryu.fail_add = True
        # A failing Ryu adapter can also prevent compensation from restoring
        # the old flows. This is explicitly UNRESOLVED, never a clean failure.
        self.assertEqual('unresolved', self.execute(updated))
        with self.factory() as db:
            p = db.get(PolicyRecord, created.policy_id)
            self.assertEqual(1, p.revision)
            self.assertEqual('10.0.0.3/32', p.definition['match']['destination']['value'])
            self.assertEqual('unknown', p.applied_state)
        self.assertEqual(1, self.count(ScopeReservation))
        with self.assertRaises(OperationBusy):
            self.execute(updated)

    def test_failed_update_uses_new_monotonic_revision_number(self):
        created = self.submit('create', key='a', definition=policy())
        self.execute(created)
        update1 = self.submit('update', key='b', policy_id=created.policy_id,
                              definition=policy(dst='10.0.0.2/32'), expected_revision=1)
        # Preflight fails safely (no network change), releasing the scope.
        class OfflineRyu(FakeRyu):
            def switches(self):
                return set()
        offline = OfflineRyu()
        self.assertEqual('failed', run_operation(update1.operation_id,
                         session_factory=self.factory, adapter=offline, sleep=lambda _: None))
        update2 = self.submit('update', key='c', policy_id=created.policy_id,
                              definition=policy(dst='10.0.0.4/32'), expected_revision=1)
        self.assertEqual('succeeded', self.execute(update2))
        with self.factory() as db:
            p = db.get(PolicyRecord, created.policy_id)
            self.assertEqual(3, p.revision)

    def test_idempotency_include_precondition(self):
        created = self.submit('create', key='a', definition=policy())
        self.execute(created)
        good = self.submit('update', key='u', policy_id=created.policy_id,
                           definition=policy(dst='10.0.0.2/32'), expected_revision=1)
        with self.assertRaises(SubmissionError) as ctx:
            self.submit('update', key='u', policy_id=created.policy_id,
                        definition=policy(dst='10.0.0.2/32'), expected_revision=99)
        self.assertEqual(409, ctx.exception.http_status)


if __name__ == '__main__':
    unittest.main()
