"""Stage 4B safety tests. SQLite emulates ORM; no real switch/database IO."""
import copy
from datetime import datetime, timedelta, timezone
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, select, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models import (FlowDeployment, OperationEvent, OutboxEvent, PolicyOperation,
                        PolicyRecord, PolicyRevision, ReconciliationFinding)
from app.models.scope_reservation import ScopeReservation
from app.reconciliation.repair import RepairRefused, apply, check
from app.reconciliation.service import observe_once


@compiles(JSONB, 'sqlite')
def _jsonb_sqlite(_type, _compiler, **_kwargs):
    return 'JSON'


COOKIE = (0x4C4C << 47) | 12345


def flow(src, dst, *, cookie=COOKIE):
    return {'dpid': 1, 'cookie': cookie, 'table_id': 0, 'priority': 1100,
            'match': {'eth_type': 2048, 'ipv4_src': src, 'ipv4_dst': dst}, 'actions': []}


class FakeRyu:
    def __init__(self, flows):
        self.flows = copy.deepcopy(flows)
        self.connected = {1}
        self.adds = []
        self.deletes = []
        self.fail_read = False
        self.fail_after_add = False
        self.no_install = False

    def switches(self):
        if self.fail_read:
            from app.adapters.ryu_adapter import RyuError
            raise RyuError('no switch stats')
        return self.connected

    def observed_flows(self, dpid):
        if self.fail_read:
            from app.adapters.ryu_adapter import RyuError
            raise RyuError('no flow stats')
        return copy.deepcopy(self.flows)

    def add_flow(self, spec):
        self.adds.append(copy.deepcopy(spec))
        if not self.no_install:
            self.flows.append(copy.deepcopy(spec))
        if self.fail_after_add:
            raise TimeoutError('ack was lost after network change')

    def delete_flow(self, spec):
        self.deletes.append(copy.deepcopy(spec))
        raise AssertionError('Stage 4B must never DELETE a flow')


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite+pysqlite:///:memory:',
                                    connect_args={'check_same_thread': False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.a = flow('10.0.0.2/32', '10.0.0.3/32')
        self.b = flow('10.0.0.3/32', '10.0.0.2/32')
        self.policy_id = 'FW-observer'
        self.rev_id = str(uuid4())
        self.start = datetime(2026, 11, 7, tzinfo=timezone.utc)
        policy_json = {
            'schema_version': '1.0',
            'policy': {'id': self.policy_id, 'name': 'lab-firewall', 'type': 'firewall'},
            'scope': {'network_id': 'mininet-lab', 'switches': ['1']},
            'match': {'source': {'type': 'ipv4', 'value': '10.0.0.2/32'},
                      'destination': {'type': 'ipv4', 'value': '10.0.0.3/32'},
                      'direction': 'bidirectional', 'protocol': 'any'},
            'action': {'type': 'deny'},
        }
        with self.factory.begin() as db:
            db.add(PolicyRecord(id=self.policy_id, revision=1, cookie=COOKIE,
                                definition=policy_json, compiled_flows=[self.a, self.b],
                                desired_state='enabled', applied_state='installed', status='active'))
            db.flush()
            db.add(PolicyRevision(id=self.rev_id, policy_id=self.policy_id, revision_no=1,
                                  definition=policy_json, definition_hash='a' * 64,
                                  source='test'))
            db.flush()
            p = db.get(PolicyRecord, self.policy_id)
            p.desired_revision_id = self.rev_id
            p.applied_revision_id = self.rev_id
            for idx, spec in enumerate((self.a, self.b)):
                db.add(FlowDeployment(id=f'flow-{idx}', policy_id=self.policy_id,
                                      revision_id=self.rev_id, dpid=1, flow_index=idx,
                                      cookie=COOKIE, flow_spec=spec, flow_hash='b' * 64,
                                      deployment_status='installed'))
        self.ryu = FakeRyu([self.a])
        observe_once(session_factory=self.factory, adapter=self.ryu, now=self.start)
        observe_once(session_factory=self.factory, adapter=self.ryu,
                     now=self.start + timedelta(seconds=15))
        with self.factory() as db:
            self.finding_id = db.scalar(select(ReconciliationFinding.id))
            assert self.finding_id

    def tearDown(self):
        self.engine.dispose()

    def count(self, model):
        with self.factory() as db:
            return db.scalar(select(func.count()).select_from(model))

    def run_repair(self):
        return apply(self.finding_id, session_factory=self.factory,
                     adapter=self.ryu, sleep=lambda _: None)

    def test_check_mode_is_strictly_read_only_and_stages_nothing(self):
        result = check(self.finding_id, session_factory=self.factory, adapter=self.ryu)
        self.assertEqual('eligible', result.status)
        self.assertEqual('missing', result.reason)
        self.assertEqual(0, self.count(PolicyOperation))
        self.assertEqual(0, self.count(ScopeReservation))
        self.assertEqual([], self.ryu.adds)

    def test_succeeded_repairs_only_missing_and_preserves_revision(self):
        result = self.run_repair()
        self.assertEqual('succeeded', result.status)
        self.assertEqual('flow_restored_and_verified', result.reason)
        self.assertEqual([self.b], self.ryu.adds)
        self.assertEqual([], self.ryu.deletes)
        self.assertEqual(0, self.count(ScopeReservation))
        self.assertEqual(0, self.count(OutboxEvent))
        self.assertGreaterEqual(self.count(OperationEvent), 3)
        with self.factory() as db:
            p = db.get(PolicyRecord, self.policy_id)
            self.assertEqual(1, p.revision)
            self.assertEqual(self.rev_id, p.applied_revision_id)
            self.assertEqual('installed', p.applied_state)
            o = db.get(PolicyOperation, result.operation_id)
            self.assertEqual('reconcile', o.operation_type)
            self.assertEqual('system:reconciler', o.requester_id)
            self.assertIsNone(o.airflow_run_id)
            self.assertEqual('succeeded', o.status)
            self.assertEqual('installed', db.get(FlowDeployment, 'flow-1').deployment_status)
            f = db.get(ReconciliationFinding, self.finding_id)
            self.assertIsNotNone(f.resolved_at)
            self.assertEqual(result.operation_id, f.evidence['repair_operation_id'])

    def test_second_apply_refuses_resolved_finding(self):
        self.run_repair()
        with self.assertRaises(RepairRefused):
            self.run_repair()
        self.assertEqual(1, len(self.ryu.adds))

    def test_external_restore_is_idempotent_no_write(self):
        self.ryu.flows.append(copy.deepcopy(self.b))
        result = self.run_repair()
        self.assertEqual('succeeded', result.status)
        self.assertEqual('already_present_no_write', result.reason)
        self.assertEqual([], self.ryu.adds)

    def test_foreign_flow_same_slot_blocks_repair(self):
        self.ryu.flows.append(flow('10.0.0.3/32', '10.0.0.2/32', cookie=123))
        result = self.run_repair()
        self.assertEqual('failed', result.status)
        self.assertEqual([], self.ryu.adds)
        self.assertEqual(0, self.count(ScopeReservation))

    def test_modified_rule_same_cookie_blocks_repair(self):
        altered = copy.deepcopy(self.b)
        altered['actions'] = ['OUTPUT:2']
        self.ryu.flows.append(altered)
        result = self.run_repair()
        self.assertEqual('failed', result.status)
        self.assertEqual([], self.ryu.adds)

    def test_unexpected_cookie_extra_blocks_repair(self):
        rogue = flow('10.0.0.9/32', '10.0.0.10/32')
        self.ryu.flows.append(rogue)
        result = self.run_repair()
        self.assertEqual('failed', result.status)
        self.assertEqual([], self.ryu.adds)

    def test_ryu_unknown_before_add_refuses_without_lease(self):
        self.ryu.fail_read = True
        result = self.run_repair()
        self.assertEqual('failed', result.status)
        self.assertEqual([], self.ryu.adds)
        self.assertEqual(0, self.count(ScopeReservation))

    def test_ambiguous_add_holds_reservation_and_marks_unknown(self):
        self.ryu.fail_after_add = True
        result = self.run_repair()
        self.assertEqual('unresolved', result.status)
        self.assertEqual(1, self.count(ScopeReservation))
        with self.factory() as db:
            p = db.get(PolicyRecord, self.policy_id)
            self.assertEqual('unknown', p.applied_state)
            self.assertEqual('unknown', db.get(FlowDeployment, 'flow-1').deployment_status)
            self.assertIsNone(db.get(ReconciliationFinding, self.finding_id).resolved_at)

    def test_unverified_post_is_unresolved_not_succeeded(self):
        self.ryu.no_install = True
        result = self.run_repair()
        self.assertEqual('unresolved', result.status)
        self.assertEqual(1, len(self.ryu.adds))
        self.assertEqual(1, self.count(ScopeReservation))

    def test_pending_operation_blocks_repair(self):
        with self.factory.begin() as db:
            db.add(PolicyOperation(id=str(uuid4()), policy_id=self.policy_id,
                                   operation_type='disable', requested_revision_id=self.rev_id,
                                   requester_id='unit-test', idempotency_key='conflict',
                                   request_hash='h' * 64, status='pending'))
        with self.assertRaises(RepairRefused):
            self.run_repair()
        self.assertEqual([], self.ryu.adds)

    def test_switch_reservation_blocks_repair(self):
        op_id = str(uuid4())
        with self.factory.begin() as db:
            db.add(PolicyOperation(id=op_id, policy_id=self.policy_id,
                                   operation_type='disable', requested_revision_id=self.rev_id,
                                   requester_id='unit-test', idempotency_key='held',
                                   request_hash='h' * 64, status='succeeded'))
            db.flush()
            db.add(ScopeReservation(network_id='mininet-lab', dpid=1, operation_id=op_id))
        with self.assertRaises(RepairRefused):
            self.run_repair()
        self.assertEqual([], self.ryu.adds)

    def test_disabled_policy_blocks_repair(self):
        with self.factory.begin() as db:
            p = db.get(PolicyRecord, self.policy_id)
            p.desired_state = 'disabled'
        with self.assertRaises(RepairRefused):
            self.run_repair()
        self.assertEqual([], self.ryu.adds)

    def test_unconfirmed_finding_blocks_repair(self):
        with self.factory.begin() as db:
            f = db.get(ReconciliationFinding, self.finding_id)
            f.confirmed_at = None
        with self.assertRaises(RepairRefused):
            self.run_repair()
        self.assertEqual([], self.ryu.adds)

    def test_network_read_does_not_remove_any_rule(self):
        self.run_repair()
        self.assertEqual([], self.ryu.deletes)
        self.assertEqual(2, len(self.ryu.flows))


if __name__ == '__main__':
    unittest.main()
