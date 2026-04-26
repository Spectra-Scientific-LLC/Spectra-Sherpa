from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class User(Base):
    """User identity model shared by OSS and server distributions.

    OSS code should program against the ``CurrentActor`` protocol
    (``contracts.actors``) rather than importing this class directly.
    The protocol requires only ``id``, ``username``, and ``is_active``.

    This ORM now owns only local-platform identity fields. Managed auth,
    admin, and account metadata belong to the commercial server.
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_active: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")
    experiments = relationship("Experiment", back_populates="user", cascade="all, delete-orphan")
    calibrations = relationship("Calibration", back_populates="user", cascade="all, delete-orphan")
    workflows = relationship("Workflow", back_populates="user", cascade="all, delete-orphan")
    background_jobs = relationship("BackgroundJob", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    doe_configs = relationship("DOEConfig", back_populates="user", cascade="all, delete-orphan")
    # Data egress permissions (HYBRID mode)
    egress_permissions = relationship("DataEgressPermission", back_populates="user", cascade="all, delete-orphan")
    egress_defaults = relationship(
        "UserEgressDefaults", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
