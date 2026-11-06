# LLNet — SDN Policy Manager v0.2 (Stage 2)

A modular, research-oriented SDN policy lifecycle built with FastAPI, PostgreSQL, Ryu, Mininet and OpenFlow 1.3.

## Stage 2 quick start

Apply `LLNet_v0.2_Stage2_Overlay.zip` on top of the already-migrated Stage 1 tree. Then:

```bash
docker compose build policy-api
docker compose stop policy-api
docker compose run --rm --no-deps policy-api alembic upgrade head
docker compose run --rm --no-deps policy-api python scripts/verify_migration.py
docker compose run --rm --no-deps policy-api python -m unittest discover -s tests -p 'test_v02_*.py' -v
docker compose up -d --no-deps policy-api
```

The expected Alembic revision is `0002_v02_lifecycle`.

## Policy lifecycle

- Submit policy JSON via `POST /api/v1/policies` with `Idempotency-Key: ...`.
- FastAPI returns `HTTP 202` and a `pending` operation without touching Ryu.
- Execute the operation explicitly in the lab via:

```bash
docker compose exec policy-api python -m app.cli.run_operation '<operation_id>'
```

- Read execution result and append-only events at `/api/v1/operations/{operation_id}` and `/api/v1/operations/{operation_id}/events`.
- Manage revisions through `PATCH /api/v1/policies/{id}` with `If-Match`, or enable/disable/delete commands with their own Idempotency Keys.

**The CLI is temporary:** Stage 3 adds Airflow LocalExecutor and dispatcher, without putting policy business logic inside the DAG. Stage 4 adds independent reconciliation and failure injection in real Mininet/OVS.

## Design documents

- `APPLY_STAGE2_FA.md`: detailed Persian setup and test steps.
- `docs/architecture.md`: deployed architecture and boundaries.
- `docs/llnet-v02-stage2-operation-engine.md`: schema, API, state transitions and known limitations.

**Security:** no production authentication yet. Run only in a trusted localhost laboratory. No guarantees of atomic multi-switch updates or exactly-once execution across external OpenFlow side effects.
