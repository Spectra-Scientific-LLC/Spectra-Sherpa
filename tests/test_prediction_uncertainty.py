"""Model-bound conformal record, independent order statistics and portability."""

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.core.canonical_artifact import ReadOnlyCanonicalArtifactReader
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.sdk.canonical_application_execution import execute_canonical_application
from spectra_sherpa.sdk.prediction_uncertainty import (
    BoundPredictionUncertainty,
    ReferenceMethod,
    UncertaintyRecord,
    calibrate_prediction_intervals,
    reference_precision,
)
from tests.test_campaign_folder_watch import _EARLY_CANONICAL_PACKAGE
from tests.test_campaign_folder_watch import campaign as imported_campaign
from tests.test_canonical_project_import import _PACKAGE

campaign = imported_campaign

DECLARATIONS = dict(
    model_frozen_before_calibration=True, calibration_not_used_for_fit_or_selection=True, exchangeability_declared=True
)
METHOD = dict(
    method_id="synthetic-reference",
    version="1",
    response_identity={"names": None, "units": ["percent"]},
    measurement_basis="single_measurement",
    measurements_per_label=1,
    precision=None,
)


def dataset(n=30):
    # Same spectral manifold, disjoint specimens, explicitly measured-reference labels.
    x = np.linspace(4, 80, n)
    X = x[:, None] + np.arange(8)[None, :]
    return SherpaDataset(
        X=X,
        target=0.3 * X[:, 0] + 0.1 * X[:, 1] + np.linspace(-1, 1, n),
        feature_axis=SpectralAxis(values=np.arange(8, dtype=float), units="cm-1"),
        domain=DomainContext(technique="NIR", measurement_mode="reflectance"),
        target_context=TargetContext(target_type="continuous", target_units="percent"),
    )


@pytest.fixture
def runtime(tmp_path):
    root = tmp_path / "canonical"
    root.mkdir(mode=0o700)
    packages = (_PACKAGE, _EARLY_CANONICAL_PACKAGE)
    for package in packages:
        package.artifact.write_new(root / package.artifact.artifact_digest)
    return ExecutionRuntime(
        canonical_artifact_reader=ReadOnlyCanonicalArtifactReader(
            tmp_path, allowed_artifact_digests=tuple(p.artifact.artifact_digest for p in packages), artifact_root=root
        )
    )


async def record(runtime, source=None, *, package=_PACKAGE, **kwargs):
    source = dataset() if source is None else source
    return await calibrate_prediction_intervals(
        package.application_plan,
        source,
        runtime=runtime,
        specimen_ids=[f"cal-{i}" for i in range(len(source.X))],
        specimen_namespace="synthetic-specimens-v1",
        reference_method=METHOD,
        alpha=0.1,
        intended_population="Synthetic linear spectra",
        declarations=DECLARATIONS,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_independent_order_statistic_and_export_apply(runtime):
    ds = dataset()
    value = await record(runtime, ds)
    assert value.specimens == 30
    assert value.order_statistic_rank == 28
    assert value.widths[0] == pytest.approx(np.sort(np.abs(np.linspace(-1, 1, 30)))[27], abs=1e-10)
    reopened = UncertaintyRecord.load(value.canonical_bytes())
    result = await execute_canonical_application(
        _PACKAGE.application_plan,
        ds,
        runtime=runtime,
        uncertainty_record=reopened.model_dump(),
        uncertainty_population=reopened.intended_population,
    )
    output = result.output("model", "prediction_intervals")
    assert output["record_digest"] == value.record_digest
    assert output["membership_check"] == "not_verified"
    assert output["reference_method"]["precision"] is None
    rows = [r for r in output["rows"] if r["status"] == "available"]
    assert rows
    assert all(r["upper"][0] - r["lower"][0] == pytest.approx(2 * value.widths[0]) for r in rows)
    plain = await execute_canonical_application(_PACKAGE.application_plan, ds, runtime=runtime)
    assert plain.output("model", "prediction_intervals")["status"] == "point_only"


@pytest.mark.asyncio
async def test_duplicate_or_overlapping_specimens_refuse(runtime):
    with pytest.raises(ValueError, match="overlap"):
        await record(runtime, training_specimen_ids=["cal-1"])
    with pytest.raises(ValueError, match="insufficient"):
        await record(runtime, dataset(2))


@pytest.mark.asyncio
async def test_unit_and_missing_response_authority_refuse(runtime):
    ds = dataset()
    ds.target_context = TargetContext(target_type="continuous", target_units="fraction")
    with pytest.raises(ValueError, match="response authority"):
        await record(runtime, ds)
    ds = dataset()
    ds.target[0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        await record(runtime, ds)


def test_reference_precision_independent_pooled_calculation():
    values = np.array([[[1.0], [3.0]], [[4.0], [8.0]]])
    result = reference_precision(values)
    assert result["degrees_of_freedom"] == 2
    assert result["sd"][0] == pytest.approx(np.sqrt(5))
    assert ReferenceMethod.model_validate({**METHOD, "precision": result}).precision is not None
    with pytest.raises(ValueError, match="basis"):
        ReferenceMethod.model_validate({**METHOD, "measurement_basis": "replicate_mean"})


@pytest.mark.asyncio
async def test_tampering_and_wrong_pipeline_refuse(runtime):
    value = await record(runtime)
    tampered = value.model_dump()
    tampered["widths"] = [100.0]
    with pytest.raises(ValueError, match="integrity"):
        UncertaintyRecord.load(tampered)
    with pytest.raises(ValueError, match="pipeline"):
        BoundPredictionUncertainty.bind(
            value.model_copy(update={"application_plan_digest": "b" * 64}), _PACKAGE.application_plan
        )


@pytest.mark.parametrize("scale", [1e-200, 1e200])
def test_reference_precision_preserves_extreme_representable_magnitudes(scale):
    values = np.array([[[1.0], [3.0]], [[4.0], [8.0]]]) * scale
    sd = reference_precision(values)["sd"][0]
    assert sd / scale == pytest.approx(np.sqrt(5), rel=1e-14)


def test_reference_precision_opposite_extremes_and_large_offsets():
    assert reference_precision([[[-1e308], [1e308]]])["sd"][0] / 1e308 == pytest.approx(np.sqrt(2))
    offset = 1e200
    delta = np.spacing(offset)
    assert reference_precision([[[offset], [offset + 2 * delta]]])["sd"][0] / delta == pytest.approx(np.sqrt(2))
    assert reference_precision([[[offset], [offset]]])["sd"] == [0.0]
    with pytest.raises(ValueError, match="representable"):
        reference_precision([[[-1.7e308], [1.7e308]]])


@pytest.mark.asyncio
async def test_empty_training_identity_cannot_claim_disjointness(runtime):
    with pytest.raises(ValueError, match="unique nonempty"):
        await record(runtime, training_specimen_ids=[])


@pytest.mark.asyncio
@pytest.mark.parametrize("population", [None, "Different specimens"])
async def test_population_acceptance_is_required(runtime, population):
    value = await record(runtime)
    with pytest.raises(ValueError, match="acceptance"):
        await execute_canonical_application(
            _PACKAGE.application_plan,
            dataset(),
            runtime=runtime,
            uncertainty_record=value.model_dump(),
            uncertainty_population=population,
        )


@pytest.mark.asyncio
async def test_watch_persists_and_revalidates_population_declaration(
    campaign, runtime, auth_client, test_session, test_user, tmp_path, monkeypatch
):
    from spectra_sherpa.app.models.folder_watch import FolderWatch
    from spectra_sherpa.app.services.deployment_binding import resolve_deployment_binding

    imported, artifact, factory = campaign
    value = await record(runtime, package=imported.canonical_package)
    incoming = tmp_path / "uncertainty-incoming"
    incoming.mkdir()
    payload = dict(
        workflow_id=imported.workflow_id,
        canonical_artifact_id=artifact.id,
        name="Declared interval population",
        folder_path=str(incoming),
        uncertainty_record=value.model_dump(),
        file_pattern="*.csv",
        settle_time_seconds=0,
    )
    refused = await auth_client.post("/api/v1/deploy/watches", json=payload)
    assert refused.status_code == 422, refused.text
    payload["uncertainty_population"] = value.intended_population
    created = await auth_client.post("/api/v1/deploy/watches", json=payload)
    assert created.status_code == 201, created.text
    watch_id = created.json()["id"]
    test_session.expire_all()
    watch = await test_session.get(FolderWatch, watch_id)
    assert watch.uncertainty_population == value.intended_population
    assert watch.uncertainty_record == value.model_dump()
    binding = await resolve_deployment_binding(
        test_session,
        user_id=watch.user_id,
        workflow_id=watch.workflow_id,
        artifact_uid=None,
        canonical_artifact_id=watch.canonical_artifact_id,
        uncertainty_record=watch.uncertainty_record,
        uncertainty_population=watch.uncertainty_population,
    )
    assert binding.uncertainty_provider is not None
    await test_session.refresh(test_user)
    refused = await auth_client.patch(
        f"/api/v1/deploy/watches/{watch_id}", json={"uncertainty_population": "Different population"}
    )
    assert refused.status_code == 422, refused.text
    refused = await auth_client.patch(f"/api/v1/deploy/watches/{watch_id}", json={"uncertainty_record": None})
    assert refused.status_code == 422, refused.text
    # A fresh service executes through the real persisted folder-watch binding.
    from sqlalchemy import select

    from spectra_sherpa.app.lib.export_artifact import build_export_artifact, materialize_export_artifact
    from spectra_sherpa.app.models.batch_prediction import BatchPrediction
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.schemas.run_evidence import RunEvidence
    from spectra_sherpa.app.services import folder_watch_service
    from spectra_sherpa.app.services.run_output_retention import read_output

    source = dataset(12)
    source.target = None
    source.target_context = TargetContext()
    materialize_export_artifact(build_export_artifact(source, filename="incoming.csv", format="csv"), incoming)
    enabled = await auth_client.post(f"/api/v1/deploy/watches/{watch_id}/enable")
    assert enabled.status_code == 200, enabled.text
    monkeypatch.setattr(folder_watch_service, "async_session", factory)
    await test_session.refresh(watch)
    await folder_watch_service.FolderWatchService()._process_watch(watch)
    prediction = await test_session.scalar(select(BatchPrediction))
    assert prediction.status == "completed", prediction.error_message
    run = await test_session.get(ExecutionRun, prediction.run_id)
    outputs = RunEvidence.model_validate(run.evidence_completeness).outputs["file_0::model"]
    intervals = read_output(test_user.id, outputs["prediction_intervals"])
    assert intervals["record_digest"] == value.record_digest
    assert UncertaintyRecord.load(intervals["calibration_record"]) == value
    assert intervals["population_compatibility"] == "declared_by_operator_not_verified"
    assert len(intervals["rows"]) == 12
    assert intervals["prediction_identity"]["shape"] == [12, 1]
    disabled = await auth_client.post(f"/api/v1/deploy/watches/{watch_id}/disable")
    assert disabled.status_code == 200, disabled.text
    cleared = await auth_client.patch(
        f"/api/v1/deploy/watches/{watch_id}", json={"uncertainty_record": None, "uncertainty_population": None}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["uncertainty_record"] is None
    assert cleared.json()["uncertainty_population"] is None
    # Clearing mutable watch configuration must not erase earlier calibration authority.
    historical = read_output(test_user.id, outputs["prediction_intervals"])
    assert UncertaintyRecord.load(historical["calibration_record"]) == value
    assert historical["population_compatibility"] == "declared_by_operator_not_verified"


@pytest.mark.asyncio
async def test_untouched_synthetic_reference_population_coverage(runtime):
    # Fixed seed, independent errors and specimen rows. Coverage concerns the
    # full exchangeable population, not the subset passing global screening.
    rng = np.random.default_rng(19371)
    calibration = dataset(999)
    calibration.target = 0.3 * calibration.X[:, 0] + 0.1 * calibration.X[:, 1] + rng.normal(0.4, 1.0, 999)
    value = await record(runtime, calibration)
    future = dataset(10000)
    truth = 0.3 * future.X[:, 0] + 0.1 * future.X[:, 1] + rng.normal(0.4, 1.0, 10000)
    executed = await execute_canonical_application(_PACKAGE.application_plan, future, runtime=runtime)
    prediction = np.asarray(executed.output("model", "default")).reshape(-1)
    coverage = np.mean(np.abs(truth - prediction) <= value.widths[0])
    assert 0.87 < coverage < 0.94
    # Calibration error includes bias rather than silently centering it away.
    assert value.widths[0] > 1.5


@pytest.mark.asyncio
async def test_calibration_endpoint_executes_bound_pipeline_and_checks_source(
    campaign, auth_client, test_session, test_user, tmp_path, monkeypatch
):
    from dataclasses import replace

    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.experiment_file import ExperimentFile
    from spectra_sherpa.app.services import batch_predict, dataset_source_resolver

    imported, artifact, factory = campaign
    experiment = Experiment(
        user_id=test_user.id,
        project_id=imported.project_id,
        name="Independent calibration",
        metadata_path="metadata.json",
    )
    test_session.add(experiment)
    await test_session.flush()
    directory = tmp_path / "experiments" / f"exp_{experiment.id:03d}"
    directory.mkdir(parents=True)
    path = directory / "reference.csv"
    path.write_text("fixture read is substituted after real source custody resolution\n")
    file = ExperimentFile(experiment_id=experiment.id, file_path="reference.csv", stage="raw", file_type="csv")
    test_session.add(file)
    await test_session.commit()
    monkeypatch.setattr(dataset_source_resolver, "async_session", factory)
    monkeypatch.setattr(
        dataset_source_resolver, "settings", replace(dataset_source_resolver.settings, data_dir=tmp_path)
    )
    source = dataset()
    source.sample_axis = SampleAxis(labels=[f"independent-{i}" for i in range(30)])

    def load_file(selected, **kwargs):
        assert selected == path
        return source

    monkeypatch.setattr(batch_predict, "load_single_file", load_file)
    payload = dict(
        canonical_artifact_id=artifact.id,
        experiment_id=experiment.id,
        file_id=file.id,
        stage="raw",
        specimen_namespace="lab-register",
        reference_method_id="synthetic-reference",
        reference_method_version="1",
        measurement_basis="single_measurement",
        measurements_per_label=1,
        alpha=0.1,
        intended_population="Synthetic linear spectra",
        declarations=DECLARATIONS,
    )
    route = f"/api/v1/deploy/workflows/{imported.workflow_id}/uncertainty/calibrate"
    response = await auth_client.post(route, json=payload)
    assert response.status_code == 200, response.text
    record_value = UncertaintyRecord.load(response.json()["record"])
    assert record_value.specimens == 30
    assert record_value.artifact_digest == artifact.artifact_digest
    for changed, code in [
        ({"stage": "preprocessed"}, 422),
        ({"experiment_id": 999999}, 404),
        ({"file_id": 999999}, 422),
    ]:
        refused = await auth_client.post(route, json={**payload, **changed})
        assert refused.status_code == code, refused.text
    from spectra_sherpa.app.models.user import User

    other = User(username="unrelated-calibration-owner")
    test_session.add(other)
    await test_session.flush()
    experiment.user_id = other.id
    await test_session.commit()
    refused = await auth_client.post(route, json=payload)
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["outside_global_screen", "unavailable"])
async def test_no_intervals_for_outside_or_unavailable_screening(runtime, status):
    from copy import deepcopy

    value = await record(runtime)
    result = await execute_canonical_application(_PACKAGE.application_plan, dataset(), runtime=runtime)
    identity = result.output("model", "prediction_identity")
    screening = deepcopy(result.output("model", "applicability"))
    for row in screening["rows"]:
        row["screening_status"] = status
    provider = BoundPredictionUncertainty.bind(value, _PACKAGE.application_plan, value.intended_population)
    output = provider.apply(result.output("model", "default"), identity, screening)
    assert all(row["lower"] is None and row["upper"] is None for row in output["rows"])
    assert all(row["status"] == "unavailable_screening" for row in output["rows"])
    assert output["coverage_scope"].endswith("not_screen_conditional")
