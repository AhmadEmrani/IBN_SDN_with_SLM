import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app


class Stage3InternalTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.path = '/api/v1/internal/operations/some-id/preflight'

    def test_missing_secret_is_forbidden(self):
        with patch('app.api.audit._write_event'):
            with patch.dict(os.environ, {'LLNET_INTERNAL_TOKEN':'secret-test'}):
                self.assertEqual(403, self.client.get(self.path).status_code)

    def test_wrong_secret_is_forbidden(self):
        with patch('app.api.audit._write_event'):
            with patch.dict(os.environ, {'LLNET_INTERNAL_TOKEN':'secret-test'}):
                self.assertEqual(403, self.client.get(self.path, headers={'X-Internal-Token':'invalid'}).status_code)

    def test_internal_routes_hidden_from_swagger_schema(self):
        docs = self.client.get('/openapi.json').json()['paths']
        self.assertNotIn(self.path, docs)
        self.assertFalse(any('/internal/' in path for path in docs))


if __name__ == '__main__':
    unittest.main()
