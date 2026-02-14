"""Pydantic schemas for ProjectScript API requests/responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectScriptCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    language: str = "python"
    code: str = Field(..., min_length=1)
    priority: float = 50.0
    source_workflow_id: int | None = None


class ProjectScriptUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    language: str | None = None
    code: str | None = None
    priority: float | None = None


class ProjectScriptSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    description: str | None = None
    language: str
    priority: float
    source_workflow_id: int | None = None
    code_length: int
    created_at: datetime
    updated_at: datetime


class ProjectScriptDetail(ProjectScriptSummary):
    code: str


class GenerateScriptRequest(BaseModel):
    """Generate a script from a workflow's Python export."""

    workflow_id: int
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    priority: float = 50.0
