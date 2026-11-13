# Current LLNet lab architecture

## Scope

The project has two independent flows: a read-only AI intent path and a manually actionable policy-operation path. The project does not yet have runtime intent-to-deployment submission, Rate Limit enforcement, Load Profile execution, Network Digital Twin, what-if validation or global safety gate.

## Intent path (read-only)

1. `intent-orchestrator:8094` accepts `/v1/intents/route`, `/v1/intents/translate` and `/v1/intents/dry-run`.
2. `intent-retriever:8092` uses BGE to route capabilities and retrieve few-shot examples, loading versioned corpus and prompt files.
3. `phi-inference:8093` returns a model result, validated against JSON Schema; rejected or uncertain results produce no policy.
4. For the enabled Firewall capability, the server-owned lab context resolves known host IDs, adapts to existing `PolicyInput`, and runs the deterministic firewall compiler in preview mode. No database or network actuation is imported in the intent execution path.
5. `rate_limit` and `load_profile` are disabled. They must acquire separate contract, adapter, preview and execution implementations in Stage 6; a load workload should not be coerced into a firewall FlowMod.

## Policy execution path (actionable)

1. Operator submits `PolicyInput` to `policy-api:8000` with an idempotency key.
2. `submission_service` stages the operation, revision, initial event, Outbox and scope reservations atomically in PostgreSQL.
3. `policy-dispatcher` triggers Airflow. Airflow calls the authenticated internal operation API; `execution_service` is the sole backend operation runner.
4. Backend Ryu adapter submits FlowMods and verifies observed flow state before committing the outcome. Reconciler observes drift; auto-heal is configurable and disabled by default.
5. Lab operators must test apply/verify/rollback explicitly; no multi-switch atomicity or exactly-once external side effects are claimed.

## Runtime services

Defined in unified `compose.yaml`, with separate runtime images for policy, intent, BGE, Ryu and Mininet. Phi uses the upstream llama.cpp server image. Policy API, dispatcher and reconciler share a policy image definition but run separate commands.

## Future security boundary

Future Digital Twin validation must protect all authorized actionable submission paths, not only the SLM front end. `ready` and `policy_validated` in dry-run indicate syntactic/semantic preview validation, **not authorization** to deploy. Current direct Policy API is actionable without a Digital Twin gate.

See `docs/repository-layout.md` for source-of-truth paths and `docs/capability-and-deployment-boundaries.md` for detailed constraints.
