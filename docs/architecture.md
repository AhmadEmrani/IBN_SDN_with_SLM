# SDN policy manager architecture

The repository runs a Ryu OpenFlow 1.3 controller and a Mininet topology. The policy manager exposes a versioned HTTP API, validates and stores firewall policies, checks for contradictory rules, and compiles them into a transport-neutral OpenFlow rule description.

## Services

- **Ryu controller** (`controller.py`): controls switches and provides the OpenFlow control plane.
- **Mininet** (`topology.py`): creates the test network and connects to Ryu.
- **Policy manager** (`policy-manager/app`): FastAPI API and SQLite-backed policy storage.

The API is available at `/api/v1/policies`; `/health` is a basic liveness endpoint. `contracts/policy.schema.json` defines the portable policy payload. The Ryu adapter currently expects a `PUT /v1/policies` endpoint; the existing controller does not implement that endpoint yet, so API storage works independently and live reconciliation needs a matching controller endpoint.

## Local run

Copy `.env.example` to `.env`, then run `docker compose up --build`. Enter Mininet with `docker compose exec mininet-net python3 topology.py`.

For local API development, install `policy-manager/requirements.txt` and run `uvicorn app.main:app --app-dir policy-manager --reload`.
