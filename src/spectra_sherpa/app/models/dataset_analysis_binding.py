from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class DatasetAnalysisBinding(Base):
    """Explicit, durable attachment of one portable CSV sample table to X."""

    __tablename__ = "dataset_analysis_binding"
    __table_args__ = (
        UniqueConstraint("source_file_id", name="uq_dataset_analysis_binding_source_file"),
        CheckConstraint(
            "target_type IN ('continuous', 'categorical')",
            name="ck_dataset_analysis_binding_target_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("experiment_file.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sample_table_file_id: Mapped[int] = mapped_column(
        ForeignKey("experiment_file.id", ondelete="CASCADE"), nullable=False, index=True
    )
    selected_target: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source_file = relationship("ExperimentFile", foreign_keys=[source_file_id])
    sample_table_file = relationship("ExperimentFile", foreign_keys=[sample_table_file_id])
