"""
Model artifact persistence — trained model metadata and storage reference.

A ModelArtifact represents a saved, inspectable trained model. On disk,
each artifact is stored as ``manifest.json`` + ``arrays.npz`` under
``{data_dir}/models/{artifact_uid}/``.

ModelArtifact is a first-class Project member alongside Experiments,
Workflows, and Scripts.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.user import User
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.models.workflow_version import WorkflowVersion


class ModelArtifact(Base):
    """
    Persisted trained model artifact.

    Stores metadata in the DB for fast querying / listing, while the actual
    numpy arrays live on disk as ``arrays.npz`` alongside a human-readable
    ``manifest.json``.
    """

    __tablename__ = "model_artifact"

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_uid: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_version.id", ondelete="SET NULL"), nullable=True, index=True
    )
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # pca, pls, plsda, knn, simca, mcr, efa, simplisma, pcr, svr, ica, nmf
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Storage
    artifact_dir: Mapped[str] = mapped_column(String(500), nullable=False)
    integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Quick-inspect metadata (avoids loading arrays from disk)
    n_features: Mapped[int] = mapped_column(Integer, nullable=False)
    n_components: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_axis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provenance
    training_data_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preprocessing_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lifecycle
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=sa.true(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped[User] = relationship("User")
    project: Mapped[Project | None] = relationship("Project", back_populates="models")
    workflow: Mapped[Workflow | None] = relationship("Workflow")
    workflow_version: Mapped[WorkflowVersion | None] = relationship("WorkflowVersion")

    def __repr__(self) -> str:
        return (
            f"<ModelArtifact(uid={self.artifact_uid!r}, "
            f"type={self.model_type!r}, name={self.name!r})>"
        )
