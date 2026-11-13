#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo '== Orchestrator health =='
curl -fsS --max-time 15 http://127.0.0.1:8094/health | python3 -m json.tool
echo '== Real BGE -> Phi -> contract validation (no SDN calls) =='
curl -sS --max-time 240 -X POST http://127.0.0.1:8094/v1/intents/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Block TCP traffic from h1 to h2 on port 443.","capability":"firewall","top_k":3}' \
  -w '\nHTTP_STATUS:%{http_code}\n' | tee /tmp/llnet-stage5d2-response.txt
python3 - <<'PY'
from pathlib import Path
text = Path('/tmp/llnet-stage5d2-response.txt').read_text()
body, marker = text.rsplit('\nHTTP_STATUS:', 1)
import json
print(json.dumps(json.loads(body), indent=2, ensure_ascii=False))
print('HTTP status:', marker.strip())
PY
