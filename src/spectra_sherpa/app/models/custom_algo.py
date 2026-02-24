"""
CustomAlgo database model — stores user-defined algorithm nodes within a Project.

Each CustomAlgo record maps 1-to-1 to a generated plugin ``.py`` file
on disk and a registered ``node_type`` in the DAG node registry.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.user import User


class CustomAlgo(Base):
    """
    A user-defined Python algorithm node stored within a Project.

    The ``node_type`` follows the format ``ualgo.{project_id}.{slug}``
    and is registered in the DAG node registry at startup and on
    create/update.  The corresponding plugin file lives at
    ``<data_dir>/plugins/custom_algos/ualgo_{project_id}_{slug}.py``.
    """

    __tablename__ = "custom_algo"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="simple")
    icon: Mapped[str] = mapped_column(String(10), nullable=False, default="\U0001f9ea")
    node_type: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="custom_algos")
    user: Mapped[User] = relationship("User")
