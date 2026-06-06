"""Tests for experiment endpoints"""

from __future__ import annotations

import csv

import pytest
from httpx import AsyncClient

from spectra_sherpa.app.models.user import User


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
    assert spectrum["x_units"] == "1/CM"
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
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n"
        "200,2139,9549\n"
        "201,2159,9538\n"
        "202,2178,9537\n"
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
async def test_staged_axis_column_csv_matrix_preview_and_commit(auth_client: AsyncClient):
    project = (await auth_client.post("/api/v1/projects", json={"name": "Preview Project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Previewed CSV", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    csv_content = "Wavenumber (cm-1),Condition A,Condition B\n" "200,1.0,10.0\n" "201,2.0,20.0\n" "202,3.0,30.0\n"

    stage_response = await auth_client.post(
        "/api/v1/builder/upload/stage",
        files={"file": ("raman_conditions.csv", csv_content.encode("ascii"), "text/csv")},
    )
    assert stage_response.status_code == 200
    staged = stage_response.json()

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
