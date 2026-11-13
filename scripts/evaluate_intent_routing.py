#!/usr/bin/env python3
"""Stage 5D.4 routing evaluation against real local HTTP, no Phi/SDN calls.

Prototypes and dev/test are separate. Test metrics must not be used for tuning.
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT=Path(__file__).resolve().parents[1]
LABELS=['firewall','rate_limit','load_profile','multiple','ambiguous','unknown']

def predicted_label(row):
    status=row.get('routing_status')
    if status in ('selected','unsupported') and row.get('capability') in LABELS[:3]:
        return row['capability']
    if status in LABELS[3:]:return status
    return 'invalid_response'

def metrics(records):
    valid=[(r['expected'],r['predicted']) for r in records if 'error' not in r]
    accuracy=sum(a==b for a,b in valid)/len(valid) if valid else 0.0
    per={}
    for label in LABELS:
        tp=sum(a==label and b==label for a,b in valid)
        fp=sum(a!=label and b==label for a,b in valid)
        fn=sum(a==label and b!=label for a,b in valid)
        prec=tp/(tp+fp) if tp+fp else 0.0
        rec=tp/(tp+fn) if tp+fn else 0.0
        f1=2*prec*rec/(prec+rec) if prec+rec else 0.0
        per[label]={'support':sum(a==label for a,b in valid),'precision':round(prec,4),
                    'recall':round(rec,4),'f1':round(f1,4)}
    others=[(a,b) for a,b in valid if a!='firewall']
    false_fw=sum(b=='firewall' for a,b in others)
    return {'evaluated':len(valid),'failed_requests':len(records)-len(valid),
            'accuracy':round(accuracy,4),'macro_f1':round(sum(p['f1'] for p in per.values())/len(per),4),
            'false_firewall_routes':false_fw,'non_firewall_total':len(others),
            'false_firewall_rate':round(false_fw/len(others),4) if others else None,
            'latency_ms_mean':round(sum(r['latency_ms'] for r in records)/len(records),2) if records else None,
            'per_class':per}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--split',choices=['dev','test'],default='test')
    p.add_argument('--url',default='http://127.0.0.1:8094/v1/intents/route')
    args=p.parse_args()
    path=ROOT/f'data/intents/stage5d4/routing-{args.split}.jsonl'
    examples=[json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    results=[]
    for ex in examples:
        start=time.perf_counter()
        req=Request(args.url,data=json.dumps({'text':ex['text']}).encode(),
                    headers={'Content-Type':'application/json'},method='POST')
        try:
            with urlopen(req,timeout=120) as response:
                reply=json.load(response)
            result={'id':ex['id'],'text':ex['text'],'expected':ex['expected'],
                    'predicted':predicted_label(reply),'routing_status':reply.get('routing_status'),
                    'reason_code':reply.get('reason_code'),'scores':reply.get('scores',{})}
        except (HTTPError,URLError,ValueError,TimeoutError) as exc:
            result={'id':ex['id'],'text':ex['text'],'expected':ex['expected'],
                    'predicted':'request_error','error':str(exc)}
        result['latency_ms']=round((time.perf_counter()-start)*1000,2)
        results.append(result)
        print(f"{ex['id']} expected={result['expected']} predicted={result['predicted']} ({result['latency_ms']}ms)",flush=True)
    report={'stage':'5d4','split':args.split,'note':'Routing only; no Phi or SDN calls; real BGE API results',
            'metrics':metrics(results),'cases':results}
    out=ROOT/'reports/stage5d4';out.mkdir(parents=True,exist_ok=True)
    target=out/f'routing-{args.split}-report.json';target.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print('\nMETRICS:')
    print(json.dumps(report['metrics'],indent=2))
    print('REPORT:',target)
    if report['metrics']['failed_requests']:raise SystemExit('ERROR: some requests failed')

if __name__=='__main__':main()
