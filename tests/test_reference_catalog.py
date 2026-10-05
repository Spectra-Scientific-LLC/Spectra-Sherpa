"""
Tests for the reference dataset catalog API and metadata modules.

Covers:
- sklearn_info: SKLEARN_CATALOG, get_sklearn_dataset_info()
- Builder API: /reference-datasets, /reference-datasets/{source}/{name}
- Error handling: unknown source (400), unknown name (404)

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_reference_catalog.py -v --no-cov
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG
from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG, get_sklearn_dataset_info
from spectra_sherpa.app.lib.synthetic_references import (
    SYNTHETIC_REFERENCE_CATALOG,
    get_synthetic_reference_info,
    load_synthetic_reference_as_sherpa,
)

# ---------------------------------------------------------------------------
# Tests: sklearn_info module
# ---------------------------------------------------------------------------


class TestSklearnInfo:
    """Test the sklearn dataset metadata module."""

    def test_catalog_has_feature_table_entries(self):
        assert len(SKLEARN_CATALOG) == 3
        for name in ("iris", "wine", "breast_cancer"):
            assert name in SKLEARN_CATALOG

    def test_catalog_entries_have_label(self):
        for name, entry in SKLEARN_CATALOG.items():
            assert "label" in entry, f"{name} missing 'label'"

    def test_get_iris_info(self):
        info = get_sklearn_dataset_info("iris")
        assert info["name"] == "iris"
        assert info["source"] == "sklearn"
        assert info["n_samples"] == 150
        assert info["n_features"] == 4
        assert len(info["feature_names"]) == 4
        assert len(info["target_names"]) == 3
        assert "description" in info
        assert len(info["description"]) > 100  # DESCR is multi-paragraph

    def test_get_wine_info(self):
        info = get_sklearn_dataset_info("wine")
        assert info["n_samples"] == 178
        assert info["n_features"] == 13
        assert len(info["target_names"]) == 3

    def test_get_breast_cancer_info(self):
        info = get_sklearn_dataset_info("breast_cancer")
        assert info["n_samples"] == 569
        assert info["n_features"] == 30

    def test_invalid_name_raises(self):
        with pytest.raises(ValueError, match="Unknown sklearn dataset"):
            get_sklearn_dataset_info("nonexistent")

    def test_data_stats_are_numbers(self):
        info = get_sklearn_dataset_info("iris")
        assert isinstance(info["data_min"], float)
        assert isinstance(info["data_max"], float)
        assert isinstance(info["data_mean"], float)
        assert info["data_min"] < info["data_max"]


# ---------------------------------------------------------------------------
# Tests: synthetic reference datasets
# ---------------------------------------------------------------------------


class TestSyntheticReferences:
    """Test HITRAN-derived synthetic benchmark dataset packaging."""

    def test_catalog_contains_atmospheric_gas_benchmark(self):
        assert "Synthetic_atmospheric-6" in SYNTHETIC_REFERENCE_CATALOG
        entry = SYNTHETIC_REFERENCE_CATALOG["Synthetic_atmospheric-6"]
        assert entry["technique"] == "FTIR"
        assert entry["target_type"] == "continuous"

    def test_catalog_contains_atmospheric_gas_component_library(self):
        assert "Library_atmospheric-9" in SYNTHETIC_REFERENCE_CATALOG
        dataset = load_synthetic_reference_as_sherpa("Library_atmospheric-9")

        assert dataset.X.shape == (9, 7199)
        assert dataset.sample_axis is not None
        assert "Water" in list(dataset.sample_axis.labels or [])
        assert "Methane" in list(dataset.sample_axis.labels or [])
        assert dataset.units == "L mol^-1 cm^-1"
        assert dataset.domain is not None
        assert dataset.domain.data_quantity == "Molar absorption coefficient"
        assert dataset.get_extra("ground_truth.spectra_units") == ["L mol^-1 cm^-1"] * 9
        assert float(np.nanmax(dataset.X)) == pytest.approx(3053.589386031034)

    def test_mixture_and_library_keep_independent_axis_contracts(self):
        mixture = SYNTHETIC_REFERENCE_CATALOG["Synthetic_atmospheric-6"]
        library = SYNTHETIC_REFERENCE_CATALOG["Library_atmospheric-9"]

        assert mixture["expected_shape"] == (50, 5401)
        assert mixture["expected_axis_range"] == (600.0, 3300.0)
        assert library["expected_shape"] == (9, 7199)
        assert library["expected_axis_range"] == (400.002619, 3999.002619)

        library_info = get_synthetic_reference_info("Library_atmospheric-9")
        assert library_info["n_features"] == 7199
        assert library_info["wavenumber_min"] == pytest.approx(400.002619)
        assert library_info["wavenumber_max"] == pytest.approx(3999.002619)

    def test_atmospheric_gas_benchmark_loads_with_ground_truth_targets(self):
        dataset = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")

        assert dataset.X.shape == (50, 5401)
        assert dataset.units == "absorbance"
        assert dataset.domain is not None
        assert dataset.domain.data_quantity == "Absorbance"
        assert dataset.target is not None
        assert dataset.target.shape == (50, 6)
        assert dataset.target_context is not None
        assert dataset.target_context.target_units == "ppm"
        assert dataset.target_context.target_names[:3] == ["Carbon dioxide", "Carbon monoxide", "Water"]
        assert dataset.get_extra("ground_truth.spectra") is not None
        assert len(dataset.get_extra("ground_truth.spectra")) == 6
        assert dataset.get_extra("ground_truth.spectra_units") == ["L mol^-1 cm^-1"] * 6
        assert dataset.get_extra("ground_truth.spectra_names")[:3] == [
            "Carbon dioxide",
            "Carbon monoxide",
            "Water",
        ]
        assert dataset.get_extra("ground_truth.spectra_x")[0] == 600.0

    @pytest.mark.anyio
    async def test_data_source_synthetic_dataset_loads_first_party_reference(self):
        from spectra_sherpa.app.lib.synthetic_references import load_synthetic_reference_as_sherpa

        dataset = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
        assert dataset.X.shape == (50, 5401)
        assert dataset.target is not None
        assert dataset.target.shape == (50, 6)
        assert dataset.get_extra("synthetic.reference_name") == "Synthetic_atmospheric-6"
        assert dataset.get_extra("ground_truth.spectra") is not None

    def test_atmospheric_gas_benchmark_info_has_preview_and_axis(self):
        info = get_synthetic_reference_info("Synthetic_atmospheric-6")

        assert info["source"] == "synthetic"
        assert info["n_samples"] == 50
        assert info["n_features"] == 5401
        assert info["wavenumber_min"] == 600.0
        assert info["wavenumber_max"] == 3300.0
        # Backward-compatible aliases remain for older clients.
        assert info["wavelength_min"] == 600.0
        assert info["wavelength_max"] == 3300.0
        assert len(info["preview_spectra"]) > 0
        assert len(info["target_names"]) == 6


class TestEigenvectorInfoCrossCheck:
    """Additional cross-checks for Eigenvector runtime-download catalog entries."""

    def test_all_catalog_entries_declare_download_source(self):
        """All Eigenvector examples should remain cataloged without bundled raw data."""
        for name, entry in DATASET_CATALOG.items():
            assert entry["archive_url"].startswith("https://eigenvector.com/"), name
            assert entry["format"] in {"csv", "mat", "matlab_process_log"}
            assert entry["technique"]
            assert entry["description"]

    def test_default_info_reports_download_boundary_when_data_absent(self, monkeypatch, tmp_path):
        """Default Eigenvector info should fail clearly when no local/cache data exists."""
        import spectra_sherpa.app.lib.eigenvector as eigenvector
        import spectra_sherpa.app.services.eigenvector_datasets as ev

        empty_package_data = tmp_path / "empty-package-data"
        empty_package_data.mkdir()
        monkeypatch.setattr(eigenvector, "EIGENVECTOR_DATA_DIR", empty_package_data)
        monkeypatch.setattr(ev, "_runtime_data_dir", lambda: tmp_path / "runtime-cache")

        with pytest.raises(FileNotFoundError, match="no longer bundled"):
            ev.get_dataset_info("diesel_nir")


@pytest.mark.anyio
async def test_reference_dataset_catalog_exposes_known_source_filenames():
    from spectra_sherpa.app.api.v1.routes.builder import list_reference_datasets

    catalog = await list_reference_datasets()

    registered = catalog["registered"]
    assert [entry["name"] for entry in registered] == [
        "public-art-image-paint-demo-v1",
        "public-cgl-nir-lactate-v1",
        "public-corn-m5-moisture-v1",
        "public-corn-mp5-moisture-v1",
        "public-corn-mp6-moisture-v1",
        "public-diesel-d4052-v1",
        "public-diesel-high-level-d4052-v1",
        "public-diesel-low-level-b-d4052-v1",
        "public-iasim16-test1-v1",
        "public-metal-etch-machine-v1",
        "public-metal-etch-oes-v1",
        "public-metal-etch-rfm-v1",
        "public-nir-shootout-cal1-assay-v1",
        "public-nir-shootout-cal2-assay-v1",
        "public-nir-shootout-test1-assay-v1",
        "public-nir-shootout-test2-assay-v1",
        "public-nir-shootout-validation1-assay-v1",
        "public-nir-shootout-validation2-assay-v1",
    ]
    corn_registered = next(entry for entry in registered if entry["name"] == "public-corn-m5-moisture-v1")
    assert corn_registered == {
        "name": "public-corn-m5-moisture-v1",
        "source": "registered",
        "label": "Eigenvector Corn M5",
        "technique": "NIR",
        "is_spectra": True,
        "data_role": "X_spectra",
        "data_modality": "spectra",
        "description": (
            "Corn samples measured on three near-infrared instruments for calibration-transfer and regression work."
        ),
        "technical_summary": (
            "M5 instrument view of 80 matched corn samples: 700 NIR wavelength variables (nm); "
            "shared Moisture, Oil, Protein, and Starch properties."
        ),
        "provider": "Eigenvector Research",
        "provider_page": "https://eigenvector.com/resources/data-sets/",
        "download_url": "https://eigenvector.com/wp-content/uploads/2019/06/corn.mat_.zip",
        "attribution": "Eigenvector Research Corn instrument-standardization dataset; original samples from Cargill.",
        "no_endorsement": (
            "Eigenvector Research and the original contributors are not affiliated with, sponsoring, or endorsing "
            "Spectra Scientific or Spectra Sherpa."
        ),
        "admission": "exact_user_acquired_file",
        "availability": "exact_user_acquisition_required",
        "mounted": False,
        "expected_size_bytes": 1094488,
        "has_embedded_target": True,
        "target_type": "continuous",
        "target_fields": ["Moisture", "Oil", "Protein", "Starch"],
        "analysis_profile": {
            "primary_role": "X_spectra",
            "modality": "spectra",
            "technique": "NIR",
            "target_type": "continuous",
            "target_fields": ["Moisture", "Oil", "Protein", "Starch"],
            "identity_fields": ["sample_id", "specimen_id", "instrument"],
            "group_fields": ["specimen_id", "instrument"],
            "ordered_samples": False,
        },
        "dataset_package": {
            "package_id": "eigenvector-corn-v1",
            "package_title": "Eigenvector Corn",
            "package_description": (
                "The same 80 corn specimens measured on three near-infrared instruments, "
                "with one shared four-property annotation table."
            ),
            "assembly_mode": "homogeneous_collection",
            "artifact_ids": ["eigenvector-corn-archive-v1"],
            "view_id": "corn-m5",
            "view_label": "M5",
            "instrument": "M5",
            "cohort": "corn-80",
            "annotation_table": {
                "annotation_table_id": "corn-properties",
                "object_name": "propvals",
                "n_rows": 80,
                "fields": [
                    {"index": 0, "name": "Moisture", "target_type": "continuous", "units": None},
                    {"index": 1, "name": "Oil", "target_type": "continuous", "units": None},
                    {"index": 2, "name": "Protein", "target_type": "continuous", "units": None},
                    {"index": 3, "name": "Starch", "target_type": "continuous", "units": None},
                ],
                "values_sha256": "86c8c4889eefdc398ac31124d72d4169b182f53596f273cf802645a0cd4ad7e6",
            },
            "initially_selected": True,
            "relations": [
                {
                    "relation_id": "corn-instrument-views",
                    "relation_type": "same_specimens_aligned",
                    "view_ids": ["corn-m5", "corn-mp5", "corn-mp6"],
                    "row_identity": "source_row_index",
                }
            ],
        },
    }

    machine_registered = next(entry for entry in registered if entry["name"] == "public-metal-etch-machine-v1")
    assert machine_registered["is_spectra"] is False
    assert machine_registered["data_role"] == "X_features"
    assert machine_registered["technical_summary"] == (
        "Machine-sensor view of LAM 9600 etch wafers: 129 observations × 21 process variables; " "no embedded target."
    )
    oes_registered = next(entry for entry in registered if entry["name"] == "public-metal-etch-oes-v1")
    assert oes_registered["technical_summary"] == (
        "Optical-emission view of LAM 9600 etch wafers: 126 observations × 129 wavelengths (nm); " "no embedded target."
    )
    rfm_registered = next(entry for entry in registered if entry["name"] == "public-metal-etch-rfm-v1")
    assert rfm_registered["technical_summary"] == (
        "RF-monitor view of LAM 9600 etch wafers: 126 observations × 71 process variables; " "no embedded target."
    )
    corn_summaries = {
        entry["name"]: entry["technical_summary"] for entry in registered if entry["name"].startswith("public-corn-")
    }
    assert corn_summaries == {
        "public-corn-m5-moisture-v1": (
            "M5 instrument view of 80 matched corn samples: 700 NIR wavelength variables (nm); "
            "shared Moisture, Oil, Protein, and Starch properties."
        ),
        "public-corn-mp5-moisture-v1": (
            "MP5 instrument view of the same 80 corn samples: 700 NIR wavelength variables (nm); "
            "shared Moisture, Oil, Protein, and Starch properties."
        ),
        "public-corn-mp6-moisture-v1": (
            "MP6 instrument view of the same 80 corn samples: 700 NIR wavelength variables (nm); "
            "shared Moisture, Oil, Protein, and Starch properties."
        ),
    }
    assert all(entry["technical_summary"].endswith(".") for entry in registered)

    diesel = next(entry for entry in catalog["eigenvector"] if entry["name"] == "diesel_nir")
    assert diesel["file_path"] == "diesel_csv/diesel_spec.csv"
    assert diesel["files"] == ["diesel_csv/diesel_spec.csv", "diesel_csv/diesel_prop.csv"]
    assert diesel["requires_runtime_download"] is True
    assert diesel["download_page"] == "https://eigenvector.com/resources/data-sets/"

    corn = next(entry for entry in catalog["eigenvector"] if entry["name"] == "corn_m5")
    assert corn["files"] == ["corn_mat/corn.mat"]
    assert corn["target_fields"] == ["Moisture", "Oil", "Protein", "Starch"]

    synthetic = next(entry for entry in catalog["synthetic"] if entry["name"] == "Synthetic_atmospheric-6")
    assert synthetic["files"] == ["Synthetic_atmospheric-6.npz"]
    assert synthetic["target_fields"] == [
        "Carbon dioxide",
        "Carbon monoxide",
        "Water",
        "Methane",
        "Nitrous oxide",
        "Nitrogen dioxide",
    ]

    wine = next(entry for entry in catalog["sklearn"] if entry["name"] == "wine")
    assert wine["target_fields"] == ["target"]

    oes = next(entry for entry in catalog["oes"] if entry["name"] == "uvspectra10")
    assert oes["files"] == ["UVSpectra10.csv"]


@pytest.mark.anyio
async def test_demo_reference_catalog_advertises_only_governed_trial_inputs(monkeypatch):
    import spectra_sherpa.app.api.v1.routes.builder as builder
    import spectra_sherpa.app.services.experiments as experiment_services

    monkeypatch.setattr(builder.app_config, "site_profile", "demo")
    monkeypatch.setattr(experiment_services, "builtin_lavender_source_files", lambda: ["data/lavender-01.spa"])
    catalog = await builder.list_reference_datasets()
    assert [entry["name"] for entry in catalog["registered"]] == [
        "public-art-image-paint-demo-v1",
        "public-cgl-nir-lactate-v1",
        "public-corn-m5-moisture-v1",
        "public-corn-mp5-moisture-v1",
        "public-corn-mp6-moisture-v1",
        "public-diesel-d4052-v1",
        "public-diesel-high-level-d4052-v1",
        "public-diesel-low-level-b-d4052-v1",
        "public-iasim16-test1-v1",
        "public-metal-etch-machine-v1",
        "public-metal-etch-oes-v1",
        "public-metal-etch-rfm-v1",
        "public-nir-shootout-cal1-assay-v1",
        "public-nir-shootout-cal2-assay-v1",
        "public-nir-shootout-test1-assay-v1",
        "public-nir-shootout-test2-assay-v1",
        "public-nir-shootout-validation1-assay-v1",
        "public-nir-shootout-validation2-assay-v1",
    ]
    assert {entry["admission"] for entry in catalog["registered"]} == {"exact_user_acquired_file"}
    assert [entry["dataset_id"] for entry in catalog["builtin"]] == ["builtin:lavender-essential-oil-v1"]
    assert [entry["name"] for entry in catalog["synthetic"]] == list(SYNTHETIC_REFERENCE_CATALOG)
    assert [entry["name"] for entry in catalog["sklearn"]] == list(SKLEARN_CATALOG)
    assert catalog["eigenvector"] == []
    assert catalog["oes"] == []


@pytest.mark.anyio
async def test_unmounted_builtin_is_not_advertised_as_available(monkeypatch):
    import spectra_sherpa.app.api.v1.routes.builder as builder
    import spectra_sherpa.app.services.experiments as experiment_services

    monkeypatch.setattr(experiment_services, "builtin_lavender_source_files", lambda: [])

    catalog = await builder.list_reference_datasets()

    assert catalog["builtin"] == []


@pytest.mark.anyio
async def test_registered_catalog_distinguishes_governed_identity_from_mounted_bytes():
    import spectra_sherpa.app.api.v1.routes.builder as builder

    catalog = await builder.list_reference_datasets()

    assert catalog["registered"]
    assert {entry["availability"] for entry in catalog["registered"]} == {"exact_user_acquisition_required"}
    assert {entry["mounted"] for entry in catalog["registered"]} == {False}
    assert {entry["admission"] for entry in catalog["registered"]} == {"exact_user_acquired_file"}


@pytest.mark.anyio
async def test_every_embedded_target_catalog_entry_exposes_selectable_target_fields():
    """The starter wizard must never offer a target-bearing dataset with an empty target menu."""
    from spectra_sherpa.app.api.v1.routes.builder import list_reference_datasets

    catalog = await list_reference_datasets()

    missing = [
        f"{source}:{entry['name']}"
        for source, entries in catalog.items()
        for entry in entries
        if entry.get("has_embedded_target") and not entry.get("target_fields")
    ]

    assert missing == []


def test_synthetic_catalog_target_fields_match_materialized_target_context():
    """Catalog target labels remain bound to the packaged synthetic dataset rather than drifting."""
    for name, entry in SYNTHETIC_REFERENCE_CATALOG.items():
        info = get_synthetic_reference_info(name)
        assert entry["target_fields"] == info["target_names"]


@pytest.mark.anyio
async def test_msc_examples_have_no_invented_supervised_target_in_catalogs():
    from spectra_sherpa.app.api.v1.routes.builder import list_reference_datasets
    from spectra_sherpa.app.api.v1.routes.workflow_templates import _build_flat_catalog

    builder = (await list_reference_datasets())["synthetic"]
    matching = _build_flat_catalog()
    for name in ("msc_application_spectra", "msc_reference_spectra"):
        for catalog in (builder, matching):
            entry = next(row for row in catalog if row["name"] == name)
            assert entry["has_embedded_target"] is False
            assert entry["target_type"] is None
            assert entry["target_fields"] == []
