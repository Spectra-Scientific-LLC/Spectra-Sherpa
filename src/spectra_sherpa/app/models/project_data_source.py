"""Project-level data source registry and workflow associations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow


class ProjectDataSource(Base):
    """A named dataset or external data origin associated with a project."""

    __tablename__ = "project_data_source"
    __table_args__ = (UniqueConstraint("project_id", "fingerprint", name="uq_project_data_source_fingerprint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="external", index=True)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#3b82f6")
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship("Project", back_populates="data_sources")
    workflow_links: Mapped[list[WorkflowDataSource]] = relationship(
        "WorkflowDataSource",
        back_populates="data_source",
        cascade="all, delete-orphan",
    )
    primary_workflows: Mapped[list[Workflow]] = relationship(
        "Workflow",
        back_populates="primary_data_source",
        foreign_keys="Workflow.primary_data_source_id",
    )


class WorkflowDataSource(Base):
    """Association between a workflow sheet and one project data source."""

    __tablename__ = "workflow_data_source"
    __table_args__ = (UniqueConstraint("workflow_id", "data_source_id", name="uq_workflow_data_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False, index=True)
    data_source_id: Mapped[int] = mapped_column(
        ForeignKey("project_data_source.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="secondary")
    first_seen_node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_node.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="data_source_links")
    data_source: Mapped[ProjectDataSource] = relationship("ProjectDataSource", back_populates="workflow_links")
