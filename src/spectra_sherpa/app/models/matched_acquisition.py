from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class MatchedAcquisition(Base):
    """Auto-matched acquisition data"""

    __tablename__ = "matched_acquisition"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiment.id"), nullable=False, index=True)
    seq: Mapped[int | None] = mapped_column(Integer)
    filename: Mapped[str | None] = mapped_column(String(255))
    folder: Mapped[str | None] = mapped_column(String(255))
    timestamp: Mapped[int | None] = mapped_column(Integer)
    date: Mapped[str | None] = mapped_column(String(50))
    batch: Mapped[int | None] = mapped_column(Integer)
    sample_id: Mapped[str | None] = mapped_column(String(100))
    cell: Mapped[str | None] = mapped_column(String(50))
    special: Mapped[str | None] = mapped_column(String(100))
    factor_values: Mapped[dict | None] = mapped_column(JSON)  # Method/sample factor values

    experiment = relationship("Experiment", back_populates="matched_acquisitions")
