"""A flow entry tied to a revision and target switch, not merely to a cookie."""
from datetime import datetime
from sqlalchemy import DateTime, BigInteger, ForeignKey, Integer, String, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class FlowDeployment(Base):
    __tablename__ = "flow_deployments"
    __table_args__ = (
        UniqueConstraint("revision_id", "dpid", "flow_index", name="uq_flow_revision_switch_index"),
        Index("ix_flow_deployments_state", "deployment_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(64), ForeignKey("policies.id", ondelete="RESTRICT"), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(36), ForeignKey("policy_revisions.id", ondelete="RESTRICT"), nullable=False)
    operation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("policy_operations.id"), nullable=True)
    dpid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    flow_index: Mapped[int] = mapped_column(Integer, nullable=False)
    cookie: Mapped[int] = mapped_column(BigInteger, nullable=False)
    flow_spec: Mapped[dict] = mapped_column(JSONB, nullable=False)
    flow_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deployment_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unknown")
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
