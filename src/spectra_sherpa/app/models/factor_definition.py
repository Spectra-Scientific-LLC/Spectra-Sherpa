from __future__ import annotations

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FactorDefinition(Base):
    """Experimental factor definition (sample or method factors)"""

    __tablename__ = "factor_definition"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiment.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # "sample" or "method"
    type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # "categorical" or "numeric"
    unit: Mapped[str | None] = mapped_column(String(50))
    levels: Mapped[list | None] = mapped_column(JSON)  # List of level values

    experiment = relationship("Experiment", back_populates="factor_definitions")
    run_levels = relationship(
        "RunLevel", back_populates="factor_definition", cascade="all, delete-orphan"
    )
