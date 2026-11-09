"""Offline API tests; no BGE download or live service required."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.intents import retriever_api as api


class FakeEncoder:
    def __call__(self, texts):
        return [[float(len(t) % 13 + 1), float('block' in t.lower()), 1.0] for t in texts]


class RetrieverApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict('os.environ', {'LLNET_RETRIEVAL_INDEX':
                       str(Path(self.temp.name) / 'index.json')})
        self.environment.start()
        self.encoder = patch.object(api, '_encoder', return_value=FakeEncoder())
        self.encoder.start()
        # No lifespan request; the fake encoder suffices for endpoint tests.
        self.client = TestClient(api.app)

    def tearDown(self):
        self.encoder.stop()
        self.environment.stop()
        self.temp.cleanup()

    def test_health(self):
        self.assertEqual(200, self.client.get('/health').status_code)

    def test_real_http_retrieval_json_contract(self):
        r = self.client.post('/v1/retrieve', json={'text': 'Block TCP traffic from h1 to h2.'})
        self.assertEqual(200, r.status_code)
        data = r.json()
        self.assertEqual(3, len(data['retrieved']))
        self.assertNotIn('expected_policy', str(data))
        self.assertNotIn('messages', data)

    def test_index_cache_reused(self):
        body = {'text': 'Block TCP traffic from h1 to h2.'}
        self.assertFalse(self.client.post('/v1/retrieve', json=body).json()['index_cache_hit'])
        self.assertTrue(self.client.post('/v1/retrieve', json=body).json()['index_cache_hit'])

    def test_disabled_capability_rejected(self):
        r = self.client.post('/v1/retrieve', json={'text':'rate limit h1', 'capability':'rate_limit'})
        self.assertEqual(422, r.status_code)

    def test_invalid_request_rejected(self):
        for body in ({'text':''}, {'text':'x', 'top_k': 11}, {'text':'x', 'unknown':1}):
            self.assertEqual(422, self.client.post('/v1/retrieve', json=body).status_code)

    def test_prepare_contains_only_selected_fewshot_data(self):
        r = self.client.post('/v1/prepare', json={'text':'Block from h1 to h2'})
        self.assertEqual(200, r.status_code)
        data = r.json()
        self.assertEqual(8, len(data['messages']))  # 1 system + 6 examples + 1 user
        self.assertEqual('user', data['messages'][-1]['role'])
        self.assertNotIn('expected_policy', str(data))
        self.assertNotIn('fixture_id', str(data))


if __name__ == '__main__':
    unittest.main()
