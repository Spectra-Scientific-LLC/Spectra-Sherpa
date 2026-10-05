"""Recorded identity separation is narrower than independent sampling."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .prediction_uncertainty import ClosedRecord


class RecordedPopulation(ClosedRecord):
    """Operator-recorded specimen and optional batch identities for a model-development role."""

    role: Literal["fit", "selection", "interval_calibration"]
    namespace: str = Field(min_length=1, max_length=200)
    specimen_ids: list[str] = Field(min_length=1, max_length=1000000)
    batch_ids: list[str] | None = None
    source_description: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def valid_ids(self):
        if any(not value.strip() for value in self.specimen_ids):
            raise ValueError("specimen identities must be nonempty")
        if self.batch_ids is not None and (
            len(self.batch_ids) != len(self.specimen_ids) or any(not value.strip() for value in self.batch_ids)
        ):
            raise ValueError("batch identities require one nonempty value per specimen row")
        return self


class IndependenceEvidence(ClosedRecord):
    """Recorded identity registers and chronology, without asserting authenticated origin."""

    schema_version: Literal["spectrasherpa.recorded-independence/1"]
    populations: list[RecordedPopulation] = Field(default_factory=list, max_length=100)
    # Map by exact specimen ID so exclusions cannot shift row-to-batch alignment.
    validation_batches: dict[str, str] | None = None
    model_frozen_at: datetime | None = None
    policy_frozen_at: datetime | None = None
    validation_acquired_from: datetime | None = None
    chronology_source: str | None = Field(default=None, max_length=2000)

    @field_validator("model_frozen_at", "policy_frozen_at", "validation_acquired_from", mode="before")
    @classmethod
    def parse_time(cls, value):
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @model_validator(mode="after")
    def valid_chronology(self):
        for value in (self.model_frozen_at, self.policy_frozen_at, self.validation_acquired_from):
            if value is not None and value.utcoffset() is None:
                raise ValueError("chronology requires timezone-aware timestamps")
        if self.validation_batches is not None and any(
            not key.strip() or not value.strip() for key, value in self.validation_batches.items()
        ):
            raise ValueError("validation specimen and batch identities must be nonempty")
        return self


def assess_independence(
    *,
    specimen_ids: Sequence[str],
    namespace: str,
    declaration: bool,
    evidence: IndependenceEvidence | dict[str, Any] | None = None,
    sampling_declaration: bool | None = None,
) -> dict[str, Any]:
    """Compare supplied identity lists and retain the limits of operator declarations."""
    record = None if evidence is None else IndependenceEvidence.model_validate(evidence)
    comparisons = []
    if record is not None:
        if record.validation_batches is not None and not set(specimen_ids) <= set(record.validation_batches):
            raise ValueError("validation batch map omits retained validation specimens")
        for population in record.populations:
            comparable = population.namespace == namespace
            overlap = sorted(set(specimen_ids) & set(population.specimen_ids)) if comparable else None
            batch_overlap = None
            if comparable and population.batch_ids is not None and record.validation_batches is not None:
                batch_overlap = sorted(
                    set(population.batch_ids) & {record.validation_batches[value] for value in specimen_ids}
                )
            comparisons.append(
                {
                    "role": population.role,
                    "namespace": population.namespace,
                    "status": "compared_against_recorded_lists" if comparable else "unknown",
                    "scope": "set_comparison_of_recorded_identities_only",
                    "specimen_overlap": overlap,
                    "batch_overlap": batch_overlap,
                    "specimens_separate": None if overlap is None else not overlap,
                    "batches_separate": None if batch_overlap is None else not batch_overlap,
                    "source_description": population.source_description,
                    "source_authority": "operator_supplied_records",
                }
            )
    comparable = [item for item in comparisons if item["status"] == "compared_against_recorded_lists"]
    status = "compared_against_recorded_lists" if comparable else "operator_declared" if declaration else "unknown"
    chronology = {"status": "unknown", "scope": "operator_recorded_timestamps_only"}
    if record is not None and record.validation_acquired_from is not None:
        chronology = {
            "status": "operator_declared",
            "scope": "operator_recorded_timestamps_only",
            "model_frozen_before_acquisition": (
                None if record.model_frozen_at is None else record.model_frozen_at <= record.validation_acquired_from
            ),
            "policy_frozen_before_acquisition": (
                None if record.policy_frozen_at is None else record.policy_frozen_at <= record.validation_acquired_from
            ),
        }
    return {
        "schema_version": "spectrasherpa.independence-assessment/1",
        "identity_separation_status": status,
        "verified_roles": sorted({item["role"] for item in comparable}),
        "unverified_roles": sorted(
            {"fit", "selection", "interval_calibration"} - {item["role"] for item in comparable}
        ),
        "comparisons": comparisons,
        "known_specimen_overlap": any(bool(item["specimen_overlap"]) for item in comparable),
        "known_batch_overlap": any(bool(item["batch_overlap"]) for item in comparable),
        "sampling_independence_status": (
            "operator_declared"
            if (declaration if sampling_declaration is None else sampling_declaration)
            else "unknown"
        ),
        "chronology": chronology,
        "recorded_evidence": None if record is None else record.model_dump(mode="json"),
        "limitation": "System verification covers only equality of recorded IDs in matching namespaces. "
        "It does not prove completeness, authentic laboratory origin, unseen aliases, "
        "independent sampling, or external generalization.",
    }
