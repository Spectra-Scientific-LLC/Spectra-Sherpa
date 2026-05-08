"""Pydantic schemas for Project API requests/responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
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


class ExperimentBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    file_count: int = 0


class WorkflowBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    status: str = "draft"
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
    source_ref: str | None = None
    fingerprint: str | None = None
    color: str = Field("#3b82f6", pattern=r"^#[0-9a-fA-F]{6}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectDataSourceUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=255)
    source_type: str | None = Field(None, max_length=50)
    source_ref: str | None = None
    fingerprint: str | None = None
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    metadata: dict[str, Any] | None = None


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
    model_type: str
    n_features: int
    n_components: int | None = None
    metrics: dict[str, Any] | None = None
    created_at: datetime


class ProjectDetail(ProjectSummary):
    metadata: dict[str, Any] = Field(default_factory=dict)
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


class ProjectVersionListResponse(BaseModel):
    versions: list[ProjectVersionSummary]
    total: int


class SaveProjectRequest(BaseModel):
    """'Save All' — creates a new ProjectVersion snapshot."""

    change_description: str | None = None
    include_raw_data: bool = False
