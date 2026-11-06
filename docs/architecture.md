# LLNet architecture — v0.2 Stage 2

## Running lab

- `mininet-net`: Mininet/OVS network with h1–h3 and OpenFlow13 switch s1.
- `ryu-controller`: Ryu MAC-learning controller with `ryu.app.ofctl_rest`.
- `policy-api`: FastAPI, Pydantic validation, policy compilation, durable operation staging, read/query endpoints and temporary operator-only CLI execution.
- `postgres`: PostgreSQL 16, application-authoritative policy and operation state; schema managed by Alembic.

No Airflow services are running in Stage 2. Airflow LocalExecutor and a dispatcher are planned for Stage 3; reconciliation remains Stage 4.

## Control path

1. Public command (Create/Update/Enable/Disable/Delete) receives an `Idempotency-Key` and records a `pending` operation, first event, outbox envelope, and switch-scope reservation in one PostgreSQL transaction. Response is HTTP 202.
2. A **manual lab worker** is invoked with the returned operation ID: `python -m app.cli.run_operation <operation_id>`.
3. The worker claims the operation lease, builds a deployment plan from the immutable revision and existing committed policy, performs preflight, sends Ryu FlowMods, verifies observed flow stats, and attempts compensation on failure.
4. The worker atomically records operation outcome, deployment state and audit event; successful/cleanly-failed operations release scope reservations. Ambiguous states remain unresolved and locked.
5. Read endpoints expose the operation/events and committed policy state separately.

## Future AI boundary

The SLM generates proposed Policy JSON only. It will NOT invoke Ryu or Airflow directly. The same Pydantic validation, conflict checks, compilation and idempotent command API protect manual and SLM-generated intents.

## More information

See `docs/llnet-v02-stage2-operation-engine.md` and `APPLY_STAGE2_FA.md`.
