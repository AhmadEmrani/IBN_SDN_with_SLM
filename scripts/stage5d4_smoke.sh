#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import json
from urllib.request import urlopen,Request

def post(endpoint,payload):
    req=Request('http://127.0.0.1:8094'+endpoint,
                json.dumps(payload).encode(),{'Content-Type':'application/json'},method='POST')
    with urlopen(req,timeout=240) as r: return json.load(r)

health=json.load(urlopen('http://127.0.0.1:8094/health',timeout=15))
print('Health:',health)
assert health['status']=='ok'
for text,category,status in [
    ('Block TCP traffic from h1 to h2 on port 443.','firewall','selected'),
    ('Limit bandwidth from h1 to h2 to 10 Mbps.','rate_limit','unsupported'),
    ('Simulate a synthetic network workload.','load_profile','unsupported'),
    ('Block UDP and throttle bandwidth to 5 Mbps.',None,'multiple'),
    ('Make the network better.',None,'ambiguous'),
]:
    result=post('/v1/intents/route',{'text':text})
    print(text,'=>',result['routing_status'],result.get('capability'))
    assert result['routing_status']==status,(text,result)
    assert result['capability']==category,(text,result)
print('Routing checks PASS')
# Non-firewall must not reach Phi/Adapter/Compiler.
result=post('/v1/intents/dry-run',{'text':'Limit bandwidth from h1 to h2 to 10 Mbps.',
                                    'network_id':'lab','top_k':3})
assert result['status']=='unsupported' and result['policy'] is None and result['compiled_flows']==[]
print('Disabled capability does not compile: PASS')
# Real BGE -> Phi -> Adapter -> Compiler; same API but without capability.
result=post('/v1/intents/dry-run',{'text':'Block TCP traffic from h1 to h2 on port 443.',
                                    'network_id':'lab','top_k':3})
assert result['policy_validated'] and result['context_source']=='lab_fixture',result
assert result['compiled_flows'][0]['match']['tcp_dst']==443,result
assert result['deployment']=='not_requested',result
print('Auto-routed Firewall End-to-End Dry Run: PASS')
PY
