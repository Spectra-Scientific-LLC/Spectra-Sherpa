"""
Workflow database models for DAG-based analysis pipelines.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.lib.workflow_purpose import ANALYSIS_WORKFLOW

if TYPE_CHECKING:
    from spectra_sherpa.app.models.advisor_channel import AdvisorChannel
    from spectra_sherpa.app.models.project_data_source import ProjectDataSource, WorkflowDataSource


class Workflow(Base):
    """
    Represents a saved workflow (DAG pipeline).

    A workflow is a collection of nodes and edges that define a data analysis pipeline.
    """

    __tablename__ = "workflow"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('analysis', 'managed_candidate_authority')",
            name="ck_workflow_purpose",
        ),
        CheckConstraint(
            "data_origin IS NULL OR data_origin IN ('current', 'example')",
            name="ck_workflow_data_origin",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_folder.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", index=True
    )  # draft, active, archived
    # The Python default keeps isolated ORM fixtures conservative.  Every
    # production constructor is separately guarded to pass purpose explicitly;
    # the database remains closed and non-null.
    purpose: Mapped[str] = mapped_column(String(50), nullable=False, index=True, default=ANALYSIS_WORKFLOW)
    canvas_state: Mapped[dict | None] = mapped_column(JSON)  # UI state (zoom, pan, etc.)
    notes: Mapped[str | None] = mapped_column(Text)  # Markdown notes/documentation for workflow
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    integrity_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    proposal_receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Campaign cross-validation scope retained by a sheet opened from a
    # candidate; its evaluator is then scored with those exact folds.
    fold_validation_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Spectral context (Sherpa hook — provides technique/sample context for AI guidance)
    technique: Mapped[str | None] = mapped_column(String(50))  # e.g. "FTIR", "Raman", "NMR", "UV-Vis", "NIR"
    sample_type: Mapped[str | None] = mapped_column(
        String(100)
    )  # e.g. "polymer blend", "pharmaceutical tablet", "wine"
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), index=True, nullable=True
    )
    tab_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    primary_data_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_data_source.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tab_color_override: Mapped[str | None] = mapped_column(String(7), nullable=True)
    color_source: Mapped[str] = mapped_column(String(20), nullable=False, default="blank")
    created_from_template_id: Mapped[int | None] = mapped_column(nullable=True)
    created_from_template_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_from_template_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # How this sheet acquired its bound source. Nullable historical rows stay
    # explicitly unverified instead of being relabelled as current project data.
    data_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_from_workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sheet_order: Mapped[int] = mapped_column(nullable=False, default=0)

    # Relationships
    user = relationship("User", back_populates="workflows")
    project = relationship("Project", back_populates="workflows")
    created_from_workflow = relationship("Workflow", remote_side="[Workflow.id]")
    primary_data_source: Mapped[ProjectDataSource | None] = relationship(
        "ProjectDataSource",
        back_populates="primary_workflows",
        foreign_keys=[primary_data_source_id],
    )
    data_source_links: Mapped[list[WorkflowDataSource]] = relationship(
        "WorkflowDataSource",
        back_populates="workflow",
        cascade="all, delete-orphan",
    )
    advisor_channels: Mapped[list[AdvisorChannel]] = relationship(
        "AdvisorChannel",
        back_populates="workflow",
        cascade="all, delete-orphan",
    )
    nodes = relationship("WorkflowNode", back_populates="workflow", cascade="all, delete-orphan")
    edges = relationship("WorkflowEdge", back_populates="workflow", cascade="all, delete-orphan")
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
        order_by="ExecutionRun.created_at.desc()",
    )
    data_selection_revisions = relationship(
        "WorkflowDataSelectionRevision",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowDataSelectionRevision.revision_number.desc()",
    )
    tags = relationship(
        "WorkflowTag",
        secondary="workflow_tag_association",
        back_populates="workflows",
    )

    @property
    def data_source_ids(self) -> list[int]:
        links = sorted(
            self.data_source_links,
            key=lambda link: (0 if link.role == "primary" else 1, link.id),
        )
        return [link.data_source_id for link in links]

    @property
    def advisor_channel_id(self) -> int | None:
        for channel in self.advisor_channels:
            if channel.channel_type == "sheet":
                return channel.id
        return None
