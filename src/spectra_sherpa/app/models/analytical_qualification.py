"""Append-only intended-use assessment and decision history."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class AnalyticalQualificationRecord(Base):
    __tablename__ = "analytical_qualification_record"
    __table_args__ = (
        UniqueConstraint("user_id", "workflow_id", "record_digest", name="uq_qualification_workflow_digest"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False, index=True)
    canonical_artifact_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_project_artifact.id", ondelete="CASCADE"), nullable=False
    )
    record_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
