"""
Pydantic schemas for execution run API requests/responses.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from spectra_sherpa.app.schemas.run_evidence import EvidenceGap, RunEvidence
from spectra_sherpa.app.schemas.timestamps import UtcTimestamp

RunKind = Literal["training", "batch_inference", "data", "other"]
PRODUCED_ARTIFACTS_DESCRIPTION = "Model artifact UIDs created by this run."
ATTEMPTED_ARTIFACTS_DESCRIPTION = "Model artifact UIDs this run attempted to apply, including failures."
SUCCEEDED_ARTIFACTS_DESCRIPTION = "Model artifact UIDs this run successfully applied."


def _omit_legacy_null_artifact_uids(value: Any) -> Any:
    """Older canonical watch runs recorded a null where no model UID exists."""

    if isinstance(value, list):
        return [uid for uid in value if uid is not None]
    return value


class SaveRunRequest(BaseModel):
    """Schema for saving an execution run."""

    run_id: int = Field(..., gt=0, description="Exact existing auto-persisted run to name.")
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
    produced_artifact_uids: list[str] | None = Field(None, description=PRODUCED_ARTIFACTS_DESCRIPTION)
    run_kind: RunKind | None = Field(
        None,
        description="Run kind: training, batch_inference, data, or other",
    )
    attempted_artifact_uids: list[str] | None = Field(None, description=ATTEMPTED_ARTIFACTS_DESCRIPTION)
    succeeded_artifact_uids: list[str] | None = Field(None, description=SUCCEEDED_ARTIFACTS_DESCRIPTION)


class ExecutionRunOut(BaseModel):
    """Schema for execution run response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    workflow_id: int | None
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
    executed_at: UtcTimestamp
    created_at: UtcTimestamp
    notes: str | None
    labels: list[str] | None = None
    source_type: str | None = None
    source_metadata: dict[str, Any] | None = None
    environment_snapshot: dict[str, Any] | None = None
    produced_artifact_uids: list[str] | None = Field(None, description=PRODUCED_ARTIFACTS_DESCRIPTION)
    run_kind: RunKind = "other"
    attempted_artifact_uids: list[str] | None = Field(None, description=ATTEMPTED_ARTIFACTS_DESCRIPTION)
    succeeded_artifact_uids: list[str] | None = Field(None, description=SUCCEEDED_ARTIFACTS_DESCRIPTION)
    evidence_completeness: RunEvidence | None = None

    _normalize_legacy_succeeded_uids = field_validator("succeeded_artifact_uids", mode="before")(
        _omit_legacy_null_artifact_uids
    )

    @computed_field
    @property
    def evidence_gaps(self) -> list[EvidenceGap]:
        """Node/output-specific durable-evidence gaps for every client surface."""

        return (self.evidence_completeness or RunEvidence()).gaps()


class ExecutionRunList(BaseModel):
    """Schema for listing execution runs."""

    runs: list[ExecutionRunOut]
    total: int


class RunListItem(BaseModel):
    """Navigation metadata only; scientific evidence is fetched on demand."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int | None
    workflow_id: int | None
    workflow_version_id: int | None
    name: str
    display_name: str | None = None
    workflow_name: str | None = None
    status: str
    run_kind: RunKind
    executed_at: UtcTimestamp
    created_at: UtcTimestamp
    labels: list[str] | None
    produced_artifact_uids: list[str] | None = Field(description=PRODUCED_ARTIFACTS_DESCRIPTION)
    attempted_artifact_uids: list[str] | None = Field(description=ATTEMPTED_ARTIFACTS_DESCRIPTION)
    succeeded_artifact_uids: list[str] | None = Field(description=SUCCEEDED_ARTIFACTS_DESCRIPTION)

    _normalize_legacy_succeeded_uids = field_validator("succeeded_artifact_uids", mode="before")(
        _omit_legacy_null_artifact_uids
    )


class RunPage(BaseModel):
    runs: list[RunListItem]
    total: int
    limit: int
    offset: int


class EvaluationSelection(BaseModel):
    node_id: str = Field(min_length=1, max_length=255)
    presentation_id: str = Field(min_length=1, max_length=255)


class CompareRunsRequest(BaseModel):
    """Schema for run comparison request."""

    run_ids: list[int] = Field(..., min_length=2, max_length=10, description="IDs of runs to compare")
    evaluation_selections: dict[int, EvaluationSelection] = Field(default_factory=dict, max_length=10)


class ComparisonResultRole(BaseModel):
    node_id: str
    presentation_id: str
    kind: str
    source_ports: list[str]


class ComparisonResultPair(BaseModel):
    left_run_id: int
    right_run_id: int
    kind: str
    left: list[ComparisonResultRole]
    right: list[ComparisonResultRole]
    requires_pairing: bool
    state: Literal["comparable", "incompatible", "insufficient_evidence"]
    reason: str


class ComparisonResponse(BaseModel):
    """Schema for run comparison response."""

    runs: list[ExecutionRunOut]
    result_pairs: list[ComparisonResultPair] = Field(default_factory=list)
    rankable_metric_keys: list[str] = Field(
        default_factory=list, description="Metrics qualified against common evaluation evidence"
    )
    metric_keys: list[str] = Field(..., description="Union of all metric keys across compared runs")
    diff: dict[str, dict[str, Any]] = Field(
        ..., description="Per-metric values keyed by run_id: {metric: {run_id: value}}"
    )
