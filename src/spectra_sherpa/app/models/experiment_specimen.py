from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.experiment import Experiment


class ExperimentSpecimen(Base):
    """Mutable, experiment-owned specimen metadata.

    Acquisition plans may snapshot this metadata and retain ``specimen_uid``
    as provenance, but the catalog is not acquisition intent and is never the
    authority for measured-sample package data.
    """

    __tablename__ = "experiment_specimen"
    __table_args__ = (
        UniqueConstraint("specimen_uid", name="uq_experiment_specimen_uid"),
        UniqueConstraint("experiment_id", "specimen_key", name="uq_experiment_specimen_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    specimen_uid: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid.uuid4()), nullable=False)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiment.id", ondelete="CASCADE"), nullable=False, index=True
    )
    specimen_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    specimen_type: Mapped[str | None] = mapped_column(String(100))
    brand: Mapped[str | None] = mapped_column(String(100))
    cas_number: Mapped[str | None] = mapped_column(String(50))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa.true(), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    experiment: Mapped[Experiment] = relationship("Experiment", back_populates="specimens")
