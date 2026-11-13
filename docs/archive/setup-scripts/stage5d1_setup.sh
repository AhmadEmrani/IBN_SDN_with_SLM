#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

MODEL_DIR="models/llnet-phi"

echo "Checking existing Phi model..."

mapfile -d '' models < <(
  find "$MODEL_DIR" -maxdepth 1 -type f -iname '*.gguf' -print0
)

if [[ "${#models[@]}" -ne 1 ]]; then
  echo "ERROR: Expected exactly one GGUF model in $MODEL_DIR"
  echo "Found: ${#models[@]}"
  exit 1
fi

MODEL_FILE=$(basename "${models[0]}")

echo "Model found: $MODEL_FILE"

python3 - "$MODEL_FILE" <<'PY'
from pathlib import Path
import sys

model_file = sys.argv[1]

# Update Compose model path.
compose = Path("compose.stage5d.yml")
content = compose.read_text()

import re

content, count = re.subn(
    r"(?m)^(\s*-\s*)/models/[^\n]+\.gguf\s*$",
    lambda m: m.group(1) + "/models/" + model_file,
    content,
)

if count != 1:
    raise SystemExit("ERROR: Could not update model path in compose.stage5d.yml")

compose.write_text(content)

# Register all Compose files.
env = Path(".env")

if not env.exists():
    raise SystemExit("ERROR: .env missing")

lines = [
    line for line in env.read_text().splitlines()
    if not line.startswith("COMPOSE_FILE=")
]

lines.append(
    "COMPOSE_FILE=docker-compose.yml:compose.stage5c.yml:compose.stage5d.yml"
)

env.write_text("\n".join(lines) + "\n")
env.chmod(0o600)

print("Docker Compose configured")
PY

docker compose config --quiet

echo "Stage 5D.1 setup completed successfully."