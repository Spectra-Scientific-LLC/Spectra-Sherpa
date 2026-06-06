"""
Integration tests for Eigenvector Research dataset adapters.

Tests the Eigenvector parser library, SpectroChemPy integration, PCA
decomposition, and DataSourceNode DAG integration using generated fixtures.
The real datasets are cataloged for runtime download from:
https://eigenvector.com/resources/data-sets/

Covers:
- Library parser (app.lib.eigenvector): DATASET_CATALOG, load_eigenvector_dataset
- Diesel-like NIR spectral data — 784 samples × 401 wavelengths (750–1550 nm)
- Diesel-like property targets — 7 reference properties with missing values
- Corn-like NIR .mat data — 80 samples × 700 channels, 3 instruments
- PCA decomposition on real NIR spectra (SpectroChemPy + sklearn)
- DataSourceNode integration (source="eigenvector")

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_eigenvector_datasets.py -v --no-cov
"""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path

import numpy as np
import pytest
from sklearn.decomposition import PCA as SklearnPCA
from sklearn.preprocessing import StandardScaler

from spectra_sherpa.app.lib.eigenvector import (
    DATASET_CATALOG,
    EIGENVECTOR_DATA_DIR,
    extract_csv_metadata,
    extract_mat_metadata,
    get_dataset_info,
    load_eigenvector_dataset,
    parse_eigenvector_csv,
    parse_eigenvector_mat,
)
from spectra_sherpa.app.lib.scp_compat import HAS_SCP, NDDataset, scp
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

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

    def test_scp_pca_on_diesel(self, diesel_spectra):
        """SpectroChemPy PCA on Diesel NIR data should decompose cleanly."""
        data, _, wavelengths = diesel_spectra
        dataset = scp.NDDataset(data)
        dataset.x = scp.Coord(wavelengths, title="wavelength", units="nm")

        pca = scp.PCA(n_components=5)
        pca.fit(dataset)
        scores = pca.transform()
        loadings = pca.components

        assert scores.shape[0] == data.shape[0]
        assert scores.shape[1] == 5
        assert loadings.shape[0] == 5
        assert loadings.shape[1] == data.shape[1]

        # Explained variance should be available
        evr = np.array(pca.explained_variance_ratio.data).flatten()
        assert evr.sum() > 0.80, f"First 5 PCs explain {evr.sum():.1%}"

    def test_scp_pca_loadings_have_wavelengths(self, diesel_spectra):
        """PCA loadings should carry the wavelength axis from input data."""
        data, _, wavelengths = diesel_spectra
        dataset = scp.NDDataset(data)
        dataset.x = scp.Coord(wavelengths, title="wavelength", units="nm")

        pca = scp.PCA(n_components=2)
        pca.fit(dataset)
        loadings = pca.components

        # Loadings x-axis should have same wavelength range
        lx = np.array(loadings.x.data).flatten()
        assert len(lx) == len(wavelengths)
        assert lx[0] == pytest.approx(wavelengths[0])
        assert lx[-1] == pytest.approx(wavelengths[-1])


# ---------------------------------------------------------------------------
# Tests: PCA on Diesel NIR Spectra (sklearn — always available)
# ---------------------------------------------------------------------------


class TestDieselPca:
    """Test PCA decomposition on the Diesel NIR spectra using sklearn."""

    def test_pca_2_components(self, diesel_spectra):
        """PCA with 2 components should capture >40% of variance in NIR data."""
        data, _, _ = diesel_spectra
        pca = SklearnPCA(n_components=2)
        scores = pca.fit_transform(data)

        assert scores.shape == (data.shape[0], 2)
        total_var = pca.explained_variance_ratio_.sum()
        assert total_var > 0.40, f"First 2 PCs explain only {total_var:.1%} variance"

    def test_pca_5_components(self, diesel_spectra):
        """First 5 PCs should capture the majority of spectral variance."""
        data, _, _ = diesel_spectra
        pca = SklearnPCA(n_components=5)
        pca.fit(data)

        cumulative_var = np.cumsum(pca.explained_variance_ratio_)
        assert cumulative_var[-1] > 0.80, f"First 5 PCs explain only {cumulative_var[-1]:.1%} variance"

    def test_pca_scores_shape(self, diesel_spectra):
        """PCA scores should have correct dimensions."""
        data, _, _ = diesel_spectra
        n_components = 10
        pca = SklearnPCA(n_components=n_components)
        scores = pca.fit_transform(data)
        loadings = pca.components_

        assert scores.shape == (data.shape[0], n_components)
        assert loadings.shape == (n_components, data.shape[1])

    def test_pca_reconstruction_error(self, diesel_spectra):
        """PCA reconstruction with enough components should have low error."""
        data, _, _ = diesel_spectra
        pca = SklearnPCA(n_components=20)
        scores = pca.fit_transform(data)
        reconstructed = pca.inverse_transform(scores)

        # Relative reconstruction error
        mse = np.mean((data - reconstructed) ** 2)
        data_var = np.var(data)
        relative_error = mse / data_var
        assert relative_error < 0.05, f"Reconstruction error {relative_error:.4f} is too high (expected <5%)"

    def test_pca_standardized(self, diesel_spectra):
        """PCA on standardized data should work correctly."""
        data, _, _ = diesel_spectra
        scaler = StandardScaler()
        data_scaled = scaler.fit_transform(data)

        pca = SklearnPCA(n_components=5)
        scores = pca.fit_transform(data_scaled)

        assert scores.shape == (data.shape[0], 5)
        assert pca.explained_variance_ratio_.sum() > 0.5

    def test_hotelling_t2_outlier_detection(self, diesel_spectra):
        """Hotelling T² statistic should identify potential outliers."""
        data, _, _ = diesel_spectra
        pca = SklearnPCA(n_components=5)
        scores = pca.fit_transform(data)

        # Hotelling T² = sum(scores^2 / eigenvalues)
        eigenvalues = pca.explained_variance_
        t2 = np.sum((scores**2) / eigenvalues, axis=1)

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

    def test_corn_pca_sklearn(self, corn_data):
        """PCA on corn M5 NIR spectra should separate samples (sklearn)."""
        data = corn_data["m5spec"]["data"][0, 0]
        pca = SklearnPCA(n_components=3)
        scores = pca.fit_transform(data)

        assert scores.shape == (80, 3)
        # Corn NIR data should have strong structure (>80% in 3 PCs)
        total_var = pca.explained_variance_ratio_.sum()
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

    @pytest.mark.skipif(not HAS_SCP, reason="SpectroChemPy not installed")
    def test_corn_scp_pca(self, corn_data):
        """SpectroChemPy PCA on corn M5 spectra."""
        spec_data = corn_data["m5spec"]["data"][0, 0]
        dataset = scp.NDDataset(spec_data)

        pca = scp.PCA(n_components=3)
        pca.fit(dataset)
        scores = pca.transform()

        assert scores.shape[0] == 80
        assert scores.shape[1] == 3

        evr = np.array(pca.explained_variance_ratio.data).flatten()
        assert evr.sum() > 0.80


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
        pca = SklearnPCA(n_components=3)
        scores = pca.fit_transform(X)
        corr = np.abs(np.corrcoef(scores[:, 0], y)[0, 1])
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

    def test_missing_default_data_reports_runtime_download_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Default loads degrade with a clear message when upstream data is absent."""
        import spectra_sherpa.app.lib.eigenvector as ev

        empty_package_data = tmp_path / "empty-package-data"
        empty_package_data.mkdir()
        monkeypatch.setattr(ev, "EIGENVECTOR_DATA_DIR", empty_package_data)
        monkeypatch.setattr(ev, "_runtime_data_dir", lambda: tmp_path / "runtime-cache")
        monkeypatch.setenv(ev.EIGENVECTOR_RUNTIME_DOWNLOAD_ENV, "false")

        with pytest.raises(FileNotFoundError, match="no longer bundled"):
            ev.load_eigenvector_dataset("diesel_nir")

    def test_runtime_download_extracts_archive_into_user_cache(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        eigenvector_fixture_dir: Path,
    ):
        """Runtime download/cache can hydrate catalog files without bundled data."""
        import spectra_sherpa.app.lib.eigenvector as ev

        archive_path = tmp_path / "diesel.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.write(eigenvector_fixture_dir / FIXTURE_DIESEL_SPEC, "diesel_spec.csv")
            archive.write(eigenvector_fixture_dir / FIXTURE_DIESEL_PROP, "diesel_prop.csv")

        empty_package_data = tmp_path / "empty-package-data"
        empty_package_data.mkdir()
        runtime_cache = tmp_path / "runtime-cache"
        catalog = dict(ev.DATASET_CATALOG["diesel_nir"])
        catalog["archive_url"] = archive_path.as_uri()

        monkeypatch.setattr(ev, "EIGENVECTOR_DATA_DIR", empty_package_data)
        monkeypatch.setattr(ev, "_runtime_data_dir", lambda: runtime_cache)
        monkeypatch.setenv(ev.EIGENVECTOR_RUNTIME_DOWNLOAD_ENV, "true")
        monkeypatch.setitem(ev.DATASET_CATALOG, "diesel_nir", catalog)

        result = ev.load_eigenvector_dataset("diesel_nir")

        assert result["spectra"].shape == (784, 401)
        assert (runtime_cache / "diesel_csv" / "diesel_spec.csv").exists()
        assert (runtime_cache / "diesel_csv" / "diesel_prop.csv").exists()


# ---------------------------------------------------------------------------
# Tests: DataSourceNode Integration (source="eigenvector")
# ---------------------------------------------------------------------------


class TestDataSourceNodeEigenvector:
    """Test the DataSourceNode with eigenvector source."""

    @pytest.fixture(autouse=True)
    def _use_generated_eigenvector_data(self, patch_eigenvector_loader):
        return None

    @pytest.fixture
    def make_node(self):
        """Create a DataSourceNode with given parameters."""
        from spectra_sherpa.app.services.dag.nodes.data import DataSourceNode

        def _make(params: dict):
            node = DataSourceNode(node_id="test_ev", parameters=params)
            return node

        return _make

    @pytest.mark.asyncio
    async def test_eigenvector_diesel_returns_dict(self, make_node):
        """Eigenvector source should return dict with default + target."""
        node = make_node({"source": "eigenvector", "eigenvector_dataset": "diesel_nir"})
        result = await node.execute()
        assert isinstance(result, dict)
        assert "default" in result
        assert "target" in result

    @pytest.mark.asyncio
    async def test_eigenvector_diesel_spectra_shape(self, make_node):
        """Diesel NIR should load 784 × 401 spectra."""
        node = make_node({"source": "eigenvector", "eigenvector_dataset": "diesel_nir"})
        result = await node.execute()
        dataset = result["default"]
        assert isinstance(dataset, SherpaDataset)
        assert dataset.shape == (784, 401)
        assert dataset.domain.technique == "NIR"

    @pytest.mark.asyncio
    async def test_eigenvector_diesel_properties_on_target(self, make_node):
        """Properties should be available on the target port as numpy array."""
        node = make_node({"source": "eigenvector", "eigenvector_dataset": "diesel_nir"})
        result = await node.execute()
        target = result["target"]
        assert target is not None
        assert isinstance(target, np.ndarray)
        assert target.ndim == 2
        assert target.shape == (784, 7)
        # Target embedded in dataset with rich context
        dataset = result["default"]
        assert dataset.target is not None
        np.testing.assert_array_equal(dataset.target, target)
        assert dataset.target_context.target_type == "continuous"
        assert dataset.target_context.target_names == ["BP50", "CN", "D4052", "FLASH", "FREEZE", "TOTAL", "VISC"]

    @pytest.mark.asyncio
    async def test_eigenvector_corn_m5(self, make_node):
        """Corn M5 should load 80 × 700 spectra with 4 properties."""
        node = make_node({"source": "eigenvector", "eigenvector_dataset": "corn_m5"})
        result = await node.execute()
        dataset = result["default"]
        assert isinstance(dataset, SherpaDataset)
        assert dataset.shape == (80, 700)
        assert dataset.domain.technique == "NIR"
        target = result["target"]
        assert isinstance(target, np.ndarray)
        assert target.shape == (80, 4)
        # Embedded target
        assert dataset.target is not None
        np.testing.assert_array_equal(dataset.target, target)
        assert dataset.target_context.target_type == "continuous"
        assert dataset.target_context.target_names == ["Moisture", "Oil", "Protein", "Starch"]

    @pytest.mark.skipif(not HAS_SCP, reason="SpectroChemPy not installed")
    @pytest.mark.asyncio
    async def test_eigenvector_scp_nddataset(self, make_node):
        """With SCP, eigenvector should return SherpaDataset with wavelength axis."""
        node = make_node({"source": "eigenvector", "eigenvector_dataset": "diesel_nir"})
        result = await node.execute()
        dataset = result["default"]
        assert isinstance(dataset, SherpaDataset)
        assert dataset.shape == (784, 401)
        # Check wavelength axis
        spectral = dataset.feature_axis
        assert spectral is not None
        x_data = np.array(spectral.values).flatten()
        assert x_data[0] == pytest.approx(750.0)
        assert x_data[-1] == pytest.approx(1550.0)

    @pytest.mark.skipif(not HAS_SCP, reason="SpectroChemPy not installed")
    @pytest.mark.asyncio
    async def test_eigenvector_scp_provenance(self, make_node):
        """With SCP, provenance should record eigenvector_dataset parameter."""
        node = make_node({"source": "eigenvector", "eigenvector_dataset": "diesel_nir"})
        result = await node.execute()
        dataset = result["default"]
        assert len(dataset.provenance) >= 1
        source_step = dataset.provenance[0]
        assert source_step.parameters["source"] == "eigenvector"
        assert source_step.parameters["eigenvector_dataset"] == "diesel_nir"


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
