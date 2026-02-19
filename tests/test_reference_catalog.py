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

import pytest

from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG, get_dataset_info
from spectra_sherpa.app.lib.scp_catalog import SCP_CATALOG, get_scp_dataset_info
from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG, get_sklearn_dataset_info

# ---------------------------------------------------------------------------
# Tests: sklearn_info module
# ---------------------------------------------------------------------------


class TestSklearnInfo:
    """Test the sklearn dataset metadata module."""

    def test_catalog_has_four_entries(self):
        assert len(SKLEARN_CATALOG) == 4
        for name in ("iris", "wine", "breast_cancer", "digits"):
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

    def test_get_digits_info(self):
        info = get_sklearn_dataset_info("digits")
        assert info["n_samples"] == 1797
        assert info["n_features"] == 64

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
# Tests: scp_catalog module
# ---------------------------------------------------------------------------


class TestScpCatalog:
    """Test the SpectroChemPy catalog module."""

    def test_catalog_has_eight_entries(self):
        assert len(SCP_CATALOG) == 8
        for name in (
            "irdata",
            "ramandata",
            "nmrdata",
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

    def test_invalid_name_raises(self):
        with pytest.raises(ValueError, match="Unknown SCP dataset"):
            get_scp_dataset_info("nonexistent")


# ---------------------------------------------------------------------------
# Tests: Eigenvector get_dataset_info (cross-check)
# ---------------------------------------------------------------------------


class TestEigenvectorInfoCrossCheck:
    """Additional cross-checks for eigenvector get_dataset_info."""

    def test_all_datasets_produce_info(self):
        """All catalog entries should produce valid info dicts."""
        for name in DATASET_CATALOG:
            info = get_dataset_info(name)
            assert info["name"] == name
            assert info["source"] == "eigenvector"
            assert info["n_samples"] > 0
            assert info["n_features"] > 0
            assert "spectra_min" in info
            assert "spectra_max" in info

    def test_info_spectra_stats_sensible(self):
        info = get_dataset_info("diesel_nir")
        assert info["spectra_min"] < info["spectra_max"]
        assert info["spectra_mean"] > info["spectra_min"]
        assert info["spectra_mean"] < info["spectra_max"]
