"""
Workflow database models for DAG-based analysis pipelines.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.user import User
    from spectra_sherpa.app.models.workflow_node import WorkflowNode
    from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
    from spectra_sherpa.app.models.workflow_version import WorkflowVersion
    from spectra_sherpa.app.models.workflow_tag import WorkflowTag
    from spectra_sherpa.app.models.workflow_folder import WorkflowFolder
    from spectra_sherpa.app.models.execution_run import ExecutionRun


class Workflow(Base):
    """
    Represents a saved workflow (DAG pipeline).

    A workflow is a collection of nodes and edges that define a data analysis pipeline.
    """

    __tablename__ = "workflow"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_folder.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", index=True
    )  # draft, active, archived
    canvas_state: Mapped[dict | None] = mapped_column(
        JSON
    )  # UI state (zoom, pan, etc.)
    notes: Mapped[str | None] = mapped_column(
        Text
    )  # Markdown notes/documentation for workflow
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    integrity_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    # Spectral context (Sherpa hook — provides technique/sample context for AI guidance)
    technique: Mapped[str | None] = mapped_column(
        String(50)
    )  # e.g. "FTIR", "Raman", "NMR", "UV-Vis", "NIR"
    sample_type: Mapped[str | None] = mapped_column(
        String(100)
    )  # e.g. "polymer blend", "pharmaceutical tablet", "wine"
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), index=True, nullable=True
    )

    # Relationships
    user = relationship("User", back_populates="workflows")
    project = relationship("Project", back_populates="workflows")
    nodes = relationship(
        "WorkflowNode", back_populates="workflow", cascade="all, delete-orphan"
    )
    edges = relationship(
        "WorkflowEdge", back_populates="workflow", cascade="all, delete-orphan"
    )
    versions = relationship(
        "WorkflowVersion",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowVersion.version_number.desc()",
    )
    folder = relationship("WorkflowFolder", back_populates="workflows")
    runs = relationship(
        "ExecutionRun",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="ExecutionRun.created_at.desc()",
    )
    tags = relationship(
        "WorkflowTag",
        secondary="workflow_tag_association",
        back_populates="workflows",
    )
