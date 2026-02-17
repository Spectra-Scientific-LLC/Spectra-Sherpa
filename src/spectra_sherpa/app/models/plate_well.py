from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class PlateWell(Base):
    """96-well plate mapping"""

    __tablename__ = "plate_well"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiment.id"), nullable=False, index=True
    )
    well_position: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # A1, A2, ..., H12
    mixture_id: Mapped[int | None] = mapped_column(ForeignKey("mixture.id"))

    experiment = relationship("Experiment", back_populates="plate_wells")
    mixture = relationship("Mixture", back_populates="plate_wells")
