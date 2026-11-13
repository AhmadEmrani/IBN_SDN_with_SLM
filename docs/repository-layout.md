# Repository layout and migration boundaries

This repository implements a research LLNet-inspired network intent translation pipeline and a separate SDN policy execution engine. The Digital Twin and safety gate are **not implemented**.

## Authoritative runtime files

- `compose.yaml` — only active Docker Compose configuration; project name `sdn-mininet-ryu` is preserved to retain existing network and volume identity.
- `infra/docker/{policy-api,intent-api,retriever,ryu,mininet}/Dockerfile` — runtime build definitions.
- `policy-manager/app/intents` — read-only Intent API, BGE and Phi orchestration, capability preview; only the Firewall capability is enabled.
- `policy-manager/app/api`, `app/services`, `app/reconciliation` — policy lifecycle, bounded network operations, observation and recovery.
- `airflow/dags` — operation scheduling, not the authoritative business logic.
- `contracts/intent-v1`, `prompts/intents/v1`, `data/intents` — versioned contracts and research corpora. Historical dataset directory names are retained to preserve reproducibility and cache fingerprints.
- `reports/stage5d4` — experimental routing results; not an active API contract.

## Deployment boundary

`POST /v1/intents/dry-run` is **inert**. For firewall it produces a preview-only PolicyInput and flow specifications using a fixture-only network context. This does not authorize or register a policy. `rate_limit` and `load_profile` remain disabled.

`POST /api/v1/policies` is a **separate, actionable** interface: submission stages operations in PostgreSQL, the Outbox dispatcher schedules Airflow, and policy execution can modify Ryu/OVS. Do not treat read-only intent preview as a global safety gate: authenticated authorization and Digital Twin checks are future work.

## Archive

`docs/archive/` contains historical Compose files, replaced Dockerfiles, setup scripts, and manifests. They document development history but are NOT supported deployment entrypoints. Do not run archived installers: some rewrite `.env` with obsolete `COMPOSE_FILE` values.

Unit/integration tests and Alembic migration filenames retain historical version identifiers, as renaming migrations can disrupt their provenance. Historical docs under `docs/llnet-v02-*.md` preserve prior engineering decisions.

## Merge criteria

- One Compose file discovered without warnings; same project, 15 services, 6 named volumes.
- Clean builds and regression tests, including existing Backend, intent, BGE tests.
- Explicit real lab validation of Firewall policy create → apply → observed flow → remove → restored connectivity; check Airflow/Outbox and Reconciler status.
- No accidental changes to `.env`, GGUF model files, PostgreSQL/Airflow volumes, data corpora or contracts.
- Merge from a reviewed PR only after the operator confirms real SDN tests; **no automatic merging**.
