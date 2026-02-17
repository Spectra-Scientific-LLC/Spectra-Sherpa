"""
Execution run model for persisting workflow execution results.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.batch_prediction import BatchPrediction
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.models.user import User


class ExecutionRun(Base):
    """
    A saved snapshot of a workflow execution.

    Stores scalar metrics (results_summary), parameter snapshot, and diagnostics
    so users can compare runs side-by-side. Full spectral arrays are NOT stored —
    only compact scalar metrics extracted by the frontend.
    """

    __tablename__ = "execution_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_version.id", ondelete="SET NULL")
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "completed", "partial", "error"
    params_snapshot: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )  # {node_id: {param: value}}
    results_summary: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )  # {node_id: {metric: value}}
    diagnostics: Mapped[dict | None] = mapped_column(JSON)
    node_statuses: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    integrity_hash: Mapped[str | None] = mapped_column(String(64))
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list | None] = mapped_column(JSON, server_default="[]")
    source_type: Mapped[str | None] = mapped_column(
        String(50), server_default="manual"
    )  # "manual" | "batch" | "folder_watch"
    source_metadata: Mapped[dict | None] = mapped_column(JSON)

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="runs")
    user: Mapped[User] = relationship("User")
    predictions: Mapped[list[BatchPrediction]] = relationship(
        "BatchPrediction", back_populates="run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ExecutionRun(id={self.id}, workflow_id={self.workflow_id}, name='{self.name}')>"
