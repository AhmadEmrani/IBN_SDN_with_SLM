"""Durable operation envelope; Airflow must never be the source of truth."""
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class PolicyOperation(Base):
    __tablename__ = "policy_operations"
    __table_args__ = (
        UniqueConstraint("requester_id", "idempotency_key", name="uq_operation_idempotency"),
        Index("ix_policy_operations_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(64), ForeignKey("policies.id", ondelete="RESTRICT"), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_revision_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("policy_revisions.id"), nullable=True)
    base_revision_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("policy_revisions.id"), nullable=True)
    requester_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    requested_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    base_desired_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    runner_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    airflow_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
