"""Revocable bearer credentials for registered, project-scoped inspection clients."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, false
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class InspectionGrant(Base):
    __tablename__ = "inspection_grant"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), index=True)
    client_label: Mapped[str] = mapped_column(String(80))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    disclosures: Mapped[list[str]] = mapped_column(JSON)
    project_summaries: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InspectionCall(Base):
    """Local project call history, without request/result contents or integrity claims."""

    __tablename__ = "inspection_call"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("inspection_grant.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), index=True)
    operation: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    response_bytes: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
