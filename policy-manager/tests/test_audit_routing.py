"""Audit route resolution must be accurate and never expose raw path IDs."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.main import app
from app.models.event import APIRequestEvent


@compiles(JSONB, 'sqlite')
def _sqlite_jsonb(_type, _compiler, **_kwargs):
    return 'JSON'


class AuditRoutingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite+pysqlite:///:memory:',
                                    connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.patcher = patch('app.api.audit.SessionLocal', self.factory)
        self.patcher.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.patcher.stop()
        self.engine.dispose()

    def _last_event(self):
        with self.factory() as db:
            return db.scalars(select(APIRequestEvent)).all()[-1]

    def test_missing_required_header_uses_route_template(self):
        response = self.client.post('/api/v1/policies', json={})
        self.assertEqual(422, response.status_code)
        self.assertEqual('/api/v1/policies', self._last_event().route)

    def test_parameterized_path_does_not_leak_identifier(self):
        response = self.client.put('/api/v1/operations/secret-value-should-not-log')
        self.assertGreaterEqual(response.status_code, 400)
        event = self._last_event()
        self.assertEqual('/api/v1/operations/{operation_id}', event.route)
        self.assertNotIn('secret-value', event.route)

    def test_unmatched_path_uses_fixed_sentinel(self):
        response = self.client.get('/does-not-exist/private-token')
        self.assertEqual(404, response.status_code)
        self.assertEqual('/unmatched', self._last_event().route)


if __name__ == '__main__':
    unittest.main()
