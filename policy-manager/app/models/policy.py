"""Legacy PolicyRecord with additive v0.2 desired/applied revision pointers.

The v0.1 API remains operational during stage 1. New v0.2 workflows are
introduced in subsequent stages; do not infer deployed state from these fields.
"""
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, BigInteger, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from app.db.session import Base


class PolicyRecord(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cookie: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    compiled_flows: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Added in v0.2 stage 1; nullable pointers support legacy writes during migration.
    desired_state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="enabled")
    desired_revision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("policy_revisions.id", name="fk_policies_desired_revision", use_alter=True), nullable=True
    )
    applied_revision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("policy_revisions.id", name="fk_policies_applied_revision", use_alter=True), nullable=True
    )
