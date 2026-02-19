"""
WorkflowNode model - represents a node instance in a workflow.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    pass


class WorkflowNode(Base):
    """
    Represents a node instance within a workflow.

    Each node has a specific type (e.g., "model.pca", "smooth.savitzky_golay")
    and its own parameters and position on the canvas.
    """

    __tablename__ = "workflow_node"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)  # Unique ID within workflow
    node_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)  # e.g., "model.pca"
    label: Mapped[str | None] = mapped_column(String(255))  # Custom label
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    annotation: Mapped[str | None] = mapped_column(Text)  # Markdown annotation/comment for node
    position_x: Mapped[float | None] = mapped_column(Float)  # Canvas X coordinate
    position_y: Mapped[float | None] = mapped_column(Float)  # Canvas Y coordinate
    execution_order: Mapped[int | None] = mapped_column(Integer)  # Computed topological order
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )  # pending, running, completed, error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    workflow = relationship("Workflow", back_populates="nodes")
