"""
Execution run model for persisting workflow execution results.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.batch_prediction import BatchPrediction
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.user import User
    from spectra_sherpa.app.models.workflow import Workflow


class ExecutionRun(Base):
    """
    A saved snapshot of a workflow execution.

    Stores scalar metrics (results_summary), parameter snapshot, and diagnostics
    so users can compare runs side-by-side. Full spectral arrays are NOT stored —
    only compact scalar metrics extracted by the frontend.
    """

    # Allowed values for the ``status`` column. Keep in sync with
    # ``_RUN_ACTION_BY_STATUS`` in ``app/api/v1/routes/workflows/_helpers.py``
    # and the CheckConstraint below.
    #
    # Includes lifecycle (``pending`` / ``running``) AND terminal
    # (``completed`` / ``partial`` / ``error`` / ``failed`` / ``cancelled``)
    # values. The batch route (``deploy.py``) and folder-watch service
    # pre-create rows in ``running`` state, then update them on completion;
    # narrowing the constraint to terminal-only broke those paths in PR #158.
    VALID_STATUSES: tuple[str, ...] = (
        "pending",
        "running",
        "completed",
        "partial",
        "error",
        "failed",
        "cancelled",
    )

    __tablename__ = "execution_run"
    __table_args__ = (
        CheckConstraint(
            "run_kind IN ('training', 'batch_inference', 'data', 'other')",
            name="ck_execution_run_run_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'error', 'failed', 'cancelled')",
            name="ck_execution_run_status",
        ),
        # Idempotent-execute lookup AND atomic single-flight reservation.
        # UNIQUE PARTIAL index: collisions only count when a key is present,
        # so non-idempotent callers (no header) are unaffected. The
        # uniqueness lets the route claim a key by INSERTing a reservation
        # row before executing; concurrent retries with the same key lose
        # the race with IntegrityError and replay the winner's row.
        Index(
            "uq_execution_run_idempotency_key",
            "user_id",
            "workflow_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_version_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_version.id", ondelete="SET NULL"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # "completed", "partial", "error"
    params_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)  # {node_id: {param: value}}
    results_summary: Mapped[dict] = mapped_column(JSON, nullable=False)  # {node_id: {metric: value}}
    diagnostics: Mapped[dict | None] = mapped_column(JSON)
    node_statuses: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    integrity_hash: Mapped[str | None] = mapped_column(String(64))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notes: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list | None] = mapped_column(JSON, server_default="[]")
    source_type: Mapped[str | None] = mapped_column(
        String(50), server_default="manual"
    )  # "manual" | "batch" | "folder_watch"
    source_metadata: Mapped[dict | None] = mapped_column(JSON)
    model_ids: Mapped[list | None] = mapped_column(JSON)  # list of artifact_uid strings used in this run
    run_kind: Mapped[str] = mapped_column(
        String(50), default="training", server_default="training", nullable=False
    )  # "training" | "batch_inference" | "data" | "other"
    applied_artifact_uids: Mapped[list | None] = mapped_column(JSON, default=list)
    # RFC-7240-ish: opaque client-supplied token that lets a retried
    # POST /workflows/{id}/execute replay the original response instead
    # of running the workflow again. Nullable so non-idempotent callers
    # (no header) stay untouched.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Relationships
    project: Mapped[Project | None] = relationship("Project")
    workflow: Mapped[Workflow | None] = relationship("Workflow", back_populates="runs")
    user: Mapped[User] = relationship("User")
    predictions: Mapped[list[BatchPrediction]] = relationship(
        "BatchPrediction", back_populates="run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ExecutionRun(id={self.id}, workflow_id={self.workflow_id}, name='{self.name}')>"
