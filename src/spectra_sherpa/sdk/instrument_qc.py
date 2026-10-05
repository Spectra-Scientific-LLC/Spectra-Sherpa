"""Report-only instrument control evidence; never statistical certification or a run gate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import numpy as np
from pydantic import Field, model_validator

from .prediction_uncertainty import ClosedRecord, ReferenceMethod, _digest


def instant(value: str) -> datetime:
    """Parse a timezone-aware event instant and normalize it to UTC."""

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("QC timestamps require a timezone")
    return parsed.astimezone(timezone.utc)


class QCPolicy(ClosedRecord):
    """Operator-declared control limits and freshness rules; report-only authority."""

    schema_version: Literal["spectrasherpa.instrument-qc-policy/1"]
    policy_name: str = Field(min_length=1, max_length=200)
    policy_version: str = Field(min_length=1, max_length=100)
    artifact_digest: str = Field(pattern="^[a-f0-9]{64}$")
    application_plan_digest: str = Field(pattern="^[a-f0-9]{64}$")
    instrument_id: str = Field(min_length=1, max_length=200)
    acquisition_configuration_digest: str = Field(pattern="^[a-f0-9]{64}$")
    control_material_id: str = Field(min_length=1, max_length=200)
    control_material_lot: str = Field(min_length=1, max_length=200)
    control_material_expires_at: str
    reference_method: ReferenceMethod
    assigned_values: list[float] = Field(min_length=1, max_length=256)
    absolute_residual_limits: list[float] = Field(min_length=1, max_length=256)
    maximum_control_age_seconds: int = Field(gt=0, le=31536000)
    aggregation: Literal["single_observation_no_aggregation"]
    recovery: Literal["new_passing_control_and_explicit_acknowledgement"]
    action: Literal["report_only"]

    @model_validator(mode="after")
    def authority(self):
        instant(self.control_material_expires_at)
        units = self.reference_method.response_identity.units
        if any(unit is None for unit in units):
            raise ValueError("QC requires declared response units")
        if len(self.assigned_values) != len(units) or len(self.absolute_residual_limits) != len(units):
            raise ValueError("QC assigned values and limits must match response authority")
        if not np.isfinite(self.assigned_values).all() or not np.isfinite(self.absolute_residual_limits).all():
            raise ValueError("QC values and limits must be finite")
        if any(value <= 0 for value in self.absolute_residual_limits):
            raise ValueError("QC residual limits must be positive")
        return self

    @property
    def policy_digest(self) -> str:
        return _digest(self.model_dump())


class QCEvent(ClosedRecord):
    """Timestamped immutable control or maintenance evidence with digest integrity."""

    schema_version: Literal["spectrasherpa.instrument-qc-event/1"]
    event_id: str = Field(min_length=1, max_length=100)
    kind: Literal["policy", "control", "maintenance", "recovery", "revalidation"]
    occurred_at: str
    recorded_at: str
    actor: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any]
    event_digest: str = Field(pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def integrity(self):
        if instant(self.occurred_at) > instant(self.recorded_at):
            raise ValueError("future-dated QC events are refused")
        if self.event_digest != _digest(self.model_dump(exclude={"event_digest"})):
            raise ValueError("QC event integrity mismatch")
        return self


def make_event(
    *, event_id: str, kind: str, occurred_at: str, recorded_at: str, actor: str, payload: dict[str, Any]
) -> QCEvent:
    """Create a digest-bound event without claiming authenticated laboratory approval."""

    body = dict(
        schema_version="spectrasherpa.instrument-qc-event/1",
        event_id=event_id,
        kind=kind,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        actor=actor,
        payload=payload,
    )
    return QCEvent.model_validate({**body, "event_digest": _digest(body)})


def evaluate_qc(
    events: list[QCEvent],
    *,
    evaluated_at: str,
    artifact_digest: str | None,
    application_plan_digest: str | None,
    qualification_state: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Evaluate only evidence known by the stated time; preserve all concurrent reasons.

    API-owned events establish local authorship. Imported event digests establish
    integrity only. This evaluator does not authenticate an exported history.
    """
    now = instant(evaluated_at)
    known = [event for event in events if instant(event.recorded_at) <= now and instant(event.occurred_at) <= now]
    # Input order is the authoritative append sequence, including equal timestamps.
    if len({event.event_id for event in known}) != len(known):
        raise ValueError("QC event IDs must be unique")
    policies = [event for event in known if event.kind == "policy"]
    reasons: list[str] = []
    calculation: dict[str, Any] = {}
    policy = None
    if not policies:
        reasons.append("no_declared_qc_policy")
    else:
        policy = QCPolicy.model_validate(policies[-1].payload)
        if policy.artifact_digest != artifact_digest or policy.application_plan_digest != application_plan_digest:
            reasons.append("model_or_application_changed")
        if now >= instant(policy.control_material_expires_at):
            reasons.append("control_material_expired")
        controls = [
            event
            for event in known
            if event.kind == "control" and event.payload.get("policy_digest") == policy.policy_digest
        ]
        controls.sort(key=lambda event: (instant(event.occurred_at), instant(event.recorded_at)))
        policies_by_digest = {
            QCPolicy.model_validate(item.payload).policy_digest: QCPolicy.model_validate(item.payload)
            for item in policies
        }
        failures: list[QCEvent] = []
        passing: list[QCEvent] = []
        all_controls = [item for item in known if item.kind == "control"]
        for event in all_controls:
            control_policy = policies_by_digest.get(event.payload.get("policy_digest"))
            if control_policy is None:
                raise ValueError("QC observation refers to unavailable policy authority")
            measured = np.asarray(event.payload["measured_values"], dtype=float)
            if measured.shape != (len(control_policy.assigned_values),) or not np.isfinite(measured).all():
                raise ValueError("QC observation has invalid response dimensions or nonfinite values")
            valid_material = (
                event.payload["control_material_id"] == control_policy.control_material_id
                and event.payload["control_material_lot"] == control_policy.control_material_lot
                and instant(event.occurred_at) < instant(control_policy.control_material_expires_at)
            )
            residual = measured - np.asarray(control_policy.assigned_values)
            if not np.isfinite(residual).all():
                raise ValueError("QC residual is not representable as a finite value")
            # Equality is within the declared tolerance. No replicate averaging.
            within = valid_material and bool(np.all(np.abs(residual) <= control_policy.absolute_residual_limits))
            (passing if within else failures).append(event)
            if controls and event is controls[-1]:
                calculation.update(
                    latest_control_id=event.event_id,
                    observed_at=event.occurred_at,
                    recorded_at=event.recorded_at,
                    residuals=residual.tolist(),
                    within_declared_tolerances=within,
                    due_at=(
                        instant(event.occurred_at) + timedelta(seconds=policy.maximum_control_age_seconds)
                    ).isoformat(),
                )
        if not controls:
            reasons.append("missing_control_observation")
        elif now >= instant(controls[-1].occurred_at) + timedelta(seconds=policy.maximum_control_age_seconds):
            reasons.append("control_overdue")
        unresolved = []
        for failure in failures:
            recovered = any(
                event.kind == "recovery"
                and event.payload.get("policy_digest") in policies_by_digest
                and event.payload.get("failed_event_id") == failure.event_id
                and any(
                    control.event_id == event.payload.get("passing_event_id")
                    and control.payload.get("policy_digest") == event.payload.get("policy_digest")
                    and instant(control.occurred_at) > instant(failure.occurred_at)
                    and instant(control.recorded_at) <= instant(event.recorded_at)
                    for control in passing
                )
                for event in known
            )
            if not recovered:
                unresolved.append(failure.event_id)
        if unresolved:
            reasons.append("unacknowledged_control_failure")
        calculation["unresolved_failure_ids"] = unresolved
        maintenance = [event for event in known if event.kind == "maintenance"]
        if maintenance:
            latest = max(
                enumerate(maintenance),
                key=lambda item: (instant(item[1].occurred_at), instant(item[1].recorded_at), item[0]),
            )[1]
            if (
                latest.payload["instrument_id"] != policy.instrument_id
                or latest.payload["acquisition_configuration_digest"] != policy.acquisition_configuration_digest
            ):
                reasons.append("maintenance_configuration_differs")
            revalidations = [
                event
                for event in known
                if event.kind == "revalidation"
                and event.payload.get("policy_digest") == policy.policy_digest
                and event.payload.get("maintenance_event_id") == latest.event_id
                and instant(event.payload["validation_collection_started_at"]) > instant(latest.occurred_at)
                and instant(event.payload["assessment_recorded_at"]) > instant(latest.recorded_at)
                and (qualification_state or {}).get(event.event_id, {}).get("current_acceptance") is True
            ]
            if not revalidations:
                reasons.append("maintenance_requires_new_validation")
            if not any(
                instant(control.occurred_at) > instant(latest.occurred_at)
                and control.payload.get("policy_digest") == policy.policy_digest
                for control in passing
            ):
                reasons.append("maintenance_requires_fresh_control")
            calculation["maintenance_event_id"] = latest.event_id
            calculation["revalidation_event_ids"] = [event.event_id for event in revalidations]
    payload = {
        "schema_version": "spectrasherpa.instrument-qc-status/1",
        "evaluated_at": evaluated_at,
        "action": "report_only",
        "predictions_held": False,
        "status": "attention_required" if reasons else "within_declared_limits",
        "reasons": reasons,
        "policy": policy.model_dump() if policy else None,
        "policy_digest": policy.policy_digest if policy else None,
        "artifact_digest": artifact_digest,
        "application_plan_digest": application_plan_digest,
        "qualification_state": qualification_state or {},
        "event_ids": [event.event_id for event in known],
        "events": [event.model_dump() for event in known],
        "calculation": calculation,
        "scope": "Evidence known at this evaluation time; later submissions do not rewrite retained snapshots",
        "limitations": [
            "Operator-declared material, measurements and instrument authority",
            "Absolute tolerances are not statistical process control or proof of drift absence",
            "No attribution of a control failure to the instrument; no automatic slope/bias correction",
            "Imported history does not authenticate laboratory approval",
        ],
    }
    return {**payload, "snapshot_digest": _digest(payload)}
