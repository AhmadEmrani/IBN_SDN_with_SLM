#!/usr/bin/env python3
"""Read-only verification of the unified LLNet Compose infrastructure."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    'postgres','ryu-controller','mininet-net','policy-api','airflow-db',
    'airflow-auth-init','airflow-init','airflow-api-server','airflow-dag-processor',
    'airflow-scheduler','policy-dispatcher','policy-reconciler',
    'intent-retriever','phi-inference','intent-orchestrator'
}

def main():
    cp = subprocess.run(['docker','compose','config','--format','json'], cwd=ROOT,
                        capture_output=True, text=True)
    if cp.returncode:
        raise ValueError('docker compose config failed; check local secrets/settings')
    obj=json.loads(cp.stdout)
    assert obj['name']=='sdn-mininet-ryu', 'compose project name mismatch'
    assert set(obj['services'])==EXPECTED, 'compose service set mismatch'
    expected_volumes={'postgres_data','airflow_db_data','airflow_logs','airflow_auth',
                      'llnet_bge_models','llnet_retrieval_index'}
    assert set(obj['volumes'])==expected_volumes, 'compose volume names mismatch'
    assert not any(line.lstrip().startswith('COMPOSE_FILE=') for line in (ROOT/'.env').read_text().splitlines()), 'legacy COMPOSE_FILE still in .env'
    for service in ['policy-api','policy-dispatcher','policy-reconciler']:
        assert obj['services'][service]['build']['dockerfile'].endswith('infra/docker/policy-api/Dockerfile')
    print('PASS: unified Compose, 15 services, 6 volumes, single policy backend image definition')

if __name__=='__main__':
    try:main()
    except (AssertionError, ValueError, OSError, KeyError, subprocess.SubprocessError) as e:
        print('FAIL:', str(e),file=sys.stderr)
        raise SystemExit(1)
