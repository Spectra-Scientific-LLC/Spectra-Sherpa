"""
Data Egress Permission Model

Tracks user-configurable permissions for data sharing in HYBRID mode.
Each user can control what data types can be sent to which destinations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from spectra_sherpa.app.db.base import Base

if TYPE_CHECKING:
    from spectra_sherpa.app.models.user import User


class DataType:
    """Data types that can be subject to egress controls"""
    SPECTRA = "spectra"
    MODELS = "models"
    METADATA = "metadata"
    WORKFLOWS = "workflows"
    EXPERIMENTS = "experiments"
    AUDIT_LOGS = "audit_logs"

    ALL = [SPECTRA, MODELS, METADATA, WORKFLOWS, EXPERIMENTS, AUDIT_LOGS]


class EgressDestination:
    """Destinations where data can be sent"""
    SPECTRASHERPA = "spectrasherpa"  # SpectraSherpa cloud sync
    LLM_CONTEXT = "llm_context"  # Send to LLM providers
    EXPORT = "export"  # Export to external files
    NIST = "nist"  # NIST WebBook queries

    ALL = [SPECTRASHERPA, LLM_CONTEXT, EXPORT, NIST]


class DataEgressPermission(Base):
    """
    Per-user, per-data-type, per-destination permission model.

    Example permissions:
    - User A allows spectra to be sent to LLM
    - User A blocks spectra from being synced to SpectraSherpa
    - User A allows metadata to go anywhere
    """
    __tablename__ = "data_egress_permissions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    data_type = Column(String(50), nullable=False)  # spectra, models, metadata, etc.
    destination = Column(String(50), nullable=False)  # spectrasherpa, llm, export
    allowed = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="egress_permissions")

    # Unique constraint: one permission per user/data_type/destination combo
    __table_args__ = (
        UniqueConstraint("user_id", "data_type", "destination", name="uq_user_datatype_destination"),
    )

    def __repr__(self) -> str:
        status = "allowed" if self.allowed else "blocked"
        return f"<DataEgressPermission user={self.user_id} {self.data_type}->{self.destination}: {status}>"


class UserEgressDefaults(Base):
    """
    Default egress settings for a user (applies when specific permission not set).

    This provides a quick toggle for "allow all" or "block all" scenarios,
    with individual DataEgressPermission entries serving as overrides.
    """
    __tablename__ = "user_egress_defaults"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Default policies
    allow_spectrasherpa_sync = Column(Boolean, nullable=False, default=False)
    allow_llm_context = Column(Boolean, nullable=False, default=False)  # Default: explicit opt-in
    allow_export = Column(Boolean, nullable=False, default=False)  # Default: explicit opt-in
    allow_nist_queries = Column(Boolean, nullable=False, default=False)  # Default: explicit opt-in

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationship
    user = relationship("User", back_populates="egress_defaults", uselist=False)

    def __repr__(self) -> str:
        return f"<UserEgressDefaults user={self.user_id}>"

    def get_default_for_destination(self, destination: str) -> bool:
        """Get the default permission for a destination"""
        mapping = {
            EgressDestination.SPECTRASHERPA: self.allow_spectrasherpa_sync,
            EgressDestination.LLM_CONTEXT: self.allow_llm_context,
            EgressDestination.EXPORT: self.allow_export,
            EgressDestination.NIST: self.allow_nist_queries,
        }
        return mapping.get(destination, True)
