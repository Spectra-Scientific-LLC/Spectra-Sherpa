"""Wire contracts for sheet-specific workflow data selections."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from spectra_sherpa.core.target_authority import TargetAuthority


class WorkflowSourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: int = Field(ge=1)
    dataset_name: str = Field(min_length=1, max_length=255)
    stage: Literal["raw", "preprocessed", "synthetic"]
    selected_file_ids: list[int] | None = None
    asset_id: str | None = None
    source_manifest_sha256: str
    collection_definition_sha256: str | None = None
    scientific_collection_sha256: str
    target_authority: TargetAuthority | None = None
    group_column: str | None = None
    dataset_view_id: int | None = Field(default=None, ge=1)
    dataset_view_sha256: str | None = None

    @model_validator(mode="after")
    def validate_dataset_view_reference(self) -> "WorkflowSourceSelection":
        if (self.dataset_view_id is None) != (self.dataset_view_sha256 is None):
            raise ValueError("saved dataset definition id and digest must be supplied together")
        return self

    @field_validator(
        "source_manifest_sha256", "collection_definition_sha256", "scientific_collection_sha256", "dataset_view_sha256"
    )
    @classmethod
    def validate_digest(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("selection digests must be lowercase SHA-256 values")
        return value

    @field_validator("selected_file_ids")
    @classmethod
    def validate_file_ids(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if not value or any(item < 1 for item in value) or len(value) != len(set(value)):
            raise ValueError("selected_file_ids must contain distinct positive IDs")
        return value


class WorkflowDataSelectionApply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    origin: Literal["data_page", "canvas", "api", "accepted_proposal"] = "data_page"
    reason: str | None = Field(default=None, max_length=2000)
    selection: WorkflowSourceSelection


class WorkflowDataSelectionRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    workflow_name: str
    source_node_id: str
    source_node_label: str
    revision_number: int
    parent_revision_id: int | None
    created_by: int
    created_by_name: str
    created_at: datetime
    origin: str
    reason: str | None
    selection: WorkflowSourceSelection
    graph_digest: str


class WorkflowDataSelectionContext(BaseModel):
    workflow_id: int
    workflow_name: str
    source_node_id: str
    source_node_label: str
    project_id: int | None
    current_revision: WorkflowDataSelectionRevisionOut | None
    # A newly authored Collection Load node deliberately has no source
    # parameters yet.  The Data surface is the only place that can issue the
    # first governed selection, so the context must be readable before that
    # selection exists.
    saved_selection: WorkflowSourceSelection | None
