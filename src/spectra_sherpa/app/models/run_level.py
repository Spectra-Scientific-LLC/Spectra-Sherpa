from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RunLevel(Base):
    """Run sequence level for method factors"""

    __tablename__ = "run_level"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiment.id"), nullable=False, index=True
    )
    factor_definition_id: Mapped[int] = mapped_column(
        ForeignKey("factor_definition.id"), nullable=False, index=True
    )
    level_value: Mapped[str] = mapped_column(String(100), nullable=False)
    path: Mapped[str | None] = mapped_column(String(255))  # Folder path
    batch: Mapped[int | None] = mapped_column(Integer)
    file_count: Mapped[int | None] = mapped_column(Integer)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    experiment = relationship("Experiment", back_populates="run_levels")
    factor_definition = relationship("FactorDefinition", back_populates="run_levels")
