"""Sherpa Advisor channel scopes."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow


class AdvisorChannel(Base):
    """A project-level or workflow-sheet-level Sherpa Advisor conversation scope."""

    __tablename__ = "advisor_channel"
    __table_args__ = (
        UniqueConstraint("project_id", "workflow_id", "channel_type", name="uq_advisor_channel_scope"),
        UniqueConstraint("conversation_id", name="uq_advisor_channel_conversation_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow.id", ondelete="CASCADE"), nullable=True, index=True
    )
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False, default="project", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship("Project", back_populates="advisor_channels")
    workflow: Mapped[Workflow | None] = relationship("Workflow", back_populates="advisor_channels")
