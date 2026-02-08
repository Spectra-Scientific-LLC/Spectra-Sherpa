from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ExpVersion(Base):
    __tablename__ = "exp_version"
    __table_args__ = (UniqueConstraint("experiment_id", "version_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiment.id"), nullable=False, index=True
    )
    version_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    manifest_path: Mapped[str] = mapped_column(String(500), nullable=False)
    parent_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("exp_version.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    experiment = relationship("Experiment", back_populates="versions")
    parent_version = relationship("ExpVersion", remote_side="ExpVersion.id")
