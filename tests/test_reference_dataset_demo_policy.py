from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes import builder as builder_routes
from spectra_sherpa.app.api.v1.routes import experiments as experiment_routes
from spectra_sherpa.app.contracts.demo_policy import DemoPolicy, set_demo_policy_provider
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    FeatureAxis,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.app.schemas.experiments import ReferenceDatasetImportRequest
from spectra_sherpa.app.services import experiments as experiment_services


@pytest.fixture(autouse=True)
def _clear_demo_policy_provider():
    yield
    set_demo_policy_provider(lambda: DemoPolicy())


@pytest.mark.anyio
async def test_demo_reference_catalog_keeps_server_supplied_sources(monkeypatch) -> None:
    monkeypatch.setattr(app_config, "site_profile", "demo")
    monkeypatch.setattr(experiment_services, "builtin_lavender_source_files", lambda: ["data/fixture.spa"])

    catalog = await builder_routes.list_reference_datasets()

    assert catalog["builtin"]
    assert catalog["registered"]
    assert catalog["synthetic"]
    assert catalog["sklearn"]
    assert catalog["eigenvector"] == []
    assert catalog["oes"] == []

    monkeypatch.setattr(experiment_services, "builtin_lavender_source_files", lambda: [])
    unavailable = await builder_routes.list_reference_datasets()
    assert unavailable["builtin"] == []


def test_demo_reference_import_policy_allows_builtin_lavender(monkeypatch) -> None:
    monkeypatch.setattr(app_config, "site_profile", "demo")
    set_demo_policy_provider(lambda: DemoPolicy(disabled_capabilities=frozenset({"reference_data_import"})))
    payload = ReferenceDatasetImportRequest(
        datasets=[{"source": "builtin", "name": "lavender-essential-oil-v1"}],
    )

    experiment_routes._enforce_reference_import_policy(payload)


@pytest.mark.anyio
async def test_builtin_lavender_preview_applies_validated_collection_definition(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "lavender-essential-oil-v1.zip"
    fixture_path = Path(__file__).parent / "fixtures" / "omnic" / "openspecy-polyethylene-reflectance.spa"
    content = fixture_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    files: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []

    with zipfile.ZipFile(archive_path, "w") as archive:
        for index in range(33):
            source_name = f"lavender-{index + 1:02d}.spa"
            archive.writestr(f"lavender-essential-oil-v1/data/{source_name}", content)
            files.append(
                {
                    "path": f"data/{source_name}",
                    "size_bytes": len(content),
                    "sha256": digest,
                }
            )
            rows.append(
                {
                    "file_name": f"raw/{source_name}",
                    "sha256": digest,
                    "asset_id": "spectrum",
                    "source_row_index": 0,
                    "sample_id": f"LV-{index + 1:02d}",
                    "annotations": {
                        "sample_id": f"LV-{index + 1:02d}",
                        "specimen_id": f"Specimen-{index + 1:02d}",
                        "block": "A",
                    },
                }
            )
        archive.writestr(
            "lavender-essential-oil-v1/manifest.json",
            json.dumps(
                {
                    "schema_version": "spectrasherpa-avatar-essential-oils-distribution/2",
                    "dataset_id": "avatar-essential-oils/1",
                    "counts": {"files": 33, "specimens": 11, "blocks": 3},
                    "files": files,
                }
            ),
        )
        archive.writestr(
            "lavender-essential-oil-v1/collection-definition.json",
            json.dumps(
                {
                    "schema_version": "spectrasherpa-collection-definition/1",
                    "columns": ["sample_id", "specimen_id", "block"],
                    "collection": {
                        "dataset_id": "avatar-essential-oils/1",
                        "title": "Lavender Essential Oil FTIR Corpus v1",
                        "units": "reflectance",
                        "data_role": "X_spectra",
                        "domain": DomainContext(
                            technique="FTIR",
                            sample_type="essential oil",
                            expected_units="cm-1",
                            data_quantity="Reflectance",
                        ).model_dump(mode="json", exclude_none=False),
                        "sample_axis": {
                            "title": "Lavender samples",
                            "units": None,
                            "values_policy": "omit",
                        },
                    },
                    "rows": rows,
                }
            ),
        )

    from spectra_sherpa.app.services import experiments as experiment_services

    monkeypatch.setattr(experiment_services, "_builtin_lavender_archive_path", lambda: archive_path)

    catalog = await builder_routes.list_reference_datasets()
    [lavender] = catalog["builtin"]
    assert lavender["file_count"] == 33
    assert lavender["files"][:2] == ["data/lavender-01.spa", "data/lavender-02.spa"]
    assert lavender["files"][-1] == "data/lavender-33.spa"

    matrix = await builder_routes.get_data_matrix(
        builder_routes.DataMatrixRequest(
            kind="reference",
            source="builtin",
            name="lavender-essential-oil-v1",
        ),
        session=object(),
        current_user=object(),
    )

    assert matrix["shape"] == [33, 1738]
    assert matrix["row_labels"][:2] == ["LV-01", "LV-02"]
    assert matrix["data_role"] == "X_spectra"
    assert matrix["target"] is None


@pytest.mark.anyio
async def test_demo_reference_preview_ignores_import_capability(monkeypatch) -> None:
    monkeypatch.setattr(app_config, "site_profile", "demo")
    set_demo_policy_provider(lambda: DemoPolicy(disabled_capabilities=frozenset({"reference_data_import"})))

    def fake_reference_dataset(source: str, name: str) -> SherpaDataset:
        assert source == "eigenvector"
        assert name == "corn_m5"
        return SherpaDataset(
            X=np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64),
            feature_axis=SpectralAxis(values=np.asarray([1100.0, 1102.0]), title="Wavelength", units="nm"),
            sample_axis=SampleAxis(labels=["A", "B"], title="Sample"),
            title="Corn M5",
            data_role="X_spectra",
        )

    monkeypatch.setattr(builder_routes, "_reference_dataset_as_sherpa", fake_reference_dataset)

    matrix = await builder_routes.get_data_matrix(
        builder_routes.DataMatrixRequest(kind="reference", source="eigenvector", name="corn_m5"),
        session=object(),
        current_user=object(),
    )

    assert matrix["shape"] == [2, 2]
    assert matrix["matrix"] == [[1.0, 2.0], [3.0, 4.0]]


def test_demo_reference_import_policy_rejects_general_eigenvector_loader(monkeypatch) -> None:
    monkeypatch.setattr(app_config, "site_profile", "demo")
    set_demo_policy_provider(lambda: DemoPolicy(disabled_capabilities=frozenset({"reference_data_import"})))
    payload = ReferenceDatasetImportRequest(
        datasets=[{"source": "eigenvector", "name": "corn_m5"}],
    )

    with pytest.raises(HTTPException) as exc:
        experiment_routes._enforce_reference_import_policy(payload)

    assert exc.value.status_code == 403
    assert "server-issued datasets" in str(exc.value.detail)


def test_res41_eigenvector_alias_binding_preserves_governed_dataset_custody(monkeypatch) -> None:
    governed = SherpaDataset(
        X=np.asarray([[1.0, 2.0], [3.0, 4.0]]),
        feature_axis=SpectralAxis(values=np.asarray([1000.0, 1002.0]), title="Wavelength", units="nm"),
        sample_axis=SampleAxis(
            labels=["specimen-1", "specimen-2"],
            title="Specimen",
            sample_table={"specimen_id": ["S1", "S2"], "analysis_role": ["calibration", "test"]},
        ),
        target=np.asarray([0.8, 0.9]),
        target_context=TargetContext(
            target_type="continuous",
            target_name="Density",
            target_names=["Density"],
            target_units="g/mL",
        ),
        data_role="X_spectra",
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.eigenvector_datasets.load_eigenvector_dataset",
        lambda _name: {"dataset": governed, "catalog_entry": {"label": "Governed source"}},
    )

    result = builder_routes._reference_dataset_as_sherpa("eigenvector", "corn_m5")

    np.testing.assert_array_equal(result.target, [0.8, 0.9])
    assert result.target_context.target_names == ["Density"]
    assert result.sample_axis.sample_table == {
        "specimen_id": ["S1", "S2"],
        "analysis_role": ["calibration", "test"],
    }
    assert result.title == "Governed source"


def test_legacy_process_alias_preserves_feature_modality_and_sensor_names(monkeypatch) -> None:
    governed = SherpaDataset(
        X=np.asarray([[101.0, 20.0], [102.0, 21.0]]),
        feature_axis=FeatureAxis(labels=["pressure_kPa", "temperature_C"], title="Sensor"),
        sample_axis=SampleAxis(
            labels=["wafer-1", "wafer-2"],
            title="Wafer",
            sample_table={"sample_id": ["W1", "W2"], "analysis_role": ["normal", "fault"]},
        ),
        data_role="X_features",
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.eigenvector_datasets.load_eigenvector_dataset",
        lambda _name: {"dataset": governed, "catalog_entry": {"label": "Metal Etch Machine"}},
    )

    result = builder_routes._reference_dataset_as_sherpa("eigenvector", "metal_etch_machine")

    assert result.data_role == "X_features"
    assert type(result.feature_axis) is FeatureAxis
    assert result.feature_axis.labels == ["pressure_kPa", "temperature_C"]
    assert result.sample_axis.labels == ["wafer-1", "wafer-2"]
    assert result.sample_axis.sample_table["analysis_role"] == ["normal", "fault"]


def test_builtin_lavender_must_be_imported_as_its_own_collection() -> None:
    payload = ReferenceDatasetImportRequest(
        datasets=[
            {"source": "builtin", "name": "lavender-essential-oil-v1"},
            {"source": "sklearn", "name": "iris"},
        ],
    )

    with pytest.raises(HTTPException) as exc:
        experiment_routes._enforce_reference_import_batch(payload)

    assert exc.value.status_code == 400
    assert "own My Dataset" in str(exc.value.detail)
