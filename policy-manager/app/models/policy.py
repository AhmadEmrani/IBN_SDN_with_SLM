from datetime import datetime, timezone
from sqlalchemy import String, DateTime, BigInteger, Integer
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
