# LLNet v0.2 — Stage 4B Safe Repair Overlay

Based on the user's **successfully exercised Stage 4A local tree** (not GitHub main, which did not yet contain Stage 4A at build time).

New files:

- `policy-manager/app/reconciliation/repair.py` — one-flow, manually triggered safe repair with current Operation Engine claim/lease and scope reservation.
- `policy-manager/app/cli/repair_missing.py` — read-only eligibility check by default; `--apply` explicitly triggers one repair.
- `policy-manager/tests/test_v04_repair.py` — 15 unit/safety tests (SQLite ORM emulator + fake Ryu).
- `docs/llnet-v02-stage4b-safe-repair.md` — architecture and limitations.
- `APPLY_STAGE4B_FA.md` — installation, lab validation, and recovery caution.

No Alembic migration; no extra compose file; no new service; no Airflow DAG; no code changes to Stage 2/3 or Stage 4A observer.

Local regression: 73 tests passing (15 new + 58 existing). Full PostgreSQL/Mininet end-to-end validation remains to be done on the user's lab.
