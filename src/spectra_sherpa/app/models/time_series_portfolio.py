"""Immutable named selections of partitioned source acquisitions."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class TimeSeriesPortfolioRecord(Base):
    __tablename__ = "time_series_portfolio"
    __table_args__ = (UniqueConstraint("project_id", "name_key", name="uq_time_series_portfolio_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    name_key: Mapped[str] = mapped_column(String(120))
    selection: Mapped[dict] = mapped_column(JSON)
    selection_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
