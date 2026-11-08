# LLNet v0.2 — Stage 4C: Automatic Safe Healing

**Scope:** add one small, opt-in auto-trigger to the existing 15-second `policy-reconciler` observer. Stage 4B's repair executor remains the **only** network writer. No Airflow DAG, new process, queue, database migration, new network protocol adapter or new Docker Compose file.

## Mechanism

```text
policy-reconciler (single instance)
    -> Stage 4A observe_once (GET-only Ryu; persist finding evidence)
    -> if LLNET_AUTO_HEAL=true and polling mode:
         find open confirmed MISSING findings (fresh last_seen <= 45 s)
         skip any episode already automatically attempted
         call Stage 4B apply(finding_id), at most one operation per cycle
         operation holds existing switch scope reservation and runner lease
         fresh GET Ryu; verify no occupied foreign/modified flow slot
         ADD exactly one known missing DROP rule
         verify on Ryu GET
         update PostgreSQL operation + deployment + finding
```

## Invariants

1. **Opt-in only:** `LLNET_AUTO_HEAL=false` by default. `python -m app.cli.observe_flows --once` is always observe-only, even when the environment variable is `true`.
2. Only confirmed, unresolved **`missing`** findings are eligible, after two valid Stage 4A observations. Observations older than 45 seconds do not trigger action.
3. Stage 4B revalidates the enabled policy, committed applied/desired revision, stable state, deployment ownership/cookie, no busy operations, and no scope reservation. It reads Ryu fresh before any write and refuses a foreign/modified entry occupying the same OpenFlow slot.
4. Stage 4B creates a durable `reconcile` operation and `(network_id, dpid)` reservation. No policy revision increment, no Airflow DagRun and no outbox event.
5. Exactly **one automatic attempt per finding episode**, persisted under `requester_id='system:reconciler:auto'` and `idempotency_key='auto:<finding_id>'`. The existing database unique constraint makes duplicate attempts fail closed across restarts/concurrent workers.
6. If a network ADD might have happened but cannot be verified, Stage 4B returns `unresolved`, preserves the reservation, and prevents blind retries. An explicitly attempted episode with a terminal `failed` outcome is **not automatically retried**. Human review remains necessary.
7. One staged automatic Repair Operation maximum per poll; additional findings wait for following 15-second cycles. All external network changes go through existing Ryu adapter; no OpenFlow delete action in auto mode.
8. Current version supports a **single** reconciler process; do not scale `policy-reconciler` replicas. DB conflict protection exists, but this is not a distributed controller design.

## Failure semantics

| Condition | Action |
| --- | --- |
| Healthy / no confirmed drift | Observe only |
| Suspected (one observation) | Wait for second valid sample |
| Confirmed Missing, eligible | One automatic Stage 4B safe repair |
| Unknown / disconnected Ryu | No automatic repair |
| Modified / extra / foreign rule slot | No overwrite or delete |
| User Update/Delete/Pending or switch reservation | Refuse and rescan later |
| Pre-write failure after staging | Persist `failed`, no automatic retry of that episode |
| Ambiguous post-write outcome | Persist `unresolved`, retain reservation; manual investigation |

## Testing and limitations

Local 86-test regression uses fake Ryu and SQLite ORM emulation, **not** the user's PostgreSQL/Mininet deployment. Verify live Docker Compose, PostgreSQL, Ryu/OVS, and concurrent Update/Delete vs Repair before labeling Stage 4C accepted.

This is an experimental **missing DROP-flow** auto-healer, not a production SDN control plane, not an automatic recovery system for arbitrary switch/Ryu crashes, and not a distributed multi-switch transactional controller.
