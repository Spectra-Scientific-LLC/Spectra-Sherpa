"""Availability must not require optional provenance or UI choice history."""

from types import SimpleNamespace

import pytest

from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.services import project_availability as availability


@pytest.mark.asyncio
async def test_uploaded_data_available_without_choices_and_is_project_scoped(
    auth_client, test_session, test_user, tmp_path, monkeypatch
):
    project = Project(user_id=test_user.id, name="Corn")
    empty = Project(user_id=test_user.id, name="Empty")
    test_session.add_all([project, empty])
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=project.id, name="Corn", metadata_path="metadata.json")
    test_session.add(experiment)
    await test_session.flush()
    source = tmp_path / "corn.csv"
    source.write_text("wavelength,intensity\n1000,0.5\n")
    test_session.add(ExperimentFile(experiment_id=experiment.id, file_path="corn.csv", stage="raw"))
    await test_session.commit()
    monkeypatch.setattr(availability, "experiment_dir", lambda _id: tmp_path)

    response = await auth_client.get(f"/api/v1/projects/{project.id}/provenance")
    assert response.status_code == 200
    records = {item["kind"]: item for item in response.json()["records"]}
    assert response.json()["choice_event_ids"] == {}  # No synthetic scientist choices.
    for kind in ("source", "dataset"):
        assert records[kind]["availability"]["state"] == "healthy"
        assert records[kind]["state"] == "missing"  # Not a provenance certification.
    response = await auth_client.get(f"/api/v1/projects/{empty.id}/provenance")
    assert all(item["availability"]["state"] == "missing" for item in response.json()["records"])

    source.unlink()
    records = {
        item["kind"]: item
        for item in (await auth_client.get(f"/api/v1/projects/{project.id}/provenance")).json()["records"]
    }
    assert records["source"]["availability"]["state"] == "faulty"
    assert records["dataset"]["availability"]["state"] == "healthy"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active,files_present,expected", [(True, True, "healthy"), (False, True, "faulty"), (True, False, "faulty")]
)
async def test_model_availability_does_not_require_training_selection_or_metadata(
    test_session, tmp_path, monkeypatch, active, files_present, expected
):
    if files_present:
        (tmp_path / "manifest.json").write_text("{}")
        (tmp_path / "arrays.npz").write_bytes(b"stored arrays")
    monkeypatch.setattr(
        availability, "get_model_store", lambda: SimpleNamespace(artifact_directory=lambda _uid: str(tmp_path))
    )
    records = {kind: {"record_id": None, "label": kind} for kind in ("campaign", "package")}
    result = await availability.project_availability(
        test_session,
        -1,
        run=SimpleNamespace(status="completed", environment_snapshot={"python": "3.12"}),
        model=SimpleNamespace(is_active=active, artifact_uid="model"),
        records=records,
    )
    assert result["model"]["state"] == expected
    assert result["run"]["state"] == "healthy"
    assert result["environment"]["state"] == "healthy"


@pytest.mark.asyncio
async def test_failed_run_is_operational_problem(test_session):
    records = {kind: {"record_id": None, "label": kind} for kind in ("campaign", "package")}
    result = await availability.project_availability(
        test_session, -1, run=SimpleNamespace(status="failed", environment_snapshot=None), model=None, records=records
    )
    assert result["run"]["state"] == "faulty"
    assert result["model"]["state"] == "missing"


def test_source_availability_is_confined_to_its_experiment(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    root.mkdir()
    (tmp_path / "outside.csv").write_text("private")
    monkeypatch.setattr(availability, "experiment_dir", lambda _id: root)
    assert not availability._source_readable(SimpleNamespace(experiment_id=1, file_path="../outside.csv"))
