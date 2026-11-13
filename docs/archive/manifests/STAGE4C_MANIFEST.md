# LLNet v0.2 — Stage 4C Automatic Safe Healing

Source baseline: current Stage 4B on GitHub `main` checked November 7, 2026 (tree `f4e937074f356b746a6d5b949c24003420a8d813`).

Changes:

- `policy-manager/app/reconciliation/auto_heal.py` — NEW: one fresh, confirmed Missing per cycle; durable one-attempt-per-finding protection.
- `policy-manager/app/reconciliation/repair.py` — small extension to accept a stable requester/idempotency key; keeps Stage 4B manual defaults and safety behavior.
- `policy-manager/app/cli/observe_flows.py` — optional Stage 4C trigger after observe_once, only during daemon polling.
- `docker-compose.yml` — one new `LLNET_AUTO_HEAL` environment variable, default `false` on existing reconciler service.
- `policy-manager/tests/test_v04_auto_heal.py` — NEW: 13 tests; confirmed, unknown, stale, collisions, pending, unresolved, idempotency, opt-in/once and one operation per poll.
- `docs/llnet-v02-stage4c-auto-heal.md` — NEW architecture and safety specification.
- `APPLY_STAGE4C_FA.md` — NEW installation and real Mininet test guide.
- `STAGE4C_MANIFEST.md` — this file.

No new Docker service, DAG, migration, schema table or Compose override. No `.env` bundled. Existing Stage 2/3/4A and manual 4B paths remain intact. Local test suite: 86 tests PASS (fake Ryu + SQLite emulation). Live Docker/Mininet validation must be done by the user.
