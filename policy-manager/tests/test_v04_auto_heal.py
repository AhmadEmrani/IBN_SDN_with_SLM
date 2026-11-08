"""Stage 4C auto-trigger safety regression; fake Ryu + SQLite ORM emulator."""
from datetime import timedelta
import unittest
from unittest.mock import patch

from sqlalchemy import select

import test_v04_repair as fixtures
from app.models import PolicyOperation, ReconciliationFinding
from app.reconciliation.auto_heal import AUTO_REQUESTER, auto_heal_once
from app.reconciliation.service import observe_once


class AutoHealTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.RepairTests('test_check_mode_is_strictly_read_only_and_stages_nothing')
        self.fx.setUp()
        self.now = self.fx.start + timedelta(seconds=16)

    def tearDown(self):
        self.fx.tearDown()

    def heal(self):
        return auto_heal_once(session_factory=self.fx.factory,
                              adapter=self.fx.ryu, sleep=lambda _: None,
                              now=self.now)

    def test_confirmed_missing_heals_once_and_does_not_change_revision_or_outbox(self):
        result = self.heal()
        self.assertEqual('succeeded', result['status'])
        self.assertEqual([self.fx.b], self.fx.ryu.adds)
        self.assertEqual([], self.fx.ryu.deletes)
        self.assertEqual(0, self.fx.count(fixtures.OutboxEvent))
        with self.fx.factory() as db:
            op = db.get(PolicyOperation, result['operation_id'])
            self.assertEqual(AUTO_REQUESTER, op.requester_id)
            self.assertEqual('auto:' + self.fx.finding_id, op.idempotency_key)
            self.assertIsNone(op.airflow_run_id)
            self.assertEqual('succeeded', op.status)
            self.assertEqual(1, db.get(fixtures.PolicyRecord, self.fx.policy_id).revision)
            self.assertIsNotNone(db.get(ReconciliationFinding, self.fx.finding_id).resolved_at)
        self.assertIsNone(self.heal())
        self.assertEqual(1, len(self.fx.ryu.adds))

    def test_unconfirmed_missing_never_repairs(self):
        with self.fx.factory.begin() as db:
            db.get(ReconciliationFinding, self.fx.finding_id).confirmed_at = None
        self.assertIsNone(self.heal())
        self.assertEqual([], self.fx.ryu.adds)

    def test_stale_finding_is_not_actuated_on_startup(self):
        self.now += timedelta(minutes=3)
        self.assertIsNone(self.heal())
        self.assertEqual(0, self.fx.count(PolicyOperation))

    def test_unknown_observation_breaks_confirmation_and_prevents_repair(self):
        self.fx.ryu.fail_read = True
        observe_once(session_factory=self.fx.factory, adapter=self.fx.ryu,
                     now=self.fx.start + timedelta(seconds=30))
        self.now = self.fx.start + timedelta(seconds=31)
        self.assertIsNone(self.heal())
        self.assertEqual([], self.fx.ryu.adds)

    def test_pending_user_operation_prevents_auto_repair(self):
        with self.fx.factory.begin() as db:
            db.add(PolicyOperation(id='user-pending', policy_id=self.fx.policy_id,
                                   operation_type='disable', requested_revision_id=self.fx.rev_id,
                                   requester_id='user', idempotency_key='user-pending',
                                   request_hash='x'*64, status='pending'))
        self.assertEqual('refused', self.heal()['status'])
        self.assertEqual([], self.fx.ryu.adds)

    def test_foreign_slot_fails_closed_and_does_not_retry_episode(self):
        self.fx.ryu.flows.append(fixtures.flow('10.0.0.3/32','10.0.0.2/32', cookie=333))
        result = self.heal()
        self.assertEqual('failed', result['status'])
        self.assertEqual([], self.fx.ryu.adds)
        self.fx.ryu.flows.pop()
        self.assertIsNone(self.heal())  # failure is durable, no automatic retry
        self.assertEqual(1, self.fx.count(PolicyOperation))

    def test_unresolved_keeps_lock_and_never_retries(self):
        self.fx.ryu.fail_after_add = True
        result = self.heal()
        self.assertEqual('unresolved', result['status'])
        self.assertEqual(1, self.fx.count(fixtures.ScopeReservation))
        self.assertIsNone(self.heal())
        self.assertEqual(1, len(self.fx.ryu.adds))

    def test_auto_does_not_undo_valid_external_restore(self):
        self.fx.ryu.flows.append(self.fx.b.copy())
        result = self.heal()
        self.assertEqual('succeeded', result['status'])
        self.assertEqual('already_present_no_write', result['reason'])
        self.assertEqual([], self.fx.ryu.adds)

    def test_already_staged_auto_attempt_is_skipped_after_restart(self):
        with self.fx.factory.begin() as db:
            db.add(PolicyOperation(id='earlier-attempt', policy_id=self.fx.policy_id,
                                   operation_type='reconcile', requested_revision_id=self.fx.rev_id,
                                   requester_id=AUTO_REQUESTER,
                                   idempotency_key='auto:' + self.fx.finding_id,
                                   request_hash='x'*64, status='failed'))
        self.assertIsNone(self.heal())
        self.assertEqual([], self.fx.ryu.adds)

    def test_two_missing_flows_are_not_repaired_in_one_cycle(self):
        # Second flow was already confirmed in setUp; make the first missing too.
        self.fx.ryu.flows.clear()
        observe_once(session_factory=self.fx.factory, adapter=self.fx.ryu,
                     now=self.fx.start + timedelta(seconds=30))
        observe_once(session_factory=self.fx.factory, adapter=self.fx.ryu,
                     now=self.fx.start + timedelta(seconds=45))
        self.now = self.fx.start + timedelta(seconds=46)
        first = self.heal()
        self.assertEqual('succeeded', first['status'])
        self.assertEqual(1, len(self.fx.ryu.adds))
        second = self.heal()  # A separate cycle is needed for the other finding.
        self.assertEqual('succeeded', second['status'])
        self.assertEqual(2, len(self.fx.ryu.adds))
        self.assertEqual(2, self.fx.count(PolicyOperation))

    def test_auto_respects_operator_opt_in_and_once_mode(self):
        # `--once` remains a strictly observation-only diagnostic even with env on.
        from app.cli import observe_flows
        with patch.dict('os.environ', {'LLNET_AUTO_HEAL':'true'}), \
             patch('sys.argv', ['observe_flows', '--once']), \
             patch.object(observe_flows, 'observe_once', return_value={'healthy':2}), \
             patch.object(observe_flows, 'auto_heal_once') as auto:
            observe_flows.main()
            auto.assert_not_called()

    def test_auto_off_by_default_in_poll_mode(self):
        from app.cli import observe_flows
        class StopLoop(Exception):
            pass
        with patch.dict('os.environ', {'LLNET_AUTO_HEAL':'false'}), \
             patch('sys.argv', ['observe_flows','--interval','15']), \
             patch.object(observe_flows, 'observe_once', return_value={'healthy':2}), \
             patch.object(observe_flows, 'auto_heal_once') as auto, \
             patch.object(observe_flows.time, 'sleep', side_effect=StopLoop):
            with self.assertRaises(StopLoop):
                observe_flows.main()
            auto.assert_not_called()

    def test_auto_on_in_poll_mode_calls_once_after_observation(self):
        from app.cli import observe_flows
        class StopLoop(Exception):
            pass
        with patch.dict('os.environ', {'LLNET_AUTO_HEAL':'true'}), \
             patch('sys.argv', ['observe_flows','--interval','15']), \
             patch.object(observe_flows, 'observe_once', return_value={'healthy':1, 'confirmed':1}), \
             patch.object(observe_flows, 'auto_heal_once', return_value=None) as auto, \
             patch.object(observe_flows.time, 'sleep', side_effect=StopLoop):
            with self.assertRaises(StopLoop):
                observe_flows.main()
            auto.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
