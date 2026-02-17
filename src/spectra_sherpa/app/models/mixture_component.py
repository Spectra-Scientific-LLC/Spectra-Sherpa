from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class MixtureComponent(Base):
    """Component in a mixture"""

    __tablename__ = "mixture_component"

    id: Mapped[int] = mapped_column(primary_key=True)
    mixture_id: Mapped[int] = mapped_column(
        ForeignKey("mixture.id"), nullable=False, index=True
    )
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("sample.id"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)  # mL, uL, g, mg, etc.

    mixture = relationship("Mixture", back_populates="components")
    sample = relationship("Sample", back_populates="mixture_components")
