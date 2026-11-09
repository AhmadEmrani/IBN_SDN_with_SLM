"""Stage 5C BGE retrieval service. Read-only, localhost-bound via Compose.

This API does not classify user intent, call Phi, access inventory, or deploy policy.
The `capability` value is an explicit caller selection in v1, not an AI decision.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.intents.retrieval import (BGE_MODEL, RetrievalError, assemble_messages,
                                   capability_info, load_bge_encoder, retrieve)


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=4000)
    capability: str = 'firewall'
    top_k: int = Field(default=3, ge=1, le=10)


@lru_cache(maxsize=1)
def _encoder():
    model_id = os.environ.get('LLNET_BGE_MODEL', BGE_MODEL)
    return load_bge_encoder(model_id)


def _retrieve(request: RetrievalRequest) -> dict:
    try:
        capability_info(request.capability)  # Fail before invoking BGE for disabled capabilities.
        return retrieve(
            request.text,
            capability=request.capability,
            encoder=_encoder(),
            model_id=os.environ.get('LLNET_BGE_MODEL', BGE_MODEL),
            top_k=request.top_k,
            cache_path=Path(os.environ.get('LLNET_RETRIEVAL_INDEX',
                                           '/var/cache/llnet/index/firewall-v1.json')),
        )
    except RetrievalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail startup rather than accept requests without the model.
    _encoder()
    yield


app = FastAPI(title='LLNet Read-only BGE Retriever', version='0.5c', lifespan=lifespan)


@app.get('/health')
def health():
    return {'status': 'ok', 'model': os.environ.get('LLNET_BGE_MODEL', BGE_MODEL)}


@app.post('/v1/retrieve')
def retrieve_api(request: RetrievalRequest):
    result = _retrieve(request)
    return {
        'index_version': result['index_version'],
        'model_id': result['model_id'],
        'corpus_fingerprint': result['corpus_fingerprint'],
        'index_cache_hit': result['index_cache_hit'],
        'capability': result['capability'],
        'retrieved': [
            {'example_id': ex['id'], 'score': ex['score'],
             'status': ex['expected_model_result']['status']}
            for ex in result['examples']
        ],
    }


@app.post('/v1/prepare')
def prepare_prompt(request: RetrievalRequest):
    """Internal lab endpoint: prepare inert few-shot messages, no inference."""
    result = _retrieve(request)
    return {'model_id': result['model_id'],
            'capability': result['capability'],
            'retrieved_example_ids': [ex['id'] for ex in result['examples']],
            'messages': assemble_messages(request.text, result)}
