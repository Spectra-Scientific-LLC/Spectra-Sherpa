"""
Folder watch model for automated file monitoring and processing.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.user import User
    from spectra_sherpa.app.models.workflow import Workflow


class FolderWatch(Base):
    """
    Configuration for a folder monitoring watch.

    Polls a server folder for new spectral files and auto-processes them
    through a selected workflow. Results are stored as ExecutionRuns +
    BatchPredictions.
    """

    __tablename__ = "folder_watch"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    folder_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_pattern: Mapped[str] = mapped_column(String(255), nullable=False, server_default="*")
    poll_interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    settle_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    processed_files: Mapped[dict | None] = mapped_column(JSON)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    user: Mapped[User] = relationship("User")
    workflow: Mapped[Workflow] = relationship("Workflow")

    def __repr__(self) -> str:
        return f"<FolderWatch(id={self.id}, name='{self.name}', folder='{self.folder_path}')>"
