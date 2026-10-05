"""Versioned intended-use assessments; execution readiness is never qualification.

These records retain calculations, operator declarations and review decisions as
separate authorities. A digest is integrity, not laboratory certification.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Literal

import numpy as np
from pydantic import Field, PrivateAttr, model_validator

from .prediction_uncertainty import ClosedRecord, ReferenceMethod, ResponseIdentity, _digest, _specimen_ids
from .validate import bootstrap_regression_uncertainty, metrics

SCHEMA = "spectrasherpa.analytical-qualification/1"


class ResponseAcceptance(ClosedRecord):
    """Operator-declared error limits and intended range for one response."""

    max_rmsep: float = Field(gt=0)
    max_absolute_bias: float = Field(gt=0)
    intended_minimum: float
    intended_maximum: float

    @model_validator(mode="after")
    def ordered(self):
        if self.intended_minimum >= self.intended_maximum:
            raise ValueError("intended response range must have positive width")
        return self


class QualificationPolicy(ClosedRecord):
    """Frozen acceptance criteria bound to named response identities."""

    schema_version: Literal["spectrasherpa.declared-qualification-policy/1"]
    policy_name: str = Field(min_length=1, max_length=200)
    policy_version: str = Field(min_length=1, max_length=100)
    minimum_independent_specimens: int = Field(ge=2)
    minimum_specimens_per_component: float = Field(gt=0)
    response_identity: ResponseIdentity
    responses: list[ResponseAcceptance] = Field(min_length=1, max_length=256)
    require_reference_precision: bool
    minimum_screening_available_fraction: float = Field(ge=0, le=1)
    minimum_interval_available_fraction: float | None = Field(default=None, ge=0, le=1)
    minimum_observed_interval_coverage: float | None = Field(default=None, gt=0, le=1)
    bias_confidence_level: float = Field(gt=0, lt=1)
    bootstrap_resamples: int = Field(ge=200, le=10000)
    random_seed: int = Field(ge=0, le=4294967295)

    @model_validator(mode="after")
    def dimensions(self):
        if len(self.responses) != len(self.response_identity.units):
            raise ValueError("one acceptance specification per response is required")
        if (self.minimum_interval_available_fraction is None) != (self.minimum_observed_interval_coverage is None):
            raise ValueError("interval availability and observed coverage criteria must be specified together")
        return self


class QualificationContext(ClosedRecord):
    """Intended use, population and independence declarations for an assessment."""

    intended_use: str = Field(min_length=1, max_length=2000)
    intended_population: str = Field(min_length=1, max_length=2000)
    specimen_namespace: str = Field(min_length=1, max_length=200)
    reference_method: ReferenceMethod
    instrument_id: str | None = Field(default=None, min_length=1, max_length=200)
    acquisition_configuration_digest: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    domain_coverage_evidence_digest: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    policy_frozen_before_validation: bool
    model_frozen_before_validation: bool
    specimens_not_used_for_fit_selection_or_interval_calibration: bool
    independent_specimen_sampling_declared: bool
    sampling_design: str = Field(min_length=1, max_length=2000)
    evaluation_role: Literal["external_validation", "held_out_test", "calibration", "cross_validation", "surrogate"]


class QualificationDossier(ClosedRecord):
    """Retained calculations and declarations; integrity is not certification."""

    _computed_here: bool = PrivateAttr(default=False)
    schema_version: Literal["spectrasherpa.analytical-qualification/1"]
    artifact_digest: str = Field(pattern="^[a-f0-9]{64}$")
    application_plan_digest: str = Field(pattern="^[a-f0-9]{64}$")
    terminal_state_digest: str = Field(pattern="^[a-f0-9]{64}$")
    policy: QualificationPolicy
    context: QualificationContext
    cohort_digest: str = Field(pattern="^[a-f0-9]{64}$")
    original_cohort_digest: str = Field(pattern="^[a-f0-9]{64}$")
    exclusions: list[dict[str, Any]]
    specimen_identity_digest: str = Field(pattern="^[a-f0-9]{64}$")
    prediction_identity: dict[str, Any]
    calculation: dict[str, Any]
    evidence_links: list[str]
    assessment: Literal["criteria_met", "criteria_not_met", "incomplete"]
    criteria: list[dict[str, Any]]
    limitations: list[str]
    record_digest: str = Field(pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def integrity(self):
        if self.record_digest != _digest(self.model_dump(exclude={"record_digest"})):
            raise ValueError("qualification dossier integrity mismatch")
        states = [item.get("state") for item in self.criteria]
        if not states or any(state not in {"met", "not_met", "unavailable"} for state in states):
            raise ValueError("qualification criteria require explicit states")
        expected = (
            "criteria_not_met" if "not_met" in states else "incomplete" if "unavailable" in states else "criteria_met"
        )
        if self.assessment != expected:
            raise ValueError("qualification assessment contradicts its criteria")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    @classmethod
    def load(cls, value: bytes | dict[str, Any]):
        if isinstance(value, bytes):
            if len(value) > 1024 * 1024:
                raise ValueError("qualification dossier exceeds size limit")
            value = json.loads(value)
        if len(json.dumps(value, allow_nan=False).encode()) > 1024 * 1024:
            raise ValueError("qualification dossier exceeds size limit")
        return cls.model_validate(value)

    def assert_application(self, *, artifact_digest: str, application_plan_digest: str, context: QualificationContext):
        if (artifact_digest, application_plan_digest, context.model_dump()) != (
            self.artifact_digest,
            self.application_plan_digest,
            self.context.model_dump(),
        ):
            raise ValueError(
                "qualification is stale for the selected model, population, reference or instrument assumptions"
            )


def assess_validation(
    *,
    plan: Any,
    observed: Any,
    predictions: Any,
    prediction_identity: dict[str, Any],
    screening: dict[str, Any],
    effective_components: int,
    policy: QualificationPolicy,
    context: QualificationContext,
    cohort_digest: str,
    specimen_ids: list[str],
    source_rows: int,
    excluded_rows: int,
    original_cohort_digest: str,
    exclusions: list[dict[str, Any]],
    intervals: dict[str, Any] | None = None,
    evidence_links: list[str] | None = None,
    independence_evidence: dict[str, Any] | None = None,
) -> QualificationDossier:
    """Assess executed fixed-model evidence using a declared, versioned policy."""
    from .canonical_application import CanonicalApplicationPlan

    if not isinstance(plan, CanonicalApplicationPlan):
        raise ValueError("qualification requires a verified frozen application plan")
    y = np.asarray(observed, dtype=float)
    pred = np.asarray(predictions, dtype=float)
    if y.ndim == 1:
        y = y[:, None]
    if y.ndim != 2 or pred.shape != y.shape or len(y) < 2 or not np.isfinite(y).all() or not np.isfinite(pred).all():
        raise ValueError("qualification requires at least two finite complete reference/prediction rows")
    # Refuse oversized work explicitly; never lower the declared resample count
    # or subsample the scientific population silently.
    if y.size * policy.bootstrap_resamples > 20_000_000:
        raise ValueError(
            "qualification bootstrap workload exceeds 20,000,000 response-row resamples; "
            "use an explicitly revised policy or offline assessment"
        )
    ids = _specimen_ids(specimen_ids, len(y))
    from .validation_independence import assess_independence

    independence = assess_independence(
        specimen_ids=ids,
        namespace=context.specimen_namespace,
        declaration=context.specimens_not_used_for_fit_selection_or_interval_calibration,
        evidence=independence_evidence,
        sampling_declaration=context.independent_specimen_sampling_declared,
    )
    if source_rows != len(y) + excluded_rows or excluded_rows < 0 or len(exclusions) != excluded_rows:
        raise ValueError("qualification population accounting is inconsistent")
    if isinstance(effective_components, bool) or effective_components < 1:
        raise ValueError("effective fitted component count is unavailable")
    from hashlib import sha256

    if (
        prediction_identity["shape"] != list(pred.shape)
        or prediction_identity["prediction_sha256"] != sha256(np.asarray(pred, dtype="<f8").tobytes()).hexdigest()
    ):
        raise ValueError("qualification predictions differ from their receipt")
    if prediction_identity.get("sample_labels") is not None and prediction_identity["sample_labels"] != ids:
        raise ValueError("qualification specimen IDs differ from executed rows")
    if screening["prediction_identity"] != prediction_identity or len(screening["rows"]) != len(y):
        raise ValueError("qualification screening population differs from predictions")
    expected_response = policy.response_identity.model_dump()
    if (
        expected_response != context.reference_method.response_identity.model_dump()
        or expected_response != prediction_identity["response_identity"]
    ):
        raise ValueError("qualification policy/reference response authority differs from the model")
    model_node = next(n for n in plan.payload["nodes"] if n["node_id"] == plan.payload["model_node_id"])
    binding = model_node["artifact_binding"]
    custody = prediction_identity["fitted_state_custody"]
    if (
        custody.get("artifact_digest") != plan.payload["artifact_digest"]
        or custody.get("state_digest") != binding["state_digest"]
    ):
        raise ValueError("qualification model custody differs from the frozen pipeline")
    criteria = []

    def criterion(name, passed, detail):
        criteria.append(
            {
                "name": name,
                "state": "unavailable" if passed is None else "met" if passed else "not_met",
                "detail": detail,
            }
        )

    if independence["comparisons"]:
        criterion(
            "recorded_specimen_separation",
            None if not independence["verified_roles"] else not independence["known_specimen_overlap"],
            "Set comparison of recorded IDs only; consult verified and unverified roles",
        )
        if independence["known_batch_overlap"]:
            criterion(
                "recorded_batch_separation",
                False,
                "Recorded batches overlap; independent specimen sampling requires review",
            )
    criterion(
        "validation_role", context.evaluation_role in {"external_validation", "held_out_test"}, context.evaluation_role
    )
    for name in (
        "policy_frozen_before_validation",
        "model_frozen_before_validation",
        "specimens_not_used_for_fit_selection_or_interval_calibration",
        "independent_specimen_sampling_declared",
    ):
        criterion(
            name,
            True if getattr(context, name) else None,
            "operator declaration; chronology and laboratory independence not proven",
        )
    criterion(
        "response_units",
        True if all(policy.response_identity.units) else None,
        "unknown units cannot establish unit-bound acceptance",
    )
    criterion(
        "instrument_authority",
        True if context.instrument_id and context.acquisition_configuration_digest else None,
        "declared instrument and acquisition configuration",
    )
    criterion(
        "domain_coverage_evidence",
        True if context.domain_coverage_evidence_digest else None,
        "external evidence declared; observed extrema do not establish local support",
    )
    criterion("specimen_count", len(y) >= policy.minimum_independent_specimens, f"{len(y)} distinct declared specimens")
    criterion(
        "specimens_per_component",
        len(y) / effective_components >= policy.minimum_specimens_per_component,
        "declared heuristic; components are not statistical degrees of freedom",
    )
    if policy.require_reference_precision:
        criterion(
            "reference_precision",
            True if context.reference_method.precision is not None else None,
            "repeat-measurement evidence, never inferred from residuals",
        )
    available = sum(row["screening_status"] != "unavailable" for row in screening["rows"])
    criterion(
        "global_screening_available",
        available / len(y) >= policy.minimum_screening_available_fraction,
        "availability only; neither local support nor instrument equivalence",
    )
    responses = []
    for j, limit in enumerate(policy.responses):
        computed = metrics(y[:, j], pred[:, j])
        uncertainty = bootstrap_regression_uncertainty(
            y[:, j],
            pred[:, j],
            n_resamples=policy.bootstrap_resamples,
            confidence_level=policy.bias_confidence_level,
            random_state=policy.random_seed,
        ).as_dict()
        bias_ci = uncertainty["bias"]
        criterion(
            f"response_{j}_rmsep",
            computed.rmse <= limit.max_rmsep,
            "root mean squared prediction error on complete validation rows",
        )
        criterion(
            f"response_{j}_bias_equivalence",
            bias_ci["lower"] >= -limit.max_absolute_bias and bias_ci["upper"] <= limit.max_absolute_bias,
            "entire percentile bootstrap bias interval must lie within practical tolerance",
        )
        criterion(
            f"response_{j}_observed_range",
            float(y[:, j].min()) <= limit.intended_minimum and float(y[:, j].max()) >= limit.intended_maximum,
            "observed extrema only; not proof of coverage between clusters",
        )
        responses.append(
            {
                "metrics": asdict(computed),
                "metric_uncertainty": uncertainty,
                "observed_minimum": float(y[:, j].min()),
                "observed_maximum": float(y[:, j].max()),
            }
        )
    interval_summary = None
    if intervals is not None and intervals.get("status") != "point_only":
        if intervals.get("prediction_identity") != prediction_identity or len(intervals["rows"]) != len(y):
            raise ValueError("qualification interval population differs from predictions")
        calibration = intervals["calibration_record"]
        if calibration["reference_method"] != context.reference_method.model_dump():
            raise ValueError("interval calibration reference method or measurement basis differs from qualification")
        criterion(
            "interval_reference_method",
            calibration["reference_method"] == context.reference_method.model_dump(),
            "interval and validation reference method, version and measurement basis must match",
        )
        same_cohort = calibration["calibration_cohort_digest"] == cohort_digest
        same_ids = calibration["specimen_identity_digest"] == _digest(
            {"namespace": context.specimen_namespace, "ids": ids}
        )
        criterion(
            "interval_calibration_separation",
            not (same_cohort or same_ids),
            "exact cohort reuse checked; partial overlap and laboratory independence remain declared",
        )
        usable = [row for row in intervals["rows"] if row["status"] == "available"]
        covered = np.zeros(y.shape[1], dtype=int)
        for row in usable:
            index = row["row_index"]
            covered += (y[index] >= row["lower"]) & (y[index] <= row["upper"])
        interval_summary = {
            "record_digest": intervals["record_digest"],
            "available_rows": len(usable),
            "total_rows": len(y),
            "observed_coverage_among_available": (covered / len(usable)).tolist() if usable else None,
            "population_coverage": "unavailable_when_intervals_are_screened",
            "calibration_record": intervals["calibration_record"],
        }
    if policy.minimum_interval_available_fraction is not None:
        criterion(
            "interval_availability",
            (
                None
                if interval_summary is None
                else interval_summary["available_rows"] / len(y) >= policy.minimum_interval_available_fraction
            ),
            "denominator includes every complete validation row",
        )
        coverage = None if interval_summary is None else interval_summary["observed_coverage_among_available"]
        criterion(
            "observed_interval_coverage",
            None if coverage is None else all(v >= policy.minimum_observed_interval_coverage for v in coverage),
            "empirical available-row coverage only; no population or conditional guarantee",
        )
    states = [item["state"] for item in criteria]
    payload = dict(
        schema_version=SCHEMA,
        artifact_digest=plan.payload["artifact_digest"],
        application_plan_digest=plan.application_plan_digest,
        terminal_state_digest=binding["state_digest"],
        policy=policy.model_dump(),
        context=context.model_dump(),
        cohort_digest=cohort_digest,
        original_cohort_digest=original_cohort_digest,
        exclusions=exclusions,
        specimen_identity_digest=_digest({"namespace": context.specimen_namespace, "ids": ids}),
        prediction_identity=prediction_identity,
        calculation={
            "independence": independence,
            "source_rows": source_rows,
            "complete_rows": len(y),
            "excluded_rows": excluded_rows,
            "effective_fitted_components": effective_components,
            "component_count_is_statistical_dof": False,
            "responses": responses,
            "global_screening_available_rows": available,
            "intervals": interval_summary,
        },
        evidence_links=evidence_links or [],
        assessment=(
            "criteria_not_met" if "not_met" in states else "incomplete" if "unavailable" in states else "criteria_met"
        ),
        criteria=criteria,
        limitations=[
            "No ASTM or regulatory compliance claim",
            "Independent sampling, policy chronology, intended-domain and instrument evidence are declarations",
            "Bootstrap intervals describe this fixed validation cohort, not model selection uncertainty",
            "Digest integrity does not authenticate laboratory approval",
        ],
    )
    record = QualificationDossier.model_validate({**payload, "record_digest": _digest(payload)})
    record._computed_here = True
    return record


async def qualify_application(
    plan: Any,
    dataset: Any,
    *,
    runtime: Any,
    policy: QualificationPolicy,
    context: QualificationContext,
    specimen_ids: list[str],
    allow_missing_reference_exclusion: bool = False,
    uncertainty_record: dict[str, Any] | None = None,
    evidence_links: list[str] | None = None,
    independence_evidence: dict[str, Any] | None = None,
) -> QualificationDossier:
    """Execute the frozen application on explicitly separate validation specimens."""
    from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node, _response_identity

    from .canonical_application_execution import execute_canonical_application

    if dataset.target is None:
        raise ValueError("qualification dataset has no reference responses")
    ids = _specimen_ids(specimen_ids, len(dataset.X))
    for axis in (dataset.sample_axis, dataset.feature_axis):
        if axis is not None and axis.include_mask is not None and not np.all(axis.include_mask):
            raise ValueError("materialize declared sample/feature exclusions before qualification")
    y = np.asarray(dataset.target, dtype=float)
    if y.ndim == 1:
        y = y[:, None]
    if not np.isfinite(dataset.X).all() or np.isinf(y).any():
        raise ValueError("nonfinite predictors and infinite references are invalid, not missing observations")
    original_cohort_digest = dataset.scientific_digest
    complete = ~np.isnan(y).any(axis=1)
    exclusions = [
        {
            "original_row_index": i,
            "specimen_id": ids[i],
            "reason": "missing_reference",
            "missing_response_columns": np.flatnonzero(np.isnan(y[i])).tolist(),
        }
        for i in np.flatnonzero(~complete).tolist()
    ]
    if not complete.all() and not allow_missing_reference_exclusion:
        raise ValueError("missing references require explicit complete-case exclusion")
    if complete.sum() < 2:
        raise ValueError("at least two complete validation specimens are required")
    source = dataset[complete, :] if not complete.all() else dataset
    selected_ids = [value for value, keep in zip(ids, complete) if keep]
    reference_identity = _response_identity(source, targets=y.shape[1], bound_names=[], embedded=True)
    if reference_identity != context.reference_method.response_identity.model_dump():
        raise ValueError("validation reference authority differs from the declared reference method")
    node = next(n for n in plan.payload["nodes"] if n["node_id"] == plan.payload["model_node_id"])
    if node["application_operation_id"] != "model.apply_fitted_pls":
        raise ValueError("qualification currently supports canonical PLS regression only")
    if runtime.canonical_artifact_reader is None:
        raise ValueError("qualification requires explicit fitted-artifact read authority")
    binding = node["artifact_binding"]
    state = runtime.canonical_artifact_reader.load_bound_state(
        binding,
        expected_source_contract_digest=binding["source_contract_digest"],
        expected_serializer=binding["serializer"],
    )
    state = FittedPLSV2Node("qualification-state-validator", {}).validate_fitted_state(state)
    execution = await execute_canonical_application(
        plan,
        source,
        runtime=runtime,
        uncertainty_record=uncertainty_record,
        uncertainty_population=context.intended_population if uncertainty_record is not None else None,
    )
    output = execution.results[plan.payload["model_node_id"]]
    from asyncio import to_thread

    return await to_thread(
        assess_validation,
        plan=plan,
        observed=y[complete],
        predictions=output["default"],
        prediction_identity=output["prediction_identity"],
        screening=output["applicability"],
        effective_components=state["effective_n_components"],
        policy=policy,
        context=context,
        cohort_digest=source.scientific_digest,
        specimen_ids=selected_ids,
        source_rows=len(y),
        excluded_rows=int((~complete).sum()),
        original_cohort_digest=original_cohort_digest,
        exclusions=exclusions,
        intervals=output["prediction_intervals"],
        evidence_links=evidence_links,
        independence_evidence=independence_evidence,
    )


class QualificationDecision(ClosedRecord):
    """Append-only human decision bound to an exact dossier digest."""

    schema_version: Literal["spectrasherpa.qualification-decision/1"]
    dossier_digest: str = Field(pattern="^[a-f0-9]{64}$")
    decision: Literal["accepted_under_declared_policy", "rejected", "pending"]
    actor: str = Field(min_length=1, max_length=200)
    recorded_at: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=4000)
    provenance: Literal["operator_assertion"] = "operator_assertion"
    decision_digest: str = Field(pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def integrity(self):
        if self.decision_digest != _digest(self.model_dump(exclude={"decision_digest"})):
            raise ValueError("qualification decision integrity mismatch")
        return self


def decide_qualification(
    dossier: QualificationDossier, *, decision: str, actor: str, recorded_at: str, reason: str
) -> QualificationDecision:
    """A human decision, never inferred from readiness or the metric score."""
    if decision == "accepted_under_declared_policy" and not dossier._computed_here:
        raise ValueError("imported assessment is an assertion; re-execute qualification before acceptance")
    if decision == "accepted_under_declared_policy" and dossier.assessment != "criteria_met":
        raise ValueError("cannot accept incomplete or failed qualification criteria")
    payload = dict(
        schema_version="spectrasherpa.qualification-decision/1",
        dossier_digest=dossier.record_digest,
        decision=decision,
        actor=actor,
        recorded_at=recorded_at,
        reason=reason,
        provenance="operator_assertion",
    )
    return QualificationDecision.model_validate({**payload, "decision_digest": _digest(payload)})


def render_qualification_report(
    dossier: QualificationDossier, decisions: list[QualificationDecision] | None = None
) -> str:
    """Export a self-contained evidence report without promoting operational status."""
    reviewed = QualificationDossier.load(dossier.canonical_bytes())
    decisions = decisions or []
    for decision in decisions:
        QualificationDecision.model_validate(decision.model_dump())
        if decision.dossier_digest != reviewed.record_digest:
            raise ValueError("review decision belongs to another dossier")
    lines = [
        "# Analytical qualification evidence",
        "",
        "Operational readiness is separate. No ASTM, regulatory or laboratory certification is implied.",
        "Imported assessment calculations and actor identities are assertions; a checksum does not authenticate them.",
        "",
        f"Dossier: {reviewed.record_digest}",
        f"Model artifact: {reviewed.artifact_digest}",
        f"Application plan: {reviewed.application_plan_digest}",
        f"Assessment: {reviewed.assessment}",
        f"Intended use: {reviewed.context.intended_use}",
        f"Intended population: {reviewed.context.intended_population}",
        "",
        "## Exact retained record",
        "",
        "```json",
        json.dumps(reviewed.model_dump(), indent=2, allow_nan=False),
        "```",
        "",
        "## Human decision history",
        "",
        "Exported actor identity is an assertion; digest integrity does not authenticate the reviewer.",
        "",
        "```json",
        json.dumps([d.model_dump() for d in decisions], indent=2, allow_nan=False),
        "```",
        "",
    ]
    return "\n".join(lines)
