from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class ExperimentSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    file_count: int = 0

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

    model_config = ConfigDict(from_attributes=True)


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
