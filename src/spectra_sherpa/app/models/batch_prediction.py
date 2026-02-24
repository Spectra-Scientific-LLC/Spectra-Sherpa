"""
Batch prediction model for per-file results within an execution run.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.execution_run import ExecutionRun


class BatchPrediction(Base):
    """
    Per-file prediction result within a batch execution run.

    Stores individual file outcomes for both batch runs (Experiments page)
    and folder watch auto-processing (Deploy page). Linked to a parent
    ExecutionRun that holds aggregate metrics.
    """

    __tablename__ = "batch_prediction"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("execution_run.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    results: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)
    model_id: Mapped[str | None] = mapped_column(String(64), index=True)  # primary model artifact_uid for this prediction # noqa: E501
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    run: Mapped[ExecutionRun] = relationship("ExecutionRun", back_populates="predictions")

    def __repr__(self) -> str:
        return f"<BatchPrediction(id={self.id}, file='{self.file_name}', status='{self.status}')>"
