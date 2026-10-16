"""Append-only scientist decisions scoped to one PCA workflow and exact source."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class SampleReviewRevision(Base):
    __tablename__ = "sample_review_revision"
    __table_args__ = (UniqueConstraint("workflow_id", "pca_node_id", "revision", name="uq_sample_review_revision"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow.id", ondelete="CASCADE"), index=True)
    pca_node_id: Mapped[str] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[int] = mapped_column(ForeignKey("execution_run.id", ondelete="RESTRICT"))
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    action: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    sample_ids: Mapped[list] = mapped_column(JSON)
    source_digest: Mapped[str] = mapped_column(String(64))
    graph_digest: Mapped[str] = mapped_column(String(64))
    state: Mapped[dict] = mapped_column(JSON)
