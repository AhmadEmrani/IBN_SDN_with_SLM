# Capability and Deployment Boundaries

## Scope

This document describes the **current** firewall-only implementation after the capability refactor. `rate_limit` and `load_profile` are recognized by the semantic router but remain **disabled**. No network operation is authorized by enabling a catalog flag.

## Intent / preview path (no SDN writes)

1. `intent-orchestrator:8094` accepts natural-language requests.
2. `intent-retriever:8092` performs capability routing and BGE few-shot retrieval.
3. `phi-inference:8093` produces candidate model JSON for an enabled capability.
4. JSON Schema + capability registry validate the result.
5. `build_preview()` dispatches the `ready` model result to an implemented preview builder.
6. The firewall builder resolves context through the existing adapter, uses `PolicyInput` and the existing `compile_policy()` to return a candidate flow specification.

There are **no calls** from this path to PostgreSQL, Ryu, Airflow, or the Policy Submission API. Lab fixture context is opt-in and is not a production inventory provider. Dry-run cookie `1` is a preview placeholder, not deployment identity.

## Existing policy deployment path

External policy submissions still use the **separate** `policy-api:8000` entry point and validated `PolicyInput`:

`PolicyInput -> submission_service -> PostgreSQL (operation/revision/outbox) -> policy-dispatcher -> Airflow -> internal_operations -> execution_service -> deployment_service -> Ryu/OVS -> verification/reconciliation`

The policy API **currently allows direct policy submissions**. Thus there is no global Digital Twin safety gate in this stage. Do not equate a safe intent preview with enforced safety for all policy submission paths.

## Stage 6 extension design

- `firewall`: currently compiled into OpenFlow drop flows.
- `rate_limit`: should use a distinct typed contract and QoS/meter or queue-specific adapter, with physical enforcement verification; it must not masquerade as firewall `PolicyInput`.
- `load_profile`: should create a bounded test workload specification and a workload runner with results. It does not necessarily produce OpenFlow rules. The execution lifecycle needs an operation type appropriate to workloads.
- Add a preview handler, contract, retrieval corpus, prompts, tests and a supported execution adapter **before** changing its registry `enabled` flag.
- Scope and audit the eventual operation execution boundary. In Stage 7 create a synchronized twin; in Stage 8 implement a non-bypassable policy/workload safety gate at the policy execution boundary, not merely in the intent API.

## Explicit non-goals

No new database migration, OpenFlow change, policy submission route, automatic deployment, Digital Twin or Airflow DAG is added by this refactor. The existing `PolicyInput` remains firewall-only. The preview facade deliberately returns `policy` and `compiled_flows` for current API compatibility; Stage 6 may introduce a typed preview envelope without pretending a workload is a flow.
