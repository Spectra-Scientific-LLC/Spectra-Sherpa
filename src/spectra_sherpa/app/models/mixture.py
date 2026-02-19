from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class Mixture(Base):
    """Mixture definition for DOE"""

    __tablename__ = "mixture"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiment.id"), nullable=False, index=True)
    mixture_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    basis: Mapped[str] = mapped_column(String(20), default="volume")  # volume or mass
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    experiment = relationship("Experiment", back_populates="mixtures")
    components = relationship("MixtureComponent", back_populates="mixture", cascade="all, delete-orphan")
    plate_wells = relationship("PlateWell", back_populates="mixture", cascade="all, delete-orphan")
