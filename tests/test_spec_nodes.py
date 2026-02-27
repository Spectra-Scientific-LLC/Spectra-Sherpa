"""Tests for declarative spec node base classes (Phase 2)."""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.export_helpers import (
    extract_data_lines,
    format_kwargs,
    format_value,
    header_line,
    wrap_result_lines,
)
from spectra_sherpa.app.services.dag.meta_helpers import get_processing_history
from spectra_sherpa.app.services.dag.node_base import (
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    node_registry,
    register_node,
)
from spectra_sherpa.app.services.dag.spec_nodes import (
    EstimatorSpec,
    EstimatorSpecNode,
    TransformSpec,
    TransformSpecNode,
)

# ═══════════════════════════════════════════════════════════════════════════
# Helpers: tiny transforms and specs used across tests
# ═══════════════════════════════════════════════════════════════════════════


def _double(data: np.ndarray) -> np.ndarray:
    """Trivial transform: multiply every element by 2."""
    return data * 2


def _clip_floor(data: np.ndarray, *, floor: float = 0.0) -> np.ndarray:
    return np.maximum(data, floor)


def _scale(data: np.ndarray, *, factor: float = 1.0) -> np.ndarray:
    return data * factor


def _export_double(params, inp, node_id, indent, use_scp):
    return [
        f"{indent}# --- Double ({node_id}) ---",
        f"{indent}_data = np.array({inp}.data, dtype=np.float64) * 2",
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Concrete spec node subclasses (defined once, used by many tests)
# ═══════════════════════════════════════════════════════════════════════════


class DoubleNode(TransformSpecNode):
    """Multiply all values by 2 — simplest possible spec node."""

    metadata = NodeMetadata(
        node_type="test.double",
        category="test",
        label="Double",
        description="Multiply by 2",
        parameters=[],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )
    spec = TransformSpec(transform_fn=_double)


class ClipFloorSpecNode(TransformSpecNode):
    """Spec-equivalent of the imperative ClipFloorNode."""

    metadata = NodeMetadata(
        node_type="test.clip_floor_spec",
        category="test",
        label="Clip Floor (spec)",
        description="Clip below floor",
        parameters=[
            NodeParameter(
                name="floor",
                label="Floor",
                param_type="number",
                default=0.0,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )
    spec = TransformSpec(
        transform_fn=_clip_floor,
        extra_imports=["import numpy as np"],
    )


class ScaleWithRenameNode(TransformSpecNode):
    """Tests param_map: NodeParameter 'multiplier' → kwarg 'factor'."""

    metadata = NodeMetadata(
        node_type="test.scale_rename",
        category="test",
        label="Scale (rename)",
        description="Scale with renamed param",
        parameters=[
            NodeParameter(
                name="multiplier",
                label="Multiplier",
                param_type="number",
                default=1.0,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )
    spec = TransformSpec(
        transform_fn=_scale,
        param_map={"multiplier": "factor"},
    )


class DoubleWithExportNode(TransformSpecNode):
    """Spec node with an export function."""

    metadata = NodeMetadata(
        node_type="test.double_export",
        category="test",
        label="Double (export)",
        description="Multiply by 2 with export support",
        parameters=[],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )
    spec = TransformSpec(
        transform_fn=_double,
        export_lines_fn=_export_double,
        extra_imports=["import numpy as np"],
    )


class UnitsOverrideNode(TransformSpecNode):
    """Spec node that sets output_units."""

    metadata = NodeMetadata(
        node_type="test.units_override",
        category="test",
        label="Dimensionless Double",
        description="Double with explicit units",
        parameters=[],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )
    spec = TransformSpec(
        transform_fn=_double,
        output_units="dimensionless",
    )


# ═══════════════════════════════════════════════════════════════════════════
# TransformSpecNode tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTransformSpecNode:
    """TransformSpecNode unit tests."""

    @pytest.fixture
    def sample_ds(self):
        return SherpaDataset(
            X=np.array([[1.0, -2.0, 3.0], [4.0, -5.0, 6.0]]),
            feature_axis=SpectralAxis(values=np.array([100.0, 200.0, 300.0])),
            sample_axis=SampleAxis(labels=["sample_A", "sample_B"]),
            title="test spectra",
            units="absorbance",
        )

    @pytest.mark.asyncio
    async def test_basic_execute(self, sample_ds):
        node = DoubleNode("dbl_1")
        result = await node.execute(sample_ds)

        assert isinstance(result, SherpaDataset)
        np.testing.assert_array_equal(result.X, sample_ds.X * 2)
        assert result.shape == sample_ds.shape

    @pytest.mark.asyncio
    async def test_param_mapping(self, sample_ds):
        node = ScaleWithRenameNode("scale_1", {"multiplier": 3.0})
        result = await node.execute(sample_ds)

        np.testing.assert_array_almost_equal(result.X, sample_ds.X * 3.0)

    @pytest.mark.asyncio
    async def test_provenance_recorded(self, sample_ds):
        node = ClipFloorSpecNode("clip_1", {"floor": 0.0})
        result = await node.execute(sample_ds)

        history = get_processing_history(result)
        assert len(history) >= 1
        last = history[-1]
        assert last["op_id"] == "test.clip_floor_spec"
        assert last["parameters"]["floor"] == 0.0
        assert last["node_id"] == "clip_1"

    @pytest.mark.asyncio
    async def test_output_units_explicit(self, sample_ds):
        node = UnitsOverrideNode("units_1")
        result = await node.execute(sample_ds)

        assert result.units == "dimensionless"

    @pytest.mark.asyncio
    async def test_output_units_inherited(self, sample_ds):
        node = DoubleNode("dbl_2")
        result = await node.execute(sample_ds)

        # None output_units → inherited from input
        assert result.units == "absorbance"

    @pytest.mark.asyncio
    async def test_axes_preserved(self, sample_ds):
        node = DoubleNode("dbl_3")
        result = await node.execute(sample_ds)

        # x-axis values preserved
        np.testing.assert_array_equal(result.feature_axis.values, sample_ds.feature_axis.values)
        # y-axis labels preserved
        assert result.sample_axis.labels == sample_ds.sample_axis.labels

    @pytest.mark.asyncio
    async def test_title_preserved(self, sample_ds):
        node = DoubleNode("dbl_4")
        result = await node.execute(sample_ds)

        assert result.title == "test spectra"

    @pytest.mark.asyncio
    async def test_clip_floor_spec_behavior(self, sample_ds):
        node = ClipFloorSpecNode("clip_2", {"floor": 0.0})
        result = await node.execute(sample_ds)

        expected = np.maximum(sample_ds.X, 0.0)
        np.testing.assert_array_equal(result.X, expected)

    def test_generate_python_with_export_fn(self):
        node = DoubleWithExportNode("dbl_exp")
        lines = node.generate_python({"input": "results['src']"})

        assert any("Double" in line for line in lines)
        assert any("results['src']" in line for line in lines)

    def test_supports_export_with_fn(self):
        node = DoubleWithExportNode("dbl_exp")
        assert node.supports_python_export() is True

    def test_no_export_without_fn(self):
        node = DoubleNode("dbl_noexp")
        assert node.supports_python_export() is False

    def test_extra_imports_merged(self):
        node = DoubleWithExportNode("dbl_imp")
        assert "import numpy as np" in node.python_extra_imports

    @pytest.mark.asyncio
    async def test_resolve_params_defaults(self, sample_ds):
        node = ClipFloorSpecNode("clip_def")
        # No explicit params → uses default floor=0.0
        result = await node.execute(sample_ds)

        expected = np.maximum(sample_ds.X, 0.0)
        np.testing.assert_array_equal(result.X, expected)

    @pytest.mark.asyncio
    async def test_override_execute_for_diagnostics(self, sample_ds):
        """Subclass can override execute, call super, and add diagnostics."""

        class DiagDoubleNode(TransformSpecNode):
            metadata = NodeMetadata(
                node_type="test.diag_double",
                category="test",
                label="Diag Double",
                description="Double with diagnostics",
                parameters=[],
                input_types=["NDDataset"],
                output_type="NDDataset",
            )
            spec = TransformSpec(transform_fn=_double)

            async def execute(self, input_data=None, **kwargs):
                result = await super().execute(input_data, **kwargs)
                return NodeResult(
                    outputs={"default": result},
                    diagnostics={"mean_after": float(np.mean(result.X))},
                )

        node = DiagDoubleNode("diag_1")
        result = await node.execute(sample_ds)

        assert isinstance(result, NodeResult)
        assert "mean_after" in result.diagnostics
        assert isinstance(result.outputs["default"], SherpaDataset)


# ═══════════════════════════════════════════════════════════════════════════
# EstimatorSpecNode tests
# ═══════════════════════════════════════════════════════════════════════════


class TestEstimatorSpecNode:
    """EstimatorSpecNode unit tests."""

    @pytest.fixture
    def regression_data(self):
        rng = np.random.RandomState(42)
        X = rng.randn(30, 5)
        y = X @ np.array([1.0, 2.0, 0.5, -1.0, 0.3]) + 0.1 * rng.randn(30)
        X_ds = SherpaDataset(X=X)
        return X_ds, y

    @pytest.mark.asyncio
    async def test_basic_fit_predict(self, regression_data):
        from sklearn.linear_model import LinearRegression

        class LRNode(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.lr",
                category="test",
                label="Linear Regression",
                description="Simple LR",
                parameters=[
                    NodeParameter(
                        name="fit_intercept",
                        label="Fit Intercept",
                        param_type="boolean",
                        default=True,
                    ),
                ],
                input_types=["array", "array"],
                output_type="dict",
                input_ports=[
                    PortMetadata(
                        name="X",
                        type_ref="spectrasherpa://types/SpectralDataset/1.0",
                        label="X",
                    ),
                    PortMetadata(
                        name="y",
                        type_ref="spectrasherpa://types/Array1D/1.0",
                        label="y",
                    ),
                ],
            )
            spec = EstimatorSpec(estimator_class=LinearRegression)

        X_ds, y = regression_data
        node = LRNode("lr_1")
        result = await node.execute(X=X_ds, y=y)

        assert "model" in result
        assert "r2" in result
        assert "rmse" in result
        assert "predictions" in result
        assert "residuals" in result
        assert result["r2"] > 0.9  # synthetic data, should fit well

    @pytest.mark.asyncio
    async def test_pipeline_with_scaling(self, regression_data):
        from sklearn.linear_model import LinearRegression
        from sklearn.pipeline import Pipeline

        class ScaledLRNode(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.scaled_lr",
                category="test",
                label="Scaled LR",
                description="LR with scaling",
                parameters=[
                    NodeParameter(
                        name="fit_intercept",
                        label="Fit Intercept",
                        param_type="boolean",
                        default=True,
                    ),
                    NodeParameter(
                        name="scale",
                        label="Scale",
                        param_type="boolean",
                        default=True,
                    ),
                ],
                input_types=["array", "array"],
                output_type="dict",
            )
            spec = EstimatorSpec(
                estimator_class=LinearRegression,
                scale=True,
                scale_param="scale",
            )

        X_ds, y = regression_data
        node = ScaledLRNode("slr_1")
        result = await node.execute(X=X_ds, y=y)

        assert isinstance(result["model"], Pipeline)
        assert result["r2"] > 0.9

    @pytest.mark.asyncio
    async def test_param_mapping(self, regression_data):
        from sklearn.linear_model import Ridge

        class RidgeNode(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.ridge",
                category="test",
                label="Ridge",
                description="Ridge regression",
                parameters=[
                    NodeParameter(
                        name="regularization",
                        label="Regularization",
                        param_type="number",
                        default=1.0,
                    ),
                ],
                input_types=["array", "array"],
                output_type="dict",
            )
            spec = EstimatorSpec(
                estimator_class=Ridge,
                param_map={"regularization": "alpha"},
            )

        X_ds, y = regression_data
        node = RidgeNode("ridge_1", {"regularization": 0.5})
        result = await node.execute(X=X_ds, y=y)

        # Verify the model used alpha=0.5
        model = result["model"]
        assert model.alpha == 0.5
        assert result["r2"] > 0.9

    @pytest.mark.asyncio
    async def test_post_fit_hook(self, regression_data):
        from sklearn.linear_model import LinearRegression

        def _extras(model, X_data, y_array, X_ds, params, node_id):
            return {
                "coef": model.coef_.tolist(),
                "intercept": float(model.intercept_),
            }

        class LRExtrasNode(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.lr_extras",
                category="test",
                label="LR + extras",
                description="LR with post-fit hook",
                parameters=[],
                input_types=["array", "array"],
                output_type="dict",
            )
            spec = EstimatorSpec(
                estimator_class=LinearRegression,
                post_fit_fn=_extras,
            )

        X_ds, y = regression_data
        node = LRExtrasNode("lr_ext")
        result = await node.execute(X=X_ds, y=y)

        assert "coef" in result
        assert "intercept" in result
        assert len(result["coef"]) == 5  # 5 features

    @pytest.mark.asyncio
    async def test_y_not_required(self):
        """Unsupervised estimator (no y needed)."""
        from sklearn.cluster import KMeans

        class KMeansNode(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.kmeans",
                category="test",
                label="K-Means",
                description="K-Means clustering",
                parameters=[
                    NodeParameter(
                        name="n_clusters",
                        label="Clusters",
                        param_type="number",
                        default=3,
                    ),
                ],
                input_types=["array"],
                output_type="dict",
            )
            spec = EstimatorSpec(
                estimator_class=KMeans,
                y_required=False,
                param_map={"n_clusters": "n_clusters"},
            )

        X_ds = SherpaDataset(X=np.random.RandomState(0).randn(20, 4))
        node = KMeansNode("km_1", {"n_clusters": 3})
        result = await node.execute(X=X_ds)

        assert "model" in result
        assert "y_pred" in result
        labels = result["y_pred"]
        assert len(labels) == 20
        assert set(labels) == {0, 1, 2}

    @pytest.mark.asyncio
    async def test_custom_metrics(self, regression_data):
        from sklearn.linear_model import LinearRegression
        from sklearn.metrics import mean_absolute_error

        class MAENode(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.mae_lr",
                category="test",
                label="LR (MAE)",
                description="LR with custom MAE metric",
                parameters=[],
                input_types=["array", "array"],
                output_type="dict",
            )
            spec = EstimatorSpec(
                estimator_class=LinearRegression,
                metric_fns={
                    "mae": lambda yt, yp: float(mean_absolute_error(yt, yp)),
                },
            )

        X_ds, y = regression_data
        node = MAENode("mae_1")
        result = await node.execute(X=X_ds, y=y)

        assert "mae" in result
        assert "r2" not in result  # custom metrics replace defaults
        assert result["mae"] >= 0

    def test_supports_export_without_fn(self):
        from sklearn.linear_model import LinearRegression

        class NoExportLR(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.noexp_lr",
                category="test",
                label="LR (no export)",
                description="No export",
                parameters=[],
                input_types=["array", "array"],
                output_type="dict",
            )
            spec = EstimatorSpec(estimator_class=LinearRegression)

        node = NoExportLR("ne_1")
        assert node.supports_python_export() is False

    def test_supports_export_with_fn(self):
        from sklearn.linear_model import LinearRegression

        def _dummy_export(params, inputs, node_id, indent, use_scp):
            return [f"{indent}# exported"]

        class ExportLR(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.exp_lr",
                category="test",
                label="LR (export)",
                description="With export",
                parameters=[],
                input_types=["array", "array"],
                output_type="dict",
            )
            spec = EstimatorSpec(
                estimator_class=LinearRegression,
                export_lines_fn=_dummy_export,
            )

        node = ExportLR("e_1")
        assert node.supports_python_export() is True
        lines = node.generate_python({"X": "results['src']"})
        assert any("exported" in line for line in lines)


# ═══════════════════════════════════════════════════════════════════════════
# Registry integration
# ═══════════════════════════════════════════════════════════════════════════


@register_node
class _RegisteredDoubleNode(TransformSpecNode):
    """Test node that auto-registers via decorator."""

    metadata = NodeMetadata(
        node_type="test._registered_double",
        category="test",
        label="Registered Double",
        description="Registered spec double",
        parameters=[],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )
    spec = TransformSpec(transform_fn=_double)


# ═══════════════════════════════════════════════════════════════════════════
# Export helpers tests
# ═══════════════════════════════════════════════════════════════════════════


class TestExportHelpers:
    """Tests for export_helpers.py building blocks."""

    def test_header_line(self):
        result = header_line("Clip Floor", "clip_1", "    ")
        assert result == "    # --- Clip Floor (clip_1) ---"

    def test_extract_data_lines(self):
        lines = extract_data_lines("results['src']", "    ")
        assert len(lines) == 1
        assert "np.array(results['src'].data, dtype=np.float64)" in lines[0]

    def test_wrap_result_lines_scp(self):
        lines = wrap_result_lines("n1", "_data", "inp", "    ", use_scp=True)
        assert any("scp.NDDataset" in l for l in lines)
        assert any("results['n1']" in l for l in lines)

    def test_wrap_result_lines_numpy(self):
        lines = wrap_result_lines("n1", "_data", "inp", "    ", use_scp=False)
        assert any("_Result" in l for l in lines)
        assert any("results['n1']" in l for l in lines)

    def test_format_kwargs_simple(self):
        result = format_kwargs({"alpha": 0.5, "fit_intercept": True})
        assert "alpha=0.5" in result
        assert "fit_intercept=True" in result

    def test_format_kwargs_with_param_map(self):
        result = format_kwargs(
            {"regularization": 0.5},
            param_map={"regularization": "alpha"},
        )
        assert "alpha=0.5" in result
        assert "regularization" not in result

    def test_format_kwargs_empty(self):
        assert format_kwargs({}) == ""

    def test_format_value_bool(self):
        assert format_value(True) == "True"
        assert format_value(False) == "False"

    def test_format_value_string(self):
        assert format_value("hello") == "'hello'"

    def test_format_value_float(self):
        assert format_value(0.5) == "0.5"


# ═══════════════════════════════════════════════════════════════════════════
# TransformSpecNode auto-export tests (numpy_expr)
# ═══════════════════════════════════════════════════════════════════════════


class ClipFloorAutoExportNode(TransformSpecNode):
    """Spec node with numpy_expr for auto-export."""

    metadata = NodeMetadata(
        node_type="test.clip_floor_auto",
        category="test",
        label="Clip Floor (auto)",
        description="Clip below floor with auto-export",
        parameters=[
            NodeParameter(
                name="floor",
                label="Floor",
                param_type="number",
                default=0.0,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )
    spec = TransformSpec(
        transform_fn=_clip_floor,
        numpy_expr="np.maximum(_data, {floor})",
        extra_imports=["import numpy as np"],
    )


class TestTransformAutoExport:
    """TransformSpecNode auto-export via numpy_expr."""

    def test_supports_export_with_numpy_expr(self):
        node = ClipFloorAutoExportNode("ae_1")
        assert node.supports_python_export() is True

    def test_numpy_expr_generates_python_scp(self):
        node = ClipFloorAutoExportNode("ae_2", {"floor": 0.5})
        lines = node.generate_python(
            {"input": "results['src']"},
            use_scp=True,
        )
        code = "\n".join(lines)
        # Header
        assert "Clip Floor (auto)" in code
        assert "ae_2" in code
        # Data extraction
        assert "np.array(results['src'].data" in code
        # Expression with substituted param
        assert "_result = np.maximum(_data, 0.5)" in code
        # SCP wrapping
        assert "scp.NDDataset" in code

    def test_numpy_expr_generates_python_numpy(self):
        node = ClipFloorAutoExportNode("ae_3", {"floor": 0.5})
        lines = node.generate_python(
            {"input": "results['src']"},
            use_scp=False,
        )
        code = "\n".join(lines)
        # numpy mode uses _Result
        assert "_Result" in code
        assert "scp.NDDataset" not in code

    def test_numpy_expr_params_substituted(self):
        node = ClipFloorAutoExportNode("ae_4", {"floor": 1e-5})
        lines = node.generate_python({"input": "results['x']"})
        code = "\n".join(lines)
        # Small float → scientific notation (format_value produces "1.000000e-05")
        assert "e-05" in code

    def test_export_lines_fn_priority_over_numpy_expr(self):
        """Custom export_lines_fn should win over numpy_expr."""

        def custom_fn(params, inp, node_id, indent, use_scp):
            return [f"{indent}# custom wins"]

        class PriorityNode(TransformSpecNode):
            metadata = NodeMetadata(
                node_type="test.priority",
                category="test",
                label="Priority",
                description="Test priority",
                parameters=[],
                input_types=["NDDataset"],
                output_type="NDDataset",
            )
            spec = TransformSpec(
                transform_fn=_double,
                export_lines_fn=custom_fn,
                numpy_expr="should_not_appear",
            )

        node = PriorityNode("p_1")
        lines = node.generate_python({"input": "results['x']"})
        assert any("custom wins" in l for l in lines)
        assert not any("should_not_appear" in l for l in lines)

    def test_numpy_expr_with_no_params(self):
        """numpy_expr that has no param placeholders still works."""

        class AbsNode(TransformSpecNode):
            metadata = NodeMetadata(
                node_type="test.abs_auto",
                category="test",
                label="Abs",
                description="Absolute value",
                parameters=[],
                input_types=["NDDataset"],
                output_type="NDDataset",
            )
            spec = TransformSpec(
                transform_fn=lambda data: np.abs(data),
                numpy_expr="np.abs(_data)",
                extra_imports=["import numpy as np"],
            )

        node = AbsNode("abs_1")
        lines = node.generate_python({"input": "results['x']"})
        code = "\n".join(lines)
        assert "_result = np.abs(_data)" in code

    @pytest.mark.asyncio
    async def test_numpy_expr_node_still_executes(self):
        """Having numpy_expr doesn't break execute()."""
        node = ClipFloorAutoExportNode("ae_5", {"floor": 0.0})
        ds = SherpaDataset(X=np.array([[1.0, -2.0, 3.0]]))
        result = await node.execute(ds)
        np.testing.assert_array_equal(result.X, np.array([[1.0, 0.0, 3.0]]))


# ═══════════════════════════════════════════════════════════════════════════
# EstimatorSpecNode auto-export tests (estimator_import)
# ═══════════════════════════════════════════════════════════════════════════


class TestEstimatorAutoExport:
    """EstimatorSpecNode auto-export via estimator_import."""

    def _make_lr_node_class(self):
        from sklearn.linear_model import LinearRegression

        class AutoExportLR(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.auto_lr",
                category="test",
                label="Auto LR",
                description="LR with auto-export",
                parameters=[
                    NodeParameter(
                        name="fit_intercept",
                        label="Fit Intercept",
                        param_type="boolean",
                        default=True,
                    ),
                ],
                input_types=["array", "array"],
                output_type="dict",
                input_ports=[
                    PortMetadata(
                        name="X",
                        type_ref="spectrasherpa://types/SpectralDataset/1.0",
                    ),
                    PortMetadata(
                        name="y",
                        type_ref="spectrasherpa://types/Array1D/1.0",
                    ),
                ],
            )
            spec = EstimatorSpec(
                estimator_class=LinearRegression,
                estimator_import="from sklearn.linear_model import LinearRegression",
            )

        return AutoExportLR

    def test_supports_export_with_estimator_import(self):
        cls = self._make_lr_node_class()
        node = cls("alr_1")
        assert node.supports_python_export() is True

    def test_estimator_import_generates_python(self):
        cls = self._make_lr_node_class()
        node = cls("alr_2")
        lines = node.generate_python(
            {"X": "results['data']", "y": "results['labels']"},
        )
        code = "\n".join(lines)
        # Header
        assert "Auto LR" in code
        # Import
        assert "from sklearn.linear_model import LinearRegression" in code
        # X extraction
        assert "np.array(results['data'].data" in code
        # y extraction
        assert "np.array(results['labels']" in code
        # Constructor
        assert "model = LinearRegression(" in code
        # Fit + predict
        assert "model.fit(X, y)" in code
        assert "model.predict(X)" in code
        # Result
        assert "results['alr_2']" in code

    def test_estimator_import_with_scale(self):
        from sklearn.linear_model import LinearRegression

        class ScaledAutoLR(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.scaled_auto_lr",
                category="test",
                label="Scaled Auto LR",
                description="Scaled LR with auto-export",
                parameters=[
                    NodeParameter(
                        name="scale",
                        label="Scale",
                        param_type="boolean",
                        default=True,
                    ),
                ],
                input_types=["array", "array"],
                output_type="dict",
            )
            spec = EstimatorSpec(
                estimator_class=LinearRegression,
                scale=True,
                scale_param="scale",
                estimator_import="from sklearn.linear_model import LinearRegression",
            )

        node = ScaledAutoLR("slr_auto")
        lines = node.generate_python(
            {"X": "results['d']", "y": "results['l']"},
        )
        code = "\n".join(lines)
        assert "Pipeline" in code
        assert "StandardScaler" in code
        assert "_est = LinearRegression()" in code

    def test_estimator_import_param_mapping(self):
        from sklearn.linear_model import Ridge

        class AutoRidge(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.auto_ridge",
                category="test",
                label="Auto Ridge",
                description="Ridge with auto-export",
                parameters=[
                    NodeParameter(
                        name="regularization",
                        label="Reg",
                        param_type="number",
                        default=1.0,
                    ),
                ],
                input_types=["array", "array"],
                output_type="dict",
            )
            spec = EstimatorSpec(
                estimator_class=Ridge,
                param_map={"regularization": "alpha"},
                estimator_import="from sklearn.linear_model import Ridge",
            )

        node = AutoRidge("ar_1", {"regularization": 0.5})
        lines = node.generate_python(
            {"X": "results['d']", "y": "results['l']"},
        )
        code = "\n".join(lines)
        assert "Ridge(alpha=0.5)" in code
        assert "regularization" not in code

    def test_estimator_import_unsupervised(self):
        from sklearn.cluster import KMeans

        class AutoKMeans(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.auto_km",
                category="test",
                label="Auto KMeans",
                description="KMeans with auto-export",
                parameters=[
                    NodeParameter(
                        name="n_clusters",
                        label="K",
                        param_type="number",
                        default=3,
                    ),
                ],
                input_types=["array"],
                output_type="dict",
            )
            spec = EstimatorSpec(
                estimator_class=KMeans,
                y_required=False,
                estimator_import="from sklearn.cluster import KMeans",
            )

        node = AutoKMeans("akm_1", {"n_clusters": 5})
        lines = node.generate_python({"X": "results['d']"})
        code = "\n".join(lines)
        # Should NOT have y extraction
        assert "y = np.array" not in code
        # Should fit without y
        assert "model.fit(X)" in code
        # Constructor with param
        assert "n_clusters=5" in code

    def test_export_lines_fn_priority_over_estimator_import(self):
        from sklearn.linear_model import LinearRegression

        def custom_fn(params, inputs, node_id, indent, use_scp):
            return [f"{indent}# custom estimator export"]

        class PriorityEstNode(EstimatorSpecNode):
            metadata = NodeMetadata(
                node_type="test.priority_est",
                category="test",
                label="Priority Est",
                description="Test priority",
                parameters=[],
                input_types=["array", "array"],
                output_type="dict",
            )
            spec = EstimatorSpec(
                estimator_class=LinearRegression,
                export_lines_fn=custom_fn,
                estimator_import="should_not_appear",
            )

        node = PriorityEstNode("pe_1")
        lines = node.generate_python({"X": "results['d']"})
        assert any("custom estimator export" in l for l in lines)
        assert not any("should_not_appear" in l for l in lines)


# ═══════════════════════════════════════════════════════════════════════════
# Registry integration
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistryIntegration:
    """Verify spec nodes work with the node registry."""

    def test_registered_in_registry(self):
        meta = node_registry.get_metadata("test._registered_double")
        assert meta.label == "Registered Double"

    @pytest.mark.asyncio
    async def test_create_and_execute_via_registry(self):
        node = node_registry.create_node("test._registered_double", "reg_1")
        ds = SherpaDataset(X=np.array([[1.0, 2.0]]))
        result = await node.execute(ds)

        assert isinstance(result, SherpaDataset)
        np.testing.assert_array_equal(result.X, np.array([[2.0, 4.0]]))
