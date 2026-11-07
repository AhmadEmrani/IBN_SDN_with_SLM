"""Stage-3 dispatcher tests. SQLite emulates DB, not PostgreSQL SKIP LOCKED."""
import unittest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models import PolicyOperation, OutboxEvent, OperationEvent, PolicyRecord
from app.schemas.policy import PolicyInput
from app.services.submission_service import submit
from app.services.outbox_dispatcher import dispatch_once


@compiles(JSONB, 'sqlite')
def _sqlite_jsonb(_type, _compiler, **_kw):
    return 'JSON'


def definition():
    return PolicyInput.model_validate({
        'schema_version':'1.0', 'policy':{'name':'stage3','type':'firewall'},
        'scope':{'network_id':'mininet-lab','switches':['1']},
        'match':{'source':{'type':'ipv4','value':'10.0.0.2/32'},
                 'destination':{'type':'ipv4','value':'10.0.0.3/32'},
                 'direction':'bidirectional','protocol':'any'},
        'action':{'type':'deny'},
    })


class AirflowFake:
    def __init__(self):
        self.runs = set()
        self.fail = False
    def trigger(self, op_id):
        if self.fail:
            raise RuntimeError('Airflow unavailable')
        self.runs.add(op_id)
        return 'llnet__' + op_id


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite+pysqlite:///:memory:',
            connect_args={'check_same_thread':False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.airflow = AirflowFake()
        self.op = submit('create', requester='user', key='key1', policy=definition(),
                         session_factory=self.factory)

    def tearDown(self):
        self.engine.dispose()

    def test_deliver_pending_event(self):
        self.assertTrue(dispatch_once(session_factory=self.factory, client=self.airflow))
        self.assertFalse(dispatch_once(session_factory=self.factory, client=self.airflow))
        with self.factory() as db:
            op = db.get(PolicyOperation, self.op.operation_id)
            self.assertEqual('queued', op.status)
            self.assertEqual('llnet__' + self.op.operation_id, op.airflow_run_id)
            event = db.scalar(select(OutboxEvent))
            self.assertEqual('delivered', event.dispatch_status)
            self.assertIsNotNone(event.delivered_at)
            self.assertIsNone(event.lease_owner)
            self.assertEqual(1, db.scalar(select(func.count()).select_from(OperationEvent).where(
                OperationEvent.event_type=='operation.dispatched')))

    def test_failed_airflow_delivery_retries_without_ack(self):
        self.airflow.fail = True
        self.assertTrue(dispatch_once(session_factory=self.factory, client=self.airflow))
        with self.factory() as db:
            event = db.scalar(select(OutboxEvent))
            self.assertEqual('pending', event.dispatch_status)
            self.assertEqual(1, event.attempts)
            op = db.get(PolicyOperation, self.op.operation_id)
            self.assertEqual('pending', op.status)
        self.airflow.fail = False
        with self.factory.begin() as db:
            event = db.scalar(select(OutboxEvent))
            event.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.assertTrue(dispatch_once(session_factory=self.factory, client=self.airflow))
        with self.factory() as db:
            self.assertEqual('delivered', db.scalar(select(OutboxEvent)).dispatch_status)

    def test_expired_dispatch_claim_can_be_recovered(self):
        with self.factory.begin() as db:
            event = db.scalar(select(OutboxEvent))
            event.dispatch_status = 'dispatching'
            event.lease_owner = 'crashed-dispatcher'
            event.lease_until = datetime.now(timezone.utc) - timedelta(seconds=5)
        self.assertTrue(dispatch_once(session_factory=self.factory, client=self.airflow))
        with self.factory() as db:
            self.assertEqual('delivered', db.scalar(select(OutboxEvent)).dispatch_status)

    def test_recent_dispatch_claim_is_not_stolen(self):
        with self.factory.begin() as db:
            event = db.scalar(select(OutboxEvent))
            event.dispatch_status = 'dispatching'
            event.lease_owner = 'active-dispatcher'
            event.lease_until = datetime.now(timezone.utc) + timedelta(seconds=50)
        self.assertFalse(dispatch_once(session_factory=self.factory, client=self.airflow))

    def test_terminal_operation_never_triggers_again(self):
        with self.factory.begin() as db:
            op = db.get(PolicyOperation, self.op.operation_id)
            op.status = 'succeeded'
        self.assertTrue(dispatch_once(session_factory=self.factory, client=self.airflow))
        self.assertEqual(set(), self.airflow.runs)
        with self.factory() as db:
            self.assertEqual('delivered', db.scalar(select(OutboxEvent)).dispatch_status)

    def test_claim_does_not_call_ryu(self):
        self.assertTrue(dispatch_once(session_factory=self.factory, client=self.airflow))
        with self.factory() as db:
            self.assertEqual('disabled', db.get(PolicyRecord, self.op.policy_id).desired_state)


if __name__ == '__main__':
    unittest.main()
