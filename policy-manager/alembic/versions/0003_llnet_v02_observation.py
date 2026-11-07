"""Stage 4A: read-only network observation findings.

Revision ID: 0003_v02_observation
Revises: 0002_v02_lifecycle
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_v02_observation"
down_revision = "0002_v02_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reconciliation_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("finding_key", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("dpid", sa.BigInteger(), nullable=False),
        sa.Column("policy_id", sa.String(64), sa.ForeignKey("policies.id"), nullable=True),
        sa.Column("deployment_id", sa.String(36), sa.ForeignKey("flow_deployments.id"), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_count", sa.Integer(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False),
    )
    op.create_index(
        "uq_reconciliation_open_finding", "reconciliation_findings", ["finding_key"],
        unique=True, postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index(
        "ix_reconciliation_findings_open", "reconciliation_findings", ["resolved_at", "dpid"],
    )


def downgrade():
    raise RuntimeError("Destructive downgrade intentionally disabled; restore a verified backup.")
