# LLNet Stage 3 — Single-Compose Overlay

GitHub base inspected: AhmadEmrani/IBN_SDN_with_SLM `main` at `1c930958c02ba6604126841e97ea8ee0147701ba`.

- Replaces root `docker-compose.yml` with a single definition for all Stage-2 and Stage-3 services, preserving `postgres_data`, `sdn-net`, Ryu/Mininet settings, and original policy-api settings.
- Adds Airflow 3.2.2 + LocalExecutor, separate `airflow-db`, Outbox Dispatcher, Airflow Adapter, private backend endpoints and DAG `llnet_policy_operation`.
- No Docker Compose wrapper script or additional Compose override required.
- Local secret generation is documented with shell/openssl; existing Postgres password is preserved.
- Stage-2 code is untouched except `policy-manager/app/main.py` which includes Stage-3 internal router.
- No new Alembic migration required.
- Tested: YAML syntax and structural compatibility of 11 service definitions, Python syntax of new code. Full Docker/Airflow/Mininet integration must be tested on user's host.
- GitHub is read-only from this session; no commits/pushes performed.

Start with `APPLY_STAGE3_FA.md`.
