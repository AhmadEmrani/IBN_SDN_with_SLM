#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo '== Health =='
curl -fsS http://127.0.0.1:8094/health | python3 -m json.tool
echo '== Real BGE -> Phi -> Adapter -> Compiler (LAB FIXTURE ONLY; no SDN writes) =='
body=$(curl -fsS --max-time 240 -X POST http://127.0.0.1:8094/v1/intents/dry-run \
  -H 'Content-Type: application/json' \
  -d '{"text":"Block TCP traffic from h1 to h2 on port 443.","capability":"firewall","top_k":3,"network_id":"lab"}')
python3 - "$body" <<'PY'
import json, sys
r = json.loads(sys.argv[1])
assert r['status'] == 'ready', r
assert r['policy_validated'] is True, r
assert r['deployment'] == 'not_requested', r
assert r['context_source'] == 'lab_fixture', r
m = r['policy']['match']
assert m['source']['value'] == '10.0.0.1/32', m
assert m['destination']['value'] == '10.0.0.2/32', m
assert m['protocol'] == 'tcp' and m['destination_ports'] == [443], m
flows = r['compiled_flows']
assert flows and flows[0]['match']['tcp_dst'] == 443, flows
print(json.dumps({
 'status': r['status'], 'model_validated': r['model_validated'],
 'policy_validated': r['policy_validated'], 'context_source': r['context_source'],
 'match': m, 'flow_count': len(flows), 'compiled_flows': flows,
 'deployment': r['deployment'],
}, indent=2))
print('PASS: Stage 5D.3 dry run')
PY
