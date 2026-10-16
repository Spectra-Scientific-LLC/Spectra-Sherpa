"""Append-only E1655 history bound to one native saved-model artifact."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class SavedModelQualificationRecord(Base):
    __tablename__ = "saved_model_qualification_record"
    __table_args__ = (
        UniqueConstraint("user_id", "artifact_uid", "record_digest", name="uq_saved_model_qualification_digest"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_uid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    record_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    application_plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_view_id: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_view_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
