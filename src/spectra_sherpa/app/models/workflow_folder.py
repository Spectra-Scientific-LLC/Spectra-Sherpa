"""
Workflow folder models for hierarchical workflow organization.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    pass


class WorkflowFolder(Base):
    """
    Represents a folder for organizing workflows hierarchically.

    Folders are user-scoped and can be nested to create a tree structure.
    """

    __tablename__ = "workflow_folder"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_folder.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user = relationship("User")
    parent = relationship("WorkflowFolder", remote_side=[id], back_populates="children")
    children = relationship("WorkflowFolder", back_populates="parent", cascade="all, delete-orphan")
    workflows = relationship("Workflow", back_populates="folder")

    def __repr__(self) -> str:
        return f"<WorkflowFolder(name={self.name}, parent_id={self.parent_id})>"
