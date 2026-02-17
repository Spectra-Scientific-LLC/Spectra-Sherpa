from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class Calibration(Base):
    __tablename__ = "calibration"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    compound_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    concentration_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    x_unit: Mapped[str] = mapped_column(String(50), nullable=False)
    pathlength_m: Mapped[float | None] = mapped_column(nullable=True)
    metadata_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="calibrations")
    files = relationship(
        "CalibrationFile", back_populates="calibration", cascade="all, delete-orphan"
    )
    models = relationship(
        "CalModel", back_populates="calibration", cascade="all, delete-orphan"
    )
