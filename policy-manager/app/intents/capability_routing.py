"""Stage 5D.4 semantic capability routing. No Phi, inventory or SDN calls.

The prototype corpus is dedicated to routing, disjoint from Stage 5A few-shots
and evaluation sets. Similarities are *not* calibrated probabilities.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from app.intents.retrieval import BGE_MODEL, QUERY_INSTRUCTION, _normalized, _dot, _get_corpus_vectors
from app.intents.capability_registry import enabled_map

ROOT = Path(__file__).resolve().parents[3]
PROTOTYPES = ROOT / 'data/intents/stage5d4/routing-prototypes.jsonl'
REGISTRY = ROOT / 'contracts/intent-v1/capabilities.json'
ROUTING_INDEX = Path(os.getenv('LLNET_ROUTING_INDEX', '/var/cache/llnet/index/routing-v1.json'))

# Rules are *guards* for explicit multi-intent requests, not a replacement for BGE.
FIREWALL = re.compile(r'\b(block|deny|drop|reject|disallow|prevent|firewall|acl)\b', re.I)
RATE = re.compile(r'\b(throttl\w*|bandwidth|rate.limit\w*|qos|polic\w*|shap\w*|throughput|\d+\s*(?:m|k|g)bps|bit\s*rate)\b', re.I)
LOAD = re.compile(r'\b(simulat\w*|emulat\w*|synthetic|workload|stress.test|load.test|load.profile|traffic.generation|traffic.profile|benchmark\w*|replay\w*)\b', re.I)
VAGUE = re.compile(r'\b(optimi[sz]\w*|improv\w*|better|faster|performance)\b', re.I)


def load_prototypes(path: Path = PROTOTYPES) -> list[dict]:
    records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not records or len({x['id'] for x in records}) != len(records):
        raise ValueError('invalid routing prototypes')
    if {x['capability'] for x in records} != {'firewall', 'rate_limit', 'load_profile'}:
        raise ValueError('routing prototypes must cover all three capabilities')
    return [{'id':r['id'], 'text':r['text'], 'result':{'capability':r['capability']}} for r in records]


def guard_labels(text: str) -> set[str]:
    result=set()
    if FIREWALL.search(text): result.add('firewall')
    if RATE.search(text): result.add('rate_limit')
    if LOAD.search(text): result.add('load_profile')
    return result


def route_intent(text: str, *, encoder, model_id: str = BGE_MODEL,
                 cache_path: Path | None = ROUTING_INDEX,
                 prototype_path: Path = PROTOTYPES,
                 min_score: float = 0.72, min_margin: float = 0.025) -> dict:
    if not isinstance(text,str) or not text.strip() or len(text)>4000:
        raise ValueError('text must contain 1..4000 characters')
    labels = guard_labels(text)
    if len(labels)>1:
        return {'routing_status':'multiple','capability':None,'supported':False,
                'reason_code':'multiple_intents','scores':{},'method':'explicit_multi_guard'}
    if not labels and VAGUE.search(text):
        return {'routing_status':'ambiguous','capability':None,'supported':False,
                'reason_code':'ambiguous_intent','scores':{},'method':'vague_guard'}
    rows=load_prototypes(prototype_path)
    vectors, hit, fingerprint=_get_corpus_vectors(
        rows,encoder=encoder,model_id=model_id,capability='routing',cache_path=cache_path)
    query_vectors=list(encoder([QUERY_INSTRUCTION+text]))
    if len(query_vectors)!=1: raise ValueError('invalid query embedding count')
    vec=_normalized(query_vectors[0])
    scores={cap:-1.0 for cap in ('firewall','rate_limit','load_profile')}
    for r,v in zip(rows,vectors):
        cap=r['result']['capability']
        scores[cap]=max(scores[cap],_dot(vec,v))
    ranking=sorted(scores,key=lambda cap:(-scores[cap],cap))
    best, runnerup=ranking[:2]
    gap=scores[best]-scores[runnerup]
    # If a requested *explicit* category conflicts with similarity, abstain;
    # never silently turn bandwidth limiting into a firewall rule.
    if labels:
        signalled=next(iter(labels))
        if best!=signalled and scores[best]-scores[signalled]>=min_margin:
            status,chosen,reason='ambiguous',None,'routing_conflict'
        elif scores[signalled]<min_score:
            status,chosen,reason='unknown',None,'insufficient_semantic_evidence'
        else:
            status,chosen,reason='selected',signalled,None
    elif scores[best]<min_score:
        status,chosen,reason='unknown',None,'out_of_scope'
    elif gap<min_margin:
        status,chosen,reason='ambiguous',None,'low_margin'
    else:
        # Without a lexical signal, a greater bar reduces forced open-set routing.
        if scores[best]<min_score+0.08:
            status,chosen,reason='ambiguous',None,'insufficient_semantic_evidence'
        else:
            status,chosen,reason='selected',best,None
    enabled = enabled_map()
    if status=='selected' and not enabled.get(chosen,False):
        status,reason='unsupported','capability_disabled'
    return {'routing_status':status,'capability':chosen,'supported':status=='selected',
            'reason_code':reason,'scores':{k:round(v,6) for k,v in scores.items()},
            'method':'bge_with_guards','index_cache_hit':hit,'corpus_fingerprint':fingerprint}
