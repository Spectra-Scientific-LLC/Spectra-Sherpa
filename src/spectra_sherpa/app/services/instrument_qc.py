"""Server-owned QC history, explicit custody, and stable point-in-time snapshots."""

from datetime import datetime, timezone
from typing import Literal

import numpy as np
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.instrument_qc import InstrumentQCRecord
from spectra_sherpa.sdk.instrument_qc import QCEvent, QCPolicy, evaluate_qc, instant, make_event
from spectra_sherpa.sdk.prediction_uncertainty import ClosedRecord


class QCRequest(ClosedRecord):
    event_id: str = Field(min_length=1, max_length=100)
    expected_last_event_digest: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    kind: Literal["policy", "control", "maintenance", "recovery", "revalidation"]
    occurred_at: str
    payload: dict


class ControlInput(ClosedRecord):
    policy_digest: str = Field(pattern="^[a-f0-9]{64}$")
    control_material_id: str = Field(min_length=1, max_length=200)
    control_material_lot: str = Field(min_length=1, max_length=200)
    measured_values: list[float] = Field(min_length=1, max_length=256)
    source_evidence_digest: str = Field(pattern="^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=2000)


class MaintenanceInput(ClosedRecord):
    instrument_id: str = Field(min_length=1, max_length=200)
    acquisition_configuration_digest: str = Field(pattern="^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=2000)


class RecoveryInput(ClosedRecord):
    policy_digest: str = Field(pattern="^[a-f0-9]{64}$")
    failed_event_id: str = Field(min_length=1, max_length=100)
    passing_event_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)


class RevalidationInput(ClosedRecord):
    policy_digest: str = Field(pattern="^[a-f0-9]{64}$")
    maintenance_event_id: str = Field(min_length=1, max_length=100)
    dossier_digest: str = Field(pattern="^[a-f0-9]{64}$")
    accepted_decision_digest: str = Field(pattern="^[a-f0-9]{64}$")
    validation_collection_started_at: str
    validation_collection_ended_at: str
    independent_new_validation_declared: Literal[True]
    reason: str = Field(min_length=1, max_length=2000)


async def qc_events(session: AsyncSession, watch_id: int, user_id: int) -> list[QCEvent]:
    rows = (
        await session.scalars(
            select(InstrumentQCRecord)
            .where(InstrumentQCRecord.watch_id == watch_id, InstrumentQCRecord.user_id == user_id)
            .order_by(InstrumentQCRecord.sequence)
        )
    ).all()
    return [QCEvent.model_validate(row.payload) for row in rows]


async def qc_qualification_state(session: AsyncSession, watch, events: list[QCEvent], evaluated_at: str) -> dict:
    from spectra_sherpa.app.models.analytical_qualification import AnalyticalQualificationRecord
    from spectra_sherpa.sdk.analytical_qualification import QualificationDecision

    events = [
        event
        for event in events
        if instant(event.recorded_at) <= instant(evaluated_at) and instant(event.occurred_at) <= instant(evaluated_at)
    ]
    dossiers = {event.payload["dossier_digest"] for event in events if event.kind == "revalidation"}
    if not dossiers:
        return {}
    rows = (
        await session.scalars(
            select(AnalyticalQualificationRecord)
            .where(
                AnalyticalQualificationRecord.user_id == watch.user_id,
                AnalyticalQualificationRecord.workflow_id == watch.workflow_id,
                AnalyticalQualificationRecord.kind == "decision",
                AnalyticalQualificationRecord.parent_digest.in_(dossiers),
            )
            .order_by(AnalyticalQualificationRecord.id)
        )
    ).all()
    latest = {}
    for row in rows:
        decision = QualificationDecision.model_validate(row.payload)
        if instant(decision.recorded_at) <= instant(evaluated_at):
            latest[row.parent_digest] = row
    result = {}
    for event in events:
        if event.kind != "revalidation":
            continue
        row = latest.get(event.payload["dossier_digest"])
        result[event.event_id] = {
            "current_acceptance": bool(
                row
                and row.record_digest == event.payload["accepted_decision_digest"]
                and row.payload["decision"] == "accepted_under_declared_policy"
            ),
            "latest_decision": row.payload if row else None,
            "scope": "Latest server-retained decision known at evaluation time supersedes earlier decisions",
        }
    return result


async def qc_snapshot(session: AsyncSession, watch, binding, *, evaluated_at: str | None = None) -> dict:
    evaluated_at = evaluated_at or datetime.now(timezone.utc).isoformat()
    events = await qc_events(session, watch.id, watch.user_id)
    return evaluate_qc(
        events,
        evaluated_at=evaluated_at,
        qualification_state=await qc_qualification_state(session, watch, events, evaluated_at),
        artifact_digest=binding.canonical_read_grant.artifact_digest if binding.canonical_read_grant else None,
        application_plan_digest=binding.canonical_plan_digest,
    )


async def append_qc_event(session: AsyncSession, watch, binding, request: QCRequest, *, recorded_at: str) -> QCEvent:
    events = await qc_events(session, watch.id, watch.user_id)
    if request.expected_last_event_digest != (events[-1].event_digest if events else None):
        raise ValueError("QC history changed; refresh before appending evidence")
    if any(event.event_id == request.event_id for event in events):
        raise ValueError("QC event ID is already recorded; retained observations cannot be overwritten")
    if instant(request.occurred_at) > instant(recorded_at):
        raise ValueError("future-dated QC events are refused")
    policies = [event for event in events if event.kind == "policy"]
    policy = QCPolicy.model_validate(policies[-1].payload) if policies else None
    if request.kind == "policy":
        policy = QCPolicy.model_validate(request.payload)
        if (
            not binding.canonical_read_grant
            or policy.artifact_digest != binding.canonical_read_grant.artifact_digest
            or policy.application_plan_digest != binding.canonical_plan_digest
        ):
            raise ValueError("QC policy must bind this exact canonical application")
        from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
        from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime

        plan = binding.canonical_application_plan
        node = next(node for node in plan["nodes"] if node["node_id"] == plan["model_node_id"])
        if node["application_operation_id"] != "model.apply_fitted_pls":
            raise ValueError("QC currently supports canonical PLS applications")
        runtime = build_application_execution_runtime(canonical_artifact_read_grant=binding.canonical_read_grant)
        authority = node["artifact_binding"]
        state = runtime.canonical_artifact_reader.load_bound_state(
            authority,
            expected_source_contract_digest=authority["source_contract_digest"],
            expected_serializer=authority["serializer"],
        )
        state = FittedPLSV2Node("qc-policy-authority", {}).validate_fitted_state(state)
        if policy.reference_method.response_identity.model_dump() != state["response_identity"]:
            raise ValueError("QC response authority differs from the fitted model")
        payload = policy.model_dump()
    else:
        if policy is None:
            raise ValueError("Declare a QC policy before recording observations or maintenance")
        model: type[ClosedRecord] = {
            "control": ControlInput,
            "maintenance": MaintenanceInput,
            "recovery": RecoveryInput,
            "revalidation": RevalidationInput,
        }[request.kind]
        payload = model.model_validate(request.payload).model_dump()
        if request.kind != "maintenance" and payload["policy_digest"] != policy.policy_digest:
            raise ValueError("QC event must name the current declared policy")
        if request.kind == "control":
            if (
                payload["control_material_id"] != policy.control_material_id
                or payload["control_material_lot"] != policy.control_material_lot
            ):
                raise ValueError("QC control material or lot differs from the current policy")
            if (
                len(payload["measured_values"]) != len(policy.assigned_values)
                or not np.isfinite(payload["measured_values"]).all()
            ):
                raise ValueError("QC measured response values are invalid")
        elif request.kind == "recovery":
            selected = {event.event_id: event for event in events if event.kind == "control"}
            if payload["failed_event_id"] not in selected or payload["passing_event_id"] not in selected:
                raise ValueError("Recovery requires retained failed and passing control identities")
            failed, passing = selected[payload["failed_event_id"]], selected[payload["passing_event_id"]]
            all_policies = {
                QCPolicy.model_validate(item.payload).policy_digest: QCPolicy.model_validate(item.payload)
                for item in policies
            }

            def within(event):
                original = all_policies[event.payload["policy_digest"]]
                return bool(
                    np.all(
                        np.abs(np.asarray(event.payload["measured_values"]) - original.assigned_values)
                        <= original.absolute_residual_limits
                    )
                ) and instant(event.occurred_at) < instant(original.control_material_expires_at)

            if passing.payload["policy_digest"] != policy.policy_digest:
                raise ValueError("Recovery needs a fresh passing control under the current policy")
            if (
                within(failed)
                or not within(passing)
                or instant(passing.occurred_at) <= instant(failed.occurred_at)
                or instant(request.occurred_at) < instant(passing.occurred_at)
            ):
                raise ValueError("Recovery requires a genuinely failed control followed by a new passing control")
        elif request.kind == "revalidation":
            from spectra_sherpa.app.models.analytical_qualification import AnalyticalQualificationRecord
            from spectra_sherpa.sdk.analytical_qualification import QualificationDecision, QualificationDossier

            maintenance = next(
                (
                    event
                    for event in events
                    if event.kind == "maintenance" and event.event_id == payload["maintenance_event_id"]
                ),
                None,
            )
            if maintenance is None:
                raise ValueError("Revalidation requires retained maintenance identity")
            start, end = instant(payload["validation_collection_started_at"]), instant(
                payload["validation_collection_ended_at"]
            )
            if (
                not instant(maintenance.occurred_at)
                < start
                <= end
                <= instant(request.occurred_at)
                <= instant(recorded_at)
            ):
                raise ValueError("New validation specimens must be collected after maintenance and before recording")
            rows = (
                await session.scalars(
                    select(AnalyticalQualificationRecord).where(
                        AnalyticalQualificationRecord.user_id == watch.user_id,
                        AnalyticalQualificationRecord.workflow_id == watch.workflow_id,
                        AnalyticalQualificationRecord.record_digest.in_(
                            [payload["dossier_digest"], payload["accepted_decision_digest"]]
                        ),
                    )
                )
            ).all()
            assessment = next((row for row in rows if row.kind == "assessment"), None)
            decision_row = next((row for row in rows if row.kind == "decision"), None)
            if assessment is None or decision_row is None:
                raise ValueError("Revalidation requires a server-retained assessment and accepted decision")
            dossier = QualificationDossier.load(assessment.payload)
            decision = QualificationDecision.model_validate(decision_row.payload)
            latest_decision = await session.scalar(
                select(AnalyticalQualificationRecord)
                .where(
                    AnalyticalQualificationRecord.user_id == watch.user_id,
                    AnalyticalQualificationRecord.workflow_id == watch.workflow_id,
                    AnalyticalQualificationRecord.kind == "decision",
                    AnalyticalQualificationRecord.parent_digest == dossier.record_digest,
                )
                .order_by(AnalyticalQualificationRecord.id.desc())
                .limit(1)
            )
            if latest_decision is None or latest_decision.record_digest != decision.decision_digest:
                raise ValueError("Revalidation must use the latest qualification decision, not superseded acceptance")
            assessment_time = assessment.created_at
            if assessment_time.tzinfo is None:
                assessment_time = assessment_time.replace(tzinfo=timezone.utc)
            if assessment_time <= instant(maintenance.recorded_at) or assessment_time < end:
                raise ValueError("An old assessment accepted after maintenance is not new validation")
            if (
                decision.decision != "accepted_under_declared_policy"
                or decision.dossier_digest != dossier.record_digest
                or dossier.assessment != "criteria_met"
            ):
                raise ValueError("Revalidation requires acceptance of this successful dossier")
            if (
                dossier.context.instrument_id != policy.instrument_id
                or dossier.context.acquisition_configuration_digest != policy.acquisition_configuration_digest
                or dossier.context.reference_method != policy.reference_method
            ):
                raise ValueError("Revalidation instrument, acquisition or reference authority differs")
            dossier.assert_application(
                artifact_digest=policy.artifact_digest,
                application_plan_digest=policy.application_plan_digest,
                context=dossier.context,
            )
            payload["assessment_recorded_at"] = assessment_time.isoformat()
            payload["validation_cohort_digest"] = dossier.cohort_digest
            payload["collection_time_authority"] = "operator declaration bound to this newly computed cohort"
    event = make_event(
        event_id=request.event_id,
        kind=request.kind,
        occurred_at=request.occurred_at,
        recorded_at=recorded_at,
        actor=f"user:{watch.user_id}",
        payload=payload,
    )
    # Evaluate before persisting, so an invalid event cannot poison history.
    evaluate_qc(
        [*events, event],
        evaluated_at=recorded_at,
        artifact_digest=binding.canonical_read_grant.artifact_digest if binding.canonical_read_grant else None,
        application_plan_digest=binding.canonical_plan_digest,
    )
    session.add(
        InstrumentQCRecord(
            watch_id=watch.id,
            user_id=watch.user_id,
            sequence=len(events) + 1,
            event_id=event.event_id,
            payload=event.model_dump(),
        )
    )
    return event
