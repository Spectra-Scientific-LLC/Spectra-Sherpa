from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Experiment(Base):
    __tablename__ = "experiment"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    metadata_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="experiments")
    files = relationship(
        "ExperimentFile", back_populates="experiment", cascade="all, delete-orphan"
    )
    versions = relationship(
        "ExpVersion", back_populates="experiment", cascade="all, delete-orphan"
    )
    samples = relationship(
        "Sample", back_populates="experiment", cascade="all, delete-orphan"
    )
    mixtures = relationship(
        "Mixture", back_populates="experiment", cascade="all, delete-orphan"
    )
    factor_definitions = relationship(
        "FactorDefinition", back_populates="experiment", cascade="all, delete-orphan"
    )
    plate_wells = relationship(
        "PlateWell", back_populates="experiment", cascade="all, delete-orphan"
    )
    run_levels = relationship(
        "RunLevel", back_populates="experiment", cascade="all, delete-orphan"
    )
    matched_acquisitions = relationship(
        "MatchedAcquisition", back_populates="experiment", cascade="all, delete-orphan"
    )
