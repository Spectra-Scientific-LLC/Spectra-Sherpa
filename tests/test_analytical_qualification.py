"""Separate intended-use evidence from deployment and retention readiness."""

import numpy as np
import pytest

from spectra_sherpa.sdk.analytical_qualification import (
    QualificationContext,
    QualificationDossier,
    QualificationPolicy,
    decide_qualification,
    qualify_application,
)
from tests.test_campaign_folder_watch import campaign as imported_campaign
from tests.test_canonical_project_import import _PACKAGE
from tests.test_prediction_uncertainty import METHOD, dataset
from tests.test_prediction_uncertainty import runtime as uncertainty_runtime

runtime = uncertainty_runtime
campaign = imported_campaign


def policy(**changes):
    return QualificationPolicy.model_validate(
        {
            "schema_version": "spectrasherpa.declared-qualification-policy/1",
            "policy_name": "Synthetic test policy",
            "policy_version": "1",
            "minimum_independent_specimens": 20,
            "minimum_specimens_per_component": 5.0,
            "response_identity": METHOD["response_identity"],
            "responses": [
                {"max_rmsep": 2.0, "max_absolute_bias": 1.0, "intended_minimum": 2.0, "intended_maximum": 30.0}
            ],
            "require_reference_precision": False,
            "minimum_screening_available_fraction": 1.0,
            "bias_confidence_level": 0.95,
            "bootstrap_resamples": 200,
            "random_seed": 928,
            **changes,
        }
    )


def context(**changes):
    return QualificationContext.model_validate(
        {
            "intended_use": "Synthetic response prediction",
            "intended_population": "Synthetic linear spectra",
            "specimen_namespace": "validation-register",
            "reference_method": METHOD,
            "instrument_id": "synthetic-instrument",
            "acquisition_configuration_digest": "a" * 64,
            "domain_coverage_evidence_digest": "b" * 64,
            "policy_frozen_before_validation": True,
            "model_frozen_before_validation": True,
            "specimens_not_used_for_fit_selection_or_interval_calibration": True,
            "independent_specimen_sampling_declared": True,
            "sampling_design": "Separate independent specimens",
            "evaluation_role": "external_validation",
            **changes,
        }
    )


async def assess(runtime, source=None, *, package=_PACKAGE, **kwargs):
    source = dataset() if source is None else source
    return await qualify_application(
        package.application_plan,
        source,
        runtime=runtime,
        policy=kwargs.pop("policy", policy()),
        context=kwargs.pop("context", context()),
        specimen_ids=[f"validation-{i}" for i in range(len(source.X))],
        **kwargs,
    )


@pytest.mark.asyncio
async def test_frozen_validation_acceptance_and_roundtrip(runtime):
    record = await assess(runtime)
    assert record.assessment == "criteria_met"
    assert record.calculation["effective_fitted_components"] >= 1
    assert not record.calculation["component_count_is_statistical_dof"]
    reopened = QualificationDossier.load(record.canonical_bytes())
    assert reopened.model_dump() == record.model_dump()
    with pytest.raises(ValueError, match="imported assessment"):
        decide_qualification(
            reopened, decision="accepted_under_declared_policy", actor="reviewer", recorded_at="now", reason="import"
        )
    decision = decide_qualification(
        record,
        decision="accepted_under_declared_policy",
        actor="local reviewer",
        recorded_at="2026-09-28T00:00:00Z",
        reason="Reviewed assumptions and domain evidence",
    )
    assert decision.dossier_digest == record.record_digest
    assert decision.provenance == "operator_assertion"
    assert "No ASTM" in record.limitations[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"evaluation_role": "surrogate"},
        {"policy_frozen_before_validation": False},
        {"independent_specimen_sampling_declared": False},
        {"instrument_id": None},
        {"domain_coverage_evidence_digest": None},
    ],
)
async def test_unavailable_or_surrogate_evidence_cannot_be_accepted(runtime, changes):
    record = await assess(runtime, context=context(**changes))
    assert record.assessment != "criteria_met"
    with pytest.raises(ValueError, match="cannot accept"):
        decide_qualification(
            record, decision="accepted_under_declared_policy", actor="reviewer", recorded_at="now", reason="request"
        )


@pytest.mark.asyncio
async def test_practical_bias_equivalence_and_sample_sufficiency(runtime):
    biased = dataset()
    biased.target = biased.target + 2
    record = await assess(runtime, biased)
    criterion = next(c for c in record.criteria if c["name"] == "response_0_bias_equivalence")
    assert criterion["state"] == "not_met"
    assert record.assessment == "criteria_not_met"
    small = await assess(runtime, dataset(5))
    assert next(c for c in small.criteria if c["name"] == "specimen_count")["state"] == "not_met"


@pytest.mark.asyncio
async def test_explicit_missing_reference_accounting_and_unavailable_intervals(runtime):
    source = dataset()
    source.target[0] = np.nan
    with pytest.raises(ValueError, match="explicit"):
        await assess(runtime, source)
    record = await assess(
        runtime,
        source,
        allow_missing_reference_exclusion=True,
        policy=policy(minimum_interval_available_fraction=1.0, minimum_observed_interval_coverage=0.9),
    )
    assert record.calculation["source_rows"] == 30
    assert record.calculation["complete_rows"] == 29
    assert record.calculation["excluded_rows"] == 1
    assert next(c for c in record.criteria if c["name"] == "interval_availability")["state"] == "unavailable"


@pytest.mark.asyncio
async def test_changed_model_reference_or_population_invalidates_claim(runtime):
    record = await assess(runtime)
    record.assert_application(
        artifact_digest=record.artifact_digest,
        application_plan_digest=record.application_plan_digest,
        context=context(),
    )
    for changes in (
        {"intended_population": "Different fuels"},
        {"instrument_id": "replacement"},
        {"reference_method": {**METHOD, "version": "2"}},
    ):
        with pytest.raises(ValueError, match="stale"):
            record.assert_application(
                artifact_digest=record.artifact_digest,
                application_plan_digest=record.application_plan_digest,
                context=context(**changes),
            )
    with pytest.raises(ValueError, match="stale"):
        record.assert_application(
            artifact_digest="c" * 64, application_plan_digest=record.application_plan_digest, context=context()
        )
    tampered = record.model_dump()
    tampered["calculation"]["complete_rows"] = 1000
    with pytest.raises(ValueError, match="integrity"):
        QualificationDossier.load(tampered)


@pytest.mark.asyncio
async def test_invalid_nonfinite_is_not_silently_excluded(runtime):
    for source in (dataset(), dataset()):
        source.target[0] = np.nan
        source._X[0, 0] = np.inf
        with pytest.raises(ValueError, match="invalid"):
            await assess(runtime, source, allow_missing_reference_exclusion=True)
    source = dataset()
    source.target[0] = np.inf
    with pytest.raises(ValueError, match="invalid"):
        await assess(runtime, source, allow_missing_reference_exclusion=True)


@pytest.mark.asyncio
async def test_exclusion_receipt_retains_original_identity(runtime):
    source = dataset()
    source.target[3] = np.nan
    result = await assess(runtime, source, allow_missing_reference_exclusion=True)
    assert result.original_cohort_digest == source.scientific_digest
    assert result.exclusions == [
        {
            "original_row_index": 3,
            "specimen_id": "validation-3",
            "reason": "missing_reference",
            "missing_response_columns": [0],
        }
    ]


@pytest.mark.asyncio
async def test_forged_import_cannot_restore_computed_authority(runtime):
    record = await assess(runtime)
    imported = record.model_dump()
    imported["_computed_here"] = True
    with pytest.raises(ValueError):
        QualificationDossier.load(imported)


@pytest.mark.asyncio
async def test_server_history_decision_and_ownership(
    campaign, auth_client, test_session, test_user, tmp_path, monkeypatch
):
    from dataclasses import replace

    from sqlalchemy import select

    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis
    from spectra_sherpa.app.models.analytical_qualification import AnalyticalQualificationRecord
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.experiment_file import ExperimentFile
    from spectra_sherpa.app.models.user import User
    from spectra_sherpa.app.services import batch_predict, dataset_source_resolver

    imported, artifact, factory = campaign
    experiment = Experiment(
        user_id=test_user.id, project_id=imported.project_id, name="Validation", metadata_path="metadata.json"
    )
    test_session.add(experiment)
    await test_session.flush()
    directory = tmp_path / "experiments" / f"exp_{experiment.id:03d}"
    directory.mkdir(parents=True)
    (directory / "reference.csv").write_text("decoded fixture supplied after real source custody resolution\n")
    file = ExperimentFile(experiment_id=experiment.id, file_path="reference.csv", stage="raw")
    test_session.add(file)
    await test_session.commit()
    monkeypatch.setattr(dataset_source_resolver, "async_session", factory)
    monkeypatch.setattr(
        dataset_source_resolver, "settings", replace(dataset_source_resolver.settings, data_dir=tmp_path)
    )
    source = dataset()
    source.sample_axis = SampleAxis(labels=[f"validation-{i}" for i in range(30)])
    monkeypatch.setattr(batch_predict, "load_single_file", lambda *args, **kwargs: source)
    body = dict(
        canonical_artifact_id=artifact.id,
        experiment_id=experiment.id,
        file_id=file.id,
        policy=policy().model_dump(),
        context=context().model_dump(),
    )
    route = f"/api/v1/deploy/workflows/{imported.workflow_id}/qualification"
    candidates = await auth_client.get(f"/api/v1/deploy/projects/{imported.project_id}/qualification-applications")
    assert candidates.status_code == 200, candidates.text
    assert candidates.json()[0]["canonical_artifact_id"] == artifact.id
    unavailable = await auth_client.get("/api/v1/deploy/projects/999999/qualification-applications")
    assert unavailable.status_code == 404
    result = await auth_client.post(route, json=body)
    assert result.status_code == 201, result.text
    dossier = result.json()["dossier"]
    assert dossier["assessment"] == "criteria_met"
    decision = dict(
        dossier_digest=dossier["record_digest"],
        decision="accepted_under_declared_policy",
        reason="Reviewed declared use",
    )
    refusal = await auth_client.post(route + "/decisions", json=decision)
    assert refusal.status_code == 422, refusal.text
    decision["accepted_context_digest"] = result.json()["context_digest"]
    accepted = await auth_client.post(route + "/decisions", json=decision)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["decision"]["actor"] == f"user:{test_user.id}"
    second = await auth_client.post(route, json={**body, "context": context(instrument_id=None).model_dump()})
    assert second.status_code == 201, second.text
    failed = await auth_client.post(
        route + "/decisions",
        json={
            **decision,
            "dossier_digest": second.json()["dossier"]["record_digest"],
            "accepted_context_digest": second.json()["context_digest"],
        },
    )
    assert failed.status_code == 422, failed.text
    history = await auth_client.get(route)
    assert history.status_code == 200, history.text
    assert len(history.json()["records"]) == 3
    assert history.json()["records"][0]["payload"] == dossier
    # The same immutable scientific assessment can belong to two application
    # workflows; deduplication must never discard the second custody link.
    from spectra_sherpa.app.services.canonical_project_import import import_canonical_project

    second_import = await import_canonical_project(
        factory,
        user_id=test_user.id,
        archive=imported.canonical_archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact

    second_artifact = await test_session.scalar(
        select(CanonicalProjectArtifact).where(CanonicalProjectArtifact.workflow_id == second_import.workflow_id)
    )
    second_route = f"/api/v1/deploy/workflows/{second_import.workflow_id}/qualification"
    second_assessment = await auth_client.post(second_route, json={**body, "canonical_artifact_id": second_artifact.id})
    assert second_assessment.status_code == 201, second_assessment.text
    assert second_assessment.json()["dossier"]["record_digest"] == dossier["record_digest"]
    second_history = await auth_client.get(second_route)
    assert len(second_history.json()["records"]) == 1
    second_decision = await auth_client.post(second_route + "/decisions", json=decision)
    assert second_decision.status_code == 201, second_decision.text
    other = User(username="unrelated-qualification-owner")
    test_session.add(other)
    await test_session.flush()
    row = await test_session.scalar(
        select(AnalyticalQualificationRecord).where(
            AnalyticalQualificationRecord.record_digest == dossier["record_digest"],
            AnalyticalQualificationRecord.workflow_id == imported.workflow_id,
        )
    )
    row.user_id = other.id
    await test_session.commit()
    refused = await auth_client.post(route + "/decisions", json=decision)
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_interval_reference_and_calibration_separation(runtime):
    from tests.test_prediction_uncertainty import record as calibrate

    calibration = await calibrate(runtime)
    reused = await assess(runtime, uncertainty_record=calibration.model_dump())
    assert reused.assessment == "criteria_not_met"
    assert next(c for c in reused.criteria if c["name"] == "interval_calibration_separation")["state"] == "not_met"
    changed_method = {**METHOD, "version": "different-reference-method"}
    with pytest.raises(ValueError, match="reference method"):
        await assess(
            runtime, context=context(reference_method=changed_method), uncertainty_record=calibration.model_dump()
        )
    independent = await assess(runtime, source=dataset(31), uncertainty_record=calibration.model_dump())
    assert next(c for c in independent.criteria if c["name"] == "interval_calibration_separation")["state"] == "met"
    interval = independent.calculation["intervals"]
    assert interval["total_rows"] == 31
    assert interval["available_rows"] <= 31
    assert interval["population_coverage"] == "unavailable_when_intervals_are_screened"


@pytest.mark.asyncio
async def test_bootstrap_budget_refuses_without_silent_sampling(runtime):
    with pytest.raises(ValueError, match="20,000,000"):
        await assess(runtime, source=dataset(2100), policy=policy(bootstrap_resamples=10000))


@pytest.mark.asyncio
async def test_report_preserves_policy_context_and_decision(runtime):
    from spectra_sherpa.sdk.analytical_qualification import render_qualification_report

    dossier = await assess(runtime)
    decision = decide_qualification(
        dossier,
        decision="pending",
        actor="reviewer",
        recorded_at="2026-09-28T00:00:00Z",
        reason="Independent review pending",
    )
    report = render_qualification_report(QualificationDossier.load(dossier.canonical_bytes()), [decision])
    assert dossier.record_digest in report
    assert dossier.context.intended_population in report
    assert decision.reason in report
    assert "assertions" in report


def test_migration_preserves_existing_rows_and_workflow_scopes_history():
    import importlib

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = importlib.import_module("spectra_sherpa.alembic.versions.d3e5f7g9h131_qualification_history")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        for table in ("user", "workflow", "canonical_project_artifact"):
            connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql(f"INSERT INTO {table} VALUES (1), (2)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        table = sa.Table("analytical_qualification_record", sa.MetaData(), autoload_with=connection)
        for workflow in (1, 2):
            connection.execute(
                table.insert().values(
                    user_id=1,
                    workflow_id=workflow,
                    canonical_artifact_id=workflow,
                    record_digest="a" * 64,
                    kind="assessment",
                    payload={"retained": True},
                )
            )
        assert connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one() == 2
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert not sa.inspect(connection).has_table("analytical_qualification_record")
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM workflow").scalar_one() == 2
    engine.dispose()


@pytest.mark.asyncio
async def test_known_recorded_overlap_cannot_meet_declared_policy(runtime):
    record = await assess(
        runtime,
        independence_evidence={
            "schema_version": "spectrasherpa.recorded-independence/1",
            "populations": [
                {
                    "role": "fit",
                    "namespace": context().specimen_namespace,
                    "specimen_ids": ["validation-0"],
                    "source_description": "Calibration register",
                }
            ],
        },
    )
    assert record.assessment == "criteria_not_met"
    assert record.calculation["independence"]["known_specimen_overlap"]
    reloaded = QualificationDossier.load(record.model_dump())
    assert reloaded.calculation["independence"] == record.calculation["independence"]
