"""Private custody of model files not yet registered as completed artifacts."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, false
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class ModelPublication(Base):
    __tablename__ = "model_publication"

    artifact_uid: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_dir: Mapped[str] = mapped_column(String(500), nullable=False)
    cleanup_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    # NULL denotes a legacy claim: no execution owner may be inferred for it.
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # Retain a fence after removing bytes so late registration cannot resurrect
    # a reclaimed publication. Account erasure removes these small tombstones.
    reclaimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
