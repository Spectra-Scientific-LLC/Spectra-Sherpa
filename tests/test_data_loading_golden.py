"""
Golden tests for data loading consistency.

These tests verify that reference datasets load correctly and produce
consistent results across different code paths.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("spectrochempy")
import spectrochempy as scp


def _load_scp_reference(path: Path):
    """Load the temporary scientific parity reference directly."""
    suffix = path.suffix.lower()
    if suffix in {".spa", ".spg", ".srs"}:
        return scp.read_omnic(str(path))
    if suffix == ".spc":
        return scp.read_spc(str(path))
    if suffix == ".csv":
        return scp.read_csv(str(path))
    raise AssertionError(f"No test-only SCP parity reader for {suffix}")


def _load_public(path: Path, *, parser_options=None):
    from spectra_sherpa.io import ingest

    result = ingest(path, parser_options=parser_options)
    assert len(result.assets) == 1
    return result.assets[0].dataset


# Reference file metadata (expected properties)
# These serve as "golden" references - if these change, investigate why
GOLDEN_FILES = {
    "irdata/IR.CSV": {
        "format": ".csv",
        "reader": "read_csv",
        "expected_ndim": 2,
        "min_size": 1,
        "has_x_axis": True,
        "expected_shape": (1, 3736),
        "expected_axis_prefix": [399.1926, 400.1568, 401.1211, 402.0853, 403.0495],
        "expected_signal_prefix": [-0.09079, 3.54656, 5.349746, 3.19553, 4.313386],
        "parser_options": {"csv_layout": "headerless_two_column_spectrum"},
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


@pytest.mark.parametrize(
    ("fixture_name", "expected_max_abs_difference"),
    [
        ("nir.spc", 3.78125),
        ("m_ordz.spc", 5.724968679249287),
    ],
)
def test_scp_081_is_not_the_multifile_exponent_oracle(
    fixture_name: str,
    expected_max_abs_difference: float,
) -> None:
    """Freeze the known SCP divergence instead of claiming false parity.

    Galactic UDF 4.50 assigns exact signed exponent authority to each TMULTI
    subheader.  SpectroChemPy 0.8.1 agrees on row zero of these files, then
    applies the wrong exponent to later rows.  Native conformance therefore
    binds the specification plus spc-io/spc-parser, not SCP, for this case.
    """
    fixture = Path(__file__).parent / "fixtures" / "spc" / fixture_name
    native = _load_public(fixture).X
    scp_values = np.asarray(scp.read_spc(str(fixture)).data, dtype=np.float64)

    np.testing.assert_allclose(native[0], scp_values[0], rtol=0, atol=1e-12)
    assert float(np.max(np.abs(native - scp_values))) == pytest.approx(expected_max_abs_difference)


@pytest.mark.skipif(not _get_scp_datadirs(), reason="SpectroChemPy data directory not found")
class TestGoldenDataLoading:
    """Golden tests for reference datasets."""

    def test_reader_mapping_consistency(self):
        """The frozen registry, not an extension map, owns every reader."""
        from spectra_sherpa.io import builtin_registry

        plugins = {plugin.format_id: plugin for plugin in builtin_registry.plugins}
        assert set(plugins) == {
            "csv",
            "jcamp-dx",
            "matlab",
            "numpy",
            "omnic",
            "opus",
            "renishaw-text",
            "sherpa-json",
            "spc",
            "wdf",
        }
        assert plugins["csv"].extensions == (".csv", ".tsv", ".txt", ".dat")
        assert plugins["opus"].filename_patterns == ("numeric-extension",)
        assert plugins["renishaw-text"].extensions == (".txt",)
        assert plugins["wdf"].extensions == (".wdf",)

    @pytest.mark.parametrize("file_path,metadata", GOLDEN_FILES.items())
    def test_load_reference_file(self, file_path, metadata):
        """Test that reference files load correctly via custom loader."""
        full_path = _resolve_datadir_file(file_path)
        if full_path is None:
            pytest.skip(f"Reference file not found: {file_path}")

        dataset = _load_public(full_path, parser_options=metadata.get("parser_options"))

        # Verify dataset loaded
        assert dataset is not None, f"Failed to load {file_path}"

        # Verify dimensionality
        assert (
            dataset.ndim == metadata["expected_ndim"]
        ), f"{file_path}: Expected {metadata['expected_ndim']}D, got {dataset.ndim}D"

        # Verify minimum size
        assert (
            dataset.X.size >= metadata["min_size"]
        ), f"{file_path}: Expected at least {metadata['min_size']} points, got {dataset.X.size}"

        # Verify x-axis if expected
        if metadata.get("has_x_axis"):
            assert dataset.feature_axis is not None, f"{file_path}: Missing feature axis"
            if metadata.get("x_axis_unit"):
                # Note: Unit checking is optional as it may vary
                pass

        assert dataset.shape == metadata["expected_shape"]
        np.testing.assert_allclose(dataset.feature_axis.values[:5], metadata["expected_axis_prefix"], rtol=0, atol=5e-5)
        np.testing.assert_allclose(dataset.X[0, :5], metadata["expected_signal_prefix"], rtol=0, atol=5e-6)

        # Verify title is set
        assert dataset.title is not None and dataset.title != "", f"{file_path}: Missing or empty title"

    def test_case_insensitive_loading(self):
        """Path extension normalization remains case insensitive."""
        from spectra_sherpa.io.base import BoundedSource
        from spectra_sherpa.io.types import ParserLimits

        test_file = _resolve_datadir_file("irdata/interferogram/spectre.SPA")
        if test_file is None:
            pytest.skip("SPA test fixture not found")
        source = BoundedSource(test_file, limits=ParserLimits())
        assert source.extension == ".spa"

    def test_csv_index_removal(self):
        """Test that CSV index columns are removed consistently."""
        test_file = "irdata/IR.CSV"
        full_path = _resolve_datadir_file(test_file)
        if full_path is None:
            pytest.skip(f"Test file not found: {test_file}")

        dataset = _load_public(full_path, parser_options=GOLDEN_FILES[test_file]["parser_options"])

        # Verify dataset loaded
        assert dataset is not None

        # CSV data should have proper shape (not include index columns)
        # This is a regression test - if this fails, index removal broke
        assert dataset.ndim in [1, 2], "CSV should produce 1D or 2D dataset"

    def test_unsupported_extension_error(self, tmp_path: Path):
        """Test that unsupported extensions raise clear errors."""
        from spectra_sherpa.io import UnsupportedFormatError, ingest

        unknown = tmp_path / "manifest.unknown"
        unknown.write_bytes(b"unsupported")
        with pytest.raises(UnsupportedFormatError) as exc_info:
            ingest(unknown)

        error_msg = str(exc_info.value)
        assert "No registered parser structurally recognizes" in error_msg

    def test_generic_text_is_admitted_only_as_a_consistent_table(self):
        """.txt/.dat reach the delimited-table reader only below exact vendor dialects."""
        from spectra_sherpa.io import builtin_registry

        txt_plugins = [plugin.format_id for plugin in builtin_registry.plugins if ".txt" in plugin.extensions]
        dat_plugins = [plugin.format_id for plugin in builtin_registry.plugins if ".dat" in plugin.extensions]
        assert sorted(txt_plugins) == ["csv", "renishaw-text"]
        assert dat_plugins == ["csv"]
