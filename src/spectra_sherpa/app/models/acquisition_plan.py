from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class AcquisitionPlan(Base):
    """The complete, versioned scientific intent for one multi-well experiment."""

    __tablename__ = "acquisition_plan"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiment.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    document: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    experiment = relationship("Experiment", back_populates="acquisition_plan")


class AcquisitionPlanPreset(Base):
    """A user-owned reusable acquisition and matching preset."""

    __tablename__ = "acquisition_plan_preset"
    __table_args__ = (UniqueConstraint("user_id", "preset_key", name="uq_acquisition_plan_preset_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    preset_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False)

    user = relationship("User", back_populates="acquisition_plan_presets")


class UserWorkbenchPreferences(Base):
    """Small user-owned defaults used by scientific authoring surfaces."""

    __tablename__ = "user_workbench_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    default_plate_format_id: Mapped[str] = mapped_column(
        String(100), nullable=False, default="plate-96", server_default="plate-96"
    )

    user = relationship("User", back_populates="workbench_preferences")
