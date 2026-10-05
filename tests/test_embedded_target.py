"""Tests for the embedded target architecture.

Verifies:
1. Data Source embeds target into dataset.target with TargetContext
2. Single-wire workflows (DataSource → PLS) work without explicit y port
3. Backward-compat: explicit y wiring still works
4. AttachTarget utility node
5. TargetContext.target_names serialization roundtrip
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import (
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.app.lib.target_authority import issue_target_authority
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_selected_target_dataset
from tests._optional_scp import HAS_SCP

_skip_no_scp = pytest.mark.skipif(not HAS_SCP, reason="spectrochempy not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_node():
    """Create a DAG node by type with given parameters."""

    def _make(node_type: str, params: dict | None = None, node_id: str = "test"):
        return node_registry.create_node(node_type, node_id, params or {})

    return _make


def _make_dataset_with_target(
    n_samples: int = 50,
    n_features: int = 100,
    n_targets: int = 1,
    target_type: str = "continuous",
    target_names: list[str] | None = None,
) -> SherpaDataset:
    """Create a SherpaDataset with embedded target for testing."""
    rng = np.random.RandomState(42)
    X = rng.randn(n_samples, n_features)
    if target_type == "continuous":
        target = rng.randn(n_samples, n_targets) if n_targets > 1 else rng.randn(n_samples)
    else:
        target = rng.choice(["A", "B", "C"], size=n_samples)

    ds = SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(
            values=np.arange(n_features, dtype=np.float64),
            title="Wavelength",
        ),
        target=target,
        target_context=TargetContext(
            target_type=target_type,
            target_names=target_names,
        ),
        backend="numpy",
    )
    return ds


def _load_materialized_reference(
    tmp_path: Path,
    reference: dict[str, object],
    *,
    selected_target: str,
    target_type: str,
) -> SherpaDataset:
    """Exercise the same reference-to-portable-file boundary used by imports."""
    from spectra_sherpa.app.services.dag.nodes.data.file_load_node import FileLoadNode

    spectra = np.asarray(reference["spectra"], dtype=np.float64)
    wavelengths = reference.get("wavelengths")
    columns = (
        [str(value) for value in np.asarray(wavelengths).reshape(-1)]
        if wavelengths is not None
        else [str(index) for index in range(spectra.shape[1])]
    )
    frame = pd.DataFrame(spectra, columns=columns)
    properties = np.asarray(reference["properties"])
    for index, property_name in enumerate(reference.get("prop_names") or []):
        frame[str(property_name)] = properties[:, index]
    path = tmp_path / "managed-reference.csv"
    frame.to_csv(path, index_label="sample_id")
    return FileLoadNode("source", {"experiment_id": 1, "file_id": 1})._load_file(
        path,
        selected_target=selected_target,
        target_type=target_type,
    )


# ---------------------------------------------------------------------------
# 1. TargetContext.target_names
# ---------------------------------------------------------------------------


class TestTargetContext:
    def test_target_names_serialization_roundtrip(self):
        """target_names should survive to_dict() / from_dict() cycle."""
        ds = _make_dataset_with_target(
            n_targets=4,
            target_names=["Moisture", "Oil", "Protein", "Starch"],
        )
        d = ds.to_dict()
        restored = SherpaDataset.from_dict(d)
        assert restored.target_context.target_names == ["Moisture", "Oil", "Protein", "Starch"]
        assert restored.target_context.target_type == "continuous"
        np.testing.assert_array_equal(restored.target, ds.target)

    def test_target_names_none_when_not_set(self):
        """target_names defaults to None."""
        ctx = TargetContext(target_type="continuous")
        assert ctx.target_names is None

    def test_target_context_copy(self):
        """TargetContext copy should be deep."""
        ds = _make_dataset_with_target(
            n_targets=2,
            target_names=["A", "B"],
        )
        ds_copy = ds.copy()
        ds_copy.target_context.target_names.append("C")
        assert ds.target_context.target_names == ["A", "B"]


# ---------------------------------------------------------------------------
# 2. Data Source embeds target
# ---------------------------------------------------------------------------


class TestDataSourceEmbeddedTarget:
    @pytest.mark.parametrize(
        ("target_name", "target_index"),
        [("Moisture", 0), ("Oil", 1), ("Protein", 2), ("Starch", 3)],
    )
    def test_eigenvector_corn_m5_embedded(
        self,
        tmp_path: Path,
        patch_eigenvector_loader,
        target_name: str,
        target_index: int,
    ):
        """Every Corn response remains available through explicit selection."""
        reference = patch_eigenvector_loader("corn_m5")
        dataset = _load_materialized_reference(
            tmp_path,
            reference,
            selected_target=target_name,
            target_type="continuous",
        )

        assert dataset.target is not None
        assert dataset.target.shape == (80,)
        np.testing.assert_allclose(dataset.target, np.asarray(reference["properties"])[:, target_index])
        assert dataset.target_context.target_type == "continuous"
        assert dataset.target_context.selected_target == target_name

    def test_sklearn_iris_embedded(self, tmp_path: Path):
        """A materialized categorical reference preserves all Iris classes."""
        from sklearn.datasets import load_iris

        iris = load_iris()
        reference = {
            "spectra": iris.data,
            "wavelengths": None,
            "properties": np.asarray(iris.target).reshape(-1, 1),
            "prop_names": ["species"],
        }
        dataset = _load_materialized_reference(
            tmp_path,
            reference,
            selected_target="species",
            target_type="categorical",
        )

        assert dataset.target is not None
        assert len(dataset.target) == 150
        assert dataset.target_context.target_type == "categorical"

    def test_target_port_matches_embedded(self, tmp_path: Path, patch_eigenvector_loader):
        """The canonical target port is the embedded response object."""
        from spectra_sherpa.app.services.dag.io_contracts import extract_target_like

        dataset = _load_materialized_reference(
            tmp_path,
            patch_eigenvector_loader("diesel_nir"),
            selected_target="CN",
            target_type="continuous",
        )
        target_port = extract_target_like(dataset)

        assert target_port is dataset.target

    def test_exact_native_response_selection_does_not_require_a_sample_table(self):
        dataset = _make_dataset_with_target(
            n_samples=12,
            n_features=8,
            n_targets=2,
            target_names=["Carbon dioxide", "Water"],
        )
        dataset.target_context.target_units = "ppm"
        dataset.meta["source_collection"] = {
            "scientific_collection_sha256": "a" * 64,
            "manifest_digest": "b" * 64,
        }
        authority = issue_target_authority(
            dataset,
            column="Carbon dioxide",
            target_type="continuous",
        )

        selected = attach_selected_target_dataset(
            dataset,
            target_type="continuous",
            target_column="Carbon dioxide",
            node_id="data_1",
            target_authority=authority,
        )

        np.testing.assert_array_equal(selected.target, np.asarray(dataset.target)[:, 0])
        assert selected.target_context.selected_target == "Carbon dioxide"
        assert selected.target_context.target_names == ["Carbon dioxide"]
        assert selected.target_context.selected_authority == authority
        assert selected.meta.get("supervision_binding") is None


# ---------------------------------------------------------------------------
# 3. Single-wire PLS (no explicit y port)
# ---------------------------------------------------------------------------


class TestSingleWirePLS:
    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pls_infers_target_from_dataset(self, make_node):
        """PLS should extract y from dataset.target when y not wired."""
        ds = _make_dataset_with_target(n_samples=50, n_features=100, n_targets=1)
        node = make_node("model.fitted_pls", {"n_components": 2, "scale": True})
        result = await node.execute(input_data=ds)

        assert "default" in result.outputs
        assert "fitted_state" in result.outputs

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pls_multi_target_inferred(self, make_node):
        """PLS with 4 embedded targets should produce multi-target model."""
        ds = _make_dataset_with_target(
            n_samples=50,
            n_features=100,
            n_targets=4,
            target_names=["Moisture", "Oil", "Protein", "Starch"],
        )
        node = make_node("model.fitted_pls", {"n_components": 3, "scale": True})
        result = await node.execute(input_data=ds)

        assert "fitted_state" in result.outputs
        assert result.outputs["default"].shape == (50, 4)

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pls_explicit_y_still_works(self, make_node):
        """Explicit y wiring should override embedded target."""
        ds = _make_dataset_with_target(n_samples=50, n_features=100, n_targets=1)
        # Provide explicit y that differs from embedded
        explicit_y = np.random.randn(50)
        node = make_node("model.fitted_pls", {"n_components": 2, "scale": True})
        result = await node.execute(input_data=ds, y=explicit_y)

        assert "fitted_state" in result.outputs

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pls_explicit_y_dataset_names_override_embedded_names(self, make_node):
        """Explicit y dataset labels should override embedded X target names."""
        ds = _make_dataset_with_target(
            n_samples=50,
            n_features=100,
            n_targets=2,
            target_names=["Old A", "Old B"],
        )
        explicit_y = SherpaDataset(
            X=np.random.randn(50, 2),
            target_context=TargetContext(target_type="continuous", target_names=["Moisture", "Oil"]),
            backend="numpy",
        )
        node = make_node("model.fitted_pls", {"n_components": 2, "scale": True})
        result = await node.execute(input_data=ds, y=explicit_y)

        assert result.outputs["default"].shape == (50, 2)

    @pytest.mark.asyncio
    async def test_pls_no_target_gives_helpful_error(self, make_node):
        """PLS with no target anywhere should give helpful error."""
        ds = SherpaDataset(
            X=np.random.randn(50, 100),
            backend="numpy",
        )
        node = make_node("model.fitted_pls", {"n_components": 2})
        with pytest.raises(ValueError, match="requires training targets"):
            await node.execute(input_data=ds)


# ---------------------------------------------------------------------------
# 4. Single-wire PCR
# ---------------------------------------------------------------------------


class TestSingleWirePCR:
    @pytest.mark.asyncio
    async def test_pcr_infers_target(self, make_node):
        """PCR should extract y from dataset.target when y not wired."""
        ds = _make_dataset_with_target(n_samples=50, n_features=100, n_targets=1)
        node = make_node("model.pcr", {"n_components": 2, "scale": True})
        result = await node.execute(X=ds)

        assert "model" in result.outputs
        assert "default" in result.outputs  # scores


# ---------------------------------------------------------------------------
# 5. AttachTarget node
# ---------------------------------------------------------------------------


class TestAttachTarget:
    @pytest.mark.asyncio
    async def test_attach_continuous_target(self, make_node):
        """AttachTarget should embed target in dataset."""
        ds = SherpaDataset(X=np.random.randn(50, 100), backend="numpy")
        y = np.random.randn(50, 3)
        node = make_node("data.attach_target", {"target_type": "continuous"})
        result = await node.execute(X=ds, y=y)

        out = result["default"]
        assert isinstance(out, SherpaDataset)
        assert out.target is not None
        assert out.target.shape == (50, 3)

    @pytest.mark.asyncio
    async def test_attach_target_preserves_labeled_y_dataset_names(self, make_node):
        """AttachTarget should copy target names from an explicit labeled y dataset."""
        ds = SherpaDataset(X=np.random.randn(50, 100), backend="numpy")
        y_ds = SherpaDataset(
            X=np.random.randn(50, 2),
            target_context=TargetContext(target_type="continuous", target_names=["Protein", "Moisture"]),
            backend="numpy",
        )
        node = make_node("data.attach_target", {"target_type": "continuous"})
        result = await node.execute(X=ds, y=y_ds)

        assert result["default"].target_context.target_names == ["Protein", "Moisture"]


class TestMyDatasetEmbeddedCsvTargets:
    @_skip_no_scp
    def test_axis_column_csv_loads_shared_x_axis_as_two_spectra(self, make_node, tmp_path: Path):
        """Canonical file loading recognizes a shared wavenumber column."""
        node = make_node("data.file_load", {"experiment_id": 1, "file_id": 1})

        csv_path = tmp_path / "axis_column.csv"
        csv_path.write_text(
            "Wavenumber (cm-1),Condition A,Condition B\n" "200,1.0,10.0\n" "201,2.0,20.0\n" "202,3.0,30.0\n",
            encoding="ascii",
        )

        dataset = node._load_file(str(csv_path))

        assert isinstance(dataset, SherpaDataset)
        assert dataset.shape == (2, 3)
        assert dataset.data_role == "X_spectra"
        assert dataset.get_extra("csv.layout") == "axis_column_conditions"
        assert dataset.target is None
        assert dataset.feature_axis.title == "Wavenumber"
        assert dataset.feature_axis.units == "cm-1"
        assert dataset.sample_axis.labels == ["Condition A", "Condition B"]
        np.testing.assert_allclose(dataset.feature_axis.values, np.array([200.0, 201.0, 202.0]))
        np.testing.assert_allclose(dataset.X, np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]]))

    @_skip_no_scp
    def test_each_exact_csv_file_exposes_its_selected_target(self, make_node, tmp_path: Path):
        """Canonical loading keeps each file visible and binds one response."""
        node = make_node("data.file_load", {"experiment_id": 1, "file_id": 1})

        csv_a = tmp_path / "part_a.csv"
        csv_b = tmp_path / "part_b.csv"
        csv_a.write_text(
            "sample_id,1000.0,1001.0,Moisture,Oil\n" "a1,1.0,1.1,10.0,4.0\n" "a2,2.0,2.1,11.0,5.0\n",
            encoding="ascii",
        )
        csv_b.write_text(
            "sample_id,1000.0,1001.0,Moisture,Oil\n" "b1,3.0,3.1,12.0,6.0\n" "b2,4.0,4.1,13.0,7.0\n",
            encoding="ascii",
        )

        loaded = [
            node._load_file(str(csv_a), selected_target="Moisture", target_type="continuous"),
            node._load_file(str(csv_b), selected_target="Moisture", target_type="continuous"),
        ]

        np.testing.assert_allclose(loaded[0].target, [10.0, 11.0])
        np.testing.assert_allclose(loaded[1].target, [12.0, 13.0])
        assert all(dataset.target_context.selected_target == "Moisture" for dataset in loaded)

    @pytest.mark.asyncio
    async def test_attach_categorical_target(self, make_node):
        """AttachTarget with categorical type should set n_classes."""
        ds = SherpaDataset(X=np.random.randn(30, 50), backend="numpy")
        y = np.array([0, 1, 2] * 10)
        node = make_node("data.attach_target", {"target_type": "categorical"})
        result = await node.execute(X=ds, y=y)

        out = result["default"]
        assert out.target_context.target_type == "categorical"
        assert out.target_context.n_classes == 3

    @pytest.mark.asyncio
    async def test_attach_validates_sample_count(self, make_node):
        """AttachTarget should error if y has wrong number of samples."""
        ds = SherpaDataset(X=np.random.randn(50, 100), backend="numpy")
        y = np.random.randn(30)  # Wrong count
        node = make_node("data.attach_target")
        with pytest.raises(ValueError, match="50 samples"):
            await node.execute(X=ds, y=y)

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_attach_then_pls(self, make_node):
        """AttachTarget → PLS should work as single-wire pipeline."""
        ds = SherpaDataset(X=np.random.randn(50, 100), backend="numpy")
        y = np.random.randn(50)

        attach_node = make_node("data.attach_target", {"target_type": "continuous"}, node_id="attach")
        attach_result = await attach_node.execute(X=ds, y=y)
        ds_with_target = attach_result["default"]

        pls_node = make_node("model.fitted_pls", {"n_components": 2, "scale": True}, node_id="pls")
        pls_result = await pls_node.execute(input_data=ds_with_target)  # No y — inferred from embedded

        assert "fitted_state" in pls_result.outputs
