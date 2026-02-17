"""
Workflow version history models for tracking workflow changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.models.user import User


class WorkflowVersion(Base):
    """
    Represents a saved version of a workflow.

    Each time a workflow is saved, a new version record is created with a snapshot
    of the complete workflow state (nodes, edges, parameters, canvas state).
    """

    __tablename__ = "workflow_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True
    )
    change_description: Mapped[str | None] = mapped_column(
        Text
    )  # Optional user-provided description of changes
    snapshot: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )  # Complete workflow state: nodes, edges, params, canvas

    # Relationships
    workflow = relationship("Workflow", back_populates="versions")
    user = relationship("User")

    def __repr__(self) -> str:
        return f"<WorkflowVersion(workflow_id={self.workflow_id}, version={self.version_number})>"
