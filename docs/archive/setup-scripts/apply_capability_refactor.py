#!/usr/bin/env python3
"""Apply capability boundaries to the verified refactor/stages application tree.

Transactional preflight: check all expected anchors before changing any file.
Run in repository root after extracting the overlay. Does not touch DB or Docker.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def replace_between(text: str, begin: str, end: str, content: str, rel: str) -> str:
    if begin not in text or end not in text or text.count(begin) != 1:
        raise RuntimeError(f"unexpected source layout: {rel} ({begin!r})")
    before, rest = text.split(begin, 1)
    _middle, after = rest.split(end, 1)
    return before + content + end + after


def replace_once(text: str, before: str, after: str, rel: str) -> str:
    if text.count(before) != 1:
        raise RuntimeError(f"unexpected source layout: {rel} ({before[:64]!r})")
    return text.replace(before, after, 1)


def main():
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT,
                            text=True, capture_output=True, check=True).stdout.strip()
    if branch != "refactor/stages":
        raise RuntimeError(f"expected refactor/stages, got {branch!r}")
    changes = {}

    rel = "policy-manager/app/intents/orchestrator_service.py"
    t = (ROOT / rel).read_text(encoding="utf-8")
    t = replace_once(t, 'from app.intents.requests import TranslateRequest\n',
        'from app.intents.requests import TranslateRequest\n'
        'from app.intents.capability_registry import (require_enabled, CapabilityUnavailable, CapabilityConfigurationError)\n', rel)
    t = replace_between(t, 'def _check_capability(capability: str) -> None:\n',
        '\ndef _parse_model_json(',
        'def _check_capability(capability: str) -> None:\n'
        '    try:\n'
        '        require_enabled(capability)\n'
        '    except CapabilityUnavailable as exc:\n'
        '        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc\n'
        '    except CapabilityConfigurationError as exc:\n'
        '        raise HTTPException(status_code=503, detail={"code": str(exc)}) from exc\n', rel)
    changes[rel] = t

    rel = "policy-manager/app/intents/retrieval.py"
    t = (ROOT / rel).read_text(encoding="utf-8")
    t = replace_once(t, 'from typing import Any, Callable\n',
        'from typing import Any, Callable\n'
        'from app.intents.capability_registry import require_enabled, CapabilityUnavailable, CapabilityConfigurationError\n', rel)
    t = replace_between(t, 'def capability_info(capability: str, registry_path: Path = REGISTRY) -> dict:\n',
        '\ndef load_corpus(',
        'def capability_info(capability: str, registry_path: Path = REGISTRY) -> dict:\n'
        '    try:\n'
        '        return require_enabled(capability, path=registry_path)\n'
        '    except (CapabilityUnavailable, CapabilityConfigurationError) as exc:\n'
        '        raise RetrievalError(str(exc)) from exc\n', rel)
    changes[rel] = t

    rel = "policy-manager/app/intents/adapter.py"
    t = (ROOT / rel).read_text(encoding="utf-8")
    t = replace_once(t, 'from app.services.compiler import compile_policy\n',
        'from app.services.compiler import compile_policy\n'
        'from app.intents.capability_registry import require_enabled, CapabilityUnavailable\n', rel)
    t = replace_once(t,
        '    registry = _schema(CAPABILITIES_PATH)\n'
        '    enabled = {entry["id"] for entry in registry["capabilities"] if entry.get("enabled")}\n'
        '    status = result["status"]\n'
        '    capability = result["capability"]\n',
        '    status = result["status"]\n'
        '    capability = result["capability"]\n', rel)
    t = replace_once(t,
        '    if capability not in enabled:\n'
        '        raise IntentContractError("capability_disabled")\n',
        '    try:\n'
        '        require_enabled(capability)\n'
        '    except CapabilityUnavailable as exc:\n'
        '        raise IntentContractError(str(exc)) from exc\n', rel)
    changes[rel] = t

    rel = "policy-manager/app/intents/capability_routing.py"
    t = (ROOT / rel).read_text(encoding="utf-8")
    t = replace_once(t, 'from app.intents.retrieval import BGE_MODEL, QUERY_INSTRUCTION, _normalized, _dot, _get_corpus_vectors\n',
        'from app.intents.retrieval import BGE_MODEL, QUERY_INSTRUCTION, _normalized, _dot, _get_corpus_vectors\n'
        'from app.intents.capability_registry import enabled_map\n', rel)
    t = replace_once(t,
        "    enabled={x['id']:bool(x.get('enabled')) for x in json.loads(REGISTRY.read_text())['capabilities']}\n",
        '    enabled = enabled_map()\n', rel)
    changes[rel] = t

    rel = "policy-manager/app/intents/dry_run_service.py"
    t = (ROOT / rel).read_text(encoding="utf-8")
    t = replace_once(t,
        'from app.intents.adapter import IntentContractError, adapt_model_result\n',
        'from app.intents.adapter import IntentContractError\n'
        'from app.intents.capability_preview import build_preview\n', rel)
    t = replace_once(t,
        'from app.schemas.policy import PolicyInput\nfrom app.services.compiler import compile_policy\n', '', rel)
    t = replace_between(t,
        '        converted = adapt_model_result(\n',
        '    except (IntentContractError, ValueError) as exc:\n',
        '        preview = build_preview(\n'
        '            translation["model_result"], context=context, network_id=request.network_id,\n'
        '            intent_id=intent_id, allow_fixture=allow_fixture,\n'
        '        )\n', rel)
    t = replace_once(t,
        '        "policy": policy.model_dump(mode="json"),\n'
        '        "compiled_flows": flows,\n',
        '        "policy": preview["policy"],\n'
        '        "compiled_flows": preview["compiled_flows"],\n', rel)
    changes[rel] = t

    rel = "infra/docker/intent-api/Dockerfile"
    t = (ROOT / rel).read_text(encoding="utf-8")
    t = replace_once(t,
        'COPY policy-manager/tests/test_intent_architecture.py /workspace/policy-manager/tests/test_intent_architecture.py\n',
        'COPY policy-manager/tests/test_intent_architecture.py /workspace/policy-manager/tests/test_intent_architecture.py\n'
        'COPY policy-manager/tests/test_capability_boundaries.py /workspace/policy-manager/tests/test_capability_boundaries.py\n', rel)
    changes[rel] = t

    # Ensure all preflight checks passed before writing anything.
    for rel, body in changes.items():
        compile(body, rel, 'exec') if rel.endswith('.py') else None
    for rel, body in changes.items():
        (ROOT / rel).write_text(body, encoding="utf-8")
    print("PASS: capability registry, preview dispatcher and API boundaries integrated")
    print("Changed files:")
    for rel in changes:
        print("  ", rel)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        sys.exit(1)
