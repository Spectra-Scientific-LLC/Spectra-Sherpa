"""Append-only watch QC history with optimistic sequence authority."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class InstrumentQCRecord(Base):
    __tablename__ = "instrument_qc_record"
    __table_args__ = (
        UniqueConstraint("watch_id", "sequence", name="uq_watch_qc_sequence"),
        UniqueConstraint("watch_id", "event_id", name="uq_watch_qc_event"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("folder_watch.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(nullable=False)
    event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
