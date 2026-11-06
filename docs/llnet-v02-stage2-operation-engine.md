# LLNet v0.2 — Stage 2: Durable Operation Engine

## Stage completion

- Stages each Create/Update/Enable/Disable/Delete into a PostgreSQL transaction.
- Each submission creates or reuses one PolicyOperation, OperationEvent, OutboxEvent and persistent `(network_id, dpid)` reservation.
- The public API returns **HTTP 202**. No OpenFlow effects happen during submission.
- A temporary CLI worker runs the operation, performing preflight, deploy, verify and compensation through the Ryu adapter. Airflow replaces manual triggering in Stage 3.
- Separate `policies.desired_state` (committed intent) and `policies.applied_state` (last verified outcome). A pending operation keeps its proposed state in `policy_operations.requested_state`.
- Revision snapshots and deployment specs are immutable per revision. Failed revisions stay in history; next revision number uses `max(revision_no)+1`.
- Once compensation has been verified, failure can be terminal. If a network effect is ambiguous, the operation becomes **unresolved** and its scope reservation stays locked for a future reconciler.
- No unauthenticated internal HTTP execution endpoint is exposed. The worker CLI is intentionally only available to an operator with container access.

## Module boundaries

| Layer | File | Role |
| --- | --- | --- |
| HTTP write | `app/api/v1/policy_commands.py` | Header parsing and 202 submission |
| HTTP read | `app/api/v1/policy_queries.py`, `operations.py` | Read-only state/events |
| API audit | `app/api/audit.py` | Sanitized 4xx/5xx audit (best effort) |
| Contracts | `app/schemas/operation.py`, `schemas/policy.py` | Public schema validation |
| Domain | `app/domain/cookies.py`, `domain/fingerprint.py`, `domain/states.py` | Pure helpers/vocabulary |
| Submission | `app/services/submission_service.py` | Transactional business commands and overlap checks |
| Repository | `app/repositories/operation_repository.py` | Stage operation, event, outbox atomically |
| Execution | `app/services/execution_service.py` | Lease ownership, DB transitions, evidence |
| Deployment | `app/services/deployment_service.py` | Side effects, verification, compensation |
| Protocol adapter | `app/adapters/ryu_adapter.py` | Ryu REST only; unchanged from Stage 1 |
| Worker | `app/cli/run_operation.py` | Manual trigger; no orchestration logic |

## Public endpoints

| Method | Endpoint | Note |
| --- | --- | --- |
| POST | `/api/v1/policies` | Returns 202, requires Idempotency-Key |
| PATCH | `/api/v1/policies/{id}` | Complete PolicyInput body, requires `If-Match` revision and Idempotency-Key |
| POST | `/api/v1/policies/{id}/enable` | Requires Idempotency-Key |
| POST | `/api/v1/policies/{id}/disable` | Requires Idempotency-Key |
| DELETE | `/api/v1/policies/{id}` | Returns 202, requires Idempotency-Key |
| GET | `/api/v1/policies/{id}` | Committed state and revision pointers |
| GET | `/api/v1/policies/{id}/status` | Live status or explicit unknown/pending |
| GET | `/api/v1/policies/{id}/deployments` | Flow specifications and observation state |
| GET | `/api/v1/operations/{id}` | Outcome and error code |
| GET | `/api/v1/operations/{id}/events` | Append-only audit events |
| POST | `/api/v1/policies/{validate,compile}` | Pure dry-run operations, no network effects |

The `X-Client-Id` header is **not authentication**. This build is for the localhost lab only. Before moving beyond the lab, add genuine caller identity, service-to-service auth, role authorization and rate limits.

## Status semantics

- The synchronous v0.1 mutation API is intentionally **retired**. It does not continue beside the new asynchronous API.
- `pending` means stored in PostgreSQL, **not deployed**. In Stage 2, the operator explicitly invokes the CLI worker.
- Successful execution updates the committed `desired_revision_id`, `desired_state`, `applied_revision_id`, `applied_state`, and legacy read fields together.
- An attempted operation that fails cleanly keeps the previous committed desired state. The new revision stays in history.
- A worker interrupted after claiming might have changed the network. An expired lease is deliberately classified `unresolved`, not automatically retried.
- Scope reservation is per `(network_id, dpid)` and remains held for unresolved effects. There is **no automatic repair** until Stage 4.
- `LocalExecutor` and Airflow are **not** installed in Stage 2; Stage 3 adds them.

## Known limitations before production

1. No authentication; localhost-bound API and trusted Docker container operators only.
2. Multi-switch updates are not atomic. A temporary overblocking interval may exist; observed failures attempt compensation and leave unresolved where necessary.
3. Ryu REST HTTP 200 is not an OF barrier acknowledgement. Flow stat verification is stronger than HTTP response but not proof of traffic-level correctness.
4. Stage 2 tests use a simulated adapter and local SQLite behavior (JSONB emulation). PostgreSQL migrations and Mininet integration **must be tested in the user's actual Docker environment**.
5. Conflicts are conservative: even same-action CIDR overlap is rejected; full allow/deny precedence and port-range conflict proofs are deferred.
6. Lease-based crash recovery and automatic reconciliation are in Stage 4. Operators must not bypass scope reservations by manual SQL edits.
7. API 4xx/5xx auditing is best effort if PostgreSQL itself is unavailable; logs go to the application logger as fallback.
8. Outbox dispatch to Airflow is not active yet. Local CLI completion marks the envelope delivered to prevent later duplicate dispatch.
9. Error evidence currently contains structured result codes and events, not full controller packet traces or external observability sinks.
