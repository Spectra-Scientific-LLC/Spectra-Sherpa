from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class Sample(Base):
    """Sample database - stores metadata only (no spectra)"""

    __tablename__ = "sample"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiment.id"), nullable=False, index=True)
    sample_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str | None] = mapped_column(String(100))  # Solvent, Standard, Unknown
    brand: Mapped[str | None] = mapped_column(String(100))
    cas_number: Mapped[str | None] = mapped_column(String(50))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    experiment = relationship("Experiment", back_populates="samples")
    mixture_components = relationship("MixtureComponent", back_populates="sample", cascade="all, delete-orphan")
