# LLNet — Intent-Driven SDN Research Lab

A reproducible, **laboratory-only** implementation of natural-language network intent translation and an independent SDN policy lifecycle. Stack: BGE embeddings, Phi-3.5-mini inference (llama.cpp), FastAPI, PostgreSQL 16, Airflow 3, Ryu, OpenFlow 1.3, Mininet/OVS.

> Research baseline, **not production-ready**. The current AI path is preview-only, uses an explicitly enabled lab fixture for context, and never automatically submits a policy. Digital Twin and deployment safety gate are planned for later stages.

## Quick start

Requirements: Linux with Docker Engine and Compose plugin, Mininet-compatible privileges/kernel, a local Phi GGUF file at `models/llnet-phi/phi-3.5-mini-instruct-q4_k_m.gguf`, and environment credentials. **Do not overwrite an existing `.env` or Docker volumes.** For a new installation only:

```bash
cp .env.example .env
# Edit placeholder passwords/tokens before running Compose.
# Download an authorized GGUF model separately into models/llnet-phi/.
docker compose config --quiet
docker compose build
docker compose run --rm policy-api alembic upgrade head
docker compose up -d
```

**Database migrations** must be applied explicitly for a new DB; the policy API does not automatically migrate it. The command above is for clean installation only.

For an existing deployment, check `docker compose run --rm --no-deps policy-api alembic current` first; do not initialize or reset existing databases. Airflow maintains its own DB/init services in `compose.yaml`.

## Services

| Service | Host port | Role |
| --- | --- | --- |
| `policy-api` | 8000 | Actionable policy API and lifecycle |
| `airflow-api-server` | 8081 | Airflow API/UI |
| `ryu-controller` | 6653 | OpenFlow controller (REST internal) |
| `intent-retriever` | 8092 | BGE retrieval and capability candidates |
| `phi-inference` | 8093 | llama.cpp / Phi GGUF |
| `intent-orchestrator` | 8094 | Translation and **read-only** dry-run |
| `postgres`, `airflow-db`, dispatcher, reconciler, scheduler, processor, Mininet, init jobs | internal | Data, scheduling and lab switching |

All host-published ports bind to `127.0.0.1`; some services can affect the lab network. Inspect `compose.yaml` and set `LLNET_AUTO_HEAL=false` unless independently tested.

## Test intent pipeline

```bash
bash scripts/smoke_intent_dry_run.sh
bash scripts/smoke_intent_routing.sh
python3 scripts/evaluate_intent_routing.py --split test
bash scripts/check_merge_readiness.sh
```

Supported `POST http://127.0.0.1:8094/v1/intents/dry-run` requires `{"text":"Block TCP traffic from h1 to h2 on port 443.","network_id":"lab"}`. `capability` can be omitted for auto-routing; only Firewall currently proceeds to validated preview. `rate_limit` and `load_profile` are recognized but disabled.

## Network deployment is separate

`POST http://127.0.0.1:8000/api/v1/policies` accepts policy JSON with an `Idempotency-Key`, stages an operation in PostgreSQL and can result in actual Ryu/OVS changes via Outbox, Airflow and the execution service. This API is **not protected by a Digital Twin safety gate**. Use only in a trusted, isolated lab.

See [repository layout](docs/repository-layout.md), [capability and deployment boundaries](docs/capability-and-deployment-boundaries.md), and [detailed architecture](docs/architecture.md). Historical guides, retired Compose and setup scripts are under `docs/archive/`.
