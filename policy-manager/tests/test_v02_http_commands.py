"""Route wiring and durable 202 responses without touching Ryu/real DB."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.models.event import APIRequestEvent
from app.main import app
from app.schemas.policy import PolicyInput
from app.services.execution_service import run_operation
from tests.test_v02_lifecycle import FakeRyu, policy


@compiles(JSONB, 'sqlite')
def _sqlite_jsonb(_type, _compiler, **_kwargs):
    return 'JSON'


class PublicCommands(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite+pysqlite:///:memory:',
            connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.patch = patch('app.services.submission_service.SessionLocal', self.factory)
        self.patch.start()
        self.audit_patch = patch('app.api.audit.SessionLocal', self.factory)
        self.audit_patch.start()
        def override_db():
            with self.factory() as db:
                yield db
        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.patch.stop()
        self.audit_patch.stop()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_202_contract_and_history(self):
        body = policy().model_dump(mode='json')
        headers = {'Idempotency-Key': 'my-first-request'}
        response = self.client.post('/api/v1/policies', json=body, headers=headers)
        self.assertEqual(202, response.status_code)
        operation_id = response.json()['operation_id']
        self.assertEqual('pending', response.json()['status'])
        replay = self.client.post('/api/v1/policies', json=body, headers=headers)
        self.assertEqual(202, replay.status_code)
        self.assertEqual(operation_id, replay.json()['operation_id'])
        self.assertFalse(replay.json()['created'])
        operation = self.client.get(f'/api/v1/operations/{operation_id}')
        self.assertEqual(200, operation.status_code)
        self.assertEqual('pending', operation.json()['status'])
        event = self.client.get(f'/api/v1/operations/{operation_id}/events')
        self.assertEqual(1, len(event.json()))
        ryu = FakeRyu()
        self.assertEqual('succeeded', run_operation(operation_id, session_factory=self.factory, adapter=ryu, sleep=lambda _: None))
        self.assertEqual('succeeded', self.client.get(f'/api/v1/operations/{operation_id}').json()['status'])
        policy_id = response.json()['policy_id']
        self.assertEqual('enabled', self.client.get(f'/api/v1/policies/{policy_id}').json()['desired_state'])

    def test_missing_idempotency_key_is_422(self):
        r = self.client.post('/api/v1/policies', json=policy().model_dump(mode='json'))
        self.assertEqual(422, r.status_code)
        with self.factory() as db:
            events = db.scalars(select(APIRequestEvent)).all()
            self.assertEqual(1, len(events))
            self.assertEqual(422, events[0].status_code)
            self.assertEqual('/api/v1/policies', events[0].route)

    def test_change_command_routes_are_separate(self):
        paths = self.client.get('/openapi.json').json()['paths']
        self.assertIn('patch', paths['/api/v1/policies/{policy_id}'])
        self.assertIn('post', paths['/api/v1/policies/{policy_id}/enable'])
        self.assertIn('post', paths['/api/v1/policies/{policy_id}/disable'])
        self.assertIn('delete', paths['/api/v1/policies/{policy_id}'])

if __name__ == '__main__':
    unittest.main()
