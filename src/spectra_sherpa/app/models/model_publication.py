"""Private custody of model files not yet registered as completed artifacts."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class ModelPublication(Base):
    __tablename__ = "model_publication"

    artifact_uid: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_dir: Mapped[str] = mapped_column(String(500), nullable=False)
