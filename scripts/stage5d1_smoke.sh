#!/usr/bin/env bash
set -euo pipefail
base="http://127.0.0.1:8093"
echo 'Checking Phi HTTP health...'
curl --fail --silent --show-error "$base/health" | python3 -m json.tool
echo 'Running real model inference (no network actuation)...'
curl --fail --silent --show-error --max-time 180 \
  -H 'Content-Type: application/json' \
  -d '{"model":"phi-3.5-mini","messages":[{"role":"system","content":"Answer briefly with plain text. You are not connected to any network controller."},{"role":"user","content":"Reply exactly: PHI_READY"}],"temperature":0,"max_tokens":32,"stream":false}' \
  "$base/v1/chat/completions" | python3 -m json.tool
