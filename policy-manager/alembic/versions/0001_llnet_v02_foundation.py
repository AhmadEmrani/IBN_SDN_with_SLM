"""Create v0.2 operational schema and preserve v0.1 policy records.

Revision ID: 0001_v02_foundation
Revises:

This intentional bootstrap supports either the already-running v0.1 PostgreSQL
schema or a fresh database. It NEVER deletes legacy policy rows.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_v02_foundation"
down_revision = None
branch_labels = None
depends_on = None


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def upgrade():
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())

    # v0.1 originally created this table with Base.metadata.create_all().
    if "policies" not in existing_tables:
        op.create_table(
            "policies",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("cookie", sa.BigInteger(), nullable=False, unique=True),
            sa.Column("definition", JSONB(), nullable=False),
            sa.Column("compiled_flows", JSONB(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
            sa.Column("last_error", sa.String(2000), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )

    op.create_table(
        "policy_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("policy_id", sa.String(64), sa.ForeignKey("policies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("intent_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("policy_id", "revision_no", name="uq_policy_revision_number"),
    )

    existing_cols = {c["name"] for c in sa.inspect(bind).get_columns("policies")}
    if "desired_state" not in existing_cols:
        op.add_column("policies", sa.Column("desired_state", sa.String(16), nullable=False, server_default="enabled"))
    if "desired_revision_id" not in existing_cols:
        op.add_column("policies", sa.Column("desired_revision_id", sa.String(36), nullable=True))
    if "applied_revision_id" not in existing_cols:
        op.add_column("policies", sa.Column("applied_revision_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_policies_desired_revision", "policies", "policy_revisions", ["desired_revision_id"], ["id"])
    op.create_foreign_key("fk_policies_applied_revision", "policies", "policy_revisions", ["applied_revision_id"], ["id"])

    op.create_table(
        "policy_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("policy_id", sa.String(64), sa.ForeignKey("policies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operation_type", sa.String(20), nullable=False),
        sa.Column("requested_revision_id", sa.String(36), sa.ForeignKey("policy_revisions.id"), nullable=True),
        sa.Column("base_revision_id", sa.String(36), sa.ForeignKey("policy_revisions.id"), nullable=True),
        sa.Column("requester_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("airflow_run_id", sa.String(255), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("requester_id", "idempotency_key", name="uq_operation_idempotency"),
    )
    op.create_index("ix_policy_operations_status_created", "policy_operations", ["status", "created_at"])

    op.create_table(
        "operation_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("policy_operations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("step_name", sa.String(64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("details", JSONB(), nullable=False),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_operation_events_operation_time", "operation_events", ["operation_id", "created_at"])

    op.create_table(
        "flow_deployments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("policy_id", sa.String(64), sa.ForeignKey("policies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("policy_revisions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("policy_operations.id"), nullable=True),
        sa.Column("dpid", sa.BigInteger(), nullable=False),
        sa.Column("flow_index", sa.Integer(), nullable=False),
        sa.Column("cookie", sa.BigInteger(), nullable=False),
        sa.Column("flow_spec", JSONB(), nullable=False),
        sa.Column("flow_hash", sa.String(64), nullable=False),
        sa.Column("deployment_status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_snapshot", JSONB(), nullable=True),
        sa.UniqueConstraint("revision_id", "dpid", "flow_index", name="uq_flow_revision_switch_index"),
    )
    op.create_index("ix_flow_deployments_state", "flow_deployments", ["deployment_status"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("policy_operations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("dispatch_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("operation_id", "event_type", name="uq_outbox_operation_event"),
    )
    op.create_index("ix_outbox_status_next_retry", "outbox_events", ["dispatch_status", "next_retry_at"])

    op.create_table(
        "api_request_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(72), nullable=False),
        sa.Column("method", sa.String(12), nullable=False),
        sa.Column("route", sa.String(255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Import existing policies. Historical OpenFlow installation is *not*
    # assumed to be currently installed: every imported deployment is unknown.
    legacy_rows = bind.execute(sa.text(
        "SELECT id, revision, cookie, definition, compiled_flows, status, created_at "
        "FROM policies WHERE desired_revision_id IS NULL ORDER BY id"
    )).mappings().all()

    for row in legacy_rows:
        definition = row["definition"]
        if not isinstance(definition, dict):
            raise ValueError(f"Policy {row['id']} contains non-object JSON definition")
        metadata = definition.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        status = row["status"]
        desired_state = "deleted" if status == "deleted" else (
            "disabled" if (definition.get("policy") or {}).get("enabled") is False else "enabled"
        )
        rev_id = str(uuid4())
        bind.execute(sa.text(
            "INSERT INTO policy_revisions "
            "(id, policy_id, revision_no, definition, definition_hash, source, intent_id, created_at) "
            "VALUES (:id, :policy_id, :revision_no, CAST(:definition AS jsonb), "
            ":definition_hash, :source, :intent_id, :created_at)"
        ), dict(
            id=rev_id, policy_id=row["id"], revision_no=row["revision"],
            definition=_canonical(definition), definition_hash=_digest(definition),
            source=metadata.get("source") or "legacy", intent_id=metadata.get("intent_id"),
            created_at=row["created_at"] or datetime.now(timezone.utc),
        ))
        bind.execute(sa.text(
            "UPDATE policies SET desired_state=:desired_state, desired_revision_id=:revision_id, "
            "applied_revision_id=:applied_revision WHERE id=:policy_id"
        ), dict(desired_state=desired_state, revision_id=rev_id,
                applied_revision=rev_id if status == "active" else None, policy_id=row["id"]))

        flows = row["compiled_flows"] or []
        if not isinstance(flows, list):
            raise ValueError(f"Policy {row['id']} compiled_flows is not a list")
        per_switch_count = {}
        for flow in flows:
            dpid = int(flow["dpid"])
            flow_index = per_switch_count.get(dpid, 0)
            per_switch_count[dpid] = flow_index + 1
            bind.execute(sa.text(
                "INSERT INTO flow_deployments "
                "(id, policy_id, revision_id, operation_id, dpid, flow_index, cookie, "
                "flow_spec, flow_hash, deployment_status, last_observed_at, observed_snapshot) "
                "VALUES (:id, :policy_id, :revision_id, NULL, :dpid, :flow_index, :cookie, "
                "CAST(:flow_spec AS jsonb), :flow_hash, 'unknown', NULL, NULL)"
            ), dict(id=str(uuid4()), policy_id=row["id"], revision_id=rev_id,
                    dpid=dpid, flow_index=flow_index,
                    cookie=int(flow.get("cookie", row["cookie"])),
                    flow_spec=_canonical(flow), flow_hash=_digest(flow)))


def downgrade():
    raise RuntimeError("Destructive downgrade is intentionally blocked. Restore a verified DB backup instead.")
