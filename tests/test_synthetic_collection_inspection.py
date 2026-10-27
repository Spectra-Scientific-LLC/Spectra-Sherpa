"""Native FTIR responses stay inspectable without changing source custody."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from spectra_sherpa.app.api.v1.routes import datasets, experiments
from spectra_sherpa.app.contracts import demo_policy
from spectra_sherpa.app.lib.synthetic_references import load_synthetic_reference_as_sherpa


def _admit_collection(monkeypatch):
    monkeypatch.setattr(datasets, "_validated_collection_source_identity", lambda *_: (1, "a" * 64, {}))


def test_native_synthetic_response_table_preserves_values_units_and_scientific_identity(monkeypatch):
    _admit_collection(monkeypatch)
    dataset = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
    before = dataset.scientific_digest
    assert dataset.sample_axis.sample_table is None
    table = datasets._complete_collection_sample_table(dataset)
    assert table["row_count"] == 50
    assert table["columns"] == ["sample_id", *dataset.target_context.target_names]
    for index, name in enumerate(dataset.target_context.target_names):
        np.testing.assert_array_equal(table["sample_table"][name], dataset.target[:, index])
        assert table["column_units"][name] == "ppm"
    assert table["labels"] == dataset.sample_axis.labels
    assert dataset.scientific_digest == before
    assert dataset.sample_axis.sample_table is None


@pytest.mark.parametrize("damage", ["names", "duplicate", "conflict"])
def test_response_table_refuses_ambiguous_columns(monkeypatch, damage):
    _admit_collection(monkeypatch)
    dataset = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
    if damage == "names":
        dataset.target_context.target_names = ["one"]
    elif damage == "duplicate":
        dataset.target_context.target_names = ["one"] * 6
    else:
        axis = dataset.sample_axis
        axis.sample_table = {"Carbon dioxide": [999.0] * 50}
        dataset.sample_axis = axis
    with pytest.raises(ValueError, match="response"):
        datasets._complete_collection_sample_table(dataset)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["raw", "synthetic", "preprocessed"])
async def test_collection_definition_admits_the_inventory_stage(monkeypatch, stage):
    monkeypatch.setattr(experiments, "_require_experiment", AsyncMock(return_value=SimpleNamespace(project_id=134)))
    monkeypatch.setattr(experiments, "preferred_experiment_stage", AsyncMock(return_value=stage))
    monkeypatch.setattr(experiments, "read_collection_definition", lambda *_: None)
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(demo_policy, "require_trial_dataset_access", admission)
    session = object()
    receipt = await experiments.get_collection_definition_endpoint(201, session, SimpleNamespace(id=11))
    assert receipt.status == "absent"
    admission.assert_awaited_once_with(
        session=session,
        user_id=11,
        workflow_project_id=134,
        experiment_id=201,
        stage=stage,
        file_id=None,
        asset_id=None,
    )


@pytest.mark.parametrize("annotations", [False, True])
def test_missing_native_responses_stay_null_without_changing_science(monkeypatch, annotations):
    _admit_collection(monkeypatch)
    dataset = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
    dataset.target[1, 0] = np.nan
    if annotations:
        axis = dataset.sample_axis
        values = dataset.target[:, 0].tolist()
        values[1] = None
        axis.sample_table = {"Carbon dioxide": values}
        dataset.sample_axis = axis
    before = dataset.scientific_digest
    table = datasets._complete_collection_sample_table(dataset)
    assert table["sample_table"]["Carbon dioxide"][1] is None
    assert dataset.scientific_digest == before
    assert np.isnan(dataset.target[1, 0])


def test_infinite_native_response_is_not_treated_as_missing(monkeypatch):
    _admit_collection(monkeypatch)
    dataset = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
    dataset.target[1, 0] = np.inf
    with pytest.raises(ValueError):
        datasets._complete_collection_sample_table(dataset)


def test_response_width_refuses_before_scalar_conversion(monkeypatch):
    _admit_collection(monkeypatch)
    dataset = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
    monkeypatch.setattr(datasets, "_COLLECTION_SAMPLE_TABLE_MAX_COLUMNS", 6)

    def unexpected_scalar(_):
        pytest.fail("over-wide response must refuse before converting cells")

    monkeypatch.setattr(datasets, "_sample_table_scalar", unexpected_scalar)
    with pytest.raises(ValueError, match="1-6 columns"):
        datasets._complete_collection_sample_table(dataset)


def test_response_projection_stops_at_incremental_byte_budget(monkeypatch):
    _admit_collection(monkeypatch)
    dataset = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
    original = datasets._sample_table_scalar
    converted = []

    def counting_scalar(value):
        converted.append(value)
        return original(value)

    monkeypatch.setattr(datasets, "_sample_table_scalar", counting_scalar)
    monkeypatch.setattr(datasets, "_COLLECTION_SAMPLE_TABLE_MAX_JSON_BYTES", 5000)
    with pytest.raises(ValueError, match="4 MiB"):
        datasets._complete_collection_sample_table(dataset)
    assert len(converted) < 50 * 7


@pytest.mark.asyncio
async def test_imported_native_ftir_inspection_retrieves_complete_response_table(auth_client, test_session, test_user):
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.services.experiments import import_reference_dataset

    project = Project(user_id=test_user.id, name="FTIR table qualification", description="")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id, project_id=project.id, name="Synthetic_atmospheric-6", description="", metadata_path="{}"
    )
    test_session.add(experiment)
    await test_session.flush()
    await import_reference_dataset(test_session, experiment.id, "synthetic", "Synthetic_atmospheric-6")
    await test_session.commit()
    preview = await auth_client.post("/api/v1/builder/file-info", json={"experiment_id": experiment.id})
    assert preview.status_code == 200, preview.text
    wire = preview.json()
    handle = wire["metadata"]["api_serialization"]["full_dataset_handle"]
    assert handle
    response = await auth_client.get(f"/api/v1/datasets/{handle}/sample-table")
    assert response.status_code == 200, response.text
    table = response.json()
    assert table["row_count"] == 50
    assert len(table["columns"]) == 7
    assert table["column_units"] == {name: "ppm" for name in wire["target_context"]["target_names"]}
    expected = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
    for index, name in enumerate(expected.target_context.target_names):
        np.testing.assert_array_equal(table["sample_table"][name], expected.target[:, index])
