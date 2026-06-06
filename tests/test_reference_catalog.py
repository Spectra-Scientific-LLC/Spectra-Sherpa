"""
Tests for the reference dataset catalog API and metadata modules.

Covers:
- sklearn_info: SKLEARN_CATALOG, get_sklearn_dataset_info()
- scp_catalog: SCP_CATALOG, get_scp_dataset_info()
- Builder API: /reference-datasets, /reference-datasets/{source}/{name}
- Error handling: unknown source (400), unknown name (404)

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_reference_catalog.py -v --no-cov
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG
from spectra_sherpa.app.lib.sample_labels import clean_sample_labels
from spectra_sherpa.app.lib.scp_catalog import (
    SCP_CATALOG,
    _concat_compatible_sherpa,
    build_scp_catalog,
    get_scp_dataset_info,
)
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
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
        from spectra_sherpa.app.services.dag.nodes.data.source import DataSourceNode

        node = DataSourceNode("data_1", {"source": "synthetic", "synthetic_dataset": "Synthetic_atmospheric-6"})
        result = await node.execute()

        dataset = result["default"]
        assert dataset.X.shape == (50, 5401)
        assert dataset.target is not None
        assert dataset.target.shape == (50, 6)
        assert dataset.get_extra("reference_name") == "Synthetic_atmospheric-6"
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


# ---------------------------------------------------------------------------
# Tests: scp_catalog module
# ---------------------------------------------------------------------------


class TestScpCatalog:
    """Test the SpectroChemPy catalog module."""

    def test_catalog_has_public_spectroscopy_entries(self):
        assert len(SCP_CATALOG) == 7
        for name in (
            "irdata",
            "ramandata",
            "galacticdata",
            "agirdata",
            "matlabdata",
            "msdata",
            "dscdata",
        ):
            assert name in SCP_CATALOG

    def test_catalog_entries_have_required_fields(self):
        for name, entry in SCP_CATALOG.items():
            assert "label" in entry, f"{name} missing 'label'"
            assert "technique" in entry, f"{name} missing 'technique'"
            assert "description" in entry, f"{name} missing 'description'"

    def test_get_irdata_info(self):
        info = get_scp_dataset_info("irdata")
        assert info["name"] == "irdata"
        assert info["source"] == "spectrochempy"
        assert info["technique"] == "FTIR"
        assert len(info["description"]) > 10

    def test_get_ramandata_info(self):
        info = get_scp_dataset_info("ramandata")
        assert info["technique"] == "Raman"

    def test_build_catalog_hides_non_importable_nmr_examples(self):
        pytest.importorskip("spectrochempy", reason="SpectroChemPy not installed")
        entries = build_scp_catalog(force=True)
        nmr_entries = [entry for entry in entries if entry.get("technique") == "NMR"]
        assert nmr_entries == []

    def test_build_catalog_uses_preferred_complete_datadir(self, monkeypatch, tmp_path):
        partial = tmp_path / "partial"
        complete = tmp_path / "complete"

        (partial / "irdata").mkdir(parents=True)

        for dirname in ("irdata", "ramandata", "nmrdata", "galacticdata", "agirdata"):
            (complete / dirname).mkdir(parents=True, exist_ok=True)
        (complete / "irdata" / "nh4y-activation.spg").write_text("x")
        (complete / "irdata" / "OPUS").mkdir(parents=True)
        for idx in range(4):
            (complete / "irdata" / "OPUS" / f"test.{idx:04d}").write_text("x")
        (complete / "ramandata" / "wire").mkdir(parents=True)
        (complete / "ramandata" / "wire" / "sp.wdf").write_text("x")
        nested_nmr = complete / "nmrdata" / "bruker" / "tests" / "nmr" / "topspin_1d" / "1"
        nested_nmr.mkdir(parents=True)
        (nested_nmr / "fid").write_text("x")
        for idx in range(30):
            (complete / "irdata" / f"sample_{idx}.SPA").write_text("x")

        monkeypatch.setattr(
            "spectra_sherpa.app.lib.scp_compat.get_preferred_scp_datadir",
            lambda: complete,
        )

        entries = build_scp_catalog(force=True)

        assert any(entry["name"] == "irdata/nh4y-activation.spg" for entry in entries)
        opus_entry = next(entry for entry in entries if entry["name"] == "irdata/OPUS")
        assert opus_entry["files"] == [
            "irdata/OPUS/test.0000",
            "irdata/OPUS/test.0001",
            "irdata/OPUS/test.0002",
            "irdata/OPUS/test.0003",
        ]
        assert not any(entry["name"] == "nmrdata/bruker/tests/nmr/topspin_1d/1" for entry in entries)

    def test_invalid_name_raises(self):
        with pytest.raises(ValueError, match="Unknown SCP dataset"):
            get_scp_dataset_info("nonexistent")

    def test_concat_compatible_sherpa_rejects_interior_axis_mismatch(self):
        first = SherpaDataset(
            np.array([[1.0, 2.0, 3.0]]),
            feature_axis=SpectralAxis(values=np.array([100.0, 200.0, 300.0]), units="cm-1"),
            sample_axis=SampleAxis(labels=["first"]),
        )
        second = SherpaDataset(
            np.array([[4.0, 5.0, 6.0]]),
            feature_axis=SpectralAxis(values=np.array([100.0, 250.0, 300.0]), units="cm-1"),
            sample_axis=SampleAxis(labels=["second"]),
        )

        with pytest.raises(ValueError, match="incompatible feature axes"):
            _concat_compatible_sherpa([(first, Path("first.spa")), (second, Path("second.spa"))], title="bad")

    def test_concat_compatible_sherpa_stacks_full_axis_match(self):
        axis = np.array([100.0, 200.0, 300.0])
        first = SherpaDataset(
            np.array([[1.0, 2.0, 3.0]]),
            feature_axis=SpectralAxis(values=axis, units="cm-1"),
            sample_axis=SampleAxis(labels=["first"]),
        )
        second = SherpaDataset(
            np.array([[4.0, 5.0, 6.0]]),
            feature_axis=SpectralAxis(values=axis.copy(), units="cm-1"),
            sample_axis=SampleAxis(labels=["second"]),
        )

        stacked = _concat_compatible_sherpa([(first, Path("first.spa")), (second, Path("second.spa"))], title="ok")

        assert stacked.X.shape == (2, 3)
        assert stacked.sample_axis is not None
        assert stacked.sample_axis.labels == ["first", "second"]

    def test_concat_compatible_sherpa_shortens_verbose_scp_labels_into_sample_metadata(self):
        axis = np.array([100.0, 200.0, 300.0])
        raw_label = (
            "[datetime.datetime(2020, 11, 4, 17, 21, 31, 995000), "
            "PosixPath('/tmp/irdata/carroucell_samp/10-Z22-Si-S7_0.spa')]"
        )
        dataset = SherpaDataset(
            np.array([[1.0, 2.0, 3.0]]),
            feature_axis=SpectralAxis(values=axis, units="cm-1"),
            sample_axis=SampleAxis(labels=[raw_label]),
        )

        stacked = _concat_compatible_sherpa([(dataset, Path("10-Z22-Si-S7_0.spa"))], title="FTIR")

        assert stacked.sample_axis is not None
        assert stacked.sample_axis.labels == ["10-Z22-Si-S7_0"]
        assert stacked.sample_axis.sample_table is not None
        assert stacked.sample_axis.sample_table["source_file"] == ["10-Z22-Si-S7_0.spa"]
        assert stacked.sample_axis.sample_table["acquired_datetime"] == ["2020-11-04T17:21:31"]

    def test_concat_compatible_sherpa_extracts_time_series_sample_metadata(self):
        axis = np.array([100.0, 200.0, 300.0])
        dataset = SherpaDataset(
            np.array([[1.0, 2.0, 3.0], [1.5, 2.5, 3.5]]),
            feature_axis=SpectralAxis(values=axis, units="cm-1"),
            sample_axis=SampleAxis(labels=["Linked spectrum at 0.025 min", "Linked spectrum at 0.050 min"]),
        )

        stacked = _concat_compatible_sherpa([(dataset, Path("GC_Demo.srs"))], title="OMNIC")

        assert stacked.sample_axis is not None
        assert stacked.sample_axis.labels == ["0.025 min", "0.050 min"]
        assert stacked.sample_axis.title == "Time"
        assert stacked.sample_axis.units == "min"
        np.testing.assert_allclose(stacked.sample_axis.values, np.array([0.025, 0.05]))
        assert stacked.sample_axis.sample_table is not None
        assert stacked.sample_axis.sample_table["time_value"] == [0.025, 0.05]
        assert stacked.sample_axis.sample_table["time_units"] == ["min", "min"]
        assert "raw_label" not in stacked.sample_axis.sample_table

    def test_concat_compatible_sherpa_normalizes_time_unit_words(self):
        dataset = SherpaDataset(
            np.array([[1.0, 2.0, 3.0], [1.5, 2.5, 3.5]]),
            feature_axis=SpectralAxis(values=np.array([100.0, 200.0, 300.0]), units="cm-1"),
            sample_axis=SampleAxis(labels=["Linked spectrum at 0.003 minutes", "Linked spectrum at 0.007 min"]),
        )

        stacked = _concat_compatible_sherpa([(dataset, Path("TGA_demo.srs"))], title="TGA")

        assert stacked.sample_axis is not None
        assert stacked.sample_axis.labels == ["0.003 min", "0.007 min"]
        assert stacked.sample_axis.title == "Time"
        assert stacked.sample_axis.units == "min"
        np.testing.assert_allclose(stacked.sample_axis.values, np.array([0.003, 0.007]))

    def test_concat_compatible_sherpa_promotes_clean_time_labels_to_sample_axis(self):
        dataset = SherpaDataset(
            np.array([[1.0, 2.0, 3.0], [1.5, 2.5, 3.5]]),
            feature_axis=SpectralAxis(values=np.array([100.0, 200.0, 300.0]), units="cm-1"),
            sample_axis=SampleAxis(labels=["0.003 min", "0.007 min"]),
        )

        stacked = _concat_compatible_sherpa([(dataset, Path("high_speed.srs"))], title="High Speed")

        assert stacked.sample_axis is not None
        assert stacked.sample_axis.labels == ["0.003 min", "0.007 min"]
        assert stacked.sample_axis.title == "Time"
        assert stacked.sample_axis.units == "min"
        np.testing.assert_allclose(stacked.sample_axis.values, np.array([0.003, 0.007]))

    def test_concat_compatible_sherpa_converts_mixed_time_units_to_seconds(self):
        dataset = SherpaDataset(
            np.array([[1.0, 2.0, 3.0], [1.5, 2.5, 3.5]]),
            feature_axis=SpectralAxis(values=np.array([100.0, 200.0, 300.0]), units="cm-1"),
            sample_axis=SampleAxis(labels=["Linked spectrum at 500 ms", "Linked spectrum at 1 sec"]),
        )

        stacked = _concat_compatible_sherpa([(dataset, Path("TGA_demo.srs"))], title="TGA")

        assert stacked.sample_axis is not None
        assert stacked.sample_axis.labels == ["500 ms", "1 s"]
        assert stacked.sample_axis.title == "Time"
        assert stacked.sample_axis.units == "s"
        np.testing.assert_allclose(stacked.sample_axis.values, np.array([0.5, 1.0]))

    def test_concat_compatible_sherpa_drops_binary_reader_raw_label_metadata(self):
        dataset = SherpaDataset(
            np.array([[1.0, 2.0, 3.0]]),
            feature_axis=SpectralAxis(values=np.array([100.0, 200.0, 300.0]), units="cm-1"),
            sample_axis=SampleAxis(labels=["Linked spectrum at 0.083 min.\n\x12\n(binary-reader-payload)"]),
        )

        stacked = _concat_compatible_sherpa([(dataset, Path("TGA_demo.srs"))], title="TGA")

        assert stacked.sample_axis is not None
        assert stacked.sample_axis.labels == ["0.083 min"]
        assert stacked.sample_axis.title == "Time"
        assert stacked.sample_axis.units == "min"
        np.testing.assert_allclose(stacked.sample_axis.values, np.array([0.083]))
        assert stacked.sample_axis.sample_table is not None
        assert stacked.sample_axis.sample_table["time_value"] == [0.083]
        assert "raw_label" not in stacked.sample_axis.sample_table

    def test_clean_sample_labels_replaces_collapsed_generic_values_with_indices(self):
        labels = clean_sample_labels(["normal", "normal", "normal"], 3)

        assert labels == ["Sample 001", "Sample 002", "Sample 003"]

    def test_clean_sample_labels_preserves_repeated_class_values(self):
        labels = clean_sample_labels(["control", "treated", "control", "treated"], 4)

        assert labels == ["control", "treated", "control", "treated"]

    def test_clean_sample_labels_preserves_descriptive_quantity_labels(self):
        labels = clean_sample_labels(
            [
                "Sample at 5 ppm CO concentration",
                "Sample at 5 ppm NO concentration",
                "Reaction after 10 min, cooling step one",
                "Batch 2020 torr run A",
            ],
            4,
        )

        assert labels == [
            "Sample at 5 ppm CO concentration",
            "Sample at 5 ppm NO concentration",
            "Reaction after 10 min, cooling step one",
            "Batch 2020 torr run A",
        ]

    def test_clean_sample_labels_normalizes_bare_quantity_labels(self):
        labels = clean_sample_labels(["0.003 minutes", "5 ppm"], 2)

        assert labels == ["0.003 min", "5 ppm"]

    def test_clean_sample_labels_removes_reader_prefix_from_numbered_samples(self):
        labels = clean_sample_labels(["ion_currents: sample 1", "ion_currents: sample 2"], 2)

        assert labels == ["sample 1", "sample 2"]

    def test_clean_sample_labels_preserves_numbered_opus_filenames(self):
        labels = clean_sample_labels(
            ["PosixPath('/tmp/irdata/OPUS/test.0000')", "PosixPath('/tmp/irdata/OPUS/test.0001')"],
            2,
        )

        assert labels == ["test.0000", "test.0001"]

    def test_concat_compatible_sherpa_uses_indices_when_multisample_file_has_no_labels(self):
        dataset = SherpaDataset(
            np.ones((3, 4)),
            feature_axis=SpectralAxis(values=np.arange(4.0), units="m/z"),
            sample_axis=None,
        )

        stacked = _concat_compatible_sherpa([(dataset, Path("ion_currents.asc"))], title="MS")

        assert stacked.sample_axis is not None
        assert stacked.sample_axis.labels == ["Sample 001", "Sample 002", "Sample 003"]


# ---------------------------------------------------------------------------
# Tests: Eigenvector get_dataset_info (cross-check)
# ---------------------------------------------------------------------------


class TestEigenvectorInfoCrossCheck:
    """Additional cross-checks for Eigenvector runtime-download catalog entries."""

    def test_all_catalog_entries_declare_download_source(self):
        """All Eigenvector examples should remain cataloged without bundled raw data."""
        for name, entry in DATASET_CATALOG.items():
            assert entry["archive_url"].startswith("https://eigenvector.com/"), name
            assert entry["format"] in {"csv", "mat", "metal_etch"}
            assert entry["technique"]
            assert entry["description"]

    def test_default_info_reports_download_boundary_when_data_absent(self, monkeypatch, tmp_path):
        """Default Eigenvector info should fail clearly when no local/cache data exists."""
        import spectra_sherpa.app.lib.eigenvector as ev

        empty_package_data = tmp_path / "empty-package-data"
        empty_package_data.mkdir()
        monkeypatch.setattr(ev, "EIGENVECTOR_DATA_DIR", empty_package_data)
        monkeypatch.setattr(ev, "_runtime_data_dir", lambda: tmp_path / "runtime-cache")
        monkeypatch.setenv(ev.EIGENVECTOR_RUNTIME_DOWNLOAD_ENV, "false")

        with pytest.raises(FileNotFoundError, match="no longer bundled"):
            ev.get_dataset_info("diesel_nir")


@pytest.mark.anyio
async def test_reference_dataset_catalog_exposes_known_source_filenames():
    from spectra_sherpa.app.api.v1.routes.builder import list_reference_datasets

    catalog = await list_reference_datasets()

    diesel = next(entry for entry in catalog["eigenvector"] if entry["name"] == "diesel_nir")
    assert diesel["file_path"] == "diesel_csv/diesel_spec.csv"
    assert diesel["files"] == ["diesel_csv/diesel_spec.csv", "diesel_csv/diesel_prop.csv"]
    assert diesel["requires_runtime_download"] is True
    assert diesel["download_page"] == "https://eigenvector.com/resources/data-sets/"

    corn = next(entry for entry in catalog["eigenvector"] if entry["name"] == "corn_m5")
    assert corn["files"] == ["corn_mat/corn.mat"]

    synthetic = next(entry for entry in catalog["synthetic"] if entry["name"] == "Synthetic_atmospheric-6")
    assert synthetic["files"] == ["Synthetic_atmospheric-6.npz"]

    oes = next(entry for entry in catalog["oes"] if entry["name"] == "uvspectra10")
    assert oes["files"] == ["UVSpectra10.csv"]
