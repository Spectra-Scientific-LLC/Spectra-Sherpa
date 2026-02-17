from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class CalModel(Base):
    __tablename__ = "cal_model"
    __table_args__ = (UniqueConstraint("calibration_id", "version_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    calibration_id: Mapped[int] = mapped_column(
        ForeignKey("calibration.id"), nullable=False, index=True
    )
    version_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_type: Mapped[str] = mapped_column(String(50), nullable=False)
    model_path: Mapped[str] = mapped_column(String(500), nullable=False)
    r_squared: Mapped[float | None] = mapped_column(nullable=True)
    rmse: Mapped[float | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    calibration = relationship("Calibration", back_populates="models")
