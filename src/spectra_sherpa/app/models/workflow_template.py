"""
Workflow template models for pre-built workflow patterns.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text, JSON, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    pass


class WorkflowTemplate(Base):
    """
    Represents a pre-built workflow template for common analysis patterns.

    Templates are system-defined workflows that users can instantiate
    to quickly set up common chemometrics pipelines (calibration, classification, etc.).
    """

    __tablename__ = "workflow_template"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )  # calibration, classification, preprocessing, qc, etc.
    template_data: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )  # Complete workflow structure: nodes, edges, canvas_state
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )  # Can be disabled without deletion
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<WorkflowTemplate(name={self.name}, category={self.category})>"
