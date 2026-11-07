# LLNet v0.2 — Stage 3: Airflow integration

## Contract

- Source of truth: LLNet PostgreSQL `policy_operations` / `policies` / revisions / events / `outbox_events`.
- Airflow 3.2.2 + **LocalExecutor** schedules work; it never imports the Ryu adapter or Policy ORM.
- `POST /api/v1/policies` remains `202 Accepted` and commits the outbox in the original transaction.
- Dedicated Dispatcher claims outbox rows with `FOR UPDATE SKIP LOCKED`, commits, triggers a uniquely named Airflow run, then acknowledges the outbox.
- DagRun ID is deterministically `llnet__<operation_id>`; POST 409 triggers GET and confirmation of `conf.operation_id` before acknowledging.
- If a Dispatcher dies between POST and DB acknowledgment, the lease expires and the next delivery reconciles the same DagRun (not a second run).
- The DAG has **preflight → execute → verify** HTTP tasks. `execute` calls Stage-2 `run_operation` exactly once from inside the Backend, with Stage-2 runner leases and compensation semantics.
- No automatic retry of execution task; ambiguous effects require Stage-4 reconciliation.
- Airflow metadata is stored in **a separate** `airflow-db` PostgreSQL; never mix it with policy tables.
- Airflow 3 API token: `/auth/token`, DAG trigger: `/api/v2/dags/llnet_policy_operation/dagRuns`.
- API-internal routes require `X-Internal-Token`, hidden from public Swagger.

## Scope & caveats

- Local lab, **not a production deployment**: simple auth manager, plaintext credentials in .env/volume, no TLS; ports bind to 127.0.0.1 only.
- Airflow event delivery is at-least-once, not exactly-once network effects.
- If the Airflow DAG fails after dispatch, operation can remain `queued`; Stage 4 will add DAG-failure monitoring, repair/reconciliation and observability.
- Airflow does not guarantee atomic OpenFlow multi-switch updates.
- Keep Swagger status/events from the LLNet API as authoritative; Airflow UI is orchestration telemetry.
- No new Alembic migration is needed for this stage (Stage-2 outbox, run-id field already exist).

See `APPLY_STAGE3_FA.md` for terminal, Swagger and Mininet checks. This variant uses only `docker-compose.yml`, with no Stage-3 Compose override.
