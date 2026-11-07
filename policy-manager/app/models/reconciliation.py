"""One durable row per observed anomaly episode, not one row per poll."""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ReconciliationFinding(Base):
    __tablename__ = "reconciliation_findings"
    __table_args__ = (
        Index(
            "uq_reconciliation_open_finding", "finding_key", unique=True,
            postgresql_where=text("resolved_at IS NULL"),
            sqlite_where=text("resolved_at IS NULL"),
        ),
        Index("ix_reconciliation_findings_open", "resolved_at", "dpid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    finding_key: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # missing, modified, extra, unknown
    dpid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    policy_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("policies.id"), nullable=True)
    deployment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("flow_deployments.id"), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
