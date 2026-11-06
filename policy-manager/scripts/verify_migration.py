"""Read-only DB sanity checks after applying Alembic Stage 2 (0002).

Usage inside policy-api image: python scripts/verify_migration.py
"""
from sqlalchemy import create_engine, inspect, text
from app.config import DATABASE_URL

TABLES = {
    "policies", "policy_revisions", "policy_operations", "operation_events",
    "flow_deployments", "outbox_events", "api_request_events", "alembic_version", "scope_reservations",
}


def main():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        names = set(inspect(conn).get_table_names())
        missing = TABLES - names
        if missing:
            raise SystemExit(f"FAIL: missing tables: {sorted(missing)}")
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if version != "0002_v02_lifecycle":
            raise SystemExit(f"FAIL: unexpected schema version {version}")
        policy_count = conn.execute(text("SELECT count(*) FROM policies")).scalar_one()
        imported_count = conn.execute(text("SELECT count(*) FROM policy_revisions")).scalar_one()
        missing_revisions = conn.execute(text(
            "SELECT count(*) FROM policies WHERE desired_revision_id IS NULL"
        )).scalar_one()
        missing_targets = conn.execute(text(
            "SELECT count(*) FROM policies p LEFT JOIN policy_revisions r "
            "ON p.desired_revision_id = r.id "
            "WHERE p.desired_revision_id IS NOT NULL AND r.id IS NULL"
        )).scalar_one()
        print(f"Schema: {version} | policies: {policy_count} | revisions: {imported_count}")
        print(f"Null desired revision pointers: {missing_revisions} | broken pointers: {missing_targets}")
        if missing_revisions or missing_targets or imported_count < policy_count:
            raise SystemExit("FAIL: incomplete historical import")
        print("PASS: v0.2 stage2 tables and policy revision pointers")
    engine.dispose()


if __name__ == "__main__":
    main()
