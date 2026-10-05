from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    project_id: Optional[int] = Field(None, description="Link experiment to a project")


class ExperimentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    project_id: Optional[int] = Field(None, description="Move experiment to a project")


class ExperimentAnalysisSelectionUpdate(BaseModel):
    """Dataset-scoped scientific intent selected in My Dataset."""

    selected_target: Optional[str] = Field(None, max_length=255)
    target_type: Optional[Literal["categorical", "continuous"]] = None
    group_column: Optional[str] = Field(None, max_length=255)
    source_digest: Optional[str] = Field(None, pattern=r"^[0-9a-f]{64}$")


class ExperimentAnalysisSelection(ExperimentAnalysisSelectionUpdate):
    schema_version: Literal["spectra-sherpa-analysis-selection/1"]
    updated_at: datetime


class ExperimentSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    file_count: int = 0
    project_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class ExperimentDetail(ExperimentSummary):
    metadata: dict[str, Any]


class ExperimentFileOut(BaseModel):
    id: int
    file_path: str
    file_type: Optional[str]
    stage: str
    file_size_bytes: Optional[int]
    created_at: datetime
    shape: list[int] | None = None
    n_samples: int | None = None
    n_features: int | None = None
    data_role: str | None = None
    x_title: str | None = None
    x_units: str | None = None
    is_spectra: bool | None = None
    target_names: list[str] | None = None
    target_types: dict[str, str] | None = None

    model_config = ConfigDict(from_attributes=True)


class ScientificAssetOut(BaseModel):
    """One exact scientist-selectable result contained in an experiment file."""

    asset_id: str
    title: str | None = None
    shape: list[int]
    dimension_roles: list[str]
    data_role: str
    x_title: str | None = None
    x_units: str | None = None
    data_quantity: str | None = None
    value_units: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ExperimentFileAssetsOut(BaseModel):
    """Parser-bound asset inventory for one exact experiment file."""

    format_id: str
    variant: str
    parser_id: str
    parser_version: str
    source_sha256: str
    assets: list[ScientificAssetOut]


class CollectionDefinitionReceipt(BaseModel):
    """Bounded scientist-facing status for one experiment collection definition."""

    schema_version: Literal["spectrasherpa-collection-definition-receipt/1"]
    status: Literal["absent", "preview", "attached", "stale", "invalid"]
    experiment_id: int
    definition_sha256: str | None = None
    source_manifest_sha256: str | None = None
    scientific_collection_sha256: str | None = None
    file_count: int = 0
    row_count: int = 0
    column_count: int = 0
    columns: list[str] = Field(default_factory=list)
    shape: list[int] | None = None
    dataset_id: str | None = None
    title: str | None = None
    target_present: bool = False
    sample_classes_present: bool = False
    message: str

    model_config = ConfigDict(extra="forbid")


class ReferenceDatasetImportItem(BaseModel):
    source: str = Field(..., description="One of: builtin, synthetic, eigenvector, sklearn, oes")
    name: str = Field(..., min_length=1)
    overrides: dict[str, Any] | None = Field(
        default=None,
        description="Prepared-data metadata overrides applied only to the imported experiment files",
    )


class ReferenceDatasetImportRequest(BaseModel):
    datasets: List[ReferenceDatasetImportItem] = Field(..., min_length=1)


class ReferenceDatasetImportResponse(BaseModel):
    imported: int
    files: List[ExperimentFileOut]
    experiment_id: int | None = None
    reused_existing: bool = False
    initial_file_ids: List[int] = Field(default_factory=list)


class VersionCreate(BaseModel):
    version_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    file_ids: Optional[List[int]] = None
    stages: Optional[List[str]] = None
    parent_version_id: Optional[int] = None


class VersionInfo(BaseModel):
    id: int
    version_name: str
    description: Optional[str]
    created_at: datetime
    parent_version_id: Optional[int]
    file_count: int

    model_config = ConfigDict(from_attributes=True)
