"""Test real Airflow 3 REST contract with an in-memory HTTP transport."""
import unittest
import httpx
from app.adapters.airflow_adapter import AirflowClient, AirflowDeliveryError


class AirflowAdapterTests(unittest.TestCase):
    def setUp(self):
        self.runs = {}
        self.token_calls = 0
        self.post_calls = 0
        self.invalid_get = False

        def api(request):
            if request.url.path == '/auth/token':
                self.token_calls += 1
                return httpx.Response(200, json={'access_token': 'fake-token'})
            self.assertEqual('Bearer fake-token', request.headers.get('authorization'))
            path = request.url.path
            root = '/api/v2/dags/llnet_policy_operation/dagRuns'
            if request.method == 'POST' and path == root:
                self.post_calls += 1
                payload = __import__('json').loads(request.content)
                run_id = payload['dag_run_id']
                self.assertIsNone(payload['logical_date'])
                if run_id in self.runs:
                    return httpx.Response(409, json={'detail':'already exists'})
                self.runs[run_id] = payload
                return httpx.Response(200, json=payload)
            if request.method == 'GET' and path.startswith(root + '/'):
                run_id = path.split('/')[-1]
                if run_id not in self.runs:
                    return httpx.Response(404)
                data = dict(self.runs[run_id])
                if self.invalid_get:
                    data['conf'] = {'operation_id': 'wrong'}
                return httpx.Response(200, json=data)
            return httpx.Response(404)

        self.client = AirflowClient(base_url='http://airflow:8080', username='llnet',
                                    password='fake', transport=httpx.MockTransport(api))

    def test_one_run_id_is_stable_across_redelivery(self):
        run_id = self.client.trigger('11111111-1111-4111-8111-111111111111')
        self.assertEqual('llnet__11111111-1111-4111-8111-111111111111', run_id)
        self.assertEqual(run_id, self.client.trigger('11111111-1111-4111-8111-111111111111'))
        self.assertEqual(1, len(self.runs))
        self.assertEqual(2, self.post_calls)

    def test_409_does_not_ack_run_owned_by_someone_else(self):
        opid = '22222222-2222-4222-8222-222222222222'
        self.client.trigger(opid)
        self.invalid_get = True
        with self.assertRaises(AirflowDeliveryError):
            self.client.trigger(opid)

    def test_missing_password_rejected(self):
        from unittest.mock import patch
        with patch.dict('os.environ', {'AIRFLOW_LAB_PASSWORD':''}):
            with self.assertRaises(AirflowDeliveryError):
                AirflowClient(password='')


if __name__ == '__main__':
    unittest.main()
