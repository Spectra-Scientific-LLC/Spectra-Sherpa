"""Declared tolerances, historical custody, and explicit maintenance recovery."""

from datetime import datetime, timedelta, timezone

import pytest

from spectra_sherpa.sdk.instrument_qc import QCPolicy, evaluate_qc, make_event
from tests.test_prediction_uncertainty import METHOD

BASE = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)


def time(seconds=0):
    return (BASE + timedelta(seconds=seconds)).isoformat()


def policy(**changes):
    return QCPolicy.model_validate(
        dict(
            schema_version="spectrasherpa.instrument-qc-policy/1",
            policy_name="Synthetic control",
            policy_version="1",
            artifact_digest="a" * 64,
            application_plan_digest="b" * 64,
            instrument_id="NIR-1",
            acquisition_configuration_digest="c" * 64,
            control_material_id="control",
            control_material_lot="lot-1",
            control_material_expires_at=time(10000),
            reference_method=METHOD,
            assigned_values=[10],
            absolute_residual_limits=[1],
            maximum_control_age_seconds=60,
            aggregation="single_observation_no_aggregation",
            recovery="new_passing_control_and_explicit_acknowledgement",
            action="report_only",
            **changes,
        )
    )


def event(kind, at, payload, *, key=None, recorded=None):
    return make_event(
        event_id=key or f"{kind}-{at}",
        kind=kind,
        occurred_at=time(at),
        recorded_at=time(at if recorded is None else recorded),
        actor="user:1",
        payload=payload,
    )


def control(p, at, value, **kwargs):
    return event(
        "control",
        at,
        dict(
            policy_digest=p.policy_digest,
            control_material_id=p.control_material_id,
            control_material_lot=p.control_material_lot,
            measured_values=[value],
            source_evidence_digest="d" * 64,
            reason="Independent control",
        ),
        **kwargs,
    )


def evaluate(events, at=30, **kwargs):
    return evaluate_qc(
        events,
        evaluated_at=time(at),
        artifact_digest=kwargs.get("artifact_digest", "a" * 64),
        application_plan_digest=kwargs.get("application_plan_digest", "b" * 64),
        qualification_state=kwargs.get("qualification_state"),
    )


def test_stable_control_equality_and_exact_overdue_boundary():
    p = policy()
    events = [event("policy", 0, p.model_dump()), control(p, 1, 11)]
    snapshot = evaluate(events, 60)
    assert snapshot["status"] == "within_declared_limits"
    assert snapshot["calculation"]["residuals"] == [1]
    assert snapshot["predictions_held"] is False
    assert evaluate(events, 61)["reasons"] == ["control_overdue"]


def test_missing_and_concurrent_failure_reasons_do_not_mask_each_other():
    assert evaluate([])["reasons"] == ["no_declared_qc_policy"]
    p = policy()
    base = event("policy", 0, p.model_dump())
    assert evaluate([base])["reasons"] == ["missing_control_observation"]
    snapshot = evaluate([base, control(p, 1, 12)], 10001, artifact_digest="e" * 64)
    assert set(snapshot["reasons"]) == {
        "model_or_application_changed",
        "control_material_expired",
        "control_overdue",
        "unacknowledged_control_failure",
    }


def test_failed_observation_latches_until_fresh_pass_and_acknowledgement():
    p = policy()
    failed = control(p, 1, 13)
    passed = control(p, 2, 10)
    events = [event("policy", 0, p.model_dump()), failed, passed]
    assert "unacknowledged_control_failure" in evaluate(events)["reasons"]
    ack = event(
        "recovery",
        3,
        dict(
            policy_digest=p.policy_digest,
            failed_event_id=failed.event_id,
            passing_event_id=passed.event_id,
            reason="Cause investigated; new control acceptable",
        ),
    )
    result = evaluate([*events, ack])
    assert result["status"] == "within_declared_limits"
    assert failed.event_id in result["event_ids"]


def test_future_refusal_late_submission_and_retained_time_cutoff():
    p = policy()
    base = event("policy", 0, p.model_dump())
    with pytest.raises(ValueError, match="future-dated"):
        control(p, 20, 10, recorded=10)
    late = control(p, 1, 10, recorded=90)
    before = evaluate([base], 30)
    assert evaluate([base, late], 30) == before
    assert "control_overdue" in evaluate([base, late], 90)["reasons"]
    with pytest.raises(ValueError, match="unique"):
        evaluate([base, base])


def test_maintenance_requires_new_validation_and_new_configuration_control():
    p = policy()
    maintenance = event(
        "maintenance", 3, dict(instrument_id="NIR-1", acquisition_configuration_digest="c" * 64, reason="Lamp replaced")
    )
    events = [event("policy", 0, p.model_dump()), control(p, 1, 10), maintenance]
    assert set(evaluate(events)["reasons"]) == {
        "maintenance_requires_new_validation",
        "maintenance_requires_fresh_control",
    }
    fresh = control(p, 4, 10)
    old = event(
        "revalidation",
        6,
        dict(
            policy_digest=p.policy_digest,
            maintenance_event_id=maintenance.event_id,
            validation_collection_started_at=time(1),
            assessment_recorded_at=time(5),
        ),
    )
    assert "maintenance_requires_new_validation" in evaluate([*events, fresh, old])["reasons"]
    new = event(
        "revalidation",
        7,
        dict(
            policy_digest=p.policy_digest,
            maintenance_event_id=maintenance.event_id,
            validation_collection_started_at=time(4),
            assessment_recorded_at=time(5),
        ),
    )
    assert (
        evaluate([*events, fresh, new], qualification_state={new.event_id: {"current_acceptance": True}})["status"]
        == "within_declared_limits"
    )
    changed = event(
        "maintenance",
        8,
        dict(instrument_id="NIR-1", acquisition_configuration_digest="e" * 64, reason="New configuration"),
    )
    assert "maintenance_configuration_differs" in evaluate([*events, fresh, new, changed])["reasons"]


def test_changed_lot_policy_and_restart_keep_original_evidence():
    from spectra_sherpa.sdk.instrument_qc import QCEvent

    p = policy()
    new = QCPolicy.model_validate({**p.model_dump(), "control_material_lot": "lot-2", "policy_version": "2"})
    events = [event("policy", 0, p.model_dump()), control(p, 1, 10), event("policy", 2, new.model_dump())]
    reopened = [QCEvent.model_validate(item.model_dump()) for item in events]
    snapshot = evaluate(reopened)
    assert snapshot["reasons"] == ["missing_control_observation"]
    assert len(snapshot["events"]) == 3
    assert snapshot["policy"]["control_material_lot"] == "lot-2"


def test_policy_transition_does_not_clear_old_failure_and_equal_times_preserve_append_order():
    p = policy()
    failed = control(p, 1, 15)
    new = QCPolicy.model_validate({**p.model_dump(), "policy_version": "2"})
    events = [
        event("policy", 0, p.model_dump(), key="z-first"),
        failed,
        event("policy", 2, new.model_dump(), key="z-second"),
        event("policy", 2, p.model_dump(), key="a-latest"),
        control(p, 3, 10),
    ]
    snapshot = evaluate(events)
    assert snapshot["policy_digest"] == p.policy_digest
    assert failed.event_id in snapshot["calculation"]["unresolved_failure_ids"]
    events = events[:3] + [control(new, 4, 10)]
    assert "unacknowledged_control_failure" in evaluate(events)["reasons"]
    ack = event(
        "recovery",
        5,
        dict(
            policy_digest=new.policy_digest,
            failed_event_id=failed.event_id,
            passing_event_id=events[-1].event_id,
            reason="Explicit policy-transition failure disposition",
        ),
    )
    assert evaluate([*events, ack])["status"] == "within_declared_limits"


@pytest.fixture
async def qc_watch(campaign, auth_client, tmp_path):
    imported, artifact, factory = campaign
    folder = tmp_path / "qc-incoming"
    folder.mkdir()
    result = await auth_client.post(
        "/api/v1/deploy/watches",
        json={
            "workflow_id": imported.workflow_id,
            "canonical_artifact_id": artifact.id,
            "name": "QC inference",
            "folder_path": str(folder),
            "file_pattern": "*.csv",
            "settle_time_seconds": 0,
        },
    )
    assert result.status_code == 201, result.text
    return result.json()["id"], imported, artifact, factory, folder


async def append(client, watch_id, kind, payload, *, event_id, occurred=None, expected=None):
    route = f"/api/v1/deploy/watches/{watch_id}/qc"
    if expected is None:
        expected = (await client.get(route)).json()["last_event_digest"]
    return await client.post(
        route,
        json={
            "event_id": event_id,
            "kind": kind,
            "occurred_at": occurred or (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            "expected_last_event_digest": expected,
            "payload": payload,
        },
    )


async def install_policy(client, watch_id, **changes):
    snapshot = (await client.get(f"/api/v1/deploy/watches/{watch_id}/qc")).json()["snapshot"]
    value = policy().model_dump()
    value.update(
        artifact_digest=snapshot["artifact_digest"],
        application_plan_digest=snapshot["application_plan_digest"],
        control_material_expires_at=(datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        **changes,
    )
    result = await append(client, watch_id, "policy", value, event_id="policy-initial")
    assert result.status_code == 201, result.text
    return QCPolicy.model_validate(value)


@pytest.mark.asyncio
async def test_server_custody_conflict_future_lot_and_report_only_watch(qc_watch, auth_client, test_session):
    watch_id, _, _, _, _ = qc_watch
    p = await install_policy(auth_client, watch_id)
    body = dict(
        policy_digest=p.policy_digest,
        control_material_id=p.control_material_id,
        control_material_lot=p.control_material_lot,
        measured_values=[10],
        source_evidence_digest="d" * 64,
        reason="Measured control",
    )
    route = f"/api/v1/deploy/watches/{watch_id}/qc"
    prior = (await auth_client.get(route)).json()["last_event_digest"]
    first = await append(auth_client, watch_id, "control", body, event_id="control-1")
    assert first.status_code == 201, first.text
    assert first.json()["watch_execution_changed"] is False
    duplicate = await append(auth_client, watch_id, "control", body, event_id="control-1")
    assert duplicate.status_code == 422
    conflict = await append(auth_client, watch_id, "control", body, event_id="concurrent", expected=prior)
    assert conflict.status_code == 422
    future = await append(
        auth_client,
        watch_id,
        "control",
        body,
        event_id="future",
        occurred=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    assert future.status_code == 422
    wrong_lot = await append(
        auth_client, watch_id, "control", {**body, "control_material_lot": "wrong"}, event_id="lot"
    )
    assert wrong_lot.status_code == 422
    history = (await auth_client.get(route)).json()
    assert history["snapshot"]["status"] == "within_declared_limits"
    assert len(history["events"]) == 2
    watch = (await auth_client.get(f"/api/v1/deploy/watches/{watch_id}")).json()
    from spectra_sherpa.app.models.folder_watch import FolderWatch

    stored = await test_session.get(FolderWatch, watch_id)
    await test_session.refresh(stored)
    assert stored.configuration_generation == 0
    assert watch["is_enabled"] is False
    missing = await auth_client.get("/api/v1/deploy/watches/999999/qc")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_real_watch_retains_start_snapshot_without_holding_predictions(
    qc_watch, auth_client, test_session, test_user, monkeypatch
):
    import numpy as np
    from sqlalchemy import select

    from spectra_sherpa.app.lib.export_artifact import build_export_artifact, materialize_export_artifact
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, SpectralAxis
    from spectra_sherpa.app.models.batch_prediction import BatchPrediction
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.models.folder_watch import FolderWatch
    from spectra_sherpa.app.services import folder_watch_service

    watch_id, _, _, factory, folder = qc_watch
    p = await install_policy(auth_client, watch_id)
    failed = await append(
        auth_client,
        watch_id,
        "control",
        dict(
            policy_digest=p.policy_digest,
            control_material_id=p.control_material_id,
            control_material_lot=p.control_material_lot,
            measured_values=[15],
            source_evidence_digest="d" * 64,
            reason="Out of tolerance",
        ),
        event_id="failed-control",
    )
    assert failed.status_code == 201, failed.text
    data = SherpaDataset(
        X=np.arange(160, 184, dtype=float).reshape(3, 8),
        feature_axis=SpectralAxis(values=np.arange(8, dtype=float), units="cm-1"),
        domain=DomainContext(measurement_mode="reflectance"),
    )
    materialize_export_artifact(build_export_artifact(data, filename="new.csv", format="csv"), folder)
    enabled = await auth_client.post(f"/api/v1/deploy/watches/{watch_id}/enable")
    assert enabled.status_code == 200, enabled.text
    monkeypatch.setattr(folder_watch_service, "async_session", factory)
    watch = await test_session.get(FolderWatch, watch_id)
    await test_session.refresh(watch)
    original_execute = folder_watch_service.execute_workflow_dataset

    async def execute_with_concurrent_qc(*args, **kwargs):
        concurrent = await append(
            auth_client,
            watch_id,
            "maintenance",
            dict(
                instrument_id="NIR-1", acquisition_configuration_digest="c" * 64, reason="Logged during batch execution"
            ),
            event_id="concurrent-maintenance",
        )
        assert concurrent.status_code == 201, concurrent.text
        return await original_execute(*args, **kwargs)

    monkeypatch.setattr(folder_watch_service, "execute_workflow_dataset", execute_with_concurrent_qc)
    await folder_watch_service.FolderWatchService()._process_watch(watch)
    await test_session.rollback()
    await test_session.refresh(test_user)
    run = await test_session.scalar(select(ExecutionRun).where(ExecutionRun.source_type == "folder_watch"))
    assert run is not None
    retained = run.source_metadata["instrument_qc"]
    assert retained["reasons"] == ["unacknowledged_control_failure"]
    assert retained["predictions_held"] is False
    assert "concurrent-maintenance" not in retained["event_ids"]
    predictions = (await test_session.scalars(select(BatchPrediction).where(BatchPrediction.run_id == run.id))).all()
    assert len(predictions) == 1
    assert predictions[0].status == "completed"
    later = await append(
        auth_client,
        watch_id,
        "maintenance",
        dict(instrument_id="NIR-1", acquisition_configuration_digest="c" * 64, reason="Lamp change"),
        event_id="later-maintenance",
    )
    assert later.status_code == 201, later.text
    await test_session.refresh(run)
    assert run.source_metadata["instrument_qc"] == retained
    refreshed = (await auth_client.get(f"/api/v1/deploy/watches/{watch_id}/qc")).json()["snapshot"]
    assert "maintenance_requires_new_validation" in refreshed["reasons"]
    assert retained["snapshot_digest"] != refreshed["snapshot_digest"]


@pytest.mark.asyncio
async def test_old_validation_and_superseded_acceptance_cannot_clear_maintenance(
    qc_watch, auth_client, test_session, test_user, runtime
):
    from spectra_sherpa.app.models.analytical_qualification import AnalyticalQualificationRecord
    from spectra_sherpa.sdk.analytical_qualification import decide_qualification
    from tests.test_analytical_qualification import assess, context
    from tests.test_prediction_uncertainty import dataset

    watch_id, imported, artifact, _, _ = qc_watch
    p = await install_policy(auth_client, watch_id)
    now = datetime.now(timezone.utc)
    maintenance = await append(
        auth_client,
        watch_id,
        "maintenance",
        dict(instrument_id="NIR-1", acquisition_configuration_digest="c" * 64, reason="Lamp replaced"),
        event_id="maintenance",
        occurred=(now - timedelta(seconds=90)).isoformat(),
    )
    assert maintenance.status_code == 201, maintenance.text
    fresh = await append(
        auth_client,
        watch_id,
        "control",
        dict(
            policy_digest=p.policy_digest,
            control_material_id=p.control_material_id,
            control_material_lot=p.control_material_lot,
            measured_values=[10],
            source_evidence_digest="d" * 64,
            reason="Post-maintenance check",
        ),
        event_id="fresh-control",
    )
    assert fresh.status_code == 201, fresh.text
    dossiers = []
    for count in (30, 31):
        dossier = await assess(
            runtime,
            source=dataset(count),
            package=imported.canonical_package,
            context=context(instrument_id="NIR-1", acquisition_configuration_digest="c" * 64),
        )
        assert dossier.assessment == "criteria_met"
        decision = decide_qualification(
            dossier,
            decision="accepted_under_declared_policy",
            actor=f"user:{test_user.id}",
            recorded_at=datetime.now(timezone.utc).isoformat(),
            reason="Reviewed new evidence",
        )
        created = now - timedelta(hours=1) if count == 30 else datetime.now(timezone.utc)
        test_session.add(
            AnalyticalQualificationRecord(
                user_id=test_user.id,
                workflow_id=imported.workflow_id,
                canonical_artifact_id=artifact.id,
                record_digest=dossier.record_digest,
                kind="assessment",
                payload=dossier.model_dump(),
                created_at=created,
            )
        )
        test_session.add(
            AnalyticalQualificationRecord(
                user_id=test_user.id,
                workflow_id=imported.workflow_id,
                canonical_artifact_id=artifact.id,
                record_digest=decision.decision_digest,
                parent_digest=dossier.record_digest,
                kind="decision",
                payload=decision.model_dump(),
                created_at=datetime.now(timezone.utc),
            )
        )
        await test_session.commit()
        body = dict(
            policy_digest=p.policy_digest,
            maintenance_event_id="maintenance",
            dossier_digest=dossier.record_digest,
            accepted_decision_digest=decision.decision_digest,
            validation_collection_started_at=(now - timedelta(seconds=60)).isoformat(),
            validation_collection_ended_at=(now - timedelta(seconds=30)).isoformat(),
            independent_new_validation_declared=True,
            reason="New validation after maintenance",
        )
        result = await append(auth_client, watch_id, "revalidation", body, event_id=f"revalidate-{count}")
        assert result.status_code == (422 if count == 30 else 201), result.text
        if count == 30:
            assert "old assessment" in result.text
        dossiers.append((dossier, decision, body))
    route = f"/api/v1/deploy/watches/{watch_id}/qc"
    before = (await auth_client.get(route)).json()["snapshot"]
    assert before["status"] == "within_declared_limits", before["reasons"]
    dossier, accepted, body = dossiers[-1]
    pending = decide_qualification(
        dossier,
        decision="pending",
        actor=f"user:{test_user.id}",
        recorded_at=datetime.now(timezone.utc).isoformat(),
        reason="New concern; acceptance suspended",
    )
    test_session.add(
        AnalyticalQualificationRecord(
            user_id=test_user.id,
            workflow_id=imported.workflow_id,
            canonical_artifact_id=artifact.id,
            record_digest=pending.decision_digest,
            parent_digest=dossier.record_digest,
            kind="decision",
            payload=pending.model_dump(),
            created_at=datetime.now(timezone.utc),
        )
    )
    await test_session.commit()
    after = (await auth_client.get(route)).json()["snapshot"]
    assert "maintenance_requires_new_validation" in after["reasons"]
    assert after["qualification_state"]["revalidate-31"]["latest_decision"]["decision"] == "pending"
    obsolete = await append(auth_client, watch_id, "revalidation", body, event_id="obsolete-acceptance")
    assert obsolete.status_code == 422
    assert "latest qualification decision" in obsolete.text
    assert before["status"] == "within_declared_limits"  # retained prior evaluation remains historical


from tests.test_campaign_folder_watch import campaign as imported_campaign
from tests.test_prediction_uncertainty import runtime as uncertainty_runtime

runtime = uncertainty_runtime
campaign = imported_campaign


def test_qc_migration_preserves_watch_and_enforces_append_sequence():
    import importlib

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = importlib.import_module("spectra_sherpa.alembic.versions.e4f6g8h0i232_instrument_qc_history")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE user (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE folder_watch (id INTEGER PRIMARY KEY, processed_files TEXT)")
        connection.exec_driver_sql("INSERT INTO user VALUES (1)")
        connection.exec_driver_sql("INSERT INTO folder_watch VALUES (1, 'retained')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        table = sa.Table("instrument_qc_record", sa.MetaData(), autoload_with=connection)
        connection.execute(table.insert().values(watch_id=1, user_id=1, sequence=1, event_id="first", payload={}))
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(
                table.insert().values(watch_id=1, user_id=1, sequence=1, event_id="concurrent", payload={})
            )
        assert connection.exec_driver_sql("SELECT processed_files FROM folder_watch").scalar_one() == "retained"
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert not sa.inspect(connection).has_table("instrument_qc_record")
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM folder_watch").scalar_one() == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_qc_cross_owner_and_wrong_model_policy_refused(qc_watch, auth_client, test_session):
    from spectra_sherpa.app.models.folder_watch import FolderWatch
    from spectra_sherpa.app.models.user import User

    watch_id, _, _, _, _ = qc_watch
    invalid = await append(auth_client, watch_id, "policy", policy().model_dump(), event_id="wrong-model")
    assert invalid.status_code == 422
    assert "exact canonical application" in invalid.text
    other = User(username="unrelated-qc-owner")
    test_session.add(other)
    await test_session.flush()
    watch = await test_session.get(FolderWatch, watch_id)
    watch.user_id = other.id
    await test_session.commit()
    refused = await auth_client.get(f"/api/v1/deploy/watches/{watch_id}/qc")
    assert refused.status_code == 404


def test_control_and_maintenance_timestamp_ties_use_append_order():
    p = policy()
    events = [event("policy", 0, p.model_dump()), control(p, 1, 10, key="z-first"), control(p, 1, 11, key="a-last")]
    assert evaluate(events)["calculation"]["latest_control_id"] == "a-last"
    events += [
        event(
            "maintenance",
            2,
            dict(instrument_id="NIR-1", acquisition_configuration_digest="c" * 64),
            key="z-maintenance",
        ),
        event(
            "maintenance",
            2,
            dict(instrument_id="NIR-1", acquisition_configuration_digest="e" * 64),
            key="a-maintenance",
        ),
    ]
    snapshot = evaluate(events)
    assert snapshot["calculation"]["maintenance_event_id"] == "a-maintenance"
    assert "maintenance_configuration_differs" in snapshot["reasons"]


@pytest.mark.asyncio
async def test_decision_cutoff_uses_precise_server_time_not_sqlite_timestamp(qc_watch, test_session, test_user):
    from spectra_sherpa.app.models.analytical_qualification import AnalyticalQualificationRecord
    from spectra_sherpa.app.models.folder_watch import FolderWatch
    from spectra_sherpa.app.services.instrument_qc import qc_qualification_state
    from spectra_sherpa.sdk.analytical_qualification import QualificationDecision
    from spectra_sherpa.sdk.prediction_uncertainty import _digest

    watch_id, imported, artifact, _, _ = qc_watch
    watch = await test_session.get(FolderWatch, watch_id)
    decisions = []
    for offset, state in ((0.1, "accepted_under_declared_policy"), (0.9, "pending")):
        body = dict(
            schema_version="spectrasherpa.qualification-decision/1",
            dossier_digest="d" * 64,
            decision=state,
            actor=f"user:{test_user.id}",
            recorded_at=time(offset),
            reason="Fractional-time review",
            provenance="operator_assertion",
        )
        decision = QualificationDecision.model_validate({**body, "decision_digest": _digest(body)})
        test_session.add(
            AnalyticalQualificationRecord(
                user_id=test_user.id,
                workflow_id=imported.workflow_id,
                canonical_artifact_id=artifact.id,
                record_digest=decision.decision_digest,
                parent_digest="d" * 64,
                kind="decision",
                payload=decision.model_dump(),
                created_at=BASE,
            )
        )
        decisions.append(decision)
    await test_session.commit()
    payload = dict(dossier_digest="d" * 64, accepted_decision_digest=decisions[0].decision_digest)
    early = event("revalidation", 0.15, payload, recorded=0.2, key="known")
    late = event("revalidation", 0.6, payload, recorded=0.7, key="later")
    before = await qc_qualification_state(test_session, watch, [early, late], time(0.5))
    assert set(before) == {"known"}
    assert before["known"]["current_acceptance"] is True
    after = await qc_qualification_state(test_session, watch, [early, late], time(0.95))
    assert after["known"]["current_acceptance"] is False
    assert after["later"]["current_acceptance"] is False
