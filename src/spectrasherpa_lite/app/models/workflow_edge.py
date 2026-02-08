"""
WorkflowEdge model - represents connections between nodes in a workflow.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workflow import Workflow


class WorkflowEdge(Base):
    """
    Represents a directed edge (connection) between two nodes in a workflow.

    Defines the data flow from one node's output to another node's input.
    """

    __tablename__ = "workflow_edge"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_node_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # Source node ID (within workflow)
    to_node_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # Target node ID (within workflow)
    from_output: Mapped[str] = mapped_column(
        String(100), nullable=False, default="default"
    )  # Output port name
    to_input: Mapped[str] = mapped_column(
        String(100), nullable=False, default="default"
    )  # Input port name
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    workflow = relationship("Workflow", back_populates="edges")
