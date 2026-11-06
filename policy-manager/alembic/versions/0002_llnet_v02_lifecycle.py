"""Add durable scope reservations and worker leases for stage-2 operations.

Revision ID: 0002_v02_lifecycle
Revises: 0001_v02_foundation
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_v02_lifecycle'
down_revision = '0001_v02_foundation'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('policies', sa.Column('applied_state', sa.String(16), nullable=False, server_default='unknown'))
    op.add_column('policy_operations', sa.Column('requested_state', sa.String(16), nullable=True))
    op.add_column('policy_operations', sa.Column('base_desired_state', sa.String(16), nullable=True))
    op.add_column('policy_operations', sa.Column('runner_token', sa.String(36), nullable=True))
    op.add_column('policy_operations', sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        'scope_reservations',
        sa.Column('network_id', sa.String(100), primary_key=True),
        sa.Column('dpid', sa.BigInteger(), primary_key=True),
        sa.Column('operation_id', sa.String(36), sa.ForeignKey('policy_operations.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_scope_reservations_operation', 'scope_reservations', ['operation_id'])


def downgrade():
    raise RuntimeError('Destructive downgrade intentionally disabled; use a verified DB restore.')
