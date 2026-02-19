from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class APIKey(Base):
    """
    Stores encrypted API keys for LLM providers.

    Keys can be:
    - User-specific (user_id set): BYOK keys for individual users
    - System-wide (user_id=None): Shared keys managed by admins
    """

    __tablename__ = "api_key"
    __table_args__ = (UniqueConstraint("user_id", "service_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # user_id is nullable to allow system-wide keys (user_id=None)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True, index=True)
    service_name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user = relationship("User", back_populates="api_keys")
