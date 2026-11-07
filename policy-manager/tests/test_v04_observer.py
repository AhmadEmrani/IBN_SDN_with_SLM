"""Stage 4A contract tests: SQLite emulation, no real Ryu or PostgreSQL IO.

Actual PostgreSQL migrations and Ryu REST are verified by the deployment steps.
"""
import copy
from datetime import datetime, timedelta, timezone
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models import FlowDeployment, PolicyOperation, PolicyRecord, PolicyRevision, ReconciliationFinding
from app.models.scope_reservation import ScopeReservation
from app.reconciliation.observer import compare, signature
from app.reconciliation.service import observe_once


@compiles(JSONB, 'sqlite')
def _sqlite_jsonb(_type, _compiler, **_kwargs):
    return 'JSON'


COOKIE = (0x4C4C << 47) | 12345


def flow(src, dst, cookie=COOKIE):
    return {
        'dpid': 1, 'cookie': cookie, 'table_id': 0, 'priority': 1100,
        'match': {'eth_type': 2048, 'ipv4_src': src, 'ipv4_dst': dst}, 'actions': [],
    }


class FakeRyu:
    def __init__(self):
        self.connected = {1}
        self.flows = []
        self.error = None
        self.get_calls = 0

    def switches(self):
        self.get_calls += 1
        if self.error == 'switches':
            
            from app.adapters.ryu_adapter import RyuError
            raise RyuError('offline')
        return self.connected

    def observed_flows(self, dpid):
        self.get_calls += 1
        if self.error == 'flows':
            from app.adapters.ryu_adapter import RyuError
            raise RyuError('offline')
        return copy.deepcopy(self.flows)

    def add_flow(self, *_args):
        raise AssertionError('read-only observer must not add a flow')

    def delete_flow(self, *_args):
        raise AssertionError('read-only observer must not delete a flow')


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite+pysqlite:///:memory:',
                                    connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.ryu = FakeRyu()
        self.start = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
        self.policy_id = 'FW-test01'
        self.revision_id = str(uuid4())
        self.a = flow('10.0.0.2/32', '10.0.0.3/32')
        self.b = flow('10.0.0.3/32', '10.0.0.2/32')
        with self.factory.begin() as db:
            db.add(PolicyRecord(
                id=self.policy_id, revision=1, cookie=COOKIE, definition={'kind': 'test'},
                compiled_flows=[self.a, self.b], desired_state='enabled',
                applied_state='installed', status='active',
            ))
            db.flush()
            db.add(PolicyRevision(id=self.revision_id, policy_id=self.policy_id,
                                  revision_no=1, definition={}, definition_hash='x' * 64,
                                  source='test'))
            db.flush()
            policy = db.get(PolicyRecord, self.policy_id)
            policy.desired_revision_id = self.revision_id
            policy.applied_revision_id = self.revision_id
            for idx, spec in enumerate([self.a, self.b]):
                db.add(FlowDeployment(id=f'deploy-{idx}', policy_id=self.policy_id,
                                      revision_id=self.revision_id, dpid=1, flow_index=idx,
                                      cookie=COOKIE, flow_spec=spec, flow_hash='x' * 64,
                                      deployment_status='installed'))
        self.ryu.flows = copy.deepcopy([self.a, self.b])

    def tearDown(self):
        self.engine.dispose()

    def run_scan(self, seconds=0):
        return observe_once(session_factory=self.factory, adapter=self.ryu,
                            now=self.start + timedelta(seconds=seconds))

    def findings(self, kind=None, open_only=False):
        with self.factory() as db:
            query = select(ReconciliationFinding)
            if kind:
                query = query.where(ReconciliationFinding.kind == kind)
            if open_only:
                query = query.where(ReconciliationFinding.resolved_at.is_(None))
            return db.scalars(query.order_by(ReconciliationFinding.first_seen_at)).all()

    def deployment(self, idx):
        with self.factory() as db:
            return db.get(FlowDeployment, f'deploy-{idx}')

    def test_tcp_legacy_transport_alias_matches(self):
        tcp = flow('10.0.0.2/32', '10.0.0.3/32')
        tcp['match'].update({'ip_proto': 6, 'tcp_src': 443})
        observed = copy.deepcopy(tcp)
        observed['match'].pop('tcp_src')
        observed['match']['tp_src'] = 443
        self.assertEqual('healthy', compare(tcp, [signature(observed)]).classification)

    def test_healthy_updates_latest_snapshot_without_finding(self):
        out = self.run_scan()
        self.assertEqual(2, out['healthy'])
        self.assertEqual([], self.findings())
        self.assertEqual('healthy', self.deployment(0).observed_snapshot['classification'])
        self.assertEqual('installed', self.deployment(0).deployment_status)

    def test_missing_requires_two_valid_observations(self):
        self.ryu.flows = [self.a]
        out = self.run_scan(0)
        self.assertEqual(1, out['suspected'])
        self.assertEqual('installed', self.deployment(1).deployment_status)
        self.assertIsNone(self.findings('missing')[0].confirmed_at)
        out = self.run_scan(15)
        self.assertEqual(1, out['confirmed'])
        self.assertEqual('missing', self.deployment(1).deployment_status)
        self.assertEqual(1, len(self.findings('missing')))
        self.assertEqual(2, self.findings('missing')[0].consecutive_count)

    def test_confirmed_missing_resolves_and_can_recur_as_new_episode(self):
        self.ryu.flows = [self.a]
        self.run_scan(0); self.run_scan(15)
        self.ryu.flows.append(self.b)
        self.run_scan(30)
        self.assertEqual(0, len(self.findings('missing', open_only=True)))
        self.assertIsNotNone(self.findings('missing')[0].resolved_at)
        self.ryu.flows = [self.a]
        self.run_scan(45)
        self.assertEqual(2, len(self.findings('missing')))

    def test_bad_actions_is_modified_not_healthy(self):
        self.ryu.flows[0]['actions'] = ['OUTPUT:2']
        self.run_scan(0); self.run_scan(15)
        self.assertEqual('modified', self.deployment(0).deployment_status)
        self.assertEqual(1, len(self.findings('modified')))
        self.assertEqual(0, len(self.findings('extra')))

    def test_priority_change_is_modified(self):
        self.ryu.flows[0]['priority'] = 1200
        self.run_scan(0); self.run_scan(15)
        self.assertEqual('modified', self.deployment(0).deployment_status)

    def test_match_aliases_and_ipv4_host_format(self):
        self.ryu.flows[0]['match'] = {
            'dl_type': 2048, 'nw_src': '10.0.0.2', 'nw_dst': '10.0.0.3'}
        self.assertEqual(2, self.run_scan()['healthy'])

    def test_disconnected_switch_is_unknown_never_missing(self):
        self.ryu.connected.clear()
        self.run_scan(0); self.run_scan(15)
        self.assertEqual('unknown', self.deployment(0).deployment_status)
        self.assertEqual([], self.findings('missing'))
        self.assertEqual(1, len(self.findings('unknown')))
        self.ryu.connected = {1}
        self.run_scan(30)
        self.assertEqual(0, len(self.findings('unknown', open_only=True)))

    def test_ryu_error_is_unknown(self):
        self.ryu.error = 'flows'
        self.run_scan()
        self.assertEqual(1, len(self.findings('unknown')))
        self.assertEqual([], self.findings('missing'))

    def test_malformed_known_flow_is_unknown_not_missing(self):
        self.ryu.flows[0].pop('actions')
        self.run_scan()
        self.assertEqual(1, len(self.findings('unknown')))
        self.assertEqual([], self.findings('missing'))

    def test_extra_known_cookie_is_recorded_but_unowned_cookie_ignored(self):
        other = flow('10.0.0.8', '10.0.0.9', cookie=COOKIE)
        unrelated = flow('10.0.0.8', '10.0.0.9', cookie=101)
        self.ryu.flows.extend([other, unrelated])
        self.run_scan(0); self.run_scan(15)
        self.assertEqual(1, len(self.findings('extra')))
        self.assertIsNotNone(self.findings('extra')[0].confirmed_at)
        self.ryu.flows = self.ryu.flows[:2]
        self.run_scan(30)
        self.assertIsNotNone(self.findings('extra')[0].resolved_at)

    def test_disabled_policy_is_not_misreported_missing(self):
        with self.factory.begin() as db:
            p = db.get(PolicyRecord, self.policy_id)
            p.desired_state = 'disabled'; p.applied_state = 'absent'
            p.status = 'disabled'; p.applied_revision_id = None
        self.ryu.flows = []
        self.run_scan()
        self.assertEqual([], self.findings('missing'))
        self.assertEqual([], self.findings('extra'))
        self.assertIsNone(self.deployment(0).last_observed_at)

    def test_stale_cookie_of_disabled_policy_is_extra(self):
        with self.factory.begin() as db:
            p = db.get(PolicyRecord, self.policy_id)
            p.desired_state = 'disabled'; p.applied_state = 'absent'
            p.status = 'disabled'; p.applied_revision_id = None
        self.run_scan(0); self.run_scan(15)
        self.assertEqual(2, len(self.findings('extra')))
        self.assertEqual([], self.findings('missing'))

    def test_reservation_skips_network_and_persistence(self):
        with self.factory.begin() as db:
            db.add(PolicyOperation(id='op-reserved', policy_id=self.policy_id,
                                   operation_type='update', requester_id='u', idempotency_key='key',
                                   request_hash='x' * 64, status='running'))
            db.flush()
            db.add(ScopeReservation(network_id='mininet-lab', dpid=1,
                                    operation_id='op-reserved'))
        self.ryu.flows = []
        out = self.run_scan()
        self.assertEqual(1, out['skipped'])
        self.assertEqual(0, self.ryu.get_calls)
        self.assertEqual([], self.findings())

    def test_unknown_breaks_confirmation_streak(self):
        self.ryu.flows = [self.a]
        self.run_scan(0)
        self.ryu.connected.clear()
        self.run_scan(15)
        self.ryu.connected = {1}
        self.run_scan(30)
        self.assertEqual('unknown', self.deployment(1).deployment_status)
        self.assertEqual(1, self.findings('missing', open_only=True)[0].consecutive_count)
        self.run_scan(45)
        self.assertEqual('missing', self.deployment(1).deployment_status)

    def test_disabling_policy_closes_old_missing_episode(self):
        self.ryu.flows = [self.a]
        self.run_scan(0); self.run_scan(15)
        with self.factory.begin() as db:
            p = db.get(PolicyRecord, self.policy_id)
            p.desired_state = 'disabled'; p.applied_state = 'absent'
            p.status = 'disabled'; p.applied_revision_id = None
        self.ryu.flows = []
        self.run_scan(30)
        self.assertEqual([], self.findings('missing', open_only=True))

    def test_unstable_old_policy_does_not_block_active_observations(self):
        with self.factory.begin() as db:
            db.add(PolicyRecord(id='FW-failed-old', revision=1, cookie=123456,
                                definition={}, compiled_flows=[], status='failed',
                                desired_state='disabled', applied_state='unknown'))
            db.flush()
            db.add(PolicyRevision(id='revision-old', policy_id='FW-failed-old',
                                  revision_no=1, definition={}, definition_hash='x'*64,
                                  source='test'))
            db.flush()
            db.add(FlowDeployment(id='old-flow', policy_id='FW-failed-old',
                                  revision_id='revision-old', dpid=1, flow_index=0,
                                  cookie=123456, flow_spec=flow('10.0.0.7', '10.0.0.8', 123456),
                                  flow_hash='x'*64, deployment_status='unknown'))
        self.assertEqual(2, self.run_scan()['healthy'])

    def test_malformed_ryu_response_is_not_silent_empty_flow_list(self):
        from unittest.mock import patch
        from app.adapters import ryu_adapter

        class FakeResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return {}  # a valid empty flow list must be {'1': []}

        class FakeClient:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def get(self, _url):
                return FakeResponse()

        with patch('app.adapters.ryu_adapter.httpx.Client', FakeClient):
            with self.assertRaises(ryu_adapter.RyuError):
                ryu_adapter.observed_flows(1)

    def test_pure_compare_has_no_actions_side_effect(self):
        observed = [signature(self.a)]
        self.assertEqual('healthy', compare(self.a, observed).classification)
        self.assertEqual('missing', compare(self.b, observed).classification)


if __name__ == '__main__':
    unittest.main()
