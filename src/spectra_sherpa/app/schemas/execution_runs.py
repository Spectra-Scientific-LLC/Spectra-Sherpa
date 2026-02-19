"""
Pydantic schemas for execution run API requests/responses.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SaveRunRequest(BaseModel):
    """Schema for saving an execution run."""

    name: str = Field(..., min_length=1, max_length=255, description="Run label")
    notes: str | None = Field(None, description="Optional notes about this run")
    status: str = Field(..., description="Execution status: completed, partial, error")
    results_summary: dict[str, Any] = Field(..., description="Scalar metrics per node {node_id: {metric: value}}")
    diagnostics: dict[str, Any] | None = Field(None, description="Per-node diagnostics")
    node_statuses: dict[str, str] | None = Field(None, description="Per-node status")
    error: str | None = Field(None, description="Error message if execution failed")
    integrity_hash: str | None = Field(None, description="Workflow integrity hash")
    executed_at: str = Field(..., description="ISO timestamp of execution")
    labels: list[str] | None = Field(None, description="Optional labels for tagging")


class ExecutionRunOut(BaseModel):
    """Schema for execution run response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    workflow_version_id: int | None
    user_id: int
    name: str
    status: str
    params_snapshot: dict[str, Any]
    results_summary: dict[str, Any]
    diagnostics: dict[str, Any] | None
    node_statuses: dict[str, str] | None
    error: str | None
    integrity_hash: str | None
    executed_at: datetime
    created_at: datetime
    notes: str | None
    labels: list[str] | None = None
    source_type: str | None = None
    source_metadata: dict[str, Any] | None = None


class ExecutionRunList(BaseModel):
    """Schema for listing execution runs."""

    runs: list[ExecutionRunOut]
    total: int


class CompareRunsRequest(BaseModel):
    """Schema for run comparison request."""

    run_ids: list[int] = Field(..., min_length=2, max_length=10, description="IDs of runs to compare")


class ComparisonResponse(BaseModel):
    """Schema for run comparison response."""

    runs: list[ExecutionRunOut]
    metric_keys: list[str] = Field(..., description="Union of all metric keys across compared runs")
    diff: dict[str, dict[str, Any]] = Field(
        ..., description="Per-metric values keyed by run_id: {metric: {run_id: value}}"
    )
