"""Append-only provenance for a workflow source node's data selection."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class WorkflowDataSelectionRevision(Base):
    __tablename__ = "workflow_data_selection_revision"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "source_node_id", "revision_number", name="uq_workflow_data_selection_revision"
        ),
        UniqueConstraint(
            "workflow_id", "source_node_id", "idempotency_key", name="uq_workflow_data_selection_idempotency"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False, index=True)
    source_node_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_data_selection_revision.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    selection: Mapped[dict] = mapped_column(JSON, nullable=False)
    graph_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    workflow = relationship("Workflow", back_populates="data_selection_revisions")
    author = relationship("User")
    parent = relationship("WorkflowDataSelectionRevision", remote_side="WorkflowDataSelectionRevision.id")
