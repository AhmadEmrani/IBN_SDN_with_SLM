#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ "$(git branch --show-current)" != "refactor/stages" ]]; then
  echo 'ERROR: expected refactor/stages' >&2; exit 1
fi
if [[ -f docker-compose.yml || -f compose.stage5c.yml || -f compose.stage5d.yml ]]; then
  echo 'ERROR: obsolete root Compose files present' >&2; exit 1
fi
if [[ -n "${COMPOSE_FILE:-}" ]]; then echo 'ERROR: unset COMPOSE_FILE' >&2; exit 1; fi
if [[ -f .env ]] && grep -q '^COMPOSE_FILE=' .env; then
  echo 'ERROR: remove legacy COMPOSE_FILE setting from .env before running' >&2; exit 1
fi
echo '== Compose structural checks =='
docker compose config --quiet
python3 scripts/infra_check.py

echo '== Compose service build =='
docker compose build

echo '== Backend regression: tests inside policy image =='
docker compose run --rm --no-deps policy-api python -m unittest discover -s tests -p "test_v0[234]*.py" -v

echo '== Intent regression =='
docker compose run --rm --no-deps intent-orchestrator python -m unittest discover -s policy-manager/tests -p 'test_v05d*.py' -v
docker compose run --rm --no-deps intent-orchestrator python -m unittest discover -s policy-manager/tests -p 'test_intent_architecture.py' -v
docker compose run --rm --no-deps intent-orchestrator python -m unittest discover -s policy-manager/tests -p 'test_capability_boundaries.py' -v

echo '== Retriever regression =='
docker compose run --rm --no-deps intent-retriever python -m unittest discover -s policy-manager/tests -p 'test_v05d4_bge_routing.py' -v

echo '== Running-service smoke checks (requires started BGE, Phi, Orchestrator) =='
bash scripts/smoke_intent_dry_run.sh
bash scripts/smoke_intent_routing.sh

echo '== Current PostgreSQL schema (read-only) =='
docker compose exec -T policy-api alembic current

echo 'PASS: automated pre-merge checks; real policy apply/verify/delete is a separate operator-controlled test.'
