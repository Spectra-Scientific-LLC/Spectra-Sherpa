"""Pydantic schemas for Project API requests/responses."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from spectra_sherpa.app.lib.workflow_purpose import WorkflowPurpose
from spectra_sherpa.core.node_identity import canonicalize_serialized_workflow


class ProjectCreate(BaseModel):
    commercial_subscription_id: int | None = Field(None, gt=0, strict=True)
    commercial_workspace_id: int | None = Field(None, gt=0, strict=True)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    parent_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    technique: str | None = Field(None, max_length=50)
    sample_type: str | None = Field(None, max_length=100)


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    parent_id: int | None = None
    metadata: dict[str, Any] | None = None
    technique: str | None = Field(None, max_length=50)
    sample_type: str | None = Field(None, max_length=100)


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    parent_id: int | None = None
    technique: str | None = None
    sample_type: str | None = None
    experiment_count: int = 0
    workflow_count: int = 0
    script_count: int = 0
    model_count: int = 0
    children_count: int = 0
    version_count: int = 0
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class ExperimentBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    file_count: int = 0
    facts: list[str] = Field(default_factory=list)


class WorkflowBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    status: str = "draft"
    purpose: WorkflowPurpose
    integrity_hash: str | None = None
    tab_color: str | None = None
    sheet_order: int = 0
    primary_data_source_id: int | None = None
    data_source_ids: list[int] = Field(default_factory=list)
    color_source: str = "blank"
    tab_color_override: str | None = None
    advisor_channel_id: int | None = None
    created_from_template_name: str | None = None
    created_from_template_version: str | None = None
    created_from_workflow_id: int | None = None
    created_from_workflow_name: str | None = None


class ProjectDataSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    display_name: str
    source_type: str
    source_ref: str | None = None
    fingerprint: str | None = None
    color: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


class ProjectDataSourceCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=255)
    source_type: str = Field(default="external", max_length=50)
    source_ref: str | None = Field(None, max_length=8192)
    fingerprint: str | None = Field(None, max_length=255)
    color: str = Field("#3b82f6", pattern=r"^#[0-9a-fA-F]{6}$")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def bounded_metadata(cls, value):
        if value is not None and len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 65536:
            raise ValueError("Data-source metadata must not exceed 65536 UTF-8 bytes")
        return value


class ProjectDataSourceUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=255)
    source_type: str | None = Field(None, max_length=50)
    source_ref: str | None = Field(None, max_length=8192)
    fingerprint: str | None = Field(None, max_length=255)
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    metadata: dict[str, Any] | None = None

    @field_validator("metadata")
    @classmethod
    def bounded_metadata(cls, value):
        if value is not None and len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 65536:
            raise ValueError("Data-source metadata must not exceed 65536 UTF-8 bytes")
        return value


class AdvisorChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    workflow_id: int | None = None
    channel_type: str
    title: str
    color: str | None = None
    conversation_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AdvisorChannelUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    conversation_id: str | None = Field(None, max_length=255)


class ScriptBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    language: str = "python"
    priority: float = 50.0
    source_workflow_id: int | None = None
    code_length: int = 0


class ModelBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    artifact_uid: str
    name: str
    display_name: str | None = None
    model_type: str
    n_features: int
    n_components: int | None = None
    metrics: dict[str, Any] | None = None
    source_run_id: int | None = None
    training_dataset_id: int | None = None
    is_deploy_ready: bool = False
    tags: list[str] = Field(default_factory=list)
    created_at: datetime


class ImportedApplicationIdentity(BaseModel):
    """Opaque Deploy hand-off identity returned by canonical imports.

    The current OSS importer derives this transport identity from the verified
    application-plan digest. A release service may replace ``handle`` with a
    durable release handle without changing the frontend contract.
    """

    handle: str
    origin: str
    project_id: int
    workflow_id: int
    artifact_digest: str | None = None
    application_plan_digest: str | None = None
    status: str | None = None


class ProjectDetail(ProjectSummary):
    metadata: dict[str, Any] = Field(default_factory=dict)
    application: ImportedApplicationIdentity | None = None
    # Backward-compatible scalar for hand-off consumers that only need the handle.
    application_handle: str | None = None
    experiments: list[ExperimentBrief] = Field(default_factory=list)
    data_sources: list[ProjectDataSourceOut] = Field(default_factory=list)
    workflows: list[WorkflowBrief] = Field(default_factory=list)
    advisor_channels: list[AdvisorChannelOut] = Field(default_factory=list)
    scripts: list[ScriptBrief] = Field(default_factory=list)
    models: list[ModelBrief] = Field(default_factory=list)
    children: list[ProjectSummary] = Field(default_factory=list)


class ProjectVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_number: int
    change_description: str | None = None
    include_raw_data: bool = False
    created_at: datetime
    created_by: int


class ProjectVersionDetail(ProjectVersionSummary):
    snapshot: dict[str, Any] = Field(..., description="Complete project state snapshot")

    @field_validator("snapshot", mode="before")
    @classmethod
    def resolve_snapshot_node_types(cls, value: object) -> object:
        return canonicalize_serialized_workflow(value)


class ProjectVersionListResponse(BaseModel):
    versions: list[ProjectVersionSummary]
    total: int


class SaveProjectRequest(BaseModel):
    """'Save All' — creates a new ProjectVersion snapshot."""

    change_description: str | None = None
    include_raw_data: bool = False
