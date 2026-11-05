# LLNet Policy Manager — Stage 1

This is an **incremental reference overlay** for an existing Docker Ryu/Mininet project. Back up your original files before overwriting them. No database volume is removed by these commands.

## Start

1. Copy `.env.example` to `.env`, change the password (use URL-safe characters for the first run).
2. `docker compose up -d --build`
3. `docker exec -it mininet-net bash` and then `python3 topology.py`; keep the Mininet CLI running.
4. Verify Ryu connectivity: `docker exec llnet-policy-api python -c "import httpx; print(httpx.get('http://ryu-controller:8080/stats/switches').json())"` (expect `[1]`).
5. Open `http://localhost:8000/docs` and use **POST /api/v1/policies/validate**, then **/compile**, then **POST /api/v1/policies** with `contracts/examples/firewall-deny.json`.
6. Test in Mininet: `h1 ping -c 3 h2` should pass, `h1 ping -c 3 h3` should fail. Verify using `dpctl dump-flows -O OpenFlow13`.
7. Use **DELETE /api/v1/policies/{id}**, then test `h1 ping -c 3 h3` again.

## Scope & limitations

- v1 supports IPv4 DENY only, with optional TCP/UDP port lists for **unidirectional** policies.
- Existing hardcoded firewall rules were removed from `controller.py`; this is necessary for dynamic deletion tests.
- A newly created policy is checked against active/failed records. Overlapping IP/protocol and switch scopes are conservatively rejected, regardless of port separation.
- Ryu REST is internal-only. API bound to localhost. **No authentication** is built into this lab version.
- `Base.metadata.create_all` initializes a development DB. Alembic migrations, PATCH/disable, timed rules, background reconciliation, authentication, and atomic multi-switch deployment are deliberately postponed.
- OpenFlow REST add returns before definitive device confirmation. The API reads flow stats but this is not a complete Barrier/transaction/traffic-proof guarantee. Controller restarts can erase installed rules; the status endpoint detects drift but does not auto-repair it.
- Avoid concurrent policy creation in this version; transactional exclusion and recovery of failures need subsequent work.
- Run local unit tests from `policy-manager`: `pip install -r requirements.txt pytest && PYTHONPATH=. pytest -q`.
- `/health` is application liveness, not DB/Ryu readiness.
