from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_sherpa.app.db.base import Base


class DOEConfig(Base):
    """DOE Configuration Profile - Reusable settings for instruments/run styles"""

    __tablename__ = "doe_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # Folder/Batch Mapping Rules
    folder_batch_rules: Mapped[dict | None] = mapped_column(JSON)
    # Example: {"pattern": "timestamp", "extract_batch_from_folder": true}

    # Filename Parsing Rules
    filename_patterns: Mapped[dict | None] = mapped_column(JSON)
    # Example: {"seq_pattern": "_(\d+)\.", "cell_pattern": "([A-H][0-9]{1,2})"}

    # Scan Path Defaults
    scan_defaults: Mapped[dict | None] = mapped_column(JSON)
    # Example: {"first_cell": "A1", "orientation": "row", "seq_offset": 0}

    # Run Sequence Template
    run_sequence_template: Mapped[dict | None] = mapped_column(JSON)
    # Example: {"factors": [{"name": "Defocus", "unit": "mm", "type": "numeric"}]}

    # Matching Behavior
    match_settings: Mapped[dict | None] = mapped_column(JSON)
    # Example: {"use_plate_map": true, "use_run_sequence": true, "auto_detect_folders": true}

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="doe_configs")
