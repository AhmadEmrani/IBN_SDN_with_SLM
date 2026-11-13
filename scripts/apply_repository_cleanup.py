#!/usr/bin/env python3
"""Guarded repository cleanup, based on refactor/stages bad0cbe.

Never touches .env, models, Docker runtime, database, volumes or tracked source logic.
Changes are reversible using Git until commit. Run from repository root.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'refactor/stages'
EXPECTED_HEAD = 'bad0cbec02d13e911dda4f9ba2f0e7b620ba1306'

# Rename historical scripts; active script names describe functionality.
RELOCATE = {
    'docker-compose.yml':'docs/archive/compose/docker-compose.yml',
    'compose.stage5c.yml':'docs/archive/compose/compose.stage5c.yml',
    'compose.stage5d.yml':'docs/archive/compose/compose.stage5d.yml',
    'Dockerfile.intent-orchestrator':'docs/archive/docker/Dockerfile.intent-orchestrator',
    'Dockerfile.intent-retriever':'docs/archive/docker/Dockerfile.intent-retriever',
    'Dockerfile.mininet':'docs/archive/docker/Dockerfile.mininet',
    'Dockerfile.ryu':'docs/archive/docker/Dockerfile.ryu',
    'policy-manager/Dockerfile':'docs/archive/docker/policy-manager.Dockerfile',
    'controller_backup.py':'docs/archive/source/controller_backup.py',
    'scripts/stage3.sh':'docs/archive/setup-scripts/stage3.sh',
    'scripts/configure_stage3.sh':'docs/archive/setup-scripts/configure_stage3.sh',
    'scripts/stage5d1_setup.sh':'docs/archive/setup-scripts/stage5d1_setup.sh',
    'scripts/stage5d2_install.py':'docs/archive/setup-scripts/stage5d2_install.py',
    'scripts/stage5d3_install.py':'docs/archive/setup-scripts/stage5d3_install.py',
    'scripts/infra_migrate.py':'docs/archive/setup-scripts/infra_migrate.py',
    'scripts/apply_capability_refactor.py':'docs/archive/setup-scripts/apply_capability_refactor.py',
    'scripts/stage5d1_smoke.sh':'docs/archive/previous-smokes/stage5d1_smoke.sh',
    'scripts/stage5d2_smoke.sh':'docs/archive/previous-smokes/stage5d2_smoke.sh',
    'scripts/stage5d3_smoke.sh':'scripts/smoke_intent_dry_run.sh',
    'scripts/stage5d4_smoke.sh':'scripts/smoke_intent_routing.sh',
    'scripts/stage5d4_evaluate.py':'scripts/evaluate_intent_routing.py',
    'scripts/stage5a_validate.py':'scripts/validate_intent_fixtures.py',
    'scripts/stage5c_retrieve.py':'scripts/retrieve_examples.py',
}

MANIFEST = ['STAGE3_MANIFEST.md','STAGE4A_MANIFEST.md','STAGE4B_MANIFEST.md',
    'STAGE4C_MANIFEST.md','STAGE5A_MANIFEST.json','STAGE5B_MANIFEST.json','STAGE5C_MANIFEST.json']
for item in MANIFEST:
    RELOCATE[item] = 'docs/archive/manifests/' + item


def git(*args):
    p=subprocess.run(['git',*args],cwd=ROOT,text=True,capture_output=True)
    if p.returncode:
        raise RuntimeError('git '+ ' '.join(args) + ' failed: '+p.stderr.strip())
    return p.stdout.strip()


def main():
    if git('branch','--show-current') != BRANCH:
        raise RuntimeError('Expected refactor/stages branch. Refusing changes.')
    result = subprocess.run(
        ['git', 'merge-base', '--is-ancestor', EXPECTED_HEAD, 'HEAD'],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            'Expected base commit bad0cbe is not an ancestor of HEAD.'
        )
    if git('diff','--name-only') or git('diff','--cached','--name-only'):
        raise RuntimeError('Tracked changes present; commit/stash them first.')
    source_names=list(RELOCATE)
    missing=[p for p in source_names if not (ROOT/p).is_file()]
    targets_present=[dest for dest in RELOCATE.values() if (ROOT/dest).exists()]
    if missing or targets_present:
        raise RuntimeError('Unexpected tree; missing sources='+str(missing)+'; existing targets='+str(targets_present))
    # Don't create duplicate targets if overlay was partially applied.
    for path in ['scripts/check_merge_readiness.sh','scripts/apply_repository_cleanup.py',
                 'docs/repository-layout.md']:
        if not (ROOT/path).is_file():
            raise RuntimeError(f'Missing 5F.4 overlay file: {path}')
    # Verify new Compose references none of the archived Dockerfiles.
    compose = '\n'.join(
        line for line in (ROOT/'compose.yaml').read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    )
    for stale in ('dockerfile: Dockerfile.', 'dockerfile: policy-manager/Dockerfile',
                  'compose.stage5c.yml','compose.stage5d.yml'):
        if stale in compose: raise RuntimeError('Stale runtime Compose reference: '+stale)
    dockerfile=ROOT/'infra/docker/retriever/Dockerfile'
    df=dockerfile.read_text()
    old='COPY scripts/stage5c_retrieve.py /workspace/scripts/stage5c_retrieve.py'
    if df.count(old)!=1:raise RuntimeError('Retriever Dockerfile COPY anchor changed; refusing cleanup')
    # Guard that README/docs still refer to original content when cleanup begins.
    if '# LLNet — Intent-Driven SDN Research Lab' not in (ROOT/'README.md').read_text():
        raise RuntimeError('Expected 5F.4 README overlay before applying cleanup')
    # Only after all checks, apply renames and update one Dockerfile COPY.
    for src,dest in RELOCATE.items():
        target=ROOT/dest
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(ROOT/src),str(target))
    dockerfile.write_text(df.replace(old,'COPY scripts/retrieve_examples.py /workspace/scripts/retrieve_examples.py'))
    # Intent CLI, Dockerfile and evaluator corpus still use their original data paths.
    print('PASS: archived legacy Compose/Dockerfiles, moved retired scripts, renamed active tools')
    print('PASS: updated retriever Docker COPY and retained datasets/migrations/API contracts')
    print('NEXT: run bash scripts/check_merge_readiness.sh then real SDN deployment tests')


if __name__ == '__main__':
    try: main()
    except (RuntimeError, OSError) as e:
        print('CLEANUP REFUSED:',e,file=sys.stderr)
        sys.exit(1)
