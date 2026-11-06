# LLNet v0.2 — Stage 1: Durable Data Foundation

## Scope

This stage introduces Alembic, six new data/evidence tables, an API audit table, a
transactional-outbox repository primitive, and modular policy endpoints. It does
**not** enable asynchronous writes or Airflow scheduling. The existing v0.1
create/delete workflow remains intentionally synchronous and unchanged.

## Source of truth

- `policies`: v0.1 columns retained; desired state and revision pointers added.
- `policy_revisions`: immutable historical JSON snapshots.
- `policy_operations`: future operation envelopes and idempotency identity.
- `operation_events`: append-only steps and evidence.
- `flow_deployments`: expected flow by revision/switch/index; observed status.
- `outbox_events`: delivery envelopes, lease and retry fields.
- `api_request_events`: sanitized rejected-request audit envelopes; recording middleware comes later.

The initial migration imports all existing policy definitions and compiled flows.
Each imported deployment is `unknown` until network observation. Only legacy
`active` policy rows receive an initial `applied_revision_id`, describing the
*previously reported* successful installation, not a fresh status check.

### Compatibility window

The existing v0.1 endpoints remain operational. During stage 1, newly created
v0.1 policies continue using the old write path and may have a NULL
`desired_revision_id` until stage 2 adopts the operation engine. Do not treat
new tables as complete operational evidence until migration to the new write
path. The original `policies.status` is retained for legacy behavior.

A future stage will perform one-time backfill of any compatibility-window writes
before making revision pointers non-null and enabling v0.2 operations.

## Transaction and idempotency

`app.repositories.operation_repository.stage_operation()` stages an Operation,
initial append-only Event, and Outbox Event in the **caller's existing DB
transaction**. The caller must commit together with the Policy and Revision
inserts. For concurrent requests with the same idempotency key, the unique
constraint handles the race; a higher-level stage-2 service will catch an
`IntegrityError`, roll back, reload and return the matching operation or 409.

The repository is deliberately *not* yet attached to write endpoints. Airflow
metadata is never the source of truth for this operation state.

## API organization

- `api/v1/policy_tools.py`: validate, compile dry-run
- `api/v1/policy_queries.py`: list, get, legacy live status
- `api/v1/policy_commands.py`: synchronous legacy create/delete
- `api/v1/operations.py`: read-only operations and event history
- `api/v1/policies.py`: policy router assembly
- `main.py`: application assembly and offline Swagger assets

## Not in Stage 1

- Airflow services and DAGs
- Outbox dispatcher
- Async POST/PATCH/enable/disable/delete
- Independent reconciler
- Conflict concurrency controls and failure injection
- API request audit middleware and authenticated internal endpoints

All of those are later milestones and must not be marked as implemented.
