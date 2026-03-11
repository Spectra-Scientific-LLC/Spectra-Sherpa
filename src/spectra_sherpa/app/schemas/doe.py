"""Design of Experiments (DOE) schemas"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ==================== Sample Database ====================


class SampleBase(BaseModel):
    sample_id: str = Field(..., description="Sample identifier")
    name: str = Field(..., description="Sample name")
    type: str | None = Field(None, description="Sample type (Solvent, Standard, Unknown)")
    brand: str | None = Field(None, description="Brand or manufacturer")
    cas_number: str | None = Field(None, description="CAS registry number")
    active: bool = Field(True, description="Active status")
    notes: str | None = Field(None, description="Additional notes")


class SampleCreate(SampleBase):
    pass


class Sample(SampleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int
    created_at: datetime


class SampleImportRequest(BaseModel):
    """CSV import of samples (metadata only)"""

    csv_data: str = Field(..., description="CSV data with headers")


# ==================== Mixture ====================


class MixtureComponentBase(BaseModel):
    sample_id: int = Field(..., description="Sample database ID")
    amount: float = Field(..., description="Amount of component")
    unit: str = Field(..., description="Unit (mL, uL, g, mg, etc.)")


class MixtureComponentCreate(MixtureComponentBase):
    pass


class MixtureComponent(MixtureComponentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mixture_id: int


class MixtureBase(BaseModel):
    mixture_id: str = Field(..., description="Mixture identifier")
    name: str | None = Field(None, description="Mixture name")
    basis: Literal["volume", "mass"] = Field("volume", description="Mixture basis")
    notes: str | None = Field(None, description="Additional notes")


class MixtureCreate(MixtureBase):
    components: list[MixtureComponentCreate] = Field(default_factory=list, description="Mixture components")


class Mixture(MixtureBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int
    created_at: datetime
    components: list[MixtureComponent] = []


# ==================== Factor Definition ====================


class FactorDefinitionBase(BaseModel):
    name: str = Field(..., description="Factor name")
    scope: Literal["sample", "method"] = Field(..., description="Factor scope")
    type: Literal["categorical", "numeric"] = Field(..., description="Factor type")
    unit: str | None = Field(None, description="Unit for numeric factors")
    levels: list[str] | None = Field(None, description="Factor levels")


class FactorDefinitionCreate(FactorDefinitionBase):
    pass


class FactorDefinition(FactorDefinitionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int


# ==================== Plate Well ====================


class PlateWellBase(BaseModel):
    well_position: str = Field(..., description="Well position (A1-H12)")
    mixture_id: int | None = Field(None, description="Assigned mixture ID")


class PlateWellCreate(PlateWellBase):
    pass


class PlateWell(PlateWellBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int


class PlateMapRequest(BaseModel):
    """Bulk plate map assignment"""

    wells: list[PlateWellCreate] = Field(..., description="Well assignments")


# ==================== Run Level ====================


class RunLevelBase(BaseModel):
    factor_definition_id: int = Field(..., description="Factor definition ID")
    level_value: str = Field(..., description="Level value")
    path: str | None = Field(None, description="Folder path")
    batch: int | None = Field(None, description="Batch number")
    file_count: int | None = Field(None, description="Number of files")
    sequence_order: int = Field(0, description="Order in sequence")


class RunLevelCreate(RunLevelBase):
    pass


class RunLevel(RunLevelBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int


class RunSequenceRequest(BaseModel):
    """Manual run sequence entry"""

    levels: list[RunLevelCreate] = Field(..., description="Run levels")


# ==================== Matched Acquisition ====================


class MatchedAcquisitionBase(BaseModel):
    seq: int | None = Field(None, description="Sequence number")
    filename: str | None = Field(None, description="File name")
    folder: str | None = Field(None, description="Folder name")
    timestamp: int | None = Field(None, description="Unix timestamp")
    date: str | None = Field(None, description="Date string")
    batch: int | None = Field(None, description="Batch number")
    sample_id: str | None = Field(None, description="Sample ID")
    cell: str | None = Field(None, description="Cell position")
    special: str | None = Field(None, description="Special flags")
    factor_values: dict | None = Field(None, description="Method/sample factor values")


class MatchedAcquisitionCreate(MatchedAcquisitionBase):
    pass


class MatchedAcquisition(MatchedAcquisitionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int


class FolderBatch(BaseModel):
    """Folder with files for batch assignment"""

    folder_path: str = Field(..., description="Folder name/path")
    file_list: list[str] = Field(..., description="Files in this folder")
    batch_number: int | None = Field(None, description="Optional batch number override")


class MatchAcquisitionsRequest(BaseModel):
    """Auto-match acquisitions from file list or folders"""

    file_list: list[str] | None = Field(None, description="Simple list of filenames")
    folders: list[FolderBatch] | None = Field(None, description="Folder-based file organization")
    first_cell: str | None = Field(None, description="First cell position (e.g., A1)")
    scan_orientation: Literal["row", "column", "serpentine", "serpentine_column"] | None = Field(
        None, description="Scan orientation for plate map derivation"
    )
    seq_offset: int = Field(0, description="Starting sequence number offset")
    use_plate_map: bool = Field(True, description="Derive cell/sample from plate map")
    use_run_sequence: bool = Field(True, description="Map folders to run sequence for factor values")


# ==================== DOE Export ====================


class DOEExportRequest(BaseModel):
    format: Literal["csv", "xml", "json"] = Field("csv", description="Export format")


class DOESummary(BaseModel):
    """Summary of DOE configuration"""

    sample_count: int = Field(0, description="Number of samples")
    mixture_count: int = Field(0, description="Number of mixtures")
    factor_count: int = Field(0, description="Number of factors")
    well_count: int = Field(0, description="Number of assigned wells")
    run_level_count: int = Field(0, description="Number of run levels")
    matched_count: int = Field(0, description="Number of matched acquisitions")
