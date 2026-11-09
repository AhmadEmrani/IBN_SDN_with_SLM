"""Stage 5C: read-only BGE few-shot retrieval. No network/DB/actuation paths.

Callers select an enabled capability through a trusted router (not by guessing
from similarity scores). Model generation and routing are NOT implemented here.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / 'data/intents/stage5a/firewall-contract-seed.jsonl'
REGISTRY = ROOT / 'contracts/intent-v1/capabilities.json'
SCHEMA = ROOT / 'contracts/intent-v1/model-result.schema.json'
PROMPTS = ROOT / 'prompts/intents/v1'
BGE_MODEL = 'BAAI/bge-small-en-v1.5'
QUERY_INSTRUCTION = 'Represent this sentence for searching relevant passages: '
INDEX_VERSION = 'stage5c-v1'


class RetrievalError(ValueError):
    pass


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def capability_info(capability: str, registry_path: Path = REGISTRY) -> dict:
    if not isinstance(capability, str):
        raise RetrievalError('capability must be a string')
    for entry in read_json(registry_path)['capabilities']:
        if entry['id'] == capability:
            if not entry.get('enabled', False):
                raise RetrievalError('capability_disabled: ' + capability)
            if not entry.get('prompt'):
                raise RetrievalError('missing capability prompt')
            return entry
    raise RetrievalError('unknown_capability: ' + capability)


def load_corpus(path: Path = SEEDS, *, capability: str = 'firewall',
                registry_path: Path = REGISTRY) -> list[dict]:
    entry = capability_info(capability, registry_path)
    records = []
    seen = set()
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('split') != 'contract_seed' or row.get('retrieval_eligible') is not True:
            continue
        response = row.get('expected_model_result', {})
        # Negative examples for a disabled capability are intentionally not used
        # for an enabled firewall prompt; no forced routing from another class.
        if response.get('capability') != capability:
            continue
        if response.get('contract_version') != entry['backend_schema_version']:
            continue
        if row.get('language') != 'en':
            continue
        identifier = row.get('example_id')
        request = row.get('request', {})
        if not isinstance(identifier, str) or identifier in seen:
            raise RetrievalError('duplicate/invalid example ID at line ' + str(number))
        if not isinstance(request.get('text'), str) or not request['text'].strip():
            raise RetrievalError('missing request.text at line ' + str(number))
        if response.get('status') not in ('ready', 'needs_clarification', 'unsupported'):
            raise RetrievalError('unknown status at line ' + str(number))
        seen.add(identifier)
        # Minimal trusted whitelist: no expected_policy, fixture ID, note, or
        # metadata ever enter the prompt assembly path.
        records.append({'id': identifier, 'text': request['text'], 'result': response})
    if not records:
        raise RetrievalError('no eligible examples for ' + capability)
    return records


def _normalized(vector: Any) -> list[float]:
    try:
        values = [float(x) for x in vector]
    except (TypeError, ValueError, OverflowError) as exc:
        raise RetrievalError('invalid embedding vector') from exc
    if not values or any(not math.isfinite(x) for x in values):
        raise RetrievalError('empty/nonfinite embedding')
    norm = math.sqrt(sum(x*x for x in values))
    if norm <= 0 or not math.isfinite(norm):
        raise RetrievalError('zero/nonfinite embedding norm')
    return [x / norm for x in values]


def _dot(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise RetrievalError('embedding dimensions differ')
    return sum(a*b for a, b in zip(left, right))


def _fingerprint(rows: list[dict], model_id: str, capability: str) -> str:
    payload = {'index_version': INDEX_VERSION, 'model': model_id, 'capability': capability,
               'data': [{'id': r['id'], 'text': r['text'], 'result': r['result']} for r in rows]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _valid_cache(cache: dict, fingerprint: str, count: int) -> list[list[float]] | None:
    if cache.get('fingerprint') != fingerprint or cache.get('index_version') != INDEX_VERSION:
        return None
    vecs = cache.get('vectors')
    if not isinstance(vecs, list) or len(vecs) != count:
        return None
    try:
        normed = [_normalized(v) for v in vecs]
        if len({len(v) for v in normed}) != 1:
            return None
        return normed
    except RetrievalError:
        return None


def _get_corpus_vectors(rows: list[dict], *, encoder: Callable[[list[str]], Any],
                        model_id: str, capability: str, cache_path: Path | None) -> tuple[list[list[float]], bool, str]:
    fingerprint = _fingerprint(rows, model_id, capability)
    if cache_path is not None and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding='utf-8'))
            restored = _valid_cache(cache, fingerprint, len(rows))
            if restored is not None:
                return restored, True, fingerprint
        except (ValueError, OSError, TypeError):
            pass
    raw = encoder([r['text'] for r in rows])
    vecs = [_normalized(v) for v in raw]
    if len(vecs) != len(rows) or len({len(v) for v in vecs}) != 1:
        raise RetrievalError('encoder returned invalid corpus dimensions')
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_name(cache_path.name + '.tmp.' + str(os.getpid()))
        try:
            tmp.write_text(json.dumps({'index_version': INDEX_VERSION,
                            'fingerprint': fingerprint, 'vectors': vecs}), encoding='utf-8')
            tmp.replace(cache_path)
        finally:
            tmp.unlink(missing_ok=True)
    return vecs, False, fingerprint


def retrieve(text: str, *, capability: str, encoder: Callable[[list[str]], Any],
             model_id: str, top_k: int = 3, cache_path: Path | None = None,
             corpus_path: Path = SEEDS, registry_path: Path = REGISTRY,
             query_instruction: str = QUERY_INSTRUCTION) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise RetrievalError('text must contain 1..4000 characters')
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 10:
        raise RetrievalError('top_k must be between 1 and 10')
    if not model_id or not isinstance(model_id, str):
        raise RetrievalError('model_id is required')
    rows = load_corpus(corpus_path, capability=capability, registry_path=registry_path)
    vectors, cached, fingerprint = _get_corpus_vectors(
        rows, encoder=encoder, model_id=model_id, capability=capability, cache_path=cache_path)
    query_vectors = list(encoder([query_instruction + text]))
    if len(query_vectors) != 1:
        raise RetrievalError('encoder returned invalid query count')
    query_vector = _normalized(query_vectors[0])
    ranked = sorted(((round(_dot(query_vector, vector), 10), row) for vector, row in zip(vectors, rows)),
                    key=lambda pair: (-pair[0], pair[1]['id']))
    chosen = ranked[:top_k]
    return {'index_version': INDEX_VERSION, 'model_id': model_id,
            'corpus_fingerprint': fingerprint, 'index_cache_hit': cached,
            'capability': capability, 'examples': [
                {'id': row['id'], 'score': score, 'text': row['text'],
                 'expected_model_result': row['result']} for score, row in chosen]}


def assemble_messages(text: str, retrieval: dict, *,
                      schema_path: Path = SCHEMA, prompts_path: Path = PROMPTS,
                      registry_path: Path = REGISTRY) -> list[dict]:
    """Construct inert chat messages; no Phi calls, no live network context.

    Trusted inventory must be added by the future orchestration layer after
    authentication, never taken from user text or Stage 5A fixture automatically.
    """
    capability = retrieval['capability']
    entry = capability_info(capability, registry_path)
    if not isinstance(text, str) or not text.strip():
        raise RetrievalError('missing user text')
    system = (prompts_path / 'system.md').read_text(encoding='utf-8')
    capability_prompt = (ROOT / entry['prompt']).read_text(encoding='utf-8')
    schema = read_json(schema_path)
    messages = [{'role': 'system', 'content': system + '\n\n' + capability_prompt +
                '\n\nOutput schema (JSON):\n' + json.dumps(schema, ensure_ascii=False)}]
    for ex in retrieval['examples']:
        # Deliberately no example IDs, expected policy, labels, notes, or scores.
        messages.append({'role': 'user', 'content': ex['text']})
        messages.append({'role': 'assistant', 'content': json.dumps(ex['expected_model_result'], ensure_ascii=False)})
    messages.append({'role': 'user', 'content': text})
    return messages


def load_bge_encoder(model_id: str = BGE_MODEL, *, local_files_only: bool = False):
    """Lazy import: tests and offline CLI checks do not download a model."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RetrievalError('install requirements-stage5c.txt for BGE inference') from exc
    model = SentenceTransformer(model_id, device='cpu', local_files_only=local_files_only)
    def encode(texts: list[str]):
        return model.encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
    return encode
