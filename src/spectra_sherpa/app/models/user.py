from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base

PRINCIPAL_KIND_HUMAN = "human"
PRINCIPAL_KIND_SERVICE = "service"
PRINCIPAL_KINDS = frozenset({PRINCIPAL_KIND_HUMAN, PRINCIPAL_KIND_SERVICE})


class User(Base):
    """Principal identity model shared by OSS and server distributions.

    OSS code should program against the ``CurrentActor`` protocol
    (``contracts.actors``) rather than importing this class directly.
    The protocol requires only ``id``, ``username``, and ``is_active``.

    The table name remains ``user`` for compatibility, but rows are
    principals: most are human users today, while future service,
    instrument, and pipeline actors can use the same id space for
    authorship, audit, and tenancy backfills without requiring a managed
    password account.

    This ORM now owns only local-platform identity fields. Managed auth,
    admin, and account metadata belong to the commercial server.
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    principal_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PRINCIPAL_KIND_HUMAN,
        server_default=PRINCIPAL_KIND_HUMAN,
        index=True,
    )
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

    @property
    def is_human_principal(self) -> bool:
        return self.principal_kind == PRINCIPAL_KIND_HUMAN
