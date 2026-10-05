"""Tests for experiment endpoints"""

from __future__ import annotations

import csv
import io
import stat
import zipfile
from pathlib import Path

import pytest
from httpx import AsyncClient

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, TargetContext
from spectra_sherpa.app.models.user import User

OPUS_FIXTURE = Path(__file__).parent / "fixtures" / "opus" / "openspecy-polystyrene.0"
OPEN_SPECY_OPUS_FIXTURE = Path(__file__).parent / "fixtures" / "opus" / "openspecy-polystyrene.0"


def _scientific_zip(members: list[tuple[str, bytes]]) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return payload.getvalue()


def test_library_import_defaults_to_widest_range_mode() -> None:
    from spectra_sherpa.app.api.v1.routes.datasets import LibraryImportRequest

    payload = LibraryImportRequest(experiment_id=1, library_ids=[1, 2])

    assert payload.range_mode == "widest"


@pytest.mark.asyncio
async def test_list_experiments_empty(client: AsyncClient):
    """Test listing experiments when none exist"""
    response = await client.get("/api/v1/experiments")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_experiment(client: AsyncClient, test_user: User):
    """Test creating a new experiment"""
    payload = {
        "name": "Test Experiment",
        "description": "A test experiment",
        "metadata": {"key": "value"},
    }

    response = await client.post("/api/v1/experiments", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["name"] == "Test Experiment"
    assert data["description"] == "A test experiment"
    assert "id" in data


@pytest.mark.asyncio
async def test_get_experiment(client: AsyncClient, test_user: User):
    """Test getting a specific experiment"""
    # Create an experiment first
    create_payload = {
        "name": "Test Experiment",
        "description": "A test experiment",
        "metadata": {},
    }

    create_response = await client.post("/api/v1/experiments", json=create_payload)
    experiment_id = create_response.json()["id"]

    # Get the experiment
    response = await client.get(f"/api/v1/experiments/{experiment_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == experiment_id
    assert data["name"] == "Test Experiment"


@pytest.mark.asyncio
async def test_get_nonexistent_experiment(client: AsyncClient):
    """Test getting a nonexistent experiment"""
    response = await client.get("/api/v1/experiments/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_experiment(client: AsyncClient, test_user: User):
    """Test updating an experiment"""
    # Create an experiment first
    create_payload = {
        "name": "Original Name",
        "description": "Original description",
        "metadata": {},
    }

    create_response = await client.post("/api/v1/experiments", json=create_payload)
    experiment_id = create_response.json()["id"]

    # Update the experiment
    update_payload = {
        "name": "Updated Name",
        "description": "Updated description",
    }

    response = await client.put(f"/api/v1/experiments/{experiment_id}", json=update_payload)
    assert response.status_code == 200

    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated description"


@pytest.mark.asyncio
async def test_analysis_selection_is_durable_and_preserves_experiment_metadata(client: AsyncClient, test_user: User):
    created = await client.post(
        "/api/v1/experiments",
        json={"name": "Supervised dataset", "metadata": {"custody": {"source": "reference"}}},
    )
    experiment_id = created.json()["id"]

    response = await client.put(
        f"/api/v1/experiments/{experiment_id}/analysis-selection",
        json={
            "selected_target": "cultivar",
            "target_type": "categorical",
            "group_column": "batch",
            "source_digest": "a" * 64,
        },
    )

    assert response.status_code == 200
    selection = response.json()
    assert selection["schema_version"] == "spectra-sherpa-analysis-selection/1"
    assert selection["selected_target"] == "cultivar"
    assert selection["target_type"] == "categorical"
    assert selection["group_column"] == "batch"

    restored = (await client.get(f"/api/v1/experiments/{experiment_id}")).json()
    assert restored["metadata"]["custody"] == {"source": "reference"}
    assert restored["metadata"]["analysis_selection"] == selection


@pytest.mark.asyncio
async def test_analysis_selection_rejects_group_without_target(client: AsyncClient, test_user: User):
    created = await client.post(
        "/api/v1/experiments",
        json={"name": "Unsupervised dataset", "metadata": {}},
    )

    response = await client.put(
        f"/api/v1/experiments/{created.json()['id']}/analysis-selection",
        json={"group_column": "batch"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Grouped validation requires a selected target"


@pytest.mark.asyncio
async def test_delete_experiment(client: AsyncClient, test_user: User):
    """Test deleting an experiment"""
    # Create an experiment first
    create_payload = {
        "name": "To Delete",
        "description": "Will be deleted",
        "metadata": {},
    }

    create_response = await client.post("/api/v1/experiments", json=create_payload)
    experiment_id = create_response.json()["id"]

    # Delete the experiment
    response = await client.delete(f"/api/v1/experiments/{experiment_id}")
    assert response.status_code == 200

    # Verify it's gone
    get_response = await client.get(f"/api/v1/experiments/{experiment_id}")
    assert get_response.status_code == 404


@pytest.mark.anyio
async def test_list_experiments_filters_by_project(auth_client: AsyncClient):
    project_a = (await auth_client.post("/api/v1/projects", json={"name": "Project A"})).json()
    project_b = (await auth_client.post("/api/v1/projects", json={"name": "Project B"})).json()

    exp_a = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Dataset A", "metadata": {}, "project_id": project_a["id"]},
        )
    ).json()
    await auth_client.post(
        "/api/v1/experiments",
        json={"name": "Dataset B", "metadata": {}, "project_id": project_b["id"]},
    )

    response = await auth_client.get(f"/api/v1/experiments?project_id={project_a['id']}")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [exp_a["id"]]
    assert response.json()[0]["project_id"] == project_a["id"]


@pytest.mark.anyio
async def test_available_datasets_filters_by_project(auth_client: AsyncClient):
    project_a = (await auth_client.post("/api/v1/projects", json={"name": "Data Project A"})).json()
    project_b = (await auth_client.post("/api/v1/projects", json={"name": "Data Project B"})).json()

    exp_a = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Dataset A", "metadata": {}, "project_id": project_a["id"]},
        )
    ).json()
    await auth_client.post(
        "/api/v1/experiments",
        json={"name": "Dataset B", "metadata": {}, "project_id": project_b["id"]},
    )

    response = await auth_client.get(f"/api/v1/datasets/available?project_id={project_a['id']}")

    assert response.status_code == 200
    experiments = response.json()["experiments"]
    assert [item["id"] for item in experiments] == [exp_a["id"]]
    assert experiments[0]["project_id"] == project_a["id"]


@pytest.mark.anyio
async def test_import_library_dataset_adds_file_to_my_dataset(auth_client: AsyncClient, test_session):
    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.models.nist_library import NistLibrary
    from spectra_sherpa.app.services.experiments import experiment_dir

    library_dir = settings.data_dir / "nist_library"
    library_dir.mkdir(parents=True, exist_ok=True)
    source_file = library_dir / "acetone.jdx"
    source_file.write_text(
        "\n".join(
            [
                "##TITLE=Acetone",
                "##JCAMP-DX=5.00",
                "##DATA TYPE=INFRARED SPECTRUM",
                "##XUNITS=1/CM",
                "##YUNITS=ABSORBANCE",
                "##FIRSTX=1000",
                "##LASTX=1002",
                "##NPOINTS=3",
                "##XYDATA=(X++(Y..Y))",
                "1000 0.1 0.2 0.3",
                "##END=",
            ]
        ),
        encoding="utf-8",
    )

    entry = NistLibrary(
        compound_name="Acetone",
        cas_number="67-64-1",
        resolution="low",
        file_path="nist_library/acetone.jdx",
    )
    test_session.add(entry)
    await test_session.commit()
    await test_session.refresh(entry)

    spectrum_response = await auth_client.get(f"/api/v1/datasets/library/{entry.id}/spectrum")
    assert spectrum_response.status_code == 200
    spectrum = spectrum_response.json()
    assert spectrum["component_id"] == f"nist:{entry.id}"
    assert spectrum["name"] == "Acetone"
    assert spectrum["source"] == "nist"
    assert spectrum["x"] == [1000.0, 1001.0, 1002.0]
    assert spectrum["y"] == [0.1, 0.2, 0.3]
    assert spectrum["x_title"] == "Wavenumber"
    assert spectrum["x_units"] == "cm-1"
    assert spectrum["y_title"] == "Absorbance"
    assert spectrum["metadata"]["source_file"] == "nist_library/acetone.jdx"

    project = (await auth_client.post("/api/v1/projects", json={"name": "Library Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Library Dataset", "metadata": {}, "project_id": project["id"]},
        )
    ).json()

    response = await auth_client.post(
        "/api/v1/datasets/library/import",
        json={"experiment_id": experiment["id"], "library_ids": [entry.id]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] == 1
    assert len(payload["files"]) == 1

    files_response = await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files")
    assert files_response.status_code == 200
    files = files_response.json()
    assert len(files) == 1
    assert files[0]["stage"] == "raw"
    assert files[0]["file_path"].startswith("raw/library_nist_Acetone")
    assert files[0]["file_path"].endswith(".csv")
    assert (
        (experiment_dir(experiment["id"]) / files[0]["file_path"]).read_text(encoding="utf-8").startswith("Wavenumber")
    )


@pytest.mark.anyio
async def test_import_nist_library_caps_bulk_request(auth_client: AsyncClient, monkeypatch):
    from spectra_sherpa.app.api.v1.routes import datasets

    monkeypatch.setattr(datasets, "MAX_NIST_LIBRARY_IMPORT_COUNT", 1)
    project = (await auth_client.post("/api/v1/projects", json={"name": "Capped Library Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Capped Library Dataset", "metadata": {}, "project_id": project["id"]},
        )
    ).json()

    response = await auth_client.post(
        "/api/v1/datasets/library/import",
        json={"experiment_id": experiment["id"], "library_ids": [101, 102]},
    )

    assert response.status_code == 400
    assert "at most 1 spectra" in response.json()["detail"]


@pytest.mark.anyio
async def test_import_nist_library_reports_corrupt_entries_and_imports_rest(auth_client: AsyncClient, test_session):
    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.models.nist_library import NistLibrary

    library_dir = settings.data_dir / "nist_library"
    library_dir.mkdir(parents=True, exist_ok=True)
    source_file = library_dir / "valid_partial.jdx"
    source_file.write_text(
        "\n".join(
            [
                "##TITLE=Valid Partial",
                "##JCAMP-DX=5.00",
                "##DATA TYPE=INFRARED SPECTRUM",
                "##XUNITS=1/CM",
                "##YUNITS=ABSORBANCE",
                "##FIRSTX=1000",
                "##LASTX=1002",
                "##NPOINTS=3",
                "##XYDATA=(X++(Y..Y))",
                "1000 0.1 0.2 0.3",
                "##END=",
            ]
        ),
        encoding="utf-8",
    )
    valid = NistLibrary(
        compound_name="Valid Partial",
        cas_number="valid-partial",
        resolution="test",
        file_path="nist_library/valid_partial.jdx",
    )
    missing = NistLibrary(
        compound_name="Missing Partial",
        cas_number="missing-partial",
        resolution="test",
        file_path="nist_library/missing_partial.jdx",
    )
    test_session.add_all([valid, missing])
    await test_session.commit()
    await test_session.refresh(valid)
    await test_session.refresh(missing)

    project = (await auth_client.post("/api/v1/projects", json={"name": "Partial Library Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Partial Library Dataset", "metadata": {}, "project_id": project["id"]},
        )
    ).json()

    response = await auth_client.post(
        "/api/v1/datasets/library/import",
        json={"experiment_id": experiment["id"], "library_ids": [valid.id, missing.id]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] == 1
    assert len(payload["files"]) == 1
    assert len(payload["failures"]) == 1
    assert "Missing Partial" in payload["failures"][0]
    assert payload["message"] == "Imported 1 of 2 NIST spectra; failed 1."


@pytest.mark.anyio
async def test_write_nist_library_spectra_retries_without_finest_spacing_on_large_grid(monkeypatch):
    from fastapi import HTTPException

    from spectra_sherpa.app.api.v1.routes import datasets

    coarse = datasets._LibrarySpectrum(
        component_id="nist:coarse",
        name="Coarse",
        source="nist",
        x=[1000.0, 1001.0, 1002.0],
        y=[0.1, 0.2, 0.3],
    )
    fine = datasets._LibrarySpectrum(
        component_id="nist:fine",
        name="Fine",
        source="nist",
        x=[1000.0, 1000.1, 1000.2],
        y=[0.1, 0.2, 0.3],
    )
    calls: list[list[str]] = []

    async def fake_write_library_spectra_to_experiment(**kwargs):
        spectra = kwargs["spectra"]
        calls.append([spectrum.name for spectrum in spectra])
        if len(spectra) > 1:
            raise HTTPException(
                status_code=400,
                detail="Library x-axis grid would exceed 50,000 points. Use a wider resolution or narrower range.",
            )
        return ["created"]

    monkeypatch.setattr(datasets, "_write_library_spectra_to_experiment", fake_write_library_spectra_to_experiment)

    created, skipped = await datasets._write_nist_library_spectra_to_experiment(
        session=None,
        experiment_id=1,
        spectra=[coarse, fine],
        range_mode="widest",
    )

    assert created == ["created"]
    assert calls == [["Coarse", "Fine"], ["Coarse"]]
    assert skipped == ["Fine: skipped because the combined library grid would exceed 50,000 points"]


@pytest.mark.anyio
async def test_import_library_dataset_widest_pads_unavailable_ranges_as_missing(auth_client: AsyncClient, test_session):
    import csv

    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.models.nist_library import NistLibrary
    from spectra_sherpa.app.services.experiments import experiment_dir

    library_dir = settings.data_dir / "nist_library"
    library_dir.mkdir(parents=True, exist_ok=True)
    entries: list[NistLibrary] = []
    for name, cas, start, values in [
        ("Left Band", "test-left-band", 1000, [0.1, 0.2, 0.3]),
        ("Right Band", "test-right-band", 2000, [0.4, 0.5, 0.6]),
    ]:
        path = library_dir / f"{cas}.jdx"
        path.write_text(
            "\n".join(
                [
                    f"##TITLE={name}",
                    "##JCAMP-DX=5.00",
                    "##DATA TYPE=INFRARED SPECTRUM",
                    "##XUNITS=1/CM",
                    "##YUNITS=ABSORBANCE",
                    f"##FIRSTX={start}",
                    f"##LASTX={start + 2}",
                    "##NPOINTS=3",
                    "##XYDATA=(X++(Y..Y))",
                    f"{start} {' '.join(str(value) for value in values)}",
                    "##END=",
                ]
            ),
            encoding="utf-8",
        )
        entry = NistLibrary(
            compound_name=name,
            cas_number=cas,
            resolution="test",
            file_path=f"nist_library/{cas}.jdx",
        )
        test_session.add(entry)
        entries.append(entry)
    await test_session.commit()
    for entry in entries:
        await test_session.refresh(entry)

    project = (await auth_client.post("/api/v1/projects", json={"name": "Wide Library Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Wide Library Dataset", "metadata": {}, "project_id": project["id"]},
        )
    ).json()

    response = await auth_client.post(
        "/api/v1/datasets/library/import",
        json={
            "experiment_id": experiment["id"],
            "library_ids": [entry.id for entry in entries],
            "range_mode": "widest",
        },
    )

    assert response.status_code == 200
    files_response = await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files")
    files = files_response.json()
    assert len(files) == 2
    rows_by_file: dict[str, list[list[str]]] = {}
    for file_record in files:
        path = experiment_dir(experiment["id"]) / file_record["file_path"]
        with path.open(encoding="utf-8", newline="") as handle:
            rows_by_file[file_record["file_path"]] = list(csv.reader(handle))

    left_rows = next(rows for path, rows in rows_by_file.items() if "Left_Band" in path)
    right_rows = next(rows for path, rows in rows_by_file.items() if "Right_Band" in path)
    assert left_rows[1] == ["1000", "0.1"]
    assert left_rows[-1] == ["2002", ""]
    assert right_rows[1] == ["1000", ""]
    assert right_rows[-1] == ["2002", "0.6"]


@pytest.mark.anyio
async def test_import_library_dataset_common_rejects_disjoint_spectral_windows(auth_client: AsyncClient, test_session):
    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.models.nist_library import NistLibrary

    library_dir = settings.data_dir / "nist_library"
    library_dir.mkdir(parents=True, exist_ok=True)
    entries: list[NistLibrary] = []
    for name, cas, start in [
        ("Common Reject Left", "test-common-reject-left", 1000),
        ("Common Reject Right", "test-common-reject-right", 2000),
    ]:
        path = library_dir / f"{cas}.jdx"
        path.write_text(
            "\n".join(
                [
                    f"##TITLE={name}",
                    "##JCAMP-DX=5.00",
                    "##DATA TYPE=INFRARED SPECTRUM",
                    "##XUNITS=1/CM",
                    "##YUNITS=ABSORBANCE",
                    f"##FIRSTX={start}",
                    f"##LASTX={start + 2}",
                    "##NPOINTS=3",
                    "##XYDATA=(X++(Y..Y))",
                    f"{start} 0.1 0.2 0.3",
                    "##END=",
                ]
            ),
            encoding="utf-8",
        )
        entry = NistLibrary(
            compound_name=name,
            cas_number=cas,
            resolution="test",
            file_path=f"nist_library/{cas}.jdx",
        )
        test_session.add(entry)
        entries.append(entry)
    await test_session.commit()
    for entry in entries:
        await test_session.refresh(entry)

    project = (await auth_client.post("/api/v1/projects", json={"name": "Common Library Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Common Library Dataset", "metadata": {}, "project_id": project["id"]},
        )
    ).json()

    response = await auth_client.post(
        "/api/v1/datasets/library/import",
        json={
            "experiment_id": experiment["id"],
            "library_ids": [entry.id for entry in entries],
            "range_mode": "common",
        },
    )

    assert response.status_code == 400
    assert "no common x-axis overlap" in response.json()["detail"]


@pytest.mark.anyio
async def test_import_hitran_library_dataset_queues_uncached_download(auth_client: AsyncClient, monkeypatch):
    from spectra_sherpa.app.api.v1.routes import datasets

    cache_checks: list[tuple[tuple, dict]] = []

    def fake_cached(*args, **kwargs):
        cache_checks.append((args, kwargs))
        return False

    monkeypatch.setattr(datasets.synthesis_service, "is_component_spectrum_cached", fake_cached)

    async def fake_check_library_egress(*args, **kwargs):
        return True

    async def fake_stored_api_key(*args, **kwargs):
        return "hitran-secret"

    queued_jobs: list[int] = []

    async def fake_run_job(job_id, work):
        queued_jobs.append(job_id)

    monkeypatch.setattr(datasets, "_check_library_egress", fake_check_library_egress)
    monkeypatch.setattr(datasets, "_stored_api_key", fake_stored_api_key)
    monkeypatch.setattr(datasets.job_manager, "run_job", fake_run_job)

    project = (await auth_client.post("/api/v1/projects", json={"name": "HITRAN Library Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "HITRAN Library Dataset", "metadata": {}, "project_id": project["id"]},
        )
    ).json()

    response = await auth_client.post(
        "/api/v1/datasets/library/import",
        json={
            "experiment_id": experiment["id"],
            "source": "hitran",
            "component_ids": ["hitran:2", "hitran:4"],
            "component_specs": [
                {
                    "component_id": "hitran:2",
                    "resolution_cm1": 0.5,
                    "wavenumber_min": 2300.0,
                    "wavenumber_max": 2310.0,
                    "temperature_k": 315.0,
                    "pressure_atm": 0.75,
                },
                {
                    "component_id": "hitran:4",
                    "resolution_cm1": 1.0,
                    "wavenumber_min": 2250.0,
                    "wavenumber_max": 2255.0,
                    "temperature_k": 293.0,
                    "pressure_atm": 1.0,
                },
            ],
            "resolution_cm1": 1.0,
            "wavenumber_min": 2250.0,
            "wavenumber_max": 2255.0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["queued"] is True
    assert payload["imported"] == 0
    assert payload["files"] == []
    assert payload["job_id"] is not None
    assert "queued" in payload["message"]
    assert queued_jobs == [payload["job_id"]]
    assert cache_checks[0][0][:2] == ("hitran", "hitran:2")
    assert cache_checks[0][1]["resolution_cm1"] == 0.5
    assert cache_checks[0][1]["wavenumber_min"] == 2300.0
    assert cache_checks[0][1]["temperature_k"] == 315.0
    assert cache_checks[0][1]["pressure_atm"] == 0.75


@pytest.mark.anyio
async def test_import_hitran_library_dataset_uses_loaded_spectra_fast_path(auth_client: AsyncClient, monkeypatch):
    from spectra_sherpa.app.api.v1.routes import datasets
    from spectra_sherpa.app.lib.io import load_csv_as_sherpa
    from spectra_sherpa.app.services.experiments import experiment_dir
    from spectra_sherpa.app.services.prepared_data import load_prepared_data_overrides
    from spectra_sherpa.app.services.synthesis import (
        HITRAN_CROSS_SECTION_TO_MOLAR_ABSORPTIVITY,
        MOLAR_ABSORPTION_COEFFICIENT_UNITS,
    )

    def fail_if_cache_checked(*args, **kwargs):
        raise AssertionError("loaded spectra should not trigger HITRAN cache checks")

    monkeypatch.setattr(datasets.synthesis_service, "is_component_spectrum_cached", fail_if_cache_checked)

    project = (await auth_client.post("/api/v1/projects", json={"name": "Loaded HITRAN Library Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Loaded HITRAN Library Dataset", "metadata": {}, "project_id": project["id"]},
        )
    ).json()

    response = await auth_client.post(
        "/api/v1/datasets/library/import",
        json={
            "experiment_id": experiment["id"],
            "source": "hitran",
            "component_specs": [
                {"component_id": "hitran:2", "resolution_cm1": 1.0},
                {"component_id": "hitran:4", "resolution_cm1": 1.0},
            ],
            "spectra": [
                {
                    "component_id": "hitran:2",
                    "name": "Carbon dioxide",
                    "source": "hitran",
                    "wavenumber": [2300.0, 2301.0, 2302.0],
                    "intensity": [1.0e-22, 2.0e-22, 3.0e-22],
                    "y_quantity": "cross_section",
                    "y_units": "cm^2 molecule^-1",
                    "resolution_cm1": 1.0,
                    "apodization": "Voigt",
                },
                {
                    "component_id": "hitran:4",
                    "name": "Nitrous oxide",
                    "source": "hitran",
                    "wavenumber": [2300.0, 2301.0, 2302.0],
                    "intensity": [4.0e-22, 5.0e-22, 6.0e-22],
                    "y_quantity": "cross_section",
                    "y_units": "cm^2 molecule^-1",
                    "resolution_cm1": 1.0,
                    "apodization": "Voigt",
                },
            ],
            "range_mode": "common",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["queued"] is False
    assert payload["imported"] == 2
    assert len(payload["files"]) == 2

    available = (await auth_client.get("/api/v1/datasets/available", params={"project_id": project["id"]})).json()
    experiment_entry = next(item for item in available["experiments"] if item["id"] == experiment["id"])
    raw_file_paths = [
        item["file_path"] for item in experiment_entry["stages"]["raw"] if item["id"] in set(payload["files"])
    ]
    raw_files = sorted(experiment_dir(experiment["id"]) / path for path in raw_file_paths)
    assert len(raw_files) == 2
    carbon_dioxide = next(path for path in raw_files if "Carbon_dioxide" in path.name)
    rows = list(csv.reader(carbon_dioxide.open(encoding="utf-8")))
    assert rows[0] == ["Wavenumber (cm-1)", "Carbon dioxide"]
    assert float(rows[1][1]) == pytest.approx(1.0e-22 * HITRAN_CROSS_SECTION_TO_MOLAR_ABSORPTIVITY)

    overrides = load_prepared_data_overrides(file_path=str(carbon_dioxide.resolve()))
    assert overrides.y_title == "Molar absorption coefficient"
    assert overrides.y_units == MOLAR_ABSORPTION_COEFFICIENT_UNITS

    loaded = load_csv_as_sherpa(carbon_dioxide)
    assert loaded.domain.data_quantity == "Molar absorption coefficient"
    assert loaded.units == MOLAR_ABSORPTION_COEFFICIENT_UNITS


@pytest.mark.anyio
async def test_axis_column_csv_file_lists_report_sherpa_shape(auth_client: AsyncClient):
    project = (await auth_client.post("/api/v1/projects", json={"name": "Raman CSV Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Shared Axis CSV", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    csv_content = (
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n200,2139,9549\n201,2159,9538\n202,2178,9537\n"
    )

    upload_response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/files",
        data={"stage": "raw", "data_role": "X_spectra"},
        files={"file": ("raman_conditions.csv", csv_content.encode("ascii"), "text/csv")},
    )

    assert upload_response.status_code == 201
    uploaded = upload_response.json()
    assert uploaded["shape"] == [2, 3]
    assert uploaded["n_samples"] == 2
    assert uploaded["n_features"] == 3
    assert uploaded["data_role"] == "X_spectra"
    assert uploaded["x_title"] == "Wavenumber"
    assert uploaded["x_units"] == "cm-1"
    assert uploaded["is_spectra"] is True

    files_response = await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files")
    assert files_response.status_code == 200
    listed = files_response.json()[0]
    assert listed["shape"] == [2, 3]
    assert listed["n_samples"] == 2
    assert listed["n_features"] == 3

    available_response = await auth_client.get(f"/api/v1/datasets/available?project_id={project['id']}")
    assert available_response.status_code == 200
    available_file = available_response.json()["experiments"][0]["stages"]["raw"][0]
    assert available_file["shape"] == [2, 3]
    assert available_file["data_role"] == "X_spectra"


@pytest.mark.anyio
async def test_opus_upload_exposes_every_typed_asset_without_selecting_for_the_scientist(
    auth_client: AsyncClient,
    monkeypatch,
):
    project = (await auth_client.post("/api/v1/projects", json={"name": "OPUS Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "OPUS Data", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    upload = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/files",
        data={"stage": "raw", "data_role": "X_spectra"},
        files={"file": ("sample.0000", OPUS_FIXTURE.read_bytes(), "application/octet-stream")},
    )
    assert upload.status_code == 201

    from spectra_sherpa.app.api.v1.routes import experiments as experiments_route

    real_to_thread = experiments_route.asyncio.to_thread
    offloaded: list[object] = []

    async def recording_to_thread(operation, *args, **kwargs):
        offloaded.append(operation)
        return await real_to_thread(operation, *args, **kwargs)

    monkeypatch.setattr(experiments_route.asyncio, "to_thread", recording_to_thread)
    inspected = await auth_client.get(
        f"/api/v1/experiments/{experiment['id']}/files/{upload.json()['id']}/scientific-assets"
    )
    assert inspected.status_code == 200
    payload = inspected.json()
    assert payload["format_id"] == "opus"
    assert payload["variant"] == "directory-block-v1"
    assert len(payload["source_sha256"]) == 64
    assert [asset["asset_id"] for asset in payload["assets"]] == ["igsm", "sm", "a", "igrf", "rf"]
    absorbance = next(asset for asset in payload["assets"] if asset["asset_id"] == "a")
    assert absorbance["shape"] == [1, 2126]
    assert absorbance["data_quantity"] == "Absorbance"
    assert absorbance["x_units"] == "cm-1"
    assert offloaded


@pytest.mark.anyio
async def test_opus_refused_sibling_block_is_visible_in_staged_and_persisted_asset_inventory(
    auth_client: AsyncClient,
):
    project = (await auth_client.post("/api/v1/projects", json={"name": "OPUS Warning Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "OPUS Warning Data", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    payload = OPEN_SPECY_OPUS_FIXTURE.read_bytes()

    staged_response = await auth_client.post(
        "/api/v1/builder/upload/stage",
        files={"file": ("published.0", payload, "application/octet-stream")},
    )
    assert staged_response.status_code == 200
    staged = staged_response.json()
    assert len(staged["assets"]) == 5
    assert all(
        any("not independently qualified" in warning for warning in asset["warnings"]) for asset in staged["assets"]
    )

    upload = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/files",
        data={"stage": "raw", "data_role": "X_spectra"},
        files={"file": ("published.0", payload, "application/octet-stream")},
    )
    assert upload.status_code == 201
    inspected = await auth_client.get(
        f"/api/v1/experiments/{experiment['id']}/files/{upload.json()['id']}/scientific-assets"
    )
    assert inspected.status_code == 200
    assets = inspected.json()["assets"]
    assert len(assets) == 5
    assert all(any("not independently qualified" in warning for warning in asset["warnings"]) for asset in assets)


@pytest.mark.anyio
async def test_missingness_warning_is_visible_in_staged_and_persisted_asset_inventory(
    auth_client: AsyncClient,
):
    project = (await auth_client.post("/api/v1/projects", json={"name": "Missingness Warning Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Missingness Warning Data", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    payload = b"sample,alcohol,ash,target\nsample-A,14.23,2.43,class-A\nsample-B,13.20,,class-B\n"

    staged_response = await auth_client.post(
        "/api/v1/builder/upload/stage",
        files={"file": ("missing-feature.csv", payload, "text/csv")},
    )
    assert staged_response.status_code == 200
    staged_warnings = staged_response.json()["assets"][0]["warnings"]
    assert any("1 missing or non-finite value" in warning for warning in staged_warnings)
    assert any("sample row(s) 2" in warning for warning in staged_warnings)
    assert any("does not impute values implicitly" in warning for warning in staged_warnings)

    upload = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/files",
        data={"stage": "raw", "data_role": "X_features"},
        files={"file": ("missing-feature.csv", payload, "text/csv")},
    )
    assert upload.status_code == 201
    inspected = await auth_client.get(
        f"/api/v1/experiments/{experiment['id']}/files/{upload.json()['id']}/scientific-assets"
    )
    assert inspected.status_code == 200
    persisted_warnings = inspected.json()["assets"][0]["warnings"]
    assert any("1 missing or non-finite value" in warning for warning in persisted_warnings)
    assert any("sample row(s) 2" in warning for warning in persisted_warnings)
    assert any("does not impute values implicitly" in warning for warning in persisted_warnings)


@pytest.mark.anyio
async def test_registered_reference_inventory_exposes_only_its_governed_projection(
    auth_client: AsyncClient,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from spectra_sherpa.app.lib import reference_materialization, registered_reference_storage

    project = (await auth_client.post("/api/v1/projects", json={"name": "Governed inventory"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "CGL NIR", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    uploaded = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/files",
        data={"stage": "raw", "data_role": "X_spectra"},
        files={
            "file": (
                "CGL_nir.mat",
                b"##TITLE=container\n##XUNITS=1/CM\n##YUNITS=ABSORBANCE\n" b"##XYDATA=(X++(Y..Y))\n1 0.1 0.2\n##END=\n",
                "application/octet-stream",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    projection_id = "public-cgl-nir-lactate-v1"
    portable = {
        "projection_id": projection_id,
        "native_reader_contract": "spectrasherpa.matlab-dso/1",
        "member_sha256": "a" * 64,
    }
    dataset = SherpaDataset(
        X=[[1.0, 2.0], [3.0, 4.0]],
        title="CGL NIR",
        feature_axis=SpectralAxis(values=[1000.0, 1100.0], title="Wavelength", units="nm"),
        sample_axis=SampleAxis(labels=["CGL-001", "CGL-002"]),
        target=[0.1, 0.2],
        target_context=TargetContext(
            target_type="continuous",
            target_name="Lactate (wt %)",
            target_names=["Lactate (wt %)"],
            selected_target="Lactate (wt %)",
        ),
        domain=DomainContext(technique="NIR", data_quantity="Absorbance"),
        units="AU",
    )
    monkeypatch.setattr(
        registered_reference_storage,
        "read_registered_reference_sidecar",
        lambda _path: portable,
    )
    monkeypatch.setattr(
        reference_materialization,
        "materialize_reference_member",
        lambda _path, selected: (
            SimpleNamespace(dataset=dataset)
            if selected == projection_id
            else (_ for _ in ()).throw(AssertionError("wrong projection"))
        ),
    )

    inspected = await auth_client.get(
        f"/api/v1/experiments/{experiment['id']}/files/{uploaded.json()['id']}/scientific-assets"
    )

    assert inspected.status_code == 200, inspected.text
    payload = inspected.json()
    assert payload["parser_id"] == "spectrasherpa.matlab-dso/1"
    assert payload["source_sha256"] == "a" * 64
    assert payload["assets"] == [
        {
            "asset_id": projection_id,
            "title": "CGL NIR",
            "shape": [2, 2],
            "dimension_roles": ["sample", "spectral_variable"],
            "data_role": "X_spectra",
            "x_title": "Wavelength",
            "x_units": "nm",
            "data_quantity": "Absorbance",
            "value_units": "AU",
            "warnings": [],
        }
    ]


@pytest.mark.anyio
async def test_rejected_staged_scientific_file_releases_demo_upload_reservation(
    auth_client: AsyncClient,
    monkeypatch,
) -> None:
    from spectra_sherpa.app.api.v1.routes import builder as builder_route

    payload = bytearray(OPUS_FIXTURE.read_bytes())
    dpf_offset = payload.find(b"DPF")
    assert dpf_offset > 0
    payload[dpf_offset : dpf_offset + 3] = b"ZZZ"
    events: list[str] = []
    monkeypatch.setattr(
        builder_route,
        "reserve_demo_upload_quota_or_429",
        lambda _user_id: events.append("reserve") or True,
    )
    monkeypatch.setattr(
        builder_route,
        "consume_reserved_demo_upload_quota_if_needed",
        lambda _user_id, _reserved: events.append("consume"),
    )
    monkeypatch.setattr(
        builder_route,
        "release_demo_upload_quota_reservation_if_needed",
        lambda _user_id, _reserved: events.append("release"),
    )

    response = await auth_client.post(
        "/api/v1/builder/upload/stage",
        files={"file": ("unqualified.0000", bytes(payload), "application/octet-stream")},
    )

    assert response.status_code == 400
    assert events == ["reserve", "release"]


@pytest.mark.anyio
async def test_portable_sample_table_lists_all_typed_targets(auth_client: AsyncClient):
    project = (await auth_client.post("/api/v1/projects", json={"name": "Sample Table Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Prepared Samples", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    csv_content = (
        "row_index,source_file_id,sample_id,include,target_schema,moisture,cultivar,plate_id,well\n"
        '0,41,sample-1,true,"{""moisture"":""continuous"",""cultivar"":""categorical""}",10,A,plate-1,A01\n'
        '1,41,sample-2,true,"{""moisture"":""continuous"",""cultivar"":""categorical""}",11,B,plate-1,A02\n'
    )

    upload_response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/files",
        data={
            "stage": "preprocessed",
            "data_role": "X_features",
            "target_column": "moisture",
            "target_type": "continuous",
        },
        files={"file": ("samples.csv", csv_content.encode("utf-8"), "text/csv")},
    )

    assert upload_response.status_code == 201
    uploaded = upload_response.json()
    assert uploaded["shape"] == [2, 2]
    assert uploaded["target_names"] == ["moisture", "cultivar"]
    assert uploaded["target_types"] == {"moisture": "continuous", "cultivar": "categorical"}

    files_response = await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files")
    assert files_response.status_code == 200
    listed = files_response.json()[0]
    assert listed["target_names"] == ["moisture", "cultivar"]
    assert listed["target_types"] == {"moisture": "continuous", "cultivar": "categorical"}

    available_response = await auth_client.get(f"/api/v1/datasets/available?project_id={project['id']}")
    assert available_response.status_code == 200
    available = available_response.json()["experiments"][0]
    prepared = available["stages"]["preprocessed"][0]
    assert prepared["target_names"] == ["moisture", "cultivar"]
    assert prepared["target_types"] == {"moisture": "continuous", "cultivar": "categorical"}
    assert available["target_names"] == ["moisture", "cultivar"]
    assert available["target_types"] == {"moisture": "continuous", "cultivar": "categorical"}


@pytest.mark.anyio
async def test_bound_sample_table_csv_recomputes_and_persists_dataset_readiness(auth_client: AsyncClient):
    project = (await auth_client.post("/api/v1/projects", json={"name": "Readiness Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Bound Spectra", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    source_response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/files",
        data={"stage": "raw", "data_role": "X_spectra"},
        files={
            "file": (
                "source.csv",
                b"wavenumber,sample-1,sample-2\n1000,1,2\n900,3,4\n",
                "text/csv",
            )
        },
    )
    assert source_response.status_code == 201
    source = source_response.json()
    self_bind = await auth_client.post(
        "/api/v1/builder/analysis-binding",
        json={
            "source_file_id": source["id"],
            "sample_table_file_id": source["id"],
            "expected_revision": None,
            "selected_target": "moisture",
            "target_type": "continuous",
        },
    )
    assert self_bind.status_code == 400
    assert self_bind.json()["detail"] == "Source data and sample-table CSV must be different files"
    table_csv = (
        "row_index,source_file_id,sample_id,include,target_schema,moisture,cultivar,batch\n"
        f'0,{source["id"]},sample-1,true,'
        '"{""moisture"":""continuous"",""cultivar"":""categorical""}",10,A,day-1\n'
        f'1,{source["id"]},sample-2,true,'
        '"{""moisture"":""continuous"",""cultivar"":""categorical""}",11,B,day-2\n'
    )
    table_response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/files",
        data={
            "stage": "preprocessed",
            "data_role": "X_features",
            "target_column": "moisture",
            "target_type": "continuous",
        },
        files={"file": ("sample-table.csv", table_csv.encode("utf-8"), "text/csv")},
    )
    assert table_response.status_code == 201
    table = table_response.json()

    initial_revision = await auth_client.get(f"/api/v1/builder/analysis-binding/{source['id']}/revision")
    assert initial_revision.status_code == 200
    assert initial_revision.json() == {"revision": None}

    bind_response = await auth_client.post(
        "/api/v1/builder/analysis-binding",
        json={
            "source_file_id": source["id"],
            "sample_table_file_id": table["id"],
            "expected_revision": None,
            "selected_target": "moisture",
            "target_type": "continuous",
        },
    )
    assert bind_response.status_code == 200, bind_response.text
    binding_revision = bind_response.json()["revision"]
    assert len(binding_revision) == 64
    bound_revision = await auth_client.get(f"/api/v1/builder/analysis-binding/{source['id']}/revision")
    assert bound_revision.status_code == 200
    assert bound_revision.json() == {"revision": binding_revision}
    editor_response = await auth_client.get(f"/api/v1/builder/analysis-binding/{source['id']}")
    assert editor_response.status_code == 200
    editor_payload = editor_response.json()
    assert editor_payload["revision"] == binding_revision
    assert editor_payload["sample_table_file_id"] == table["id"]
    assert editor_payload["selected_target"] == "moisture"
    assert editor_payload["target_definitions"] == [
        {"name": "moisture", "type": "continuous"},
        {"name": "cultivar", "type": "categorical"},
    ]
    assert editor_payload["annotation_columns"] == ["batch"]
    assert editor_payload["rows"] == [
        {
            "row_index": 0,
            "source_file_id": source["id"],
            "sample_id": "sample-1",
            "include": True,
            "targets": {"moisture": "10", "cultivar": "A"},
            "plate_id": "",
            "well": "",
            "annotations": {"batch": "day-1"},
        },
        {
            "row_index": 1,
            "source_file_id": source["id"],
            "sample_id": "sample-2",
            "include": True,
            "targets": {"moisture": "11", "cultivar": "B"},
            "plate_id": "",
            "well": "",
            "annotations": {"batch": "day-2"},
        },
    ]
    stale_bind = await auth_client.post(
        "/api/v1/builder/analysis-binding",
        json={
            "source_file_id": source["id"],
            "sample_table_file_id": table["id"],
            "expected_revision": None,
            "selected_target": "moisture",
            "target_type": "continuous",
        },
    )
    assert stale_bind.status_code == 409
    assert "Reload before saving" in stale_bind.json()["detail"]

    first = await auth_client.post(
        "/api/v1/builder/file-info",
        json={"experiment_id": experiment["id"], "file_path": source["file_path"]},
    )
    second = await auth_client.post(
        "/api/v1/builder/file-info",
        json={"experiment_id": experiment["id"], "file_path": source["file_path"]},
    )
    assert first.status_code == second.status_code == 200
    for response in (first, second):
        payload = response.json()
        assert payload["analysis_binding"] == {
            "revision": binding_revision,
            "sample_table_file_id": table["id"],
            "selected_target": "moisture",
            "target_type": "continuous",
        }
        assert payload["analysis_readiness"]["scope"] == "structural"
        assert payload["analysis_readiness"]["profile"]["target_type"] == "continuous"
        assert payload["analysis_readiness"]["profile"]["target_fields"] == ["moisture"]
        assert payload["analysis_readiness"]["profile"]["group_fields"] == ["batch"]
        assert payload["analysis_readiness"]["template_count"] == sum(payload["analysis_readiness"]["counts"].values())

    rebound = await auth_client.post(
        "/api/v1/builder/analysis-binding",
        json={
            "source_file_id": source["id"],
            "sample_table_file_id": table["id"],
            "expected_revision": binding_revision,
            "selected_target": "cultivar",
            "target_type": "categorical",
        },
    )
    assert rebound.status_code == 200, rebound.text
    rebound_revision = rebound.json()["revision"]
    assert rebound_revision != binding_revision
    stale_unbind = await auth_client.delete(
        f"/api/v1/builder/analysis-binding/{source['id']}",
        params={"expected_revision": binding_revision},
    )
    assert stale_unbind.status_code == 409
    stale_rebind = await auth_client.post(
        "/api/v1/builder/analysis-binding",
        json={
            "source_file_id": source["id"],
            "sample_table_file_id": table["id"],
            "expected_revision": binding_revision,
            "selected_target": "moisture",
            "target_type": "continuous",
        },
    )
    assert stale_rebind.status_code == 409
    unbind = await auth_client.delete(
        f"/api/v1/builder/analysis-binding/{source['id']}",
        params={"expected_revision": rebound_revision},
    )
    assert unbind.status_code == 200
    assert unbind.json() == {"status": "unbound", "source_file_id": source["id"]}
    unbound_revision = await auth_client.get(f"/api/v1/builder/analysis-binding/{source['id']}/revision")
    assert unbound_revision.status_code == 200
    assert unbound_revision.json() == {"revision": None}
    after_unbind = await auth_client.post(
        "/api/v1/builder/file-info",
        json={"experiment_id": experiment["id"], "file_path": source["file_path"]},
    )
    assert after_unbind.status_code == 200
    assert "analysis_binding" not in after_unbind.json()
    assert after_unbind.json()["analysis_readiness"]["profile"]["target_type"] is None


@pytest.mark.anyio
async def test_staged_batch_accepts_folder_files_and_zip_members(auth_client: AsyncClient):
    csv_a = b"wavenumber,a\n1000,1\n1001,2\n"
    csv_b = b"wavenumber,b\n1000,3\n1001,4\n"
    archive = _scientific_zip([("nested/c.csv", csv_a), ("nested/d.csv", csv_b)])

    response = await auth_client.post(
        "/api/v1/builder/upload/stage-batch",
        files=[
            ("files", ("a.csv", csv_a, "text/csv")),
            ("files", ("b.csv", csv_b, "text/csv")),
            ("files", ("spectra.zip", archive, "application/zip")),
        ],
    )

    assert response.status_code == 200, response.text
    staged = response.json()
    assert staged["file_count"] == 4
    assert staged["refused_count"] == 0
    assert staged["refusals"] == []
    assert [item["filename"] for item in staged["files"]] == ["a.csv", "b.csv", "c.csv", "d.csv"]
    assert [item["source_name"] for item in staged["files"][-2:]] == [
        "spectra.zip:nested/c.csv",
        "spectra.zip:nested/d.csv",
    ]
    assert all(item["format_id"] == "csv" for item in staged["files"])


@pytest.mark.anyio
async def test_file_info_inspects_exact_selected_collection_members(auth_client: AsyncClient):
    project = (await auth_client.post("/api/v1/projects", json={"name": "Subset inspection"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Three spectra", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    files = []
    for index in range(3):
        response = await auth_client.post(
            f"/api/v1/experiments/{experiment['id']}/files",
            data={"stage": "raw", "data_role": "X_spectra"},
            files={
                "file": (
                    f"sample-{index + 1}.csv",
                    f"sample_id,1000,900\nsample-{index + 1},1,2\n".encode(),
                    "text/csv",
                )
            },
        )
        assert response.status_code == 201, response.text
        files.append(response.json())

    response = await auth_client.post(
        "/api/v1/builder/file-info",
        json={
            "experiment_id": experiment["id"],
            "file_ids": [files[0]["id"], files[2]["id"]],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["n_samples"] == 2
    assert payload["n_features"] == 2
    assert payload["metadata"]["contents_file_count"] == 2
    assert payload["metadata"]["source_collection"]["file_count"] == 2
    assert [member["file_name"] for member in payload["metadata"]["source_collection"]["files"]] == [
        files[0]["file_path"],
        files[2]["file_path"],
    ]

    duplicate = await auth_client.post(
        "/api/v1/builder/file-info",
        json={
            "experiment_id": experiment["id"],
            "file_ids": [files[0]["id"], files[0]["id"]],
        },
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "Selected files contain duplicate identities"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "members,reason",
    [
        ([("../escape.csv", b"x,y\n1,2\n")], "invalid"),
        ([("notes.pdf", b"not scientific")], "unsupported"),
    ],
)
async def test_staged_zip_reports_invalid_or_unsupported_members_without_publication(
    auth_client: AsyncClient,
    test_user: User,
    members: list[tuple[str, bytes]],
    reason: str,
) -> None:
    from spectra_sherpa.app.api.v1.routes.builder import _staging_root

    root = _staging_root(test_user)
    before = {path.name for path in root.iterdir()} if root.exists() else set()
    response = await auth_client.post(
        "/api/v1/builder/upload/stage-batch",
        files=[("files", ("refused.zip", _scientific_zip(members), "application/zip"))],
    )
    after = {path.name for path in root.iterdir()} if root.exists() else set()

    assert response.status_code == 200
    receipt = response.json()
    assert receipt["file_count"] == 0
    assert receipt["refused_count"] == 1
    assert reason in receipt["refusals"][0]["reason"].lower()
    assert after == before


@pytest.mark.anyio
async def test_staged_batch_loads_supported_sources_and_reports_the_rest(
    auth_client: AsyncClient,
) -> None:
    valid = b"wavenumber,a\n1000,1\n1001,2\n"
    archive = _scientific_zip(
        [
            ("nested/valid.csv", valid),
            ("nested/notes.pdf", b"not scientific"),
            ("nested/broken.npy", b"not a numpy array"),
        ]
    )

    response = await auth_client.post(
        "/api/v1/builder/upload/stage-batch",
        files=[("files", ("mixed.zip", archive, "application/zip"))],
    )

    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["file_count"] == 1
    assert [item["filename"] for item in receipt["files"]] == ["valid.csv"]
    assert receipt["refused_count"] == 2
    refused = {item["source_name"]: item["reason"] for item in receipt["refusals"]}
    assert "mixed.zip:nested/notes.pdf" in refused
    assert "Unsupported file type" in refused["mixed.zip:nested/notes.pdf"]
    assert "mixed.zip:nested/broken.npy" in refused
    assert "Could not inspect scientific assets" in refused["mixed.zip:nested/broken.npy"]


@pytest.mark.anyio
async def test_staged_zip_keeps_first_duplicate_basename_and_reports_later_member(
    auth_client: AsyncClient,
) -> None:
    csv = b"wavenumber,a\n1000,1\n1001,2\n"
    response = await auth_client.post(
        "/api/v1/builder/upload/stage-batch",
        files=[
            (
                "files",
                (
                    "duplicates.zip",
                    _scientific_zip([("one/a.csv", csv), ("two/a.csv", csv)]),
                    "application/zip",
                ),
            )
        ],
    )

    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["file_count"] == 1
    assert receipt["refused_count"] == 1
    assert receipt["refusals"] == [
        {
            "source_name": "duplicates.zip:two/a.csv",
            "reason": "Duplicate scientific filename: a.csv",
        }
    ]


@pytest.mark.anyio
async def test_staged_zip_refuses_symbolic_link_member(auth_client: AsyncClient) -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        info = zipfile.ZipInfo("linked.csv")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target.csv")

    response = await auth_client.post(
        "/api/v1/builder/upload/stage-batch",
        files=[("files", ("links.zip", payload.getvalue(), "application/zip"))],
    )

    assert response.status_code == 200
    receipt = response.json()
    assert receipt["file_count"] == 0
    assert receipt["refused_count"] == 1
    assert "symbolic links" in receipt["refusals"][0]["reason"]


@pytest.mark.anyio
async def test_staged_axis_column_csv_matrix_preview_and_commit(auth_client: AsyncClient):
    project = (await auth_client.post("/api/v1/projects", json={"name": "Preview Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Previewed CSV", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    csv_content = "Wavenumber (cm-1),Condition A,Condition B\n200,1.0,10.0\n201,2.0,20.0\n202,3.0,30.0\n"

    stage_response = await auth_client.post(
        "/api/v1/builder/upload/stage",
        files={"file": ("raman_conditions.csv", csv_content.encode("ascii"), "text/csv")},
    )
    assert stage_response.status_code == 200
    staged = stage_response.json()
    assert len(staged["assets"]) == 1
    assert staged["assets"][0]["asset_id"]

    matrix_response = await auth_client.post(
        "/api/v1/builder/data-matrix",
        json={"kind": "staged", "staging_id": staged["staging_id"]},
    )
    assert matrix_response.status_code == 200
    matrix = matrix_response.json()
    assert matrix["shape"] == [2, 3]
    assert matrix["shape_label"] == "samples x features"
    assert matrix["row_labels"] == ["Condition A", "Condition B"]
    assert matrix["col_labels"] == ["200", "201", "202"]
    assert matrix["matrix"] == [[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]]
    assert matrix["stats"]["summary"]["n_samples"] == 2
    assert matrix["stats"]["summary"]["n_features"] == 3

    commit_response = await auth_client.post(
        "/api/v1/builder/upload/commit",
        json={
            "experiment_id": experiment["id"],
            "stage": "raw",
            "files": [
                {
                    "staging_id": staged["staging_id"],
                    "overrides": {"x_title": "Raman Shift", "x_units": "cm-1", "y_title": "Intensity"},
                }
            ],
        },
    )
    assert commit_response.status_code == 200
    assert commit_response.json()["imported"] == 1

    files_response = await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files")
    assert files_response.status_code == 200
    listed = files_response.json()[0]
    assert listed["shape"] == [2, 3]
    assert listed["n_samples"] == 2
    assert listed["n_features"] == 3


@pytest.mark.anyio
async def test_staged_unheaded_supplier_csv_binds_profile_through_preview_commit_and_listing(
    auth_client: AsyncClient,
):
    project = (await auth_client.post("/api/v1/projects", json={"name": "Supplier CSV Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Supplier CSV", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    csv_content = "400.0,0.10\n401.0,0.20\n402.0,0.30\n403.0,0.40\n"

    stage_response = await auth_client.post(
        "/api/v1/builder/upload/stage",
        files={"file": ("supplier.csv", csv_content.encode("ascii"), "text/csv")},
    )

    assert stage_response.status_code == 200, stage_response.text
    staged = stage_response.json()
    assert staged["suggested_overrides"] == {"csv_layout": "headerless_two_column_spectrum"}
    assert staged["csv_import_plan"]["requires_confirmation"] is True
    assert staged["assets"][0]["shape"] == [1, 4]

    matrix_response = await auth_client.post(
        "/api/v1/builder/data-matrix",
        json={
            "kind": "staged",
            "staging_id": staged["staging_id"],
            "overrides": staged["suggested_overrides"],
        },
    )
    assert matrix_response.status_code == 200, matrix_response.text
    assert matrix_response.json()["shape"] == [1, 4]
    assert matrix_response.json()["matrix"] == [[0.1, 0.2, 0.3, 0.4]]

    commit_response = await auth_client.post(
        "/api/v1/builder/upload/commit",
        json={
            "experiment_id": experiment["id"],
            "stage": "raw",
            "files": [
                {
                    "staging_id": staged["staging_id"],
                    "overrides": staged["suggested_overrides"],
                }
            ],
        },
    )
    assert commit_response.status_code == 200, commit_response.text

    files_response = await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files")
    assert files_response.status_code == 200
    listed = files_response.json()[0]
    assert listed["shape"] == [1, 4]
    assert listed["n_samples"] == 1
    assert listed["n_features"] == 4


@pytest.mark.anyio
async def test_staged_and_persisted_opus_preview_requires_one_exact_asset(auth_client: AsyncClient):
    fixture = Path(__file__).parent / "fixtures" / "opus" / "openspecy-polystyrene.0"
    project = (await auth_client.post("/api/v1/projects", json={"name": "OPUS Preview"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "OPUS dataset", "metadata": {}, "project_id": project["id"]},
        )
    ).json()

    staged_response = await auth_client.post(
        "/api/v1/builder/upload/stage",
        files={"file": ("sample.0000", fixture.read_bytes(), "application/octet-stream")},
    )
    assert staged_response.status_code == 200
    staged = staged_response.json()
    assert [asset["asset_id"] for asset in staged["assets"]] == ["igsm", "sm", "a", "igrf", "rf"]

    omitted = await auth_client.post(
        "/api/v1/builder/data-matrix",
        json={"kind": "staged", "staging_id": staged["staging_id"]},
    )
    assert omitted.status_code == 400
    selected = await auth_client.post(
        "/api/v1/builder/data-matrix",
        json={"kind": "staged", "staging_id": staged["staging_id"], "asset_id": "a"},
    )
    assert selected.status_code == 200
    assert selected.json()["shape"] == [1, 2126]

    committed = await auth_client.post(
        "/api/v1/builder/upload/commit",
        json={
            "experiment_id": experiment["id"],
            "stage": "raw",
            "files": [{"staging_id": staged["staging_id"]}],
        },
    )
    assert committed.status_code == 200
    files = (await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files")).json()
    omitted_info = await auth_client.post(
        "/api/v1/builder/file-info",
        json={"experiment_id": experiment["id"], "file_path": files[0]["file_path"]},
    )
    assert omitted_info.status_code == 400
    selected_info = await auth_client.post(
        "/api/v1/builder/file-info",
        json={
            "experiment_id": experiment["id"],
            "file_path": files[0]["file_path"],
            "asset_id": "a",
        },
    )
    assert selected_info.status_code == 200
    assert selected_info.json()["n_features"] == 2126

    collection_info = await auth_client.post(
        "/api/v1/builder/file-info",
        json={"experiment_id": experiment["id"], "asset_id": "a"},
    )
    assert collection_info.status_code == 200
    collection_payload = collection_info.json()
    source_collection = collection_payload["metadata"]["source_collection"]
    assert collection_payload["dataset_id"]
    assert (
        collection_payload["metadata"]["api_serialization"]["full_dataset_handle"] == collection_payload["dataset_id"]
    )
    assert source_collection["schema_version"] == "spectrasherpa-source-collection/1"
    assert source_collection["file_count"] == 1
    assert source_collection["files"][0]["file_name"] == files[0]["file_path"]
    assert len(source_collection["files"][0]["prepared_data_sha256"]) == 64
    assert len(source_collection["manifest_digest"]) == 64


@pytest.mark.anyio
async def test_reference_sklearn_matrix_preview_includes_target_classes_and_stats(auth_client: AsyncClient):
    matrix_response = await auth_client.post(
        "/api/v1/builder/data-matrix",
        json={"kind": "reference", "source": "sklearn", "name": "iris"},
    )
    assert matrix_response.status_code == 200
    matrix = matrix_response.json()
    assert matrix["shape"] == [150, 4]
    assert matrix["shape_label"] == "samples x features"
    assert matrix["col_labels"] == [
        "sepal length (cm)",
        "sepal width (cm)",
        "petal length (cm)",
        "petal width (cm)",
    ]
    assert matrix["stats"]["summary"]["n_samples"] == 150
    assert matrix["stats"]["summary"]["n_features"] == 4
    assert matrix["stats"]["per_column"][0]["label"] == "sepal length (cm)"
    assert matrix["stats"]["per_column"][0]["count"] == 150

    target = matrix["target"]
    assert target["target_name"] == "Label"
    assert target["target_type"] == "categorical"
    assert target["n_classes"] == 3
    assert target["class_names"] == ["setosa", "versicolor", "virginica"]
    assert target["classes"] == [
        {"value": 0, "label": "setosa", "count": 50, "pct": pytest.approx(100 / 3)},
        {"value": 1, "label": "versicolor", "count": 50, "pct": pytest.approx(100 / 3)},
        {"value": 2, "label": "virginica", "count": 50, "pct": pytest.approx(100 / 3)},
    ]
