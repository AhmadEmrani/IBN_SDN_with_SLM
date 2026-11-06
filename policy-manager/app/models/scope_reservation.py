"""One durable reservation per network and datapath until completion."""
from datetime import datetime, timezone
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class ScopeReservation(Base):
    __tablename__ = 'scope_reservations'
    __table_args__ = (Index('ix_scope_reservations_operation', 'operation_id'),)

    network_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    dpid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(36), ForeignKey('policy_operations.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
