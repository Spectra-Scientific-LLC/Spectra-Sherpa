"""
Pydantic schemas for deploy API — folder watches, batch predictions, labels.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spectra_sherpa.app.schemas.timestamps import UtcTimestamp

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


class UpdateLabelsRequest(BaseModel):
    """Update the labels on an execution run."""

    labels: list[str] = Field(..., max_length=20, description="List of label strings (max 20)")


# ---------------------------------------------------------------------------
# Batch Predict
# ---------------------------------------------------------------------------


class BatchPredictRequest(BaseModel):
    """Start a batch prediction job from a server folder."""

    folder_path: str = Field(..., min_length=1, description="Server folder path")
    artifact_uid: str = Field(..., min_length=1, max_length=36, description="Exact deploy-ready model artifact")
    file_pattern: str = Field("*", description="Glob pattern for file matching")
    run_name: str | None = Field(None, description="Optional name for the run")
    asset_id: str | None = Field(None, min_length=1, max_length=255, description="Exact asset in every source")


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
    model_id: str | None = None
    retained_node_ids: list[str] = Field(default_factory=list)
    created_at: UtcTimestamp


class BatchPredictionList(BaseModel):
    """List of per-file prediction results."""

    predictions: list[BatchPredictionOut]
    total: int


# ---------------------------------------------------------------------------
# Folder Watch
# ---------------------------------------------------------------------------


class FolderWatchCreate(BaseModel):
    """Create a new folder watch."""

    workflow_id: int = Field(..., description="Source workflow of the selected model artifact")
    application_handle: str | None = Field(None, min_length=1, max_length=128)
    artifact_uid: str | None = Field(None, min_length=1, max_length=36)
    canonical_artifact_id: int | None = Field(None, gt=0)
    uncertainty_record: dict[str, Any] | None = None
    uncertainty_population: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def exactly_one_target(self):
        supplied = sum(
            value is not None for value in (self.application_handle, self.artifact_uid, self.canonical_artifact_id)
        )
        if supplied != 1:
            raise ValueError("Select exactly one application handle, saved model, or canonical application")
        return self

    name: str = Field(..., min_length=1, max_length=255, description="Watch name")
    folder_path: str = Field(..., min_length=1, description="Server folder to monitor")
    file_pattern: str = Field("*", description="Glob pattern for file matching")
    poll_interval_sec: int = Field(60, ge=1, description="Polling interval in seconds")
    settle_time_seconds: int = Field(2, ge=0, description="Time to wait for file writing to finish before processing")
    asset_id: str | None = Field(None, min_length=1, max_length=255, description="Exact asset in every source")


class FolderWatchUpdate(BaseModel):
    """Update a folder watch. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=255)
    application_handle: str | None = Field(None, min_length=1, max_length=128)
    artifact_uid: str | None = Field(None, min_length=1, max_length=36)
    canonical_artifact_id: int | None = Field(None, gt=0)
    uncertainty_record: dict[str, Any] | None = None
    uncertainty_population: str | None = Field(default=None, min_length=1, max_length=2000)
    folder_path: str | None = Field(None, min_length=1)
    file_pattern: str | None = None
    poll_interval_sec: int | None = Field(None, ge=1)
    settle_time_seconds: int | None = Field(None, ge=0)
    is_enabled: bool | None = None
    asset_id: str | None = Field(None, min_length=1, max_length=255)


class FolderWatchOut(BaseModel):
    """Folder watch response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    workflow_id: int
    artifact_uid: str | None = None
    workflow_version_id: int | None = None
    canonical_artifact_id: int | None = None
    canonical_plan_digest: str | None = None
    uncertainty_record: dict[str, Any] | None = None
    uncertainty_population: str | None = Field(default=None, min_length=1, max_length=2000)
    name: str
    folder_path: str
    file_pattern: str
    poll_interval_sec: int
    settle_time_seconds: int
    asset_id: str | None
    is_enabled: bool
    processed_files: dict[str, str] | None
    last_poll_at: UtcTimestamp | None
    last_error: str | None
    created_at: UtcTimestamp
    updated_at: UtcTimestamp | None


class CalibratePredictionIntervalsRequest(BaseModel):
    """Calibrate one frozen pipeline using an owned, separate reference dataset."""

    model_config = ConfigDict(extra="forbid")
    canonical_artifact_id: int = Field(gt=0)
    experiment_id: int = Field(gt=0)
    file_id: int = Field(gt=0)
    stage: str = "raw"
    asset_id: str | None = None
    specimen_namespace: str = Field(min_length=1, max_length=200)
    reference_method_id: str = Field(min_length=1, max_length=200)
    reference_method_version: str = Field(min_length=1, max_length=100)
    measurement_basis: str = "single_measurement"
    measurements_per_label: int = Field(ge=1, default=1)
    reference_precision: dict[str, Any] | None = None
    alpha: float = Field(gt=0, lt=1)
    intended_population: str = Field(min_length=1, max_length=2000)
    declarations: dict[str, bool]


class AssessQualificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_artifact_id: int = Field(gt=0)
    experiment_id: int = Field(gt=0)
    file_id: int = Field(gt=0)
    stage: Literal["raw", "preprocessed", "synthetic"] = "raw"
    asset_id: str | None = None
    policy: dict[str, Any]
    context: dict[str, Any]
    allow_missing_reference_exclusion: bool = False
    uncertainty_record: dict[str, Any] | None = None
    independence_evidence: dict[str, Any] | None = None


class DecideQualificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dossier_digest: str = Field(pattern="^[a-f0-9]{64}$")
    accepted_context_digest: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    decision: Literal["accepted_under_declared_policy", "rejected", "pending"]
    reason: str = Field(min_length=1, max_length=4000)
