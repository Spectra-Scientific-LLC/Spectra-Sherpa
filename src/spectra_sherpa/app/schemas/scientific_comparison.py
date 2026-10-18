"""Portable, provider-neutral scientific comparison contracts.

References identify evidence; they never authorize access or certify a claim.
Population counts are nullable because historical receipts may be incomplete.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EvaluationRole = Literal["calibration", "training_cv", "held_out", "outlier_challenge"]


class EvidenceOutputSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=255)
    presentation_id: str = Field(min_length=1, max_length=255)


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["spectrasherpa-evidence-reference/1"] = "spectrasherpa-evidence-reference/1"
    kind: Literal["run", "evaluation", "external"]
    id: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_output: EvidenceOutputSelection | None = None


class CompareEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    references: list[EvidenceReference] = Field(min_length=2, max_length=10)


class PopulationSummary(BaseModel):
    source_count: int | None = Field(None, ge=0)
    admitted_count: int | None = Field(None, ge=0)
    excluded_count: int | None = Field(None, ge=0)
    development_count: int | None = Field(None, ge=0)
    held_out_count: int | None = Field(None, ge=0)
    evaluation_count: int | None = Field(None, ge=0)
    group_count: int | None = Field(None, ge=0)
    grouped: bool | None = None
    response: str | None = None
    units: str | None = None
    fold_count: int | None = Field(None, ge=0)
    partition_digest: str | None = None
    source_receipt: str | None = None
    verification: Literal["verified", "partial", "unknown"] = "unknown"
    limitations: list[str] = Field(default_factory=list)


class ScientificSection(BaseModel):
    role: EvaluationRole
    state: Literal["verified", "descriptive_only", "unavailable"]
    population: PopulationSummary = Field(default_factory=PopulationSummary)
    metrics: dict[str, float] = Field(default_factory=dict)
    sample_ids: list[str] = Field(default_factory=list)
    observations: list[float] = Field(default_factory=list)
    predictions: list[float] = Field(default_factory=list)
    reason: str


class ComparisonEvidenceItem(BaseModel):
    reference: EvidenceReference
    label: str
    population: PopulationSummary = Field(default_factory=PopulationSummary)
    sections: dict[EvaluationRole, ScientificSection]
    dataset_use: dict[str, Any] | None = None


class ScientificSectionComparison(BaseModel):
    role: EvaluationRole
    state: Literal["comparable", "descriptive_only", "reevaluation_needed", "unavailable"]
    reason: str
    next_action: str
    metric_values: dict[str, dict[str, float]] = Field(default_factory=dict)


class ScientificEvidencePair(BaseModel):
    left_index: int
    right_index: int
    sections: list[ScientificSectionComparison]


class EvidenceComparisonResponse(BaseModel):
    schema_version: Literal["spectrasherpa-scientific-comparison/1"] = "spectrasherpa-scientific-comparison/1"
    items: list[ComparisonEvidenceItem]
    pairs: list[ScientificEvidencePair]
