"""Durable custody for a canonical fitted artifact imported into one project."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class CanonicalProjectArtifact(Base):
    """The sole authority record for applying an imported canonical artifact.

    The content-addressed bytes are deliberately not sufficient authority.
    This record binds those bytes to the importing user, project and visible
    application workflow, as well as to the admitted package identities.
    """

    __tablename__ = "canonical_project_artifact"
    __table_args__ = (UniqueConstraint("project_id", "artifact_digest", name="uq_canonical_project_artifact"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False, unique=True)
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    capsule_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    application_plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    # The verified, data-free application plan remains readable provenance.
    # Worker-facing apply nodes intentionally retain only their exact artifact
    # bindings, so this immutable payload is the durable home for the original
    # fitted-operation parameters and their admitted source contracts.
    application_plan_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Integrity of the re-admitted application graph before a local source is
    # bound.  This is the durable baseline that makes the imported procedure
    # immutable while still allowing the scientist to select their own input.
    application_integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_dir: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
