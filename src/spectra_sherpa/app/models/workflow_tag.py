"""
Workflow tag models for workflow categorization and search.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Table, Column, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.user import User
    from spectra_sherpa.app.models.workflow import Workflow


# Association table for many-to-many relationship between workflows and tags
workflow_tag_association = Table(
    "workflow_tag_association",
    Base.metadata,
    Column("workflow_id", Integer, ForeignKey("workflow.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("workflow_tag.id", ondelete="CASCADE"), primary_key=True),
)


class WorkflowTag(Base):
    """
    Represents a tag that can be applied to workflows.

    Tags are user-scoped and can be reused across multiple workflows for
    categorization, filtering, and search.
    """

    __tablename__ = "workflow_tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str | None] = mapped_column(
        String(7)
    )  # Hex color code (e.g., "#FF5733")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user = relationship("User")
    workflows = relationship(
        "Workflow",
        secondary=workflow_tag_association,
        back_populates="tags",
    )

    def __repr__(self) -> str:
        return f"<WorkflowTag(name={self.name}, user_id={self.user_id})>"
