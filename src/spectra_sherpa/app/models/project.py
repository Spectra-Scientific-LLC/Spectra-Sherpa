"""
Project database models — hierarchical native container for experiments,
workflows, scripts, model artifacts, versions, and export/import state.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func, or_, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.advisor_channel import AdvisorChannel
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.project_data_source import ProjectDataSource
    from spectra_sherpa.app.models.project_script import ProjectScript
    from spectra_sherpa.app.models.user import User
    from spectra_sherpa.app.models.workflow import Workflow


class Project(Base):
    """
    Hierarchical project container — aggregates Experiments, Workflows, and
    sub-Projects under a single organizational umbrella.
    """

    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True
    )  # renamed to avoid clash with SA .metadata
    technique: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sample_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="projects")
    parent: Mapped[Project | None] = relationship("Project", remote_side=[id], back_populates="children")
    children: Mapped[list[Project]] = relationship("Project", back_populates="parent", cascade="all, delete-orphan")
    experiments: Mapped[list[Experiment]] = relationship("Experiment", back_populates="project")
    workflows: Mapped[list[Workflow]] = relationship("Workflow", back_populates="project")
    data_sources: Mapped[list[ProjectDataSource]] = relationship(
        "ProjectDataSource",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectDataSource.sort_order",
    )
    advisor_channels: Mapped[list[AdvisorChannel]] = relationship(
        "AdvisorChannel",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    models: Mapped[list[ModelArtifact]] = relationship("ModelArtifact", back_populates="project")
    scripts: Mapped[list[ProjectScript]] = relationship(
        "ProjectScript",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectScript.priority",
    )
    versions: Mapped[list[ProjectVersion]] = relationship(
        "ProjectVersion",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectVersion.version_number.desc()",
    )


class ProjectVersion(Base):
    """
    Immutable snapshot of a Project tree at a point in time ("Save All").

    The ``snapshot`` JSON column captures the full state:
    {
      "name": str,
      "description": str | null,
      "metadata": dict,
      "technique": str | null,
      "sample_type": str | null,
      "experiments": [
        {"id": int, "name": str, "file_count": int,
         "files": [{"id": int, "file_path": str, "stage": str}]}
      ],
      "workflows": [
        {"id": int, "name": str, "integrity_hash": str,
         "nodes": [...], "edges": [...]}
      ],
      "children": [  # recursive sub-project snapshots
        {"id": int, "name": str, "experiments": [...], "workflows": [...], "children": [...]}
      ]
    }
    """

    __tablename__ = "project_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    change_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    include_raw_data: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="versions")
    user: Mapped[User] = relationship("User")


def live_project_filter(project_column):
    """Restrict a user-scoped listing to rows outside a deleted project.

    Permanent project deletion keeps a tree that still holds retained model
    evidence as a hidden provenance tombstone, so its rows are never removed.
    Without this filter the experiments and workflows inside that tree keep
    their ``project_id`` and stay listed and editable after the owner
    confirmed a permanent deletion. Unfiled rows (NULL ``project_id``) stay
    visible, so this cannot be written as a bare ``NOT IN``.
    """
    return or_(
        project_column.is_(None),
        project_column.in_(select(Project.id).where(Project.deleted_at.is_(None))),
    )
