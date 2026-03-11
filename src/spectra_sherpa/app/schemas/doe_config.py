"""DOE Configuration Profile schemas"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DOEConfigBase(BaseModel):
    name: str = Field(..., description="Configuration profile name")
    description: str | None = Field(None, description="Profile description")
    is_default: bool = Field(False, description="Whether this is the default profile")

    # Folder/Batch Mapping Rules
    folder_batch_rules: dict | None = Field(
        None,
        description="Folder→batch mapping patterns",
        examples=[{"pattern": "timestamp", "extract_batch_from_folder": True, "auto_increment": True}],
    )

    # Filename Parsing Rules
    filename_patterns: dict | None = Field(
        None,
        description="Custom regex patterns for seq/cell extraction",
        examples=[{"seq_pattern": r"_(\d+)\.", "cell_pattern": r"([A-H][0-9]{1,2})", "fallback_to_any_digits": True}],
    )

    # Scan Path Defaults
    scan_defaults: dict | None = Field(
        None,
        description="Default scan path settings",
        examples=[{"first_cell": "A1", "orientation": "row", "seq_offset": 0}],
    )

    # Run Sequence Template
    run_sequence_template: dict | None = Field(
        None,
        description="Factor definitions template",
        examples=[
            {
                "factors": [
                    {"name": "Defocus", "unit": "mm", "type": "numeric", "scope": "method"},
                    {"name": "Temperature", "unit": "°C", "type": "numeric", "scope": "method"},
                ]
            }
        ],
    )

    # Matching Behavior
    match_settings: dict | None = Field(
        None,
        description="Default matching behavior flags",
        examples=[{"use_plate_map": True, "use_run_sequence": True, "auto_detect_folders": True}],
    )


class DOEConfigCreate(DOEConfigBase):
    """Schema for creating a new DOE config profile"""

    pass


class DOEConfigUpdate(BaseModel):
    """Schema for updating a DOE config profile (all fields optional)"""

    name: str | None = None
    description: str | None = None
    is_default: bool | None = None
    folder_batch_rules: dict | None = None
    filename_patterns: dict | None = None
    scan_defaults: dict | None = None
    run_sequence_template: dict | None = None
    match_settings: dict | None = None


class DOEConfig(DOEConfigBase):
    """Schema for DOE config profile response"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


class DOEConfigList(BaseModel):
    """List response with multiple config profiles"""

    configs: list[DOEConfig]
    total: int
