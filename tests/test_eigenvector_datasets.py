"""
Integration tests for Eigenvector Research dataset adapters.

Tests the Eigenvector parser library, optional SpectroChemPy conversion, native PCA
decomposition, and DataSourceNode DAG integration using generated fixtures.
The real datasets are cataloged for runtime download from:
https://eigenvector.com/resources/data-sets/

Covers:
- Library parser (app.lib.eigenvector): DATASET_CATALOG, load_eigenvector_dataset
- Diesel-like NIR spectral data — 784 samples × 401 wavelengths (750–1550 nm)
- Diesel-like property targets — 7 reference properties with missing values
- Corn-like NIR .mat data — 80 samples × 700 channels, 3 instruments
- PCA decomposition on real NIR spectra through Sherpa's native authority
- DataSourceNode integration (source="eigenvector")

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_eigenvector_datasets.py -v --no-cov
"""

from __future__ import annotations

import csv
import hashlib
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from spectra_sherpa.app.lib.eigenvector import (
    DATASET_CATALOG,
    EIGENVECTOR_DATA_DIR,
    extract_csv_metadata,
    extract_mat_metadata,
    get_dataset_info,
    load_eigenvector_csv_pair_as_sherpa,
    load_eigenvector_dataset,
    parse_eigenvector_csv,
    parse_eigenvector_mat,
)
from spectra_sherpa.app.lib.pca import fit_pca
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from tests._optional_scp import HAS_SCP, NDDataset, scp

# ---------------------------------------------------------------------------
# Generated fixture paths
# ---------------------------------------------------------------------------
FIXTURE_DIESEL_SPEC = Path("diesel_csv") / "diesel_spec.csv"
FIXTURE_DIESEL_PROP = Path("diesel_csv") / "diesel_prop.csv"
FIXTURE_CORN_MAT = Path("corn_mat") / "corn.mat"


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def eigenvector_fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create generated Eigenvector-format fixtures without redistributing upstream data."""
    from scipy.io import savemat

    root = tmp_path_factory.mktemp("eigenvector-fixtures")
    diesel_dir = root / "diesel_csv"
    diesel_dir.mkdir(parents=True)
    corn_dir = root / "corn_mat"
    corn_dir.mkdir(parents=True)

    sample_count = 784
    feature_count = 401
    wavelengths = np.arange(750.0, 1552.0, 2.0)
    sample_index = np.arange(sample_count, dtype=float)
    phase = np.linspace(0.0, np.pi * 4.0, feature_count)
    spectra = (
        0.35
        + 0.08 * np.sin(phase)[None, :]
        + 0.025 * np.cos(phase * 0.3)[None, :]
        + (sample_index[:, None] / sample_count) * 0.12
        + ((sample_index % 17)[:, None] / 17.0) * 0.02
    )

    prop_names = ["BP50", "CN", "D4052", "FLASH", "FREEZE", "TOTAL", "VISC"]
    props = np.column_stack(
        [
            150 + sample_index * 0.05,
            35 + np.sin(sample_index / 40.0) * 6,
            0.8 + sample_index * 0.0001,
            45 + sample_index * 0.02,
            -30 + np.cos(sample_index / 30.0) * 4,
            10 + sample_index * 0.01,
            2 + sample_index * 0.001,
        ]
    )
    props[sample_index.astype(int) % 5 == 0] = np.nan

    def _write_rows(path: Path, rows: list[list[str]]) -> None:
        width = max(len(row) for row in rows)
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(row + [""] * (width - len(row)) for row in rows)

    def _metadata_rows(description: str) -> list[list[str]]:
        return [
            ["Name", description],
            ["Author", "SpectraSherpa generated test fixture"],
            ["Date", "2026-06-06"],
            ["Modification Date", "2026-06-06"],
            ["Description", "Generated parser fixture not upstream Eigenvector data"],
            ["", ""],
            ["", ""],
            ["Label", ""],
        ]

    spec_rows = _metadata_rows("Synthetic Diesel NIR parser fixture")
    spec_rows.append(["Label", "Sample", *[f"{w:.0f}" for w in wavelengths]])
    spec_rows.append(["Axisscale", "", *[f"{w:.0f}" for w in wavelengths]])
    for idx, row in enumerate(spectra, start=1):
        spec_rows.append(["", str(idx), *[f"{value:.8f}" for value in row]])
    _write_rows(root / FIXTURE_DIESEL_SPEC, spec_rows)

    prop_rows = _metadata_rows("Synthetic Diesel property parser fixture")
    prop_rows.append(["Label", "Sample", *prop_names])
    for idx, row in enumerate(props, start=1):
        prop_rows.append(["", str(idx), *["nan" if np.isnan(value) else f"{value:.8f}" for value in row]])
    _write_rows(root / FIXTURE_DIESEL_PROP, prop_rows)

    def _dataset_struct(name: str, data: np.ndarray) -> np.ndarray:
        dtype = [
            ("data", "O"),
            ("axisscale", "O"),
            ("name", "O"),
            ("author", "O"),
            ("date", "O"),
            ("description", "O"),
        ]
        ds = np.empty((1, 1), dtype=dtype)
        axis = np.empty((2, 2), dtype=object)
        axis[0, 0] = np.arange(data.shape[0], dtype=float)
        axis[0, 1] = "sample"
        axis[1, 0] = np.arange(data.shape[1], dtype=float)
        axis[1, 1] = "channel"
        ds["data"][0, 0] = data
        ds["axisscale"][0, 0] = axis
        ds["name"][0, 0] = np.array([name])
        ds["author"][0, 0] = np.array(["SpectraSherpa generated test fixture"])
        ds["date"][0, 0] = np.array(["2026-06-06"])
        ds["description"][0, 0] = np.array(["Generated parser fixture not upstream Eigenvector data"])
        return ds

    corn_samples = 80
    corn_features = 700
    corn_x = np.linspace(0.0, np.pi * 6.0, corn_features)
    corn_i = np.arange(corn_samples, dtype=float)
    corn_base = (
        0.5
        + 0.2 * np.sin(corn_x)[None, :]
        + 0.1 * np.cos(corn_x * 0.25)[None, :]
        + (corn_i[:, None] / corn_samples) * 0.18
    )
    corn_props = np.column_stack(
        [
            10 + corn_i * 0.02,
            3 + corn_i * 0.01,
            8 + np.sin(corn_i / 8.0),
            65 + np.cos(corn_i / 10.0),
        ]
    )
    savemat(
        root / FIXTURE_CORN_MAT,
        {
            "m5spec": _dataset_struct("M5 generated fixture", corn_base),
            "mp5spec": _dataset_struct("MP5 generated fixture", corn_base + 0.02),
            "mp6spec": _dataset_struct("MP6 generated fixture", corn_base + 0.04),
            "propvals": _dataset_struct("Properties generated fixture", corn_props),
        },
    )

    return root


@pytest.fixture(scope="module")
def diesel_spectra(eigenvector_fixture_dir: Path):
    """Parse Diesel NIR spectra CSV via library parser."""
    data, sample_ids, wavelengths = parse_eigenvector_csv(
        eigenvector_fixture_dir / FIXTURE_DIESEL_SPEC, has_axisscale=True
    )
    return data, sample_ids, wavelengths


@pytest.fixture(scope="module")
def diesel_properties(eigenvector_fixture_dir: Path):
    """Parse Diesel properties CSV via library parser."""
    data, sample_ids, _ = parse_eigenvector_csv(eigenvector_fixture_dir / FIXTURE_DIESEL_PROP, has_axisscale=False)
    return data, sample_ids


@pytest.fixture
def patch_eigenvector_loader(monkeypatch: pytest.MonkeyPatch, eigenvector_fixture_dir: Path):
    """Route node-level Eigenvector loads to generated fixtures."""

    def _load(name: str, data_dir: Path | None = None):
        return load_eigenvector_dataset(name, data_dir=data_dir or eigenvector_fixture_dir)

    monkeypatch.setattr("spectra_sherpa.app.lib.eigenvector.load_eigenvector_dataset", _load)
    return _load


# ---------------------------------------------------------------------------
# Tests: Diesel CSV Parsing
# ---------------------------------------------------------------------------


class TestDieselCsvParsing:
    def test_pair_loader_preserves_axis_specimens_properties_and_missingness(
        self, eigenvector_fixture_dir: Path
    ) -> None:
        dataset = load_eigenvector_csv_pair_as_sherpa(
            eigenvector_fixture_dir / FIXTURE_DIESEL_SPEC,
            eigenvector_fixture_dir / FIXTURE_DIESEL_PROP,
        )

        assert dataset.shape == (784, 401)
        assert dataset.target.shape == (784, 7)
        assert dataset.data_role == "X_spectra"
        assert dataset.domain.technique == "NIR"
        assert dataset.feature_axis.title == "Wavelength"
        assert dataset.feature_axis.units == "nm"
        np.testing.assert_array_equal(dataset.feature_axis.values, np.arange(750.0, 1552.0, 2.0))
        assert dataset.sample_axis.labels[:3] == ["1", "2", "3"]
        assert dataset.target_context.target_names == ["BP50", "CN", "D4052", "FLASH", "FREEZE", "TOTAL", "VISC"]
        assert np.isnan(dataset.target).any()
        cells = dataset.sample_axis.sample_table["D4052"]
        assert [value is None for value in cells] == np.isnan(dataset.target[:, 2]).tolist()
        np.testing.assert_allclose(np.asarray(cells, dtype=float), dataset.target[:, 2], equal_nan=True)
        assert len(dataset.scientific_digest) == 64

    def test_selected_csv_roles_reject_nonfinite_x_infinite_y_and_misaligned_ids(
        self, eigenvector_fixture_dir: Path, tmp_path: Path
    ) -> None:
        folder = tmp_path / "diesel_csv"
        folder.mkdir()
        spec_path = folder / "diesel_spec.csv"
        prop_path = folder / "diesel_prop.csv"
        shutil.copy2(eigenvector_fixture_dir / FIXTURE_DIESEL_SPEC, spec_path)
        shutil.copy2(eigenvector_fixture_dir / FIXTURE_DIESEL_PROP, prop_path)

        def set_cell(path: Path, row: int, column: int, value: str) -> None:
            with path.open(newline="") as handle:
                rows = list(csv.reader(handle))
            rows[row][column] = value
            with path.open("w", newline="") as handle:
                csv.writer(handle).writerows(rows)

        # Missing reference Y remains admissible in the unmodified pair.
        assert np.isnan(load_eigenvector_csv_pair_as_sherpa(spec_path, prop_path).target).any()
        set_cell(spec_path, 10, 2, "nan")
        with pytest.raises(ValueError, match="Selected Eigenvector spectral X must be a finite"):
            load_eigenvector_csv_pair_as_sherpa(spec_path, prop_path)
        with pytest.raises(ValueError, match="Selected Eigenvector spectral X must be a finite"):
            load_eigenvector_dataset("diesel_nir", data_dir=tmp_path)

        set_cell(spec_path, 10, 2, "0.5")
        set_cell(prop_path, 9, 2, "inf")
        with pytest.raises(ValueError, match="property Y may contain missing NaN values, not infinity"):
            load_eigenvector_csv_pair_as_sherpa(spec_path, prop_path)

        set_cell(prop_path, 9, 2, "0.8")
        set_cell(prop_path, 9, 1, "wrong-specimen")
        with pytest.raises(ValueError, match="different specimen IDs"):
            load_eigenvector_csv_pair_as_sherpa(spec_path, prop_path)
        with pytest.raises(ValueError, match="different specimen IDs"):
            load_eigenvector_dataset("diesel_nir", data_dir=tmp_path)

        set_cell(prop_path, 9, 1, "1")
        set_cell(spec_path, 9, 2, "inf")
        with pytest.raises(ValueError, match="Axis values.*must be finite"):
            load_eigenvector_csv_pair_as_sherpa(spec_path, prop_path)

    def test_declared_pair_requires_file_and_unique_nonblank_specimen_ids(
        self, eigenvector_fixture_dir: Path, tmp_path: Path
    ) -> None:
        folder = tmp_path / "diesel_csv"
        folder.mkdir()
        spec_path = folder / "diesel_spec.csv"
        prop_path = folder / "diesel_prop.csv"
        shutil.copy2(eigenvector_fixture_dir / FIXTURE_DIESEL_SPEC, spec_path)
        with pytest.raises(FileNotFoundError, match="Declared Eigenvector property data file"):
            load_eigenvector_dataset("diesel_nir", data_dir=tmp_path)

        shutil.copy2(eigenvector_fixture_dir / FIXTURE_DIESEL_PROP, prop_path)
        for invalid_id in ("", "1"):
            for path in (spec_path, prop_path):
                with path.open(newline="") as handle:
                    rows = list(csv.reader(handle))
                rows[10][1] = invalid_id
                with path.open("w", newline="") as handle:
                    csv.writer(handle).writerows(rows)
            with pytest.raises(ValueError, match="specimen IDs must be nonempty and unique"):
                load_eigenvector_csv_pair_as_sherpa(spec_path, prop_path)
            with pytest.raises(ValueError, match="specimen IDs must be nonempty and unique"):
                load_eigenvector_dataset("diesel_nir", data_dir=tmp_path)

    """Test parsing of the SWRI Diesel NIR CSV files."""

    def test_spectra_shape(self, diesel_spectra):
        """Spectral matrix should be 784 samples × 401 wavelengths."""
        data, sample_ids, wavelengths = diesel_spectra
        assert data.ndim == 2
        n_samples, n_features = data.shape
        assert n_samples > 700, f"Expected >700 samples, got {n_samples}"
        assert n_features == 401, f"Expected 401 wavelengths, got {n_features}"
        assert len(sample_ids) == n_samples

    def test_wavelength_range(self, diesel_spectra):
        """NIR wavelengths should span 750–1550 nm with 2 nm step."""
        _, _, wavelengths = diesel_spectra
        assert wavelengths is not None
        assert wavelengths[0] == pytest.approx(750.0)
        assert wavelengths[-1] == pytest.approx(1550.0)
        steps = np.diff(wavelengths)
        assert np.allclose(steps, 2.0), f"Expected 2 nm step, got unique steps: {np.unique(steps)}"

    def test_spectra_no_nans(self, diesel_spectra):
        """Spectral data should have no missing values."""
        data, _, _ = diesel_spectra
        assert not np.any(np.isnan(data)), "Spectral matrix contains NaN values"

    def test_spectra_value_range(self, diesel_spectra):
        """NIR absorbance values should be in a plausible range."""
        data, _, _ = diesel_spectra
        # NIR absorbance typically between -0.1 and ~1.5 AU
        assert data.min() > -0.5, f"Min absorbance {data.min()} is implausibly low"
        assert data.max() < 2.0, f"Max absorbance {data.max()} is implausibly high"

    def test_sample_ids_are_numeric(self, diesel_spectra):
        """Sample IDs in the SWRI dataset are numeric identifiers."""
        _, sample_ids, _ = diesel_spectra
        for sid in sample_ids[:10]:
            assert sid.isdigit(), f"Sample ID {sid!r} is not numeric"

    def test_properties_shape(self, diesel_properties):
        """Properties matrix should have samples × 7 columns."""
        data, sample_ids = diesel_properties
        assert data.ndim == 2
        n_samples, n_props = data.shape
        assert n_samples > 700
        assert n_props == 7, f"Expected 7 properties, got {n_props}"

    def test_properties_have_nans(self, diesel_properties):
        """Diesel properties are known to have missing values."""
        data, _ = diesel_properties
        nan_frac = np.isnan(data).sum() / data.size
        # Expect significant missing data (SWRI dataset is sparse)
        assert nan_frac > 0.1, f"Expected >10% NaN, got {nan_frac:.1%}"

    def test_sample_id_overlap(self, diesel_spectra, diesel_properties):
        """Spectra and properties should share sample IDs."""
        _, spec_ids, _ = diesel_spectra
        _, prop_ids = diesel_properties
        overlap = set(spec_ids) & set(prop_ids)
        assert len(overlap) > 600, f"Expected >600 shared sample IDs, got {len(overlap)}"


# ---------------------------------------------------------------------------
# Tests: SpectroChemPy NDDataset creation from parsed data
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_SCP, reason="SpectroChemPy not installed")
class TestDieselScpNDDataset:
    """Test creating SpectroChemPy NDDataset from parsed Diesel data."""

    def test_create_nddataset(self, diesel_spectra):
        """Parsed numpy data should convert to NDDataset with coordinates."""
        data, sample_ids, wavelengths = diesel_spectra
        dataset = scp.NDDataset(data)
        dataset.x = scp.Coord(wavelengths, title="wavelength", units="nm")
        dataset.y = scp.Coord(np.arange(data.shape[0]), title="sample")

        assert isinstance(dataset, NDDataset)
        assert dataset.shape == data.shape
        assert dataset.x.title == "wavelength"
        assert str(dataset.x.units) == "nm"


# ---------------------------------------------------------------------------
# Tests: PCA on Diesel NIR Spectra (Sherpa native — always available)
# ---------------------------------------------------------------------------


class TestDieselPca:
    """Test PCA decomposition on Diesel NIR spectra through one authority."""

    def test_pca_2_components(self, diesel_spectra):
        """PCA with 2 components should capture >40% of variance in NIR data."""
        data, _, _ = diesel_spectra
        pca = fit_pca(data, n_components=2, standardized=False, scaled=False)

        assert pca.scores.shape == (data.shape[0], 2)
        total_var = pca.explained_variance_ratio.sum()
        assert total_var > 0.40, f"First 2 PCs explain only {total_var:.1%} variance"

    def test_pca_5_components(self, diesel_spectra):
        """First 5 PCs should capture the majority of spectral variance."""
        data, _, _ = diesel_spectra
        pca = fit_pca(data, n_components=5, standardized=False, scaled=False)

        cumulative_var = np.cumsum(pca.explained_variance_ratio)
        assert cumulative_var[-1] > 0.80, f"First 5 PCs explain only {cumulative_var[-1]:.1%} variance"

    def test_pca_scores_shape(self, diesel_spectra):
        """PCA scores should have correct dimensions."""
        data, _, _ = diesel_spectra
        n_components = 10
        pca = fit_pca(data, n_components=n_components, standardized=False, scaled=False)

        assert pca.scores.shape == (data.shape[0], n_components)
        assert pca.loadings.shape == (n_components, data.shape[1])

    def test_pca_reconstruction_error(self, diesel_spectra):
        """PCA reconstruction with enough components should have low error."""
        data, _, _ = diesel_spectra
        pca = fit_pca(data, n_components=20, standardized=False, scaled=False)
        assert pca.mean is not None
        reconstructed = pca.scores @ pca.loadings + pca.mean

        # Relative reconstruction error
        mse = np.mean((data - reconstructed) ** 2)
        data_var = np.var(data)
        relative_error = mse / data_var
        assert relative_error < 0.05, f"Reconstruction error {relative_error:.4f} is too high (expected <5%)"

    def test_pca_standardized(self, diesel_spectra):
        """PCA on standardized data should work correctly."""
        data, _, _ = diesel_spectra
        pca = fit_pca(data, n_components=5, standardized=True, scaled=False)

        assert pca.scores.shape == (data.shape[0], 5)
        assert pca.explained_variance_ratio.sum() > 0.5

    def test_hotelling_t2_outlier_detection(self, diesel_spectra):
        """Hotelling T² statistic should identify potential outliers."""
        data, _, _ = diesel_spectra
        pca = fit_pca(data, n_components=5, standardized=False, scaled=False)

        # Hotelling T² = sum(scores^2 / eigenvalues)
        t2 = np.sum((pca.scores**2) / pca.explained_variance, axis=1)

        assert t2.shape == (data.shape[0],)
        assert np.all(t2 >= 0), "T² values should be non-negative"
        # Most samples should be well within limits
        assert np.median(t2) < np.percentile(t2, 99)


# ---------------------------------------------------------------------------
# Tests: Corn .mat Dataset (requires scipy)
# ---------------------------------------------------------------------------


class TestCornMatParsing:
    """Test parsing of the Corn NIR .mat dataset (Eigenvector format)."""

    @pytest.fixture(scope="class")
    def corn_data(self, eigenvector_fixture_dir: Path):
        """Load corn.mat using scipy."""
        try:
            from scipy.io import loadmat
        except ImportError:
            pytest.skip("scipy not installed")

        mat = loadmat(str(eigenvector_fixture_dir / FIXTURE_CORN_MAT), squeeze_me=False)
        return mat

    def test_mat_contains_expected_keys(self, corn_data):
        """Corn .mat should contain spectra from 3 instruments + properties."""
        keys = [k for k in corn_data.keys() if not k.startswith("_")]
        # Expected: m5spec, mp5spec, mp6spec (3 NIR instruments) + propvals
        assert "m5spec" in keys, f"Missing 'm5spec' in {keys}"
        assert "mp5spec" in keys, f"Missing 'mp5spec' in {keys}"
        assert "mp6spec" in keys, f"Missing 'mp6spec' in {keys}"
        assert "propvals" in keys, f"Missing 'propvals' in {keys}"

    def test_eigenvector_dataset_structure(self, corn_data):
        """Each spectrum variable should be an Eigenvector DataSet object."""
        for name in ("m5spec", "mp5spec", "mp6spec"):
            ds = corn_data[name]
            # Eigenvector DataSet is a structured array
            assert ds.dtype.names is not None, f"{name} should be a structured array"
            # Expected fields in Eigenvector DataSet format
            field_names = ds.dtype.names
            assert "data" in field_names, f"{name} missing 'data' field"
            assert "axisscale" in field_names, f"{name} missing 'axisscale' field"

    def test_corn_spectra_shape(self, corn_data):
        """Corn spectra should be 80 samples × 700 wavelengths."""
        for name in ("m5spec", "mp5spec", "mp6spec"):
            ds = corn_data[name]
            data = ds["data"][0, 0]
            assert data.ndim == 2, f"{name} data should be 2D"
            n_samples, n_features = data.shape
            assert n_samples == 80, f"{name}: expected 80 samples, got {n_samples}"
            assert n_features == 700, f"{name}: expected 700 wavelengths, got {n_features}"

    def test_corn_properties(self, corn_data):
        """Corn properties (moisture, oil, protein, starch) for 80 samples."""
        props = corn_data["propvals"]
        data = props["data"][0, 0]
        assert data.shape == (80, 4), f"Expected (80, 4), got {data.shape}"
        # All property values should be finite (no NaN in corn data)
        assert np.all(np.isfinite(data)), "Corn properties contain non-finite values"

    def test_corn_pca_native(self, corn_data):
        """PCA on corn M5 NIR spectra should separate samples."""
        data = corn_data["m5spec"]["data"][0, 0]
        pca = fit_pca(data, n_components=3, standardized=False, scaled=False)

        assert pca.scores.shape == (80, 3)
        # Corn NIR data should have strong structure (>80% in 3 PCs)
        total_var = pca.explained_variance_ratio.sum()
        assert total_var > 0.80, f"First 3 PCs explain only {total_var:.1%} — expected >80% for corn NIR"

    @pytest.mark.skipif(not HAS_SCP, reason="SpectroChemPy not installed")
    def test_corn_scp_nddataset(self, corn_data):
        """Corn spectra should convert to NDDataset."""
        spec_data = corn_data["m5spec"]["data"][0, 0]

        dataset = scp.NDDataset(spec_data)
        # Use integer index for x-axis (wavelength axis scale in Eigenvector
        # DataSet .mat format requires custom extraction — index is sufficient
        # for PCA)
        dataset.x = scp.Coord(np.arange(spec_data.shape[1]), title="channel")

        assert isinstance(dataset, NDDataset)
        assert dataset.shape == (80, 700)


# ---------------------------------------------------------------------------
# Tests: Cross-Dataset Validation
# ---------------------------------------------------------------------------


class TestCrossDieselValidation:
    """Cross-validation between spectra and properties."""

    def test_pls_feasibility(self, diesel_spectra, diesel_properties):
        """Verify data is suitable for PLS regression (spectra → cetane number)."""
        spec_data, spec_ids, _ = diesel_spectra
        prop_data, prop_ids = diesel_properties

        # Align samples by ID
        spec_lookup = {sid: i for i, sid in enumerate(spec_ids)}
        matched_spec = []
        matched_prop = []
        for j, pid in enumerate(prop_ids):
            if pid in spec_lookup:
                cn = prop_data[j, 1]  # Column 1 = CN (cetane number)
                if not np.isnan(cn):
                    matched_spec.append(spec_data[spec_lookup[pid]])
                    matched_prop.append(cn)

        X = np.array(matched_spec)
        y = np.array(matched_prop)

        assert X.shape[0] > 100, f"Expected >100 matched samples with CN, got {X.shape[0]}"
        assert X.shape[0] == y.shape[0]

        # Quick correlation check: PC1 should correlate with cetane number
        pca = fit_pca(X, n_components=3, standardized=False, scaled=False)
        corr = np.abs(np.corrcoef(pca.scores[:, 0], y)[0, 1])
        # Even PC1 should have some correlation with cetane (physical basis)
        assert corr > 0.1, f"PC1-CN correlation {corr:.3f} is suspiciously low"


# ---------------------------------------------------------------------------
# Tests: Eigenvector Library (app.lib.eigenvector)
# ---------------------------------------------------------------------------


class TestEigenvectorLibrary:
    """Test the eigenvector parser library (DATASET_CATALOG, loader)."""

    def test_catalog_has_all_entries(self):
        """DATASET_CATALOG should contain all datasets."""
        assert len(DATASET_CATALOG) == 13
        # Original 4
        assert "diesel_nir" in DATASET_CATALOG
        assert "corn_m5" in DATASET_CATALOG
        assert "corn_mp5" in DATASET_CATALOG
        assert "corn_mp6" in DATASET_CATALOG
        # New datasets
        assert "diesel_nir_mat" in DATASET_CATALOG
        assert "cgl_nir" in DATASET_CATALOG
        assert "nir_shootout_cal1" in DATASET_CATALOG
        assert "nir_shootout_test1" in DATASET_CATALOG
        assert "metal_etch_oes" in DATASET_CATALOG
        assert "metal_etch_machine" in DATASET_CATALOG
        assert "metal_etch_rfm" in DATASET_CATALOG

    def test_catalog_entries_have_required_fields(self):
        """Each catalog entry should have label, format, technique, description."""
        for name, entry in DATASET_CATALOG.items():
            assert "label" in entry, f"{name} missing 'label'"
            assert "format" in entry, f"{name} missing 'format'"
            assert "technique" in entry, f"{name} missing 'technique'"
            assert "description" in entry, f"{name} missing 'description'"

    def test_qualified_catalog_acquisition_is_derived_from_artifact_registry(self):
        corn = DATASET_CATALOG["corn_m5"]

        assert corn["artifact_id"] == "eigenvector-corn-archive-v1"
        assert corn["archive_url"] == "https://eigenvector.com/wp-content/uploads/2019/06/corn.mat_.zip"
        assert corn["archive_sha256"] == "8a2d1a03648b6ad334caaafa5d8377bf945ba1477a5082c4963d705d07cca795"
        assert corn["source_file_sha256"] == "e28fd4be274a54ca57b1f2c67ef5a8bf4981f8314bcc73e4c64836fe658c46b5"
        assert corn["source_scope"] == "registered_projection"
        assert corn["source_contract"] == "exact_registered_archive_member"

    def test_full_diesel_and_registered_gatest_are_distinct_source_contracts(self):
        full_csv = DATASET_CATALOG["diesel_nir"]
        full_mat = DATASET_CATALOG["diesel_nir_mat"]

        assert full_csv["source_scope"] == "complete_raw_corpus"
        assert full_csv["source_contract"] == "paired_dataset_csv"
        assert full_mat["source_scope"] == "complete_raw_corpus"
        assert full_mat["source_contract"] == "single_dataset_mat_workspace"
        assert full_csv["related_registered_family"] == "prepared_d4052_gatest"
        assert full_csv["label"] != full_mat["label"]

    def test_registered_runtime_download_verifies_archive_and_member_bytes(self, tmp_path: Path):
        import spectra_sherpa.app.lib.eigenvector as ev

        archive = tmp_path / "source.zip"
        member = tmp_path / "data" / "source.mat"
        archive.write_bytes(b"exact archive")
        member.parent.mkdir()
        member.write_bytes(b"exact member")
        catalog = {
            "mat_file": "data/source.mat",
            "archive_expected_size_bytes": archive.stat().st_size,
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "source_file_expected_size_bytes": member.stat().st_size,
            "source_file_sha256": hashlib.sha256(member.read_bytes()).hexdigest(),
        }

        ev._verify_registered_archive(archive, catalog)
        ev._verify_registered_member(tmp_path, catalog)
        member.write_bytes(b"substituted")
        with pytest.raises(ValueError, match="source (size|digest)"):
            ev._verify_registered_member(tmp_path, catalog)
        with pytest.raises(ValueError, match="source (size|digest)"):
            ev._ensure_runtime_data("qualified", catalog, tmp_path)

    def test_registered_archive_is_verified_before_extraction(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        import spectra_sherpa.app.lib.eigenvector as ev

        catalog = {
            "mat_file": "data/source.mat",
            "archive_url": "https://eigenvector.com/source.zip",
            "archive_expected_size_bytes": 10,
            "archive_sha256": "0" * 64,
            "source_file_expected_size_bytes": 10,
            "source_file_sha256": "0" * 64,
        }
        archive = ev._archive_cache_path(catalog["archive_url"], tmp_path)
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b"not trusted")
        extracted = False

        def observe_extraction(*_args) -> None:
            nonlocal extracted
            extracted = True

        monkeypatch.setattr(ev, "_extract_required_files", observe_extraction)
        with pytest.raises(FileNotFoundError, match="archive size"):
            ev._ensure_runtime_data("qualified", catalog, tmp_path)
        assert extracted is False

    def test_loader_has_no_download_capability(self):
        """Eigenvector data is never downloaded; the loader has no network client."""
        import spectra_sherpa.app.lib.eigenvector as ev

        source = Path(ev.__file__).read_text(encoding="utf-8")
        for token in ("urlopen", "urllib.request", "httpx", "requests", "_download_archive"):
            assert token not in source
        assert not hasattr(ev, "EIGENVECTOR_RUNTIME_DOWNLOAD_ENV")

    def test_package_data_dir_does_not_bundle_raw_eigenvector_files(self):
        """The AGPL package must not redistribute upstream Eigenvector raw data."""
        if EIGENVECTOR_DATA_DIR.exists():
            assert not [path for path in EIGENVECTOR_DATA_DIR.rglob("*") if path.is_file()]

    def test_load_diesel_nir(self, eigenvector_fixture_dir: Path):
        """load_eigenvector_dataset('diesel_nir') should return correct shapes."""
        result = load_eigenvector_dataset("diesel_nir", data_dir=eigenvector_fixture_dir)
        assert result["spectra"].shape == (784, 401)
        assert result["properties"].shape == (784, 7)
        assert result["wavelengths"] is not None
        assert len(result["wavelengths"]) == 401
        assert result["sample_ids"] is not None
        assert len(result["sample_ids"]) == 784
        assert result["prop_names"] == ["BP50", "CN", "D4052", "FLASH", "FREEZE", "TOTAL", "VISC"]

    def test_load_corn_m5(self, eigenvector_fixture_dir: Path):
        """load_eigenvector_dataset('corn_m5') should return correct shapes."""
        result = load_eigenvector_dataset("corn_m5", data_dir=eigenvector_fixture_dir)
        assert result["spectra"].shape == (80, 700)
        assert result["properties"].shape == (80, 4)
        assert result["prop_names"] == ["Moisture", "Oil", "Protein", "Starch"]

    def test_load_corn_mp5(self, eigenvector_fixture_dir: Path):
        """load_eigenvector_dataset('corn_mp5') should return (80, 700) spectra."""
        result = load_eigenvector_dataset("corn_mp5", data_dir=eigenvector_fixture_dir)
        assert result["spectra"].shape == (80, 700)

    def test_load_corn_mp6(self, eigenvector_fixture_dir: Path):
        """load_eigenvector_dataset('corn_mp6') should return (80, 700) spectra."""
        result = load_eigenvector_dataset("corn_mp6", data_dir=eigenvector_fixture_dir)
        assert result["spectra"].shape == (80, 700)

    def test_invalid_name_raises(self):
        """Invalid dataset name should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported Eigenvector dataset"):
            load_eigenvector_dataset("nonexistent_dataset")

    def test_load_with_custom_data_dir(self, eigenvector_fixture_dir: Path):
        """Loading with explicit data_dir should work (test fixtures path)."""
        result = load_eigenvector_dataset("diesel_nir", data_dir=eigenvector_fixture_dir)
        assert result["spectra"].shape[0] == 784

    def test_missing_data_asks_the_user_to_supply_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Missing data is never fetched; the message says where to place it."""
        import spectra_sherpa.app.lib.eigenvector as ev

        empty_package_data = tmp_path / "empty-package-data"
        empty_package_data.mkdir()
        monkeypatch.setattr(ev, "EIGENVECTOR_DATA_DIR", empty_package_data)
        monkeypatch.setenv("EGRESS_ENABLED", "true")
        monkeypatch.setenv("SPECTRASHERPA_EIGENVECTOR_DOWNLOADS", "true")
        with pytest.raises(FileNotFoundError, match="never downloads it") as error:
            ev.load_eigenvector_dataset("diesel_nir", runtime_data_dir=tmp_path / "runtime-cache")
        assert str(tmp_path / "runtime-cache") in str(error.value)
        assert not (tmp_path / "runtime-cache" / "_archives").exists()

    def test_user_supplied_registered_archive_is_extracted_into_cache(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        eigenvector_fixture_dir: Path,
    ):
        """An archive the user placed locally is extracted; nothing is fetched."""
        import spectra_sherpa.app.lib.eigenvector as ev

        empty_package_data = tmp_path / "empty-package-data"
        empty_package_data.mkdir()
        runtime_cache = tmp_path / "runtime-cache"
        catalog = dict(ev.DATASET_CATALOG["diesel_nir"])
        catalog["archive_url"] = "https://eigenvector.com/resources/data-sets/diesel.zip"
        catalog.pop("archive_sha256", None)
        catalog.pop("archive_expected_size_bytes", None)
        placed = ev._archive_cache_path(catalog["archive_url"], runtime_cache)
        placed.parent.mkdir(parents=True)
        with zipfile.ZipFile(placed, "w") as archive:
            archive.write(eigenvector_fixture_dir / FIXTURE_DIESEL_SPEC, "diesel_spec.csv")
            archive.write(eigenvector_fixture_dir / FIXTURE_DIESEL_PROP, "diesel_prop.csv")

        monkeypatch.setattr(ev, "EIGENVECTOR_DATA_DIR", empty_package_data)
        monkeypatch.setitem(ev.DATASET_CATALOG, "diesel_nir", catalog)

        result = ev.load_eigenvector_dataset("diesel_nir", runtime_data_dir=runtime_cache)

        assert result["spectra"].shape == (784, 401)
        assert (runtime_cache / "diesel_csv" / "diesel_spec.csv").exists()


# ---------------------------------------------------------------------------
# Tests: managed-reference materialization into canonical data.file_load
# ---------------------------------------------------------------------------


class TestManagedEigenvectorMaterialization:
    """Preserve reference-data guarantees at the canonical file boundary."""

    @pytest.fixture(autouse=True)
    def _use_generated_eigenvector_data(self, patch_eigenvector_loader):
        return None

    @pytest.fixture
    def materialize(self, tmp_path: Path, patch_eigenvector_loader):
        """Materialize the reference payload exactly as the import service does."""
        from spectra_sherpa.app.services.dag.nodes.data.file_load_node import FileLoadNode

        def _materialize(name: str, selected_target: str):
            reference = patch_eigenvector_loader(name)
            wavelengths = reference["wavelengths"]
            columns = (
                [str(value) for value in wavelengths]
                if wavelengths is not None
                else [str(index) for index in range(reference["spectra"].shape[1])]
            )
            frame = pd.DataFrame(reference["spectra"], columns=columns)
            for index, property_name in enumerate(reference.get("prop_names") or []):
                frame[property_name] = reference["properties"][:, index]
            if reference.get("sample_ids"):
                sample_ids = [str(value) for value in reference["sample_ids"]]
            else:
                sample_ids = [f"{name}_row_{index + 1:04d}" for index in range(reference["spectra"].shape[0])]
            frame.insert(0, "sample_id", sample_ids)
            path = tmp_path / f"{name}.csv"
            frame.to_csv(path, index=False)
            dataset = FileLoadNode("reference-file", {"experiment_id": 1, "file_id": 1})._load_file(
                path,
                selected_target=selected_target,
                target_type="continuous",
            )
            return reference, dataset

        return _materialize

    def test_materialized_diesel_preserves_spectra(self, materialize):
        """Diesel NIR survives import with one explicit response selection."""
        reference, dataset = materialize("diesel_nir", "CN")
        assert isinstance(dataset, SherpaDataset)
        assert dataset.shape == (784, 401)
        np.testing.assert_allclose(dataset.X, reference["spectra"])

    def test_materialized_diesel_preserves_explicit_target(self, materialize):
        """The canonical source exposes only the scientist-selected response."""
        reference, dataset = materialize("diesel_nir", "CN")
        assert dataset.target is not None
        np.testing.assert_allclose(dataset.target, reference["properties"][:, 1])
        assert dataset.target_context.target_type == "continuous"
        assert dataset.target_context.selected_target == "CN"

    def test_materialized_corn_preserves_spectra_and_explicit_target(self, materialize):
        """Corn M5 survives import without a dataset-specific DAG node."""
        reference, dataset = materialize("corn_m5", "Moisture")
        assert isinstance(dataset, SherpaDataset)
        assert dataset.shape == (80, 700)
        np.testing.assert_allclose(dataset.X, reference["spectra"])
        np.testing.assert_allclose(dataset.target, reference["properties"][:, 0])
        assert dataset.target_context.selected_target == "Moisture"
        assert dataset.sample_axis is not None
        assert dataset.sample_axis.labels == [f"corn_m5_row_{index + 1:04d}" for index in range(80)]

    @pytest.mark.skipif(not HAS_SCP, reason="SpectroChemPy not installed")
    def test_materialized_reference_preserves_wavelength_axis(self, materialize):
        """The portable file keeps the scientific feature coordinates."""
        _reference, dataset = materialize("diesel_nir", "CN")
        spectral = dataset.feature_axis
        assert spectral is not None
        x_data = np.array(spectral.values).flatten()
        assert x_data[0] == pytest.approx(750.0)
        assert x_data[-1] == pytest.approx(1550.0)

    def test_materialized_reference_records_canonical_file_provenance(self, materialize):
        """The DAG reports the visible canonical file boundary, not a hidden loader."""
        _reference, dataset = materialize("diesel_nir", "CN")
        assert dataset.meta["csv.target_column"] == "CN"
        assert dataset.meta["csv.target_type"] == "continuous"


# ---------------------------------------------------------------------------
# Tests: Metadata Extraction + get_dataset_info()
# ---------------------------------------------------------------------------


class TestMetadataExtraction:
    """Test CSV/MAT metadata extraction and get_dataset_info()."""

    def test_csv_metadata_extraction(self, eigenvector_fixture_dir: Path):
        """extract_csv_metadata should return Name, Author, Date from diesel CSV."""
        meta = extract_csv_metadata(eigenvector_fixture_dir / FIXTURE_DIESEL_SPEC)
        assert "name" in meta
        assert "NIR" in meta["name"] or "Diesel" in meta["name"]
        assert "author" in meta
        assert len(meta["author"]) > 0
        # Date may or may not be present depending on the file
        assert isinstance(meta, dict)

    def test_mat_metadata_extraction(self, eigenvector_fixture_dir: Path):
        """extract_mat_metadata should return metadata from corn .mat."""
        try:
            from scipy.io import loadmat
        except ImportError:
            pytest.skip("scipy not installed")
        mat = loadmat(str(eigenvector_fixture_dir / FIXTURE_CORN_MAT), squeeze_me=False)
        ds = mat["m5spec"]
        meta = extract_mat_metadata(ds)
        # .mat files typically have name and possibly date
        assert isinstance(meta, dict)

    def test_load_returns_file_metadata(self, eigenvector_fixture_dir: Path):
        """load_eigenvector_dataset should include file_metadata key."""
        result = load_eigenvector_dataset("diesel_nir", data_dir=eigenvector_fixture_dir)
        assert "file_metadata" in result
        assert isinstance(result["file_metadata"], dict)
        # Diesel CSV should have at least name and author
        assert "name" in result["file_metadata"]

    def test_load_corn_returns_file_metadata(self, eigenvector_fixture_dir: Path):
        """Corn .mat datasets should include file_metadata key."""
        result = load_eigenvector_dataset("corn_m5", data_dir=eigenvector_fixture_dir)
        assert "file_metadata" in result
        assert isinstance(result["file_metadata"], dict)

    def test_get_dataset_info_diesel(self, eigenvector_fixture_dir: Path):
        """get_dataset_info('diesel_nir') should return full info card."""
        info = get_dataset_info("diesel_nir", data_dir=eigenvector_fixture_dir)
        assert info["name"] == "diesel_nir"
        assert info["source"] == "eigenvector"
        assert info["n_samples"] == 784
        assert info["n_features"] == 401
        assert info["technique"] == "NIR"
        assert "wavelength_min" in info
        assert info["wavelength_min"] == pytest.approx(750.0)
        assert info["wavelength_max"] == pytest.approx(1550.0)
        assert "property_stats" in info
        assert len(info["property_stats"]) == 7
        # Check property stats structure
        bp50_stat = info["property_stats"][0]
        assert bp50_stat["name"] == "BP50"
        assert "min" in bp50_stat
        assert "max" in bp50_stat
        assert "nan_pct" in bp50_stat

    def test_get_dataset_info_corn(self, eigenvector_fixture_dir: Path):
        """get_dataset_info('corn_m5') should return corn info card."""
        info = get_dataset_info("corn_m5", data_dir=eigenvector_fixture_dir)
        assert info["name"] == "corn_m5"
        assert info["n_samples"] == 80
        assert info["n_features"] == 700
        assert "property_stats" in info
        assert len(info["property_stats"]) == 4

    def test_get_dataset_info_has_file_metadata(self, eigenvector_fixture_dir: Path):
        """Info card should include file_metadata from CSV/MAT headers."""
        info = get_dataset_info("diesel_nir", data_dir=eigenvector_fixture_dir)
        assert "file_metadata" in info
        assert isinstance(info["file_metadata"], dict)

    def test_parse_mat_returns_four_tuple(self, eigenvector_fixture_dir: Path):
        """parse_eigenvector_mat should now return 4-tuple with metadata."""
        result = parse_eigenvector_mat(
            eigenvector_fixture_dir / FIXTURE_CORN_MAT, spec_key="m5spec", prop_key="propvals"
        )
        assert len(result) == 4
        spec_data, axis_values, prop_data, file_metadata = result
        assert spec_data.shape == (80, 700)
        assert isinstance(file_metadata, dict)
