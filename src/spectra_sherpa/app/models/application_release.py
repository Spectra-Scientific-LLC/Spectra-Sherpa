"""Durable release identity for one deployable fitted application."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.user import User
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.models.workflow_version import WorkflowVersion


class ApplicationRelease(Base):
    """The project-scoped identity passed into Deploy and portable hand-offs.

    A release is deliberately separate from ``ModelArtifact.is_deploy_ready``.
    The latter remains a compatibility/user-interface flag; this row records
    the immutable origin and the exact release that a watch or package names.
    """

    __tablename__ = "application_release"
    __table_args__ = (
        UniqueConstraint("model_artifact_uid", name="uq_application_release_model_artifact"),
        UniqueConstraint("canonical_artifact_id", name="uq_application_release_canonical_artifact"),
        Index("ix_application_release_project_state", "project_id", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    handle: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_version.id", ondelete="SET NULL"), nullable=True
    )
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("execution_run.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_artifact_uid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    canonical_artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_project_artifact.id", ondelete="CASCADE"), nullable=True, index=True
    )
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, server_default="released")
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    package_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    package_schema_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    readiness: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provenance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship("User")
    project: Mapped[Project] = relationship("Project")
    workflow: Mapped[Workflow] = relationship("Workflow")
    workflow_version: Mapped[WorkflowVersion | None] = relationship("WorkflowVersion")
    source_run: Mapped[ExecutionRun | None] = relationship("ExecutionRun")
    model_artifact: Mapped[ModelArtifact | None] = relationship(
        "ModelArtifact",
        foreign_keys=[model_artifact_uid],
        primaryjoin="ApplicationRelease.model_artifact_uid == ModelArtifact.artifact_uid",
        viewonly=True,
    )
    canonical_artifact: Mapped[CanonicalProjectArtifact | None] = relationship("CanonicalProjectArtifact")
