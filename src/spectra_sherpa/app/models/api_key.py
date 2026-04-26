from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class APIKey(Base):
    """
    Stores encrypted BYOK API keys for LLM providers.

    OSS owns only user-scoped keys. Older deployments may still contain
    legacy system rows with ``user_id=None``; the OSS runtime ignores them.
    Server-managed shared keys live in commercial server tables instead.
    """

    __tablename__ = "api_key"
    __table_args__ = (UniqueConstraint("user_id", "service_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    service_name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user = relationship("User", back_populates="api_keys")
