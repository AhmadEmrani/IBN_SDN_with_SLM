#!/usr/bin/env python3
"""Idempotent Compose edit: add operator-only fixture mode, retain Phi config."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
compose = root / "compose.stage5d.yml"
text = compose.read_text(encoding="utf-8")
if "  intent-orchestrator:" not in text:
    raise SystemExit("ERROR: Stage 5D.2 intent-orchestrator service not found")
if "LLNET_DRY_RUN_CONTEXT_MODE:" in text:
    print("Already configured; preserving current context mode")
else:
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if "LLNET_PHI_TIMEOUT_SECONDS:" in line and line.startswith("      "):
            lines.insert(i + 1, "      LLNET_DRY_RUN_CONTEXT_MODE: fixture\n")
            break
    else:
        raise SystemExit("ERROR: expected Stage 5D.2 environment anchor not found")
    compose.write_text("".join(lines), encoding="utf-8")
    print("Fixture-only Dry Run enabled in Compose (operator-side)")
print("Stage 5D.3 install ready. Existing Compose files and Phi mount retained.")
