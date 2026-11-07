"""LLNet v0.2 Stage-3 orchestration only. No Ryu access or policy DB drivers.

Airflow executes HTTP steps. Backend owns DB state, OpenFlow, and verification.
"""
import os
import uuid
import httpx
import pendulum
from airflow.sdk import dag, task, get_current_context


BASE = os.environ.get('LLNET_POLICY_API_URL', 'http://policy-api:8000').rstrip('/')


def step(method, operation_id, suffix, *, timeout=15):
    token = os.environ.get('LLNET_INTERNAL_TOKEN', '')
    if not token:
        raise RuntimeError('LLNET_INTERNAL_TOKEN is missing')
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=5)) as client:
        resp = client.request(method, f'{BASE}/api/v1/internal/operations/{operation_id}/{suffix}',
                              headers={'X-Internal-Token': token})
        resp.raise_for_status()
        data = resp.json()
    if data.get('operation_id') != operation_id:
        raise RuntimeError('Operation ID mismatch in backend response')
    return data


@dag(
    dag_id='llnet_policy_operation',
    description='LLNet policy operation: preflight, execute, verify',
    start_date=pendulum.datetime(2026, 1, 1, tz='UTC'),
    schedule=None, catchup=False, max_active_runs=4,
    tags=['llnet', 'sdn', 'stage3'],
)
def policy_workflow():
    @task(retries=3, retry_delay=pendulum.duration(seconds=10))
    def preflight():
        conf = get_current_context()['dag_run'].conf or {}
        op_id = conf.get('operation_id')
        try:
            uuid.UUID(op_id)
        except (TypeError, ValueError, AttributeError):
            raise ValueError('Valid UUID operation_id required in DagRun conf') from None
        step('GET', op_id, 'preflight')
        return op_id

    @task(retries=0, execution_timeout=pendulum.duration(seconds=150))
    def execute(op_id):
        # The single backend execution method handles network side effects.
        # No Airflow automatic retries here: ambiguous outcomes await recovery.
        return step('POST', op_id, 'execute', timeout=120)

    @task(retries=2, retry_delay=pendulum.duration(seconds=5))
    def verify(result):
        return step('GET', result['operation_id'], 'result')

    verify(execute(preflight()))


policy_workflow()
