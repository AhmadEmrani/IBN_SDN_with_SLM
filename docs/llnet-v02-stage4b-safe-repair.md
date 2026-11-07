# LLNet v0.2 — Stage 4B: Safe Repair (manual gate)

## Scope

Stage 4B implements **one explicitly triggered Repair Operation per confirmed `missing` DROP flow**. Automatic periodic healing is intentionally **not** enabled yet. Stage 4A's observer continues to run unchanged on its own Docker service.

### Invariants

1. The finding is open, confirmed by two valid observations and still marked `missing` in `flow_deployments`.
2. The owning Policy is committed, enabled, active, with matching desired/applied revision and no busy or unresolved operation.
3. A `policy_operations` row with type `reconcile` (already an enum value), requester `system:reconciler`, and **no outbox or Airflow DAG** is persisted. An existing `scope_reservations` row serializes repair against lifecycle operations.
4. A fresh GET from Ryu checks connectivity and actual OpenFlow rules **after the reservation is committed**; it rejects a modified/foreign rule occupying the same table+priority+match and rejects unexpected entries with the same policy cookie.
5. Only **one** expected DROP flow is inserted (`add_flow`). No delete, no blind policy redeployment, and no new policy revision.
6. The new flow must be positively verified in Ryu stats before success is recorded. A request that may have mutated the network but cannot be verified becomes `unresolved` and **retains the switch reservation**. A failure before sending ADD becomes `failed` and releases it.
7. Success updates the existing `FlowDeployment` observation, resolves its finding with a `repair_operation_id`, and adds Operation Events. No new table is needed.
8. `--apply` is explicit. Without it the command performs a read-only eligibility check and stages no Operation.

### Execution path

```text
Operator CLI --finding-id ... --apply
    -> PostgreSQL (validate stable policy + confirmed finding)
    -> INSERT PolicyOperation('reconcile') + ScopeReservation + event
    -> claim via existing Operation Engine lease/token
    -> fresh GET Ryu switches + flow-stats
    -> refuse on UNKNOWN/MODIFIED/EXTRA/collision
    -> one POST Ryu add-flow
    -> GET verify (bounded retries)
    -> finalize succeeded + finding resolved, OR unresolved with reservation held
```

### Deliberate exclusions / safety limitations

- No automatic healing loop or Airflow trigger. Phase 4C can add an automatic trigger **after** a PostgreSQL/Ryu integration test.
- No repair of `modified`, `extra` or `unknown`. No deletion of OpenFlow rules.
- `unresolved` cases require **operator investigation** of both Ryu/OVS and PostgreSQL. Never delete a reservation or mark an operation succeeded without establishing the actual network state; a resolution workflow is not part of this phase.
- A successful Ryu stats match proves that the expected flow exists, **not** end-to-end packet delivery or application reachability. Real Mininet traffic tests are a separate acceptance gate.
- SQLite unit tests simulate ORM behavior and do **not** establish PostgreSQL concurrent transaction correctness. The real environment must test concurrent Update/Delete vs Repair before enabling automatic healing.
- Scripts and code in this phase assume the Stage 4A observer overlay is already applied.

### Operational acceptance gates

- All tests: `python -m unittest discover -s tests -p 'test_v0*.py' -v`.
- Fresh confirmed Missing finding triggers `--finding-id ID` (eligibility, zero OpenFlow writes).
- `--apply` restores exactly one missing Drop rule and records a `succeeded` reconcile operation.
- Existing policy revision unchanged; Operation has `airflow_run_id NULL`; no new Outbox event.
- Existing `scope_reservations` empty after success.
- Ryu GET unavailable / foreign slot occupancy fail closed before modification.
- Response after ambiguous POST must be `unresolved` with reservation preserved, not auto-retried.
