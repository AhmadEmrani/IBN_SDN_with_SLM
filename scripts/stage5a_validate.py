#!/usr/bin/env python3
"""Offline validation of Stage 5A seeds (no network, no deployment)."""
import collections, ipaddress, json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE=ROOT/'data/intents/stage5a'
def load(p): return json.loads(p.read_text(encoding='utf-8'))
def main():
    seeds=[json.loads(line) for line in (BASE/'firewall-contract-seed.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    context=load(BASE/'network-context.json')
    registry=load(ROOT/'contracts/intent-v1/capabilities.json')
    schema=load(ROOT/'contracts/intent-v1/model-result.schema.json')
    request_schema=load(ROOT/'contracts/intent-v1/translate-request.schema.json')
    assert registry['contract_version']=='1.0' and context['fixture_only'] is True
    assert len(seeds)==20 and len({x['example_id'] for x in seeds})==20
    assert collections.Counter(x['expected_model_result']['status'] for x in seeds)=={'ready':10,'needs_clarification':4,'unsupported':6}
    try:
        import jsonschema
    except ImportError:
        jsonschema=None
    for seed in seeds:
        m=seed['expected_model_result']; req=seed['request']
        assert seed['split']=='contract_seed' and seed['retrieval_eligible'] is True
        assert m['contract_version']=='1.0' and req['context']['network_id']==context['network_id']
        assert set(m)=={'contract_version','status','capability','proposal','clarification','reason_code'}
        assert isinstance(req['text'],str) and 0<len(req['text'])<=4000
        if jsonschema:
            jsonschema.Draft202012Validator(schema).validate(m)
            jsonschema.Draft202012Validator(request_schema).validate(req)
        if m['status']=='ready':
            p=m['proposal']; expected=seed['expected_policy']
            assert m['capability']=='firewall' and m['clarification'] is None and m['reason_code'] is None
            assert set(p)=={'source','destination','direction','protocol','source_ports','destination_ports','action'}
            assert p['action']=='deny' and expected['schema_version']=='1.0'
            for side in ['source','destination']:
                v=p[side]
                resolved=context['hosts'].get(v,'0.0.0.0/0' if v=='any' else v)
                normalized=str(ipaddress.IPv4Network(resolved, strict=False))
                assert expected['match'][side]['value']==normalized
            assert expected['match']['protocol']==p['protocol']
            assert expected['match']['direction']==p['direction']
            for side in ['source_ports','destination_ports']:
                ports=p[side]
                assert ports is None or (1<=len(ports)<=16 and len(set(ports))==len(ports) and all(type(v) is int and 1<=v<=65535 for v in ports))
                assert expected['match'][side]==ports
            assert not (p['protocol'] in ('any','icmp') and (p['source_ports'] is not None or p['destination_ports'] is not None))
            assert not (p['direction']=='bidirectional' and (p['source_ports'] is not None or p['destination_ports'] is not None))
            combos=len(p['source_ports'] or [None])*len(p['destination_ports'] or [None])
            directions=2 if p['direction']=='bidirectional' and normalized else 1
            assert seed['expected_flow_count']==combos*directions*len(expected['scope']['switches'])
        else:
            assert m['proposal'] is None and seed['expected_policy'] is None and seed['expected_flow_count']==0
            if m['status']=='needs_clarification': assert isinstance(m['clarification'],str) and m['clarification'] and m['reason_code']
            else: assert m['status']=='unsupported' and m['clarification'] is None and m['reason_code']
    print('Stage 5A fixture checks: 20/20 OK')
    print('Statuses: ready=10, needs_clarification=4, unsupported=6')
    print('JSON Schema engine:', 'jsonschema installed (schema checks performed)' if jsonschema else 'not installed (structural/semantic checks only)')
    print('No SLM, BGE, live backend, Mininet, or deployment test was performed.')
if __name__=='__main__':
    try: main()
    except (AssertionError,ValueError,KeyError) as e:
        print('FAILED Stage 5A fixture check:',repr(e),file=sys.stderr);sys.exit(1)
