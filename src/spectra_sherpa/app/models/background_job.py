from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class BackgroundJob(Base):
    __tablename__ = "background_job"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), server_default="pending", nullable=False, index=True
    )
    progress: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    progress_message: Mapped[str | None] = mapped_column(Text)
    result_path: Mapped[str | None] = mapped_column(String(500))
    error_message: Mapped[str | None] = mapped_column(Text)
    compute_location: Mapped[str] = mapped_column(
        String(20), server_default="local", nullable=False, index=True
    )
    compute_node: Mapped[str | None] = mapped_column(String(100))
    last_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user = relationship("User", back_populates="background_jobs")
