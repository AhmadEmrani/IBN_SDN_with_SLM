# LLNet — implementation architecture

Last updated: LLNet v0.2 stage 1 (data foundation). Do not confuse the
implemented system with the approved architecture targeted for later stages.

## Currently implemented

- OpenFlow 1.3 Ryu learning-switch controller in `controller.py`.
- Open vSwitch in the Mininet topology (`topology.py`).
- FastAPI Policy Manager in `policy-manager/app`, with v0.1 synchronous
  `POST /api/v1/policies` and `DELETE /api/v1/policies/{policy_id}`.
- PostgreSQL 16, SQLAlchemy and JSONB.
- Ryu OpenFlow REST via `ryu.app.ofctl_rest`: `/stats/switches`,
  `/stats/flowentry/add`, `/stats/flowentry/delete_strict`, `/stats/flow/{dpid}`.
- Policy schema v1 for IPv4 deny and a pure dry-run Flow compiler.
- Offline Swagger UI assets at `/docs`.
- Stage-1 Alembic schema and imported legacy revisions, operation/outbox
  models and read-only operation queries.

**NOT IMPLEMENTED YET:** Airflow, Dispatcher, async operation writes, explicit
transactional reservations, automatic Reconciler, complete rollback, internal
service authentication and rigorous cross-switch atomic deployment.

## Approved target architecture

```text
Human / future SLM
       |
   FastAPI (business logic + authorization)
       |                         |
   PostgreSQL                operation engine
   - policy revisions            |
   - operations                  v
   - audit / evidence       Ryu REST adapter -> Ryu -> OVS
   - outbox events                ^
       |                          |
  Dispatcher -> Airflow DAG -> internal operation APIs
       |
  Independent reconciler reads desired/actual state and repairs drift
```

PostgreSQL is the operational source of truth; Airflow metadata is separate.
Ryu/OVS observations are required to verify actual installation. An HTTP 200
from Ryu does not prove successful installation of a rule.

## Stage 1 compatibility notes

The original `policies.status` column remains to serve legacy API calls. The
new `desired_state`, `desired_revision_id` and `applied_revision_id` are
populated for **imported historical policies**, but v0.1 write operations
will not yet update all v0.2 structures. A future transition step must
backfill any such writes before enabling the async operation API.

## Future steps

1. Stage 2: versioned policy writes, scope reservations, lifecycle API and
   transactional outbox submission in one DB transaction.
2. Stage 3: Airflow LocalExecutor, authenticated internal operations and
   outbox Dispatcher.
3. Stage 4: independent reconciler, evidence-backed compensation and fault
   injection tests.
4. Freeze stable v0.2 contracts before integrating the SLM intent converter.

See `docs/llnet-v02-stage1-foundation.md` for migration details.
