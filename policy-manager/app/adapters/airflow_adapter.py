"""Airflow 3 public API adapter. Exactly one stable DagRun id per Operation.

No DB, Ryu, or SQLAlchemy dependencies. Airflow is a scheduler, not the
source of truth for policy state.
"""
from __future__ import annotations
import os
import httpx


class AirflowDeliveryError(RuntimeError):
    pass


class AirflowClient:
    def __init__(self, *, base_url: str | None = None, username: str | None = None,
                 password: str | None = None, transport=None):
        self.base_url = (base_url or os.environ.get('AIRFLOW_API_URL', 'http://airflow-api-server:8080')).rstrip('/')
        self.username = username or os.environ.get('AIRFLOW_USERNAME', 'llnet')
        self.password = password if password is not None else os.environ.get('AIRFLOW_LAB_PASSWORD', '')
        if not self.password:
            raise AirflowDeliveryError('AIRFLOW_LAB_PASSWORD is not configured')
        self.transport = transport

    def _request(self, method: str, path: str, **kwargs):
        with httpx.Client(base_url=self.base_url, timeout=httpx.Timeout(15, connect=5),
                          transport=self.transport) as client:
            token_response = client.post('/auth/token', json={
                'username': self.username, 'password': self.password,
            })
            token_response.raise_for_status()
            token = token_response.json().get('access_token')
            if not isinstance(token, str) or not token:
                raise AirflowDeliveryError('Airflow auth response did not include access_token')
            return client.request(method, path, headers={'Authorization': 'Bearer ' + token}, **kwargs)

    @staticmethod
    def run_id(operation_id: str) -> str:
        return f'llnet__{operation_id}'

    def trigger(self, operation_id: str) -> str:
        run_id = self.run_id(operation_id)
        path = '/api/v2/dags/llnet_policy_operation/dagRuns'
        payload = {
            'dag_run_id': run_id,
            'logical_date': None,
            'conf': {'operation_id': operation_id},
        }
        response = self._request('POST', path, json=payload)
        if response.status_code == 409:
            # An uncertain POST may have succeeded: prove ownership before ACK.
            existing = self._request('GET', path + '/' + run_id)
            existing.raise_for_status()
            data = existing.json()
            if (data.get('dag_run_id') != run_id or
                    (data.get('conf') or {}).get('operation_id') != operation_id):
                raise AirflowDeliveryError('Existing DagRun does not belong to this operation')
            return run_id
        response.raise_for_status()
        data = response.json()
        if (data.get('dag_run_id') != run_id or
                (data.get('conf') or {}).get('operation_id') != operation_id):
            raise AirflowDeliveryError('Airflow trigger response did not confirm operation ownership')
        return run_id
