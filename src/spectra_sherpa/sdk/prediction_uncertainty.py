"""Frozen-pipeline split-conformal intervals for future reference measurements.

The sidecar is an integrity-checked aggregate record, not a publisher signature
or proof of laboratory exchangeability. It never changes the fitted model.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA = "spectrasherpa.prediction-uncertainty/1"
METHOD = "split_conformal_absolute_residual_order_statistic/1"
MAX_RECORD_BYTES = 128 * 1024


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class ClosedRecord(BaseModel):
    """Immutable finite-valued record that refuses undeclared fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class ResponseIdentity(ClosedRecord):
    """Response names and units in prediction-column order."""

    names: list[str] | None
    units: list[str | None]

    @model_validator(mode="after")
    def dimensions(self):
        if not 1 <= len(self.units) <= 256:
            raise ValueError("response count outside supported range")
        if self.names is not None and (len(self.names) != len(self.units) or len(set(self.names)) != len(self.names)):
            raise ValueError("response names must be unique and match units")
        return self


class ReferencePrecision(ClosedRecord):
    """Pooled within-specimen precision with explicit replication authority."""

    estimator: Literal["pooled_within_specimen_sample_sd"]
    sd: list[float] = Field(min_length=1, max_length=256)
    degrees_of_freedom: int = Field(gt=0)
    specimens: int = Field(gt=0)
    replicates_per_specimen: int = Field(ge=2)
    evidence_digest: str = Field(pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def coherent(self):
        if any(v < 0 for v in self.sd) or self.degrees_of_freedom != self.specimens * (
            self.replicates_per_specimen - 1
        ):
            raise ValueError("invalid pooled reference precision")
        return self


class ReferenceMethod(ClosedRecord):
    """Versioned reference measurement procedure and response identity."""

    method_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    response_identity: ResponseIdentity
    measurement_basis: Literal["single_measurement", "replicate_mean"]
    measurements_per_label: int = Field(ge=1, le=10000)
    precision: ReferencePrecision | None = None

    @model_validator(mode="after")
    def coherent(self):
        if (self.measurement_basis == "single_measurement") != (self.measurements_per_label == 1):
            raise ValueError("reference measurement basis contradicts replicate count")
        if self.precision is not None and len(self.precision.sd) != len(self.response_identity.units):
            raise ValueError("reference precision response dimensions disagree")
        return self


class UncertaintyRecord(ClosedRecord):
    """Frozen-pipeline conformal calibration sidecar with cohort and artifact bindings."""

    schema_version: Literal["spectrasherpa.prediction-uncertainty/1"]
    method: Literal["split_conformal_absolute_residual_order_statistic/1"]
    artifact_digest: str = Field(pattern="^[a-f0-9]{64}$")
    application_plan_digest: str = Field(pattern="^[a-f0-9]{64}$")
    terminal_state_digest: str = Field(pattern="^[a-f0-9]{64}$")
    calibration_execution_digest: str = Field(pattern="^[a-f0-9]{64}$")
    calibration_cohort_digest: str = Field(pattern="^[a-f0-9]{64}$")
    specimen_namespace: str = Field(min_length=1, max_length=200)
    specimen_identity_digest: str = Field(pattern="^[a-f0-9]{64}$")
    specimens: int = Field(ge=1, le=1_000_000)
    alpha: float = Field(gt=0, lt=1)
    order_statistic_rank: int = Field(gt=0)
    widths: list[float] = Field(min_length=1, max_length=256)
    reference_method: ReferenceMethod
    intended_population: str = Field(min_length=1, max_length=2000)
    model_frozen_before_calibration: Literal[True]
    calibration_not_used_for_fit_or_selection: Literal[True]
    exchangeability_declared: Literal[True]
    membership_check: Literal["not_verified", "provided_training_ids_disjoint"]
    record_digest: str = Field(pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def coherent(self):
        rank = math.ceil((self.specimens + 1) * (1 - self.alpha))
        if rank > self.specimens or self.order_statistic_rank != rank:
            raise ValueError("insufficient calibration specimens for the requested interval level")
        if len(self.widths) != len(self.reference_method.response_identity.units) or any(v < 0 for v in self.widths):
            raise ValueError("interval widths contradict response identity")
        if self.record_digest != _digest(self.model_dump(exclude={"record_digest"})):
            raise ValueError("uncertainty record integrity mismatch")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    @classmethod
    def load(cls, data: bytes | dict[str, Any]) -> "UncertaintyRecord":
        if isinstance(data, bytes):
            if len(data) > MAX_RECORD_BYTES:
                raise ValueError("uncertainty record exceeds size limit")
            data = json.loads(data)
        if len(json.dumps(data, allow_nan=False).encode()) > MAX_RECORD_BYTES:
            raise ValueError("uncertainty record exceeds size limit")
        return cls.model_validate(data)


def reference_precision(replicates: Any) -> dict[str, Any]:
    """Pool within-specimen repeat measurement variance; never infer from residuals."""
    values = np.asarray(replicates, dtype=float)
    if values.ndim != 3 or min(values.shape) < 1 or values.shape[1] < 2 or not np.isfinite(values).all():
        raise ValueError("reference replicates require finite specimen × replicate × response data")
    n, r, _ = values.shape
    # Subtract a nearby origin before scaling to preserve small differences on
    # a large offset. For opposite-sign extremes, scale before subtraction.
    with np.errstate(over="ignore", invalid="ignore"):
        shifted = values - values[:, :1, :]
    overflow = ~np.isfinite(shifted).all(axis=(0, 1))
    shifted[:, :, overflow] = values[:, :, overflow]
    scale = np.max(np.abs(shifted), axis=(0, 1))
    normalized = shifted / np.where(scale == 0, 1.0, scale)
    centered = normalized - normalized.mean(axis=1, keepdims=True)
    with np.errstate(over="ignore", under="ignore"):
        sd = scale * np.sqrt(np.sum(centered * centered, axis=(0, 1)) / (n * (r - 1)))
    if not np.isfinite(sd).all() or np.any((scale > 0) & (sd == 0)):
        raise ValueError("reference precision exceeds representable numerical range")
    return ReferencePrecision(
        estimator="pooled_within_specimen_sample_sd",
        sd=sd.tolist(),
        degrees_of_freedom=n * (r - 1),
        specimens=n,
        replicates_per_specimen=r,
        evidence_digest=_digest(values.tolist()),
    ).model_dump()


def _specimen_ids(ids: Any, n: int) -> list[str]:
    if (
        n < 1
        or not isinstance(ids, list)
        or len(ids) != n
        or any(not isinstance(v, str) or not v.strip() for v in ids)
        or len(set(ids)) != n
    ):
        raise ValueError("one unique nonempty specimen ID per calibration row is required; aggregate replicates first")
    return ids


def build_record(
    *,
    predictions: Any,
    observed: Any,
    prediction_identity: dict[str, Any],
    application_plan: Any,
    cohort_digest: str,
    specimen_ids: list[str],
    specimen_namespace: str,
    reference_method: dict[str, Any],
    alpha: float,
    intended_population: str,
    declarations: dict[str, bool],
    training_specimen_ids: list[str] | None = None,
) -> UncertaintyRecord:
    """Pure record builder. Public calibration orchestrator supplies executed-pipeline evidence."""
    from .canonical_application import CanonicalApplicationPlan

    if not isinstance(application_plan, CanonicalApplicationPlan):
        raise ValueError("a verified canonical application plan is required")
    required = {
        "model_frozen_before_calibration",
        "calibration_not_used_for_fit_or_selection",
        "exchangeability_declared",
    }
    if set(declarations) != required or any(v is not True for v in declarations.values()):
        raise ValueError("frozen-model, non-selection and exchangeability declarations are required")
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not 0 < alpha < 1:
        raise ValueError("alpha must be strictly between zero and one")
    pred = np.asarray(predictions, dtype=float)
    y = np.asarray(observed, dtype=float)
    if y.ndim == 1:
        y = y[:, None]
    if (
        pred.ndim != 2
        or y.shape != pred.shape
        or not pred.size
        or not np.isfinite(pred).all()
        or not np.isfinite(y).all()
    ):
        raise ValueError("finite complete calibration predictions and aligned responses are required")
    ids = _specimen_ids(specimen_ids, len(pred))
    if prediction_identity.get("sample_labels") is not None and prediction_identity["sample_labels"] != ids:
        raise ValueError("specimen IDs differ from the executed calibration population")
    method = ReferenceMethod.model_validate(reference_method)
    if method.response_identity.model_dump() != prediction_identity["response_identity"]:
        raise ValueError("reference method response names/units differ from the model")
    if (
        prediction_identity["shape"] != list(pred.shape)
        or prediction_identity["prediction_sha256"]
        != hashlib.sha256(np.asarray(pred, dtype="<f8").tobytes()).hexdigest()
    ):
        raise ValueError("calibration predictions differ from their originating receipt")
    custody = prediction_identity["fitted_state_custody"]
    binding = next(
        v["artifact_binding"]
        for v in application_plan.payload["nodes"]
        if v["node_id"] == application_plan.payload["model_node_id"]
    )
    if (
        custody.get("artifact_digest") != application_plan.payload["artifact_digest"]
        or custody.get("state_digest") != binding["state_digest"]
    ):
        raise ValueError("calibration model custody differs from the application plan")
    membership = "not_verified"
    if training_specimen_ids is not None:
        train_ids = _specimen_ids(training_specimen_ids, len(training_specimen_ids))
        if set(train_ids) & set(ids):
            raise ValueError("calibration specimens overlap provided training specimens")
        membership = "provided_training_ids_disjoint"
    n = len(pred)
    rank = math.ceil((n + 1) * (1 - alpha))
    if rank > n:
        raise ValueError("insufficient calibration specimens for the requested interval level")
    residual = np.abs(y - pred)
    if not np.isfinite(residual).all():
        raise ValueError("calibration residuals exceed finite numerical range")
    widths = np.sort(residual, axis=0)[rank - 1]
    payload = dict(
        schema_version=SCHEMA,
        method=METHOD,
        artifact_digest=application_plan.payload["artifact_digest"],
        application_plan_digest=application_plan.application_plan_digest,
        terminal_state_digest=binding["state_digest"],
        calibration_execution_digest=_digest(
            {
                "plan": application_plan.application_plan_digest,
                "cohort": cohort_digest,
                "prediction": prediction_identity["prediction_sha256"],
                "observed": hashlib.sha256(np.asarray(y, dtype="<f8").tobytes()).hexdigest(),
            }
        ),
        calibration_cohort_digest=cohort_digest,
        specimen_namespace=specimen_namespace,
        specimen_identity_digest=_digest({"namespace": specimen_namespace, "ids": ids}),
        specimens=n,
        alpha=float(alpha),
        order_statistic_rank=rank,
        widths=widths.tolist(),
        reference_method=method.model_dump(),
        intended_population=intended_population,
        membership_check=membership,
        **declarations,
    )
    return UncertaintyRecord.model_validate({**payload, "record_digest": _digest(payload)})


@dataclass(frozen=True)
class BoundPredictionUncertainty:
    """Runtime authority bound by a verified full-pipeline executor, not node parameters."""

    record_bytes: bytes
    artifact_digest: str
    application_plan_digest: str
    terminal_state_digest: str
    accepted_population: str

    @classmethod
    def bind(
        cls, record: UncertaintyRecord, plan: Any, accepted_population: str | None = None
    ) -> "BoundPredictionUncertainty":
        from .canonical_application import CanonicalApplicationPlan

        if not isinstance(plan, CanonicalApplicationPlan):
            raise ValueError("uncertainty requires a verified application plan")
        node = next(n for n in plan.payload["nodes"] if n["node_id"] == plan.payload["model_node_id"])
        state_digest = node["artifact_binding"]["state_digest"]
        if (record.artifact_digest, record.application_plan_digest, record.terminal_state_digest) != (
            plan.payload["artifact_digest"],
            plan.application_plan_digest,
            state_digest,
        ):
            raise ValueError("selected uncertainty record differs from the frozen prediction pipeline")
        if accepted_population != record.intended_population:
            raise ValueError("Explicit acceptance of the selected record intended population is required")
        return cls(
            record.canonical_bytes(),
            record.artifact_digest,
            plan.application_plan_digest,
            state_digest,
            accepted_population,
        )

    def apply(self, predictions: Any, identity: dict[str, Any], screening: dict[str, Any]) -> dict[str, Any]:
        record = UncertaintyRecord.load(self.record_bytes)
        if (record.artifact_digest, record.application_plan_digest, record.terminal_state_digest) != (
            self.artifact_digest,
            self.application_plan_digest,
            self.terminal_state_digest,
        ):
            raise ValueError("uncertainty runtime record binding mismatch")
        if self.accepted_population != record.intended_population:
            raise ValueError("uncertainty population declaration mismatch")
        custody = identity["fitted_state_custody"]
        if (
            custody.get("artifact_digest") != self.artifact_digest
            or custody.get("state_digest") != self.terminal_state_digest
        ):
            raise ValueError("uncertainty runtime model custody mismatch")
        if record.reference_method.response_identity.model_dump() != identity["response_identity"]:
            raise ValueError("uncertainty response identity mismatch")
        pred = np.asarray(predictions, dtype=float)
        if identity["shape"] != list(pred.shape) or screening["prediction_identity"] != identity:
            raise ValueError("uncertainty prediction population mismatch")
        if (
            len(screening["rows"]) != len(pred)
            or identity["prediction_sha256"] != hashlib.sha256(np.asarray(pred, dtype="<f8").tobytes()).hexdigest()
        ):
            raise ValueError("uncertainty prediction receipt mismatch")
        rows = []
        for index, row in enumerate(screening["rows"]):
            if row["row_index"] != index:
                raise ValueError("uncertainty screening population order mismatch")
            available = row["screening_status"] == "within_global_screen"
            lower, upper = pred[index] - record.widths, pred[index] + record.widths
            if not np.isfinite(lower).all() or not np.isfinite(upper).all():
                raise ValueError("interval endpoints exceed finite numerical range")
            rows.append(
                {
                    "row_index": index,
                    "status": "available" if available else "unavailable_screening",
                    "lower": lower.tolist() if available else None,
                    "upper": upper.tolist() if available else None,
                }
            )
        return {
            "schema_version": SCHEMA,
            "status": "calibrated_reference_measurement_intervals",
            "record_digest": record.record_digest,
            "calibration_record": record.model_dump(),
            "application_plan_digest": self.application_plan_digest,
            "method": METHOD,
            "alpha": record.alpha,
            "prediction_identity": identity,
            "coverage_scope": "per_response_marginal_under_declared_exchangeability_not_screen_conditional",
            "provenance": "digest_checked_calibration_record_not_proof_of_independence",
            "membership_check": record.membership_check,
            "reference_method": record.reference_method.model_dump(),
            "intended_population": record.intended_population,
            "population_compatibility": "declared_by_operator_not_verified",
            "latent_true_concentration_uncertainty": "unavailable",
            "rows": rows,
        }


async def calibrate_prediction_intervals(
    plan: Any,
    dataset: Any,
    *,
    runtime: Any,
    specimen_ids: list[str],
    specimen_namespace: str,
    reference_method: dict[str, Any],
    alpha: float,
    intended_population: str,
    declarations: dict[str, bool],
    training_specimen_ids: list[str] | None = None,
) -> UncertaintyRecord:
    """Execute the frozen pipeline on a separate, complete calibration cohort."""
    from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import _response_identity

    from .canonical_application_execution import execute_canonical_application

    if dataset.target is None:
        raise ValueError("calibration cohort has no reference response")
    for axis in (dataset.sample_axis, dataset.feature_axis):
        if axis is not None and axis.include_mask is not None and not np.all(axis.include_mask):
            raise ValueError("materialize calibration exclusions before interval calibration")
    execution = await execute_canonical_application(
        plan, dataset, runtime=replace(runtime, prediction_uncertainty=None)
    )
    output = execution.results[plan.payload["model_node_id"]]
    target_array = np.asarray(dataset.target)
    response = _response_identity(
        dataset, targets=1 if target_array.ndim == 1 else target_array.shape[1], bound_names=[], embedded=True
    )
    if response != output["prediction_identity"]["response_identity"]:
        raise ValueError("calibration response authority differs from model response identity")
    return build_record(
        predictions=output["default"],
        observed=dataset.target,
        prediction_identity=output["prediction_identity"],
        application_plan=plan,
        cohort_digest=dataset.scientific_digest,
        specimen_ids=specimen_ids,
        specimen_namespace=specimen_namespace,
        reference_method=reference_method,
        alpha=alpha,
        intended_population=intended_population,
        declarations=declarations,
        training_specimen_ids=training_specimen_ids,
    )
