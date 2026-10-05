"""Contract tests for SCP-backed nodes.

Verifies:
1. No SCP node returns NDDataset in any output port
2. Shape conventions are correct for modeling node outputs
3. SherpaDataset outputs carry correct axis metadata
4. Matrix-only SCP projection reattaches exact native scientific identity

Run with:
    cd spectra-sherpa && .venv/bin/pytest tests/test_scp_node_contracts.py -v
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.app.services.dag.meta_helpers import (
    copy_processing_history,
    inherit_origin_context,
    inherit_sample_flags,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.serialization import serialize_result

try:
    import spectrochempy as _scp
except ImportError:
    _scp = None

_skip_no_scp = pytest.mark.skipif(_scp is None, reason="spectrochempy not installed")
_NDDataset = _scp.NDDataset if _scp is not None else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_no_nddataset(value, path=""):
    """Recursively assert that no NDDataset exists in the value tree."""
    if _NDDataset is not None and isinstance(value, _NDDataset):
        raise AssertionError(f"NDDataset found at output path '{path}'")
    if isinstance(value, dict):
        for k, v in value.items():
            _check_no_nddataset(v, f"{path}.{k}")
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _check_no_nddataset(v, f"{path}[{i}]")


def _unwrap_result(result) -> dict:
    """Unwrap NodeResult.outputs or pass through a plain dict."""
    if hasattr(result, "outputs"):
        return result.outputs
    return result


@pytest.fixture
def make_node():
    """Create a DAG node by type with given parameters."""

    def _make(node_type: str, params: dict | None = None, node_id: str = "test"):
        return node_registry.create_node(node_type, node_id, params or {})

    return _make


def _make_spectral_dataset(
    n_samples: int = 30,
    n_features: int = 100,
    *,
    n_targets: int = 0,
    target_names: list[str] | None = None,
    target_type: str = "continuous",
) -> SherpaDataset:
    """Build a synthetic SherpaDataset for testing."""
    rng = np.random.RandomState(42)
    X = rng.randn(n_samples, n_features).astype(np.float64)
    # Ensure positive values for MCR/SIMPLISMA (non-negative constraints)
    X = np.abs(X) + 0.1

    target = None
    target_context = None
    if n_targets > 0:
        if target_type == "continuous":
            target = rng.randn(n_samples, n_targets) if n_targets > 1 else rng.randn(n_samples)
        else:
            classes = np.array(["A", "B", "C"], dtype=object)
            target = np.resize(classes, n_samples)
        target_context = TargetContext(
            target_type=target_type,
            target_names=target_names,
        )

    ds = SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(
            values=np.linspace(350, 900, n_features),
            title="Wavelength",
            units="nm",
        ),
        sample_axis=SampleAxis(
            values=np.linspace(0, n_samples - 1, n_samples),
            title="Elapsed Time",
            units="s",
        ),
        domain=DomainContext(
            technique="UV-Vis",
            data_quantity="Absorbance",
            expected_units="nm",
        ),
        target=target,
        target_context=target_context,
        backend="numpy",
    )
    ds.is_time_series = True
    ds.meta.update(
        {
            "is_spectra": True,
            "spectral_technique": "UV-Vis",
            "data_quantity": "Absorbance",
            "x_title": "Wavelength",
            "x_units": "nm",
        }
    )
    return ds


def _make_adapter_mapping_dataset() -> SherpaDataset:
    """Build a mixture whose native identity cannot survive accidental defaults."""
    n_samples = 30
    n_features = 40
    sample_positions = np.cumsum(np.linspace(0.35, 2.25, n_samples))
    sample_labels = [f"Lab vial {index + 1:02d}" for index in range(n_samples)]
    descending_axis = 1900.0 - np.cumsum(np.linspace(10.0, 30.0, n_features))
    profiles = np.vstack(
        (
            np.exp(-0.5 * ((descending_axis - 1750.0) / 45.0) ** 2),
            np.exp(-0.5 * ((descending_axis - 1480.0) / 65.0) ** 2),
            np.exp(-0.5 * ((descending_axis - 1210.0) / 50.0) ** 2),
        )
    )
    progress = np.linspace(0.0, 1.0, n_samples)
    concentrations = np.column_stack(
        (
            np.clip(1.0 - 1.4 * progress, 0.0, None),
            np.sin(np.pi * progress) ** 2,
            np.clip(1.4 * progress - 0.4, 0.0, None),
        )
    )
    concentrations += 0.015
    return SherpaDataset(
        X=concentrations @ profiles + 0.001,
        feature_axis=SpectralAxis(
            values=descending_axis,
            title="Non-uniform descending Raman shift",
            units="cm-1",
        ),
        sample_axis=SampleAxis(
            values=sample_positions,
            labels=sample_labels,
            title="Named laboratory samples",
            units="min",
        ),
        units="a.u.",
        domain=DomainContext(technique="Raman", data_quantity="Intensity", expected_units="cm-1"),
        backend="numpy",
    )


def _assert_axis_exact(actual, expected) -> None:
    np.testing.assert_array_equal(actual.values, expected.values)
    assert actual.labels == expected.labels
    assert actual.title == expected.title
    assert actual.units == expected.units


# ---------------------------------------------------------------------------
# 1. No-NDDataset contract (all SCP modeling nodes)
# ---------------------------------------------------------------------------


class TestNoNDDatasetContract:
    """Every SCP modeling node must return SherpaDataset, never NDDataset."""

    @pytest.mark.asyncio
    async def test_pca_no_nddataset(self, make_node):
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        node = make_node("model.pca", {"n_components": "2"})
        result = _unwrap_result(await node.execute(input_data=ds))
        _check_no_nddataset(result, "pca")

    @pytest.mark.asyncio
    async def test_pls_no_nddataset(self, make_node):
        ds = _make_spectral_dataset(n_samples=30, n_features=50, n_targets=2, target_names=["A", "B"])
        node = make_node("model.fitted_pls", {"n_components": 2})
        result = _unwrap_result(await node.execute(input_data=ds, y=ds.target))
        _check_no_nddataset(result, "pls")

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_mcr_no_nddataset(self, make_node):
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        node = make_node("model.mcr_als", {"n_components": 2})
        result = _unwrap_result(await node.execute(input_data=ds))
        _check_no_nddataset(result, "mcr")

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_efa_no_nddataset(self, make_node):
        # EFA returns (n_samples, n_components) eigenvalues; use matching n_components
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        ds.is_time_series = True
        node = make_node("model.efa", {"n_components": 20})
        result = _unwrap_result(await node.execute(input_data=ds))
        _check_no_nddataset(result, "efa")

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_simplisma_no_nddataset(self, make_node):
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        node = make_node("model.simplisma", {"n_components": 2})
        result = _unwrap_result(await node.execute(input_data=ds))
        _check_no_nddataset(result, "simplisma")


# ---------------------------------------------------------------------------
# 2. Shape convention tests
# ---------------------------------------------------------------------------


class TestShapeConventions:
    """Verify canonical shapes for modeling node outputs."""

    @pytest.mark.asyncio
    async def test_pca_shapes(self, make_node):
        n_samples, n_features, n_components = 20, 50, 3
        ds = _make_spectral_dataset(n_samples=n_samples, n_features=n_features)
        ds.is_time_series = True
        node = make_node("model.pca", {"n_components": str(n_components)})
        result = _unwrap_result(await node.execute(input_data=ds))

        scores = result["scores"]
        loadings = result["loadings"]
        assert isinstance(scores, SherpaDataset)
        assert isinstance(loadings, SherpaDataset)
        assert scores.shape == (n_samples, n_components)
        assert loadings.shape == (n_components, n_features)

    @pytest.mark.asyncio
    async def test_pls_shapes(self, make_node):
        n_samples, n_features, n_components, n_targets = 30, 50, 3, 2
        ds = _make_spectral_dataset(
            n_samples=n_samples,
            n_features=n_features,
            n_targets=n_targets,
            target_names=["Target_A", "Target_B"],
        )
        node = make_node("model.fitted_pls", {"n_components": n_components})
        result = _unwrap_result(await node.execute(input_data=ds, y=ds.target))

        assert result["default"].shape == (n_samples, n_targets)
        assert result["vip_scores"].shape == (n_features,)
        envelope = result["fitted_state"]
        state = envelope["state"]
        assert envelope["schema_version"] == "spectrasherpa.fitted-pls-state/9"
        assert np.asarray(state["coefficients"]).shape == (n_features, n_targets)
        assert np.asarray(state["feature_offset"]).shape == (1, n_features)
        assert np.asarray(state["prediction_offset"]).shape == (1, n_targets)

    @pytest.mark.asyncio
    async def test_pls_state_preserves_training_shape_and_applies_through_one_authority(self, make_node):
        n_samples, n_features, n_components, n_targets = 5, 401, 3, 7
        ds = _make_spectral_dataset(
            n_samples=n_samples,
            n_features=n_features,
            n_targets=n_targets,
            target_names=[f"Property {i + 1}" for i in range(n_targets)],
        )
        fit = make_node("model.fitted_pls", {"n_components": n_components})
        fitted = await fit.execute(input_data=ds, y=ds.target)
        state = fitted.outputs["fitted_state"]["state"]
        assert state["reference_samples"] == n_samples
        assert state["features"] == n_features
        assert state["targets"] == n_targets
        assert state["n_components"] == n_components

        apply = make_node("model.apply_fitted_pls")
        applied = await apply.execute(input_data=ds, fitted_state=fitted.outputs["fitted_state"])
        np.testing.assert_allclose(applied.outputs["default"], fitted.outputs["default"])

    @pytest.mark.asyncio
    async def test_pls_state_records_exact_multi_target_width(self, make_node):
        ds = _make_spectral_dataset(
            n_samples=30,
            n_features=50,
            n_targets=2,
            target_names=["Moisture", "Oil"],
        )
        node = make_node("model.fitted_pls", {"n_components": 2})
        result = _unwrap_result(await node.execute(input_data=ds, y=ds.target))

        assert result["fitted_state"]["state"]["targets"] == 2
        assert result["default"].shape == (30, 2)

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_mcr_shapes(self, make_node):
        n_samples, n_features, n_components = 20, 50, 2
        ds = _make_spectral_dataset(n_samples=n_samples, n_features=n_features)
        node = make_node("model.mcr_als", {"n_components": n_components})
        result = _unwrap_result(await node.execute(input_data=ds))

        # C: (n_samples, n_components)
        assert result["default"].shape == (n_samples, n_components)
        # St: (n_components, n_features)
        assert result["St"].shape == (n_components, n_features)

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_simplisma_shapes(self, make_node):
        n_samples, n_features, n_components = 20, 50, 2
        ds = _make_spectral_dataset(n_samples=n_samples, n_features=n_features)
        node = make_node("model.simplisma", {"n_components": n_components})
        result = _unwrap_result(await node.execute(input_data=ds))

        # C (concentrations): (n_samples, n_components)
        assert isinstance(result["default"], SherpaDataset)
        assert result["default"].shape == (n_samples, n_components)
        # St (pure spectra): (n_components, n_features)
        assert isinstance(result["spectra"], SherpaDataset)
        assert result["spectra"].shape == (n_components, n_features)

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_efa_shapes(self, make_node):
        # EFA returns eigenvalues for min(n_samples, n_features) components
        n_samples, n_features = 20, 50
        n_components = n_samples  # EFA computes up to min(n_samples, n_features)
        ds = _make_spectral_dataset(n_samples=n_samples, n_features=n_features)
        node = make_node("model.efa", {"n_components": n_components})
        result = _unwrap_result(await node.execute(input_data=ds))

        # Forward eigenvalues: (n_samples, n_components)
        fwd = result["forward_eigenvalues"]
        assert isinstance(fwd, SherpaDataset)
        assert fwd.shape[0] == n_samples
        assert fwd.shape[1] == n_components


class TestOptionalAdapterScientificMapping:
    """The matrix-only SCP adapter must not erase native result identity."""

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_all_optional_nodes_reattach_exact_axes_and_sample_identity(self, make_node):
        source = _make_adapter_mapping_dataset()

        simplisma = _unwrap_result(await make_node("model.simplisma", {"n_components": 3}).execute(input_data=source))
        _assert_axis_exact(simplisma["spectra"].feature_axis, source.feature_axis)
        assert simplisma["spectra"].sample_axis.labels == [
            "Pure Spectrum 1",
            "Pure Spectrum 2",
            "Pure Spectrum 3",
        ]
        np.testing.assert_array_equal(simplisma["spectra"].sample_axis.values, np.arange(3, dtype=float))
        assert simplisma["concentrations"].feature_axis.labels == [
            "Component 1",
            "Component 2",
            "Component 3",
        ]
        np.testing.assert_array_equal(simplisma["concentrations"].feature_axis.values, np.arange(3, dtype=float))
        _assert_axis_exact(simplisma["concentrations"].sample_axis, source.sample_axis)

        mcr = _unwrap_result(
            await make_node(
                "model.mcr_als",
                {"n_components": 3, "max_iter": 200, "tol": 1e-5},
            ).execute(input_data=source)
        )
        _assert_axis_exact(mcr["St"].feature_axis, source.feature_axis)
        assert mcr["St"].sample_axis.labels == [
            "Pure Spectrum 1",
            "Pure Spectrum 2",
            "Pure Spectrum 3",
        ]
        np.testing.assert_array_equal(mcr["St"].sample_axis.values, np.arange(3, dtype=float))
        assert mcr["C"].feature_axis.labels == ["Component 1", "Component 2", "Component 3"]
        np.testing.assert_array_equal(mcr["C"].feature_axis.values, np.arange(3, dtype=float))
        _assert_axis_exact(mcr["C"].sample_axis, source.sample_axis)
        _assert_axis_exact(mcr["residuals"].feature_axis, source.feature_axis)
        _assert_axis_exact(mcr["residuals"].sample_axis, source.sample_axis)

        source.is_time_series = True
        efa = _unwrap_result(await make_node("model.efa", {"n_components": 3}).execute(input_data=source))
        for output_name in ("forward_eigenvalues", "backward_eigenvalues"):
            output = efa[output_name]
            assert output.feature_axis.labels == ["EV1", "EV2", "EV3"]
            np.testing.assert_array_equal(output.feature_axis.values, np.arange(3, dtype=float))
            _assert_axis_exact(output.sample_axis, source.sample_axis)

        _check_no_nddataset({"simplisma": simplisma, "mcr": mcr, "efa": efa}, "adapter_mapping")


# ---------------------------------------------------------------------------
# 3. Explicit algorithm identity on primary outputs
# ---------------------------------------------------------------------------


class TestExplicitOutputTypes:
    """Primary serialized outputs should retain explicit algorithm identity."""

    @pytest.mark.asyncio
    async def test_pls_outputs_have_explicit_canonical_port_types(self, make_node):
        ds = _make_spectral_dataset(
            n_samples=30,
            n_features=50,
            n_targets=2,
            target_names=["Moisture", "Oil"],
        )
        node = make_node("model.fitted_pls", {"n_components": 2})
        result = _unwrap_result(await node.execute(input_data=ds, y=ds.target))
        metadata = node.metadata

        assert [port.type_ref for port in metadata.output_ports] == [
            "spectrasherpa://types/TargetMatrix/1.0",
            "spectrasherpa://types/RegressionModel/1.0",
            "spectrasherpa://types/VariableImportance/1.0",
            "spectrasherpa://types/RegressionComparison/1.0",
            "spectrasherpa://types/ScoreMatrix/1.0",
            "spectrasherpa://types/LoadingMatrix/1.0",
            "spectrasherpa://types/ExplainedVarianceMatrix/1.0",
            "spectrasherpa://types/RegressionCoefficientMatrix/1.0",
        ]
        assert result["fitted_state"]["schema_version"] == "spectrasherpa.fitted-pls-state/9"

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_mcr_default_output_has_explicit_type(self, make_node):
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        node = make_node("model.mcr_als", {"n_components": 2})
        result = _unwrap_result(await node.execute(input_data=ds))

        payload = serialize_result(result["default"])
        assert payload["metadata"]["type"] == "MCR_ALS"

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_simplisma_default_output_has_explicit_type(self, make_node):
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        node = make_node("model.simplisma", {"n_components": 2})
        result = _unwrap_result(await node.execute(input_data=ds))

        payload = serialize_result(result["default"])
        assert payload["metadata"]["type"] == "SIMPLISMA"

    @pytest.mark.asyncio
    async def test_plsda_default_output_has_explicit_type(self, make_node):
        ds = _make_spectral_dataset(
            n_samples=60,
            n_features=50,
            n_targets=1,
            target_type="categorical",
        )
        node = make_node("classification.plsda", {"n_components": 2, "scale": False})
        result = _unwrap_result(await node.execute(X=ds))

        payload = serialize_result(result["default"])
        assert payload["metadata"]["type"] == "PLS_DA"


class TestOriginContextPropagation:
    """Transformed outputs should keep serialized Explore-tab context."""

    @pytest.mark.asyncio
    async def test_pca_serialized_outputs_preserve_technique_but_own_result_semantics(self, make_node):
        ds = _make_spectral_dataset(n_samples=24, n_features=60)
        node = make_node("model.pca", {"n_components": "3"})
        result = _unwrap_result(await node.execute(input_data=ds))

        scores_payload = serialize_result(result["scores"])
        loadings_payload = serialize_result(result["loadings"])

        assert scores_payload["metadata"]["is_time_series"] is True
        assert scores_payload["metadata"]["spectral_technique"] == "UV-Vis"
        assert scores_payload["metadata"]["data_quantity"] == "PCA score"
        assert scores_payload["metadata"]["value_units"] == "dimensionless"
        assert scores_payload["metadata"]["x_title"] == "Principal Component"

        assert loadings_payload["metadata"]["spectral_technique"] == "UV-Vis"
        assert loadings_payload["metadata"]["data_quantity"] == "PCA loading"
        assert loadings_payload["metadata"]["value_units"] == "dimensionless"
        assert loadings_payload["metadata"]["x_title"] == "Wavelength"
        assert loadings_payload["metadata"]["x_units"] == "nm"


class TestOriginContextHelpers:
    """Helper-level regression coverage for environments without SCP."""

    def test_copy_processing_history_preserves_serialized_origin_context(self):
        source = _make_spectral_dataset(n_samples=18, n_features=40)
        scores = SherpaDataset(
            X=np.ones((18, 3), dtype=np.float64),
            feature_axis=SpectralAxis(
                values=np.arange(3, dtype=np.float64),
                labels=["PC1", "PC2", "PC3"],
                title="Principal Component",
            ),
            backend="numpy",
        )
        loadings = SherpaDataset(
            X=np.ones((3, 40), dtype=np.float64),
            feature_axis=SpectralAxis(values=np.arange(40, dtype=np.float64), title="Feature"),
            backend="numpy",
        )

        copy_processing_history(source, scores)
        copy_processing_history(source, loadings)

        scores_payload = serialize_result(scores)
        loadings_payload = serialize_result(loadings)

        assert scores_payload["metadata"]["is_time_series"] is True
        assert scores_payload["metadata"]["spectral_technique"] == "UV-Vis"
        assert scores_payload["metadata"]["data_quantity"] == "Absorbance"

        assert loadings_payload["metadata"]["spectral_technique"] == "UV-Vis"
        assert loadings_payload["metadata"]["data_quantity"] == "Absorbance"
        assert loadings_payload["metadata"]["x_title"] == "Wavelength"
        assert loadings_payload["metadata"]["x_units"] == "nm"

    def test_pca_post_conversion_helpers_restore_serialized_origin_context(self):
        source = _make_spectral_dataset(n_samples=20, n_features=32)
        scores = SherpaDataset(
            X=np.ones((20, 2), dtype=np.float64),
            feature_axis=SpectralAxis(
                values=np.arange(2, dtype=np.float64),
                labels=["PC1", "PC2"],
                title="Principal Component",
            ),
            backend="numpy",
        )
        loadings = SherpaDataset(
            X=np.ones((2, 32), dtype=np.float64),
            feature_axis=SpectralAxis(values=np.arange(32, dtype=np.float64), title="Feature"),
            backend="numpy",
        )

        inherit_sample_flags(source, scores)
        inherit_origin_context(source, scores)
        inherit_origin_context(source, loadings, preserve_feature_axis=True)

        scores_payload = serialize_result(scores)
        loadings_payload = serialize_result(loadings)

        assert scores_payload["metadata"]["is_time_series"] is True
        assert scores_payload["metadata"]["spectral_technique"] == "UV-Vis"
        assert scores_payload["metadata"]["data_quantity"] == "Absorbance"

        assert loadings_payload["metadata"]["spectral_technique"] == "UV-Vis"
        assert loadings_payload["metadata"]["data_quantity"] == "Absorbance"
        assert loadings_payload["metadata"]["x_title"] == "Wavelength"
        assert loadings_payload["metadata"]["x_units"] == "nm"

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pls_state_binds_feature_axis_identity(self, make_node):
        ds = _make_spectral_dataset(
            n_samples=30,
            n_features=50,
            n_targets=2,
            target_names=["Moisture", "Oil"],
        )
        fit = make_node("model.fitted_pls", {"n_components": 2})
        result = _unwrap_result(await fit.execute(input_data=ds, y=ds.target))
        state = result["fitted_state"]["state"]

        assert state["feature_axis_values_sha256"] is not None
        assert state["feature_axis_units"] == "nm"

        changed = SherpaDataset(
            X=np.asarray(ds.X)[:, ::-1],
            feature_axis=SpectralAxis(
                values=np.asarray(ds.feature_axis.values)[::-1],
                title=ds.feature_axis.title,
                units=ds.feature_axis.units,
            ),
            backend="numpy",
        )
        apply = make_node("model.apply_fitted_pls")
        with pytest.raises(ValueError, match="fitted feature axis"):
            await apply.execute(input_data=changed, fitted_state=result["fitted_state"])
