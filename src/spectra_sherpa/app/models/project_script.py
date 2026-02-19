"""
ProjectScript database model — stores Python scripts within a Project.

Aligned with SpectroChemPy's ``scp.Script`` concept:
  scp.Script.name    → name
  scp.Script.content → code (Text column)
  scp.Script.priority → priority (Float, execution order)
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.user import User
    from spectra_sherpa.app.models.workflow import Workflow


class ProjectScript(Base):
    """
    A Python script stored within a Project.

    Scripts may be user-authored or auto-generated from a Workflow's
    Python export pipeline.  The ``source_workflow_id`` tracks provenance
    for generated scripts.
    """

    __tablename__ = "project_script"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    source_workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="python")
    code: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="scripts")
    user: Mapped[User] = relationship("User")
    source_workflow: Mapped[Workflow | None] = relationship("Workflow")
