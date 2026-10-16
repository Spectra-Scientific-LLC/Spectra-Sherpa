"""Bound, explicitly declared laboratory reference-value context.

This record describes the source of Y.  It never estimates laboratory
precision from model residuals or treats an asserted replicate count as a
verified replicate mapping.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spectra_sherpa.sdk.prediction_uncertainty import ReferenceMethod


class ReferenceValueDeclaration(BaseModel):
    """User declaration bound to one selected response and sample-table version."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    schema_version: Literal["spectrasherpa.reference-value-declaration/1"] = (
        "spectrasherpa.reference-value-declaration/1"
    )
    target_name: str = Field(min_length=1, max_length=255)
    target_type: Literal["continuous", "categorical"]
    units: str | None = Field(default=None, max_length=100)
    method: ReferenceMethod | None = None
    provenance: str | None = Field(default=None, max_length=500)
    precision_study_provenance: str | None = Field(default=None, max_length=500)
    replicate_evidence_digest: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def coherent(self) -> "ReferenceValueDeclaration":
        if self.target_type == "categorical" and self.units is not None:
            raise ValueError("Categorical labels do not have quantitative response units")
        if self.method is not None:
            identity = self.method.response_identity
            if identity.names != [self.target_name] or identity.units != [self.units]:
                raise ValueError("Reference method response name and units must match the selected target")
            if self.target_type == "categorical" and self.method.measurement_basis == "replicate_mean":
                raise ValueError("Categorical labels cannot be represented as a mean of replicate measurements")
            if self.target_type == "categorical" and self.method.precision is not None:
                raise ValueError("Numeric reference precision cannot qualify categorical labels")
            if self.method.precision is not None and not self.precision_study_provenance:
                raise ValueError("Reported reference precision requires separate study provenance")
            if self.method.measurement_basis == "single_measurement" and self.replicate_evidence_digest is not None:
                raise ValueError("Single-measurement labels cannot claim replicate evidence")
        elif self.replicate_evidence_digest is not None:
            raise ValueError("Replicate evidence requires a declared reference method")
        if (self.method is None or self.method.precision is None) and self.precision_study_provenance is not None:
            raise ValueError("Precision study provenance requires reported precision")
        return self


def reference_value_evidence(
    declaration: ReferenceValueDeclaration | None,
    *,
    source_file_id: int,
    sample_table_file_id: int,
    table_sha256: str,
    target_name: str,
    target_type: str,
    known_units: str | None = None,
    source_included_count: int,
    missing_excluded_count: int,
) -> dict[str, object]:
    """Project an exact-bound, honest qualification summary without raw Y values."""

    if declaration is not None and (declaration.target_name, declaration.target_type) != (
        target_name,
        target_type,
    ):
        raise ValueError("Reference declaration differs from the selected table target")
    if source_file_id < 1 or sample_table_file_id < 1 or source_included_count < 0 or missing_excluded_count < 0:
        raise ValueError("Reference evidence source or counts are invalid")
    method = declaration.method if declaration is not None else None
    units = declaration.units if declaration is not None else known_units
    gaps: list[str] = []
    if method is None:
        gaps.append("Reference measurement method is not recorded")
    if units is None and target_type == "continuous":
        gaps.append("Response units are not recorded")
    if method is not None and method.precision is None and target_type == "continuous":
        gaps.append("Reference measurement precision is not recorded")
    if method is not None and method.precision is not None:
        gaps.append("Reported reference precision has not been independently verified against source replicates")
        if method.measurement_basis == "single_measurement":
            gaps.append("Precision comes from a separate replicate study, not each reported single value")
        elif method.precision.replicates_per_specimen != method.measurements_per_label:
            gaps.append("Precision study replicate count differs from the per-label replicate basis")
    if method is not None and method.measurement_basis == "replicate_mean":
        if declaration is None or declaration.replicate_evidence_digest is None:
            gaps.append("Replicate-to-specimen mapping is declared but not backed by a reference-data digest")
        else:
            gaps.append("Replicate-to-specimen mapping has not been independently verified")
    return {
        "schema_version": "spectrasherpa.reference-value-evidence/1",
        "source_file_id": source_file_id,
        "sample_table_file_id": sample_table_file_id,
        "sample_table_sha256": table_sha256,
        "target_name": target_name,
        "target_type": target_type,
        "units": units,
        "method": method.model_dump(mode="json") if method is not None else None,
        "provenance": declaration.provenance if declaration is not None else None,
        "precision_study_provenance": declaration.precision_study_provenance if declaration is not None else None,
        "replicate_evidence_digest": declaration.replicate_evidence_digest if declaration is not None else None,
        "source_included_count": source_included_count,
        "missing_included_count": 0,
        "missing_excluded_count": missing_excluded_count,
        "instrument_repeatability": None,
        "qualification_gaps": gaps,
    }


def bound_reference_value_evidence(
    source: Any,
    *,
    response_names: list[str] | None,
    response_units: list[str | None],
    target_type: Literal["continuous", "categorical"],
) -> dict[str, object] | None:
    """Return a declared response record only for the fitted response identity.

    A connected Y can differ from X's embedded target. Do not attach X's
    reference claim just because both arrays have the same row count.
    """

    context = getattr(source, "target_context", None)
    record = getattr(context, "reference_value_evidence", None)
    if not isinstance(record, dict) or record.get("schema_version") != "spectrasherpa.reference-value-evidence/1":
        return None
    if (
        response_names != [record.get("target_name")]
        or response_units != [record.get("units")]
        or record.get("target_type") != target_type
    ):
        return None
    return deepcopy(record)
