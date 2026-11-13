# Stage 4A overlay manifest

Repo: `AhmadEmrani/IBN_SDN_with_SLM` — target: `main` (as fetched 2026-11-07).

- `docker-compose.yml` — add `policy-reconciler` to the existing **one-file** Compose; preserve Stage 3 services and volumes. Preserve corrected Airflow psycopg2 URL.
- `policy-manager/alembic/versions/0003_llnet_v02_observation.py` — **one additive** migration for finding episodes.
- `policy-manager/app/models/reconciliation.py` and `app/models/__init__.py` — durable ORM model registration.
- `policy-manager/app/reconciliation/observer.py` — pure comparison/normalization.
- `policy-manager/app/reconciliation/service.py` — safe read-only Ryu polling and DB persistence; no writes to Ryu.
- `policy-manager/app/cli/observe_flows.py` — `--once` or `--interval 15`; no shell wrappers.
- `policy-manager/app/adapters/ryu_adapter.py` — retains current main match aliases/verification, plus fail-closed malformed response validation.
- `policy-manager/tests/test_v04_observer.py` — 19 focused offline contract tests.
- `policy-manager/tests/test_v02_foundation.py` — allow additive tables while retaining all Stage 2 table invariants.
- `docs/llnet-v02-stage4a-observer.md` — architecture and semantics.
- `APPLY_STAGE4A_FA.md` — Persian install + validation runbook.

No Airflow DAG, new API route, worker queue, repair operation, `.env` or secrets added.
