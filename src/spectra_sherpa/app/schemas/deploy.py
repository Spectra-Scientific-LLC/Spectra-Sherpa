"""
Pydantic schemas for deploy API — folder watches, batch predictions, labels.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

class UpdateLabelsRequest(BaseModel):
    """Update the labels on an execution run."""

    labels: list[str] = Field(
        ..., max_length=20, description="List of label strings (max 20)"
    )


# ---------------------------------------------------------------------------
# Batch Predict
# ---------------------------------------------------------------------------

class BatchPredictRequest(BaseModel):
    """Start a batch prediction job from a server folder."""

    folder_path: str = Field(..., min_length=1, description="Server folder path")
    file_pattern: str = Field("*", description="Glob pattern for file matching")
    run_name: str | None = Field(None, description="Optional name for the run")


class BatchPredictResponse(BaseModel):
    """Response after starting a batch prediction job."""

    job_id: int
    run_id: int
    message: str


class BatchPredictionOut(BaseModel):
    """Per-file prediction result."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    file_name: str
    file_path: str
    status: str
    results: dict[str, Any] | None
    error_message: str | None
    processing_time_ms: int | None
    created_at: datetime


class BatchPredictionList(BaseModel):
    """List of per-file prediction results."""

    predictions: list[BatchPredictionOut]
    total: int


# ---------------------------------------------------------------------------
# Folder Watch
# ---------------------------------------------------------------------------

class FolderWatchCreate(BaseModel):
    """Create a new folder watch."""

    workflow_id: int = Field(..., description="ID of the workflow to execute")
    name: str = Field(..., min_length=1, max_length=255, description="Watch name")
    folder_path: str = Field(..., min_length=1, description="Server folder to monitor")
    file_pattern: str = Field("*", description="Glob pattern for file matching")
    poll_interval_sec: int = Field(
        60, ge=10, le=86400, description="Polling interval in seconds"
    )


class FolderWatchUpdate(BaseModel):
    """Update a folder watch. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=255)
    folder_path: str | None = Field(None, min_length=1)
    file_pattern: str | None = None
    poll_interval_sec: int | None = Field(None, ge=10, le=86400)
    is_enabled: bool | None = None


class FolderWatchOut(BaseModel):
    """Folder watch response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    workflow_id: int
    name: str
    folder_path: str
    file_pattern: str
    poll_interval_sec: int
    is_enabled: bool
    processed_files: dict[str, str] | None
    last_poll_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime | None
