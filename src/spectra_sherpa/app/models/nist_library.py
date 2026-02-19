from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class NistLibrary(Base):
    __tablename__ = "nist_library"
    __table_args__ = (UniqueConstraint("cas_number", "resolution"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cas_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    compound_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    resolution: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
