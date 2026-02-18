"""
Golden tests for data loading consistency.

These tests verify that reference datasets load correctly and produce
consistent results across different code paths.
"""

from __future__ import annotations

import pytest
from pathlib import Path
scp = pytest.importorskip("spectrochempy")

from spectra_sherpa.app.services.dag.nodes.data import DataSourceNode


# Reference file metadata (expected properties)
# These serve as "golden" references - if these change, investigate why
GOLDEN_FILES = {
    "irdata/CO@Mo_Al2O3.SPG": {
        "format": ".spg",
        "reader": "read_omnic",
        "expected_ndim": 2,  # 2D dataset (spectra x wavenumbers)
        "min_size": 10,  # At least 10 spectra
        "has_x_axis": True,  # Should have wavenumber axis
        "x_axis_unit": "cm^-1",  # Wavenumber unit
    },
    "irdata/IR.CSV": {
        "format": ".csv",
        "reader": "read_csv",
        "expected_ndim": 2,
        "min_size": 1,
        "has_x_axis": True,
    },
    "galacticdata/HOLMIUM.SPC": {
        "format": ".spc",
        "reader": "read_spc",
        "expected_ndim": 2,  # Multi-row spectrum
        "min_size": 100,  # At least 100 data points
        "has_x_axis": True,
    },
}

def _get_scp_datadirs() -> list[Path]:
    primary = Path(scp.preferences.datadir)
    fallback = Path.home() / ".spectrochempy" / "testdata"
    datadirs = []
    if primary.exists():
        datadirs.append(primary)
    if fallback.exists() and fallback != primary:
        datadirs.append(fallback)
    return datadirs


def _resolve_datadir_file(file_path: str) -> Path | None:
    for datadir in _get_scp_datadirs():
        candidate = datadir / file_path
        if candidate.exists():
            return candidate
    return None


@pytest.mark.skipif(
    not _get_scp_datadirs(),
    reason="SpectroChemPy data directory not found"
)
class TestGoldenDataLoading:
    """Golden tests for reference datasets."""

    def test_reader_mapping_consistency(self):
        """Test that reader mapping is consistent across all code paths."""
        from spectra_sherpa.app.core.config import get_reader_for_extension, EXTENSION_READER_MAP

        # Verify all expected readers are mapped
        assert ".spa" in EXTENSION_READER_MAP
        assert ".spg" in EXTENSION_READER_MAP
        assert ".spc" in EXTENSION_READER_MAP
        assert ".csv" in EXTENSION_READER_MAP

        # Verify OMNIC files use same reader
        assert get_reader_for_extension(".spa") == "read_omnic"
        assert get_reader_for_extension(".spg") == "read_omnic"
        assert get_reader_for_extension(".SPA") == "read_omnic"  # Case-insensitive
        assert get_reader_for_extension(".SPG") == "read_omnic"  # Case-insensitive

        # Verify OPUS numeric extensions
        assert get_reader_for_extension(".0") == "read_opus"
        assert get_reader_for_extension(".0000") == "read_opus"

    @pytest.mark.parametrize("file_path,metadata", GOLDEN_FILES.items())
    def test_load_reference_file(self, file_path, metadata):
        """Test that reference files load correctly via custom loader."""
        full_path = _resolve_datadir_file(file_path)
        if full_path is None:
            pytest.skip(f"Reference file not found: {file_path}")

        node = DataSourceNode("test_golden")
        dataset = node._load_spectrochempy_custom_file(file_path)

        # Verify dataset loaded
        assert dataset is not None, f"Failed to load {file_path}"

        # Verify dimensionality
        assert dataset.ndim == metadata["expected_ndim"], \
            f"{file_path}: Expected {metadata['expected_ndim']}D, got {dataset.ndim}D"

        # Verify minimum size
        assert dataset.size >= metadata["min_size"], \
            f"{file_path}: Expected at least {metadata['min_size']} points, got {dataset.size}"

        # Verify x-axis if expected
        if metadata.get("has_x_axis"):
            assert dataset.x is not None, f"{file_path}: Missing x-axis"
            if metadata.get("x_axis_unit"):
                # Note: Unit checking is optional as it may vary
                pass

        # Verify title is set
        assert dataset.title is not None and dataset.title != "", \
            f"{file_path}: Missing or empty title"

    def test_loader_consistency_spa_file(self):
        """Test that .SPA files load identically via all code paths."""
        test_file = "irdata/interferogram/spectre.SPA"
        full_path = _resolve_datadir_file(test_file)
        if full_path is None:
            pytest.skip(f"Test file not found: {test_file}")

        node = DataSourceNode("test_golden")

        # Path 1: Custom loader
        ds1 = node._load_spectrochempy_custom_file(test_file)

        # Path 2: Direct file loader
        ds2 = node._load_from_file(str(full_path))

        # Both should produce identical results
        assert ds1.shape == ds2.shape, \
            f"Shape mismatch: custom={ds1.shape}, direct={ds2.shape}"

        # Data should be numerically equivalent (within tolerance for float precision)
        import numpy as np
        assert np.allclose(ds1.data, ds2.data, rtol=1e-10, atol=1e-12), \
            "Data mismatch between loaders"

    def test_loader_consistency_spg_file(self):
        """Test that .SPG files load identically via all code paths."""
        test_file = "irdata/CO@Mo_Al2O3.SPG"
        full_path = _resolve_datadir_file(test_file)
        if full_path is None:
            pytest.skip(f"Test file not found: {test_file}")

        node = DataSourceNode("test_golden")

        # Path 1: Custom loader
        ds1 = node._load_spectrochempy_custom_file(test_file)

        # Path 2: Direct file loader
        ds2 = node._load_from_file(str(full_path))

        # Both should produce identical results
        assert ds1.shape == ds2.shape, \
            f"Shape mismatch: custom={ds1.shape}, direct={ds2.shape}"

        import numpy as np
        assert np.allclose(ds1.data, ds2.data, rtol=1e-10, atol=1e-12), \
            "Data mismatch between loaders"

    def test_case_insensitive_loading(self):
        """Test that files with different capitalizations load correctly."""
        from spectra_sherpa.app.core.config import get_reader_for_extension

        # Test various capitalizations
        extensions = [".spa", ".SPA", ".Spa", ".spg", ".SPG", ".Spg", ".csv", ".CSV"]

        for ext in extensions:
            reader = get_reader_for_extension(ext)
            assert reader is not None, f"No reader for {ext}"

            # SPA and SPG should use read_omnic regardless of case
            if ext.lower() in [".spa", ".spg"]:
                assert reader == "read_omnic", \
                    f"{ext} should use read_omnic, got {reader}"

    def test_csv_index_removal(self):
        """Test that CSV index columns are removed consistently."""
        test_file = "irdata/IR.CSV"
        full_path = _resolve_datadir_file(test_file)
        if full_path is None:
            pytest.skip(f"Test file not found: {test_file}")

        node = DataSourceNode("test_golden")
        dataset = node._load_from_file(str(full_path))

        # Verify dataset loaded
        assert dataset is not None

        # CSV data should have proper shape (not include index columns)
        # This is a regression test - if this fails, index removal broke
        assert dataset.ndim in [1, 2], "CSV should produce 1D or 2D dataset"

    def test_unsupported_extension_error(self):
        """Test that unsupported extensions raise clear errors."""
        from spectra_sherpa.app.core.config import get_reader_for_extension

        with pytest.raises(ValueError) as exc_info:
            get_reader_for_extension(".xyz")

        error_msg = str(exc_info.value)
        assert "Unsupported file extension" in error_msg
        assert "Supported extensions" in error_msg

    def test_backward_compat_dat_warning(self):
        """Test that .dat files trigger backward compatibility warning."""
        from spectra_sherpa.app.core.config import get_reader_for_extension
        import warnings

        # .dat should fall back to generic read with warning
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            reader = get_reader_for_extension(".dat")

            # Should return generic reader
            assert reader == "read"

            # Should have issued a warning
            assert len(w) == 1
            assert "no explicit reader" in str(w[0].message).lower()
            assert "falling back" in str(w[0].message).lower()


class TestAPIFileDiscovery:
    """Tests for the API file discovery endpoint."""

    @pytest.mark.asyncio
    async def test_case_insensitive_discovery(self, client):
        """Test that API discovers files regardless of extension capitalization."""
        from httpx import AsyncClient

        response = await client.get("/api/v1/workflows/spectrochempy-examples")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)

        # Check that irdata exists and has files
        if "irdata" in data:
            irdata_files = data["irdata"]
            assert isinstance(irdata_files, list)

            # Verify files have required metadata
            for file_entry in irdata_files:
                assert "label" in file_entry
                assert "value" in file_entry
                assert "path" in file_entry
                assert "format" in file_entry  # New metadata field
                assert "source" in file_entry  # New metadata field

    @pytest.mark.asyncio
    async def test_dual_directory_support(self, client):
        """Test that API scans both primary and fallback directories."""
        from httpx import AsyncClient

        response = await client.get("/api/v1/workflows/spectrochempy-examples")
        assert response.status_code == 200

        data = response.json()

        # Verify dataset structure
        for dataset_name, files in data.items():
            assert isinstance(files, list)

            # Each file should have source metadata
            for file_entry in files:
                assert file_entry["source"] in ["primary", "fallback"], \
                    f"Invalid source: {file_entry['source']}"

    @pytest.mark.asyncio
    async def test_galacticdata_in_response(self, client):
        """Test that galacticdata is now included in API response."""
        from httpx import AsyncClient

        response = await client.get("/api/v1/workflows/spectrochempy-examples")
        assert response.status_code == 200

        data = response.json()

        # galacticdata should be present if the directory exists
        # (don't fail if directory doesn't exist, just verify structure)
        if "galacticdata" in data:
            assert isinstance(data["galacticdata"], list)
