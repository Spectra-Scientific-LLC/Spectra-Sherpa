"""
Regression nodes: PCR, SVR, Linear Regression.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import (
    EvaluationResult,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history

from ...io_contracts import (
    attach_evaluation,
    bind_X,
    bind_y,
    resolve_target_names,
    to_numpy_1d,
    to_numpy_2d,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    register_node,
)
from .core_utils import (
    create_spectral_dataset as _create_spectral_dataset,
)
from .core_utils import (
    is_sequential_numeric as _is_sequential_numeric,
)
from .core_utils import (
    make_safe_coord as _make_safe_coord,
)

logger = logging.getLogger(__name__)

from sklearn.linear_model import LinearRegression
from sklearn.svm import SVR

from ...spec_nodes import EstimatorSpec, EstimatorSpecNode


@register_node
class PCRNode(Node):
    """
    Principal Component Regression (PCR) node.

    Performs PCA followed by linear regression on the scores.
    """

    metadata = NodeMetadata(
        node_type="model.pcr",
        category="regression",
        label="PCR",
        description="Principal Component Regression for calibration",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=1,
                max_value=20,
                step=1,
                description="Number of PCA components for regression",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="scale",
                label="Scale Data",
                param_type="boolean",
                default=True,
                description="Apply mean centering and scaling",
                required=False,
                category="basic",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Spectra (X)",
                description="Spectral data matrix (n_samples × n_wavenumbers)",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Targets (y)",
                description="Target values — optional if dataset has embedded target",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/RegressionModel/1.0",
                required=True,
                label="PCR Model",
                description="Trained PCR model object",
            ),
            PortMetadata(
                name="scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="Scores",
                description="PCA Scores (n_samples × n_components)",
            ),
            PortMetadata(
                name="loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="Loadings",
                description="PCA Loadings (n_features × n_components)",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for PCR regression."""
        params = self._resolve_params()
        n_components = params.get("n_components", 3)
        scale = params.get("scale", True)

        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y")

        lines: list[str] = []
        lines.append(f"{indent}# --- PCR ({self.node_id}) ---")

        # Extract X
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")

        # Extract y
        if y_expr:
            lines.append(f"{indent}_y_raw = {y_expr}")
            lines.append(
                f"{indent}_y = np.array(_y_raw.data if hasattr(_y_raw, 'data') else _y_raw, dtype=np.float64).ravel()"
            )
        else:
            lines.append(f"{indent}_y = np.array(")
            lines.append(f"{indent}    _X_input.target if hasattr(_X_input, 'target') and _X_input.target is not None")
            lines.append(f"{indent}    else _X_input.meta.get('target'),")
            lines.append(f"{indent}    dtype=np.float64,")
            lines.append(f"{indent}).ravel()")

        # Build PCR pipeline
        scale_str = "True" if scale else "False"
        lines.append(f"{indent}from sklearn.decomposition import PCA as _PCA")
        lines.append(f"{indent}from sklearn.linear_model import LinearRegression as _LR")
        lines.append(f"{indent}from sklearn.pipeline import Pipeline as _Pipeline")
        lines.append(f"{indent}from sklearn.preprocessing import StandardScaler as _Scaler")
        lines.append(f"{indent}from sklearn.metrics import r2_score as _r2_score, mean_squared_error as _mse")
        lines.append(f"{indent}_pcr = _Pipeline([")
        lines.append(f"{indent}    ('scaler', _Scaler(with_mean={scale_str}, with_std={scale_str})),")
        lines.append(f"{indent}    ('pca', _PCA(n_components={n_components})),")
        lines.append(f"{indent}    ('regressor', _LR()),")
        lines.append(f"{indent}])")
        lines.append(f"{indent}_pcr.fit(_X_data, _y)")
        lines.append(f"{indent}_y_pred = _pcr.predict(_X_data)")
        lines.append(f"{indent}_r2 = _r2_score(_y, _y_pred)")
        lines.append(f"{indent}_rmse = float(np.sqrt(_mse(_y, _y_pred)))")
        lines.append(
            f"{indent}_scores = _pcr.named_steps['pca'].transform(_pcr.named_steps['scaler'].transform(_X_data))"
        )
        lines.append(f"{indent}_loadings = _pcr.named_steps['pca'].components_")
        lines.append(f'{indent}print(f"  PCR ({n_components} components): R²={{_r2:.4f}}, RMSE={{_rmse:.4f}}")')

        # Store result
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'model': _pcr,")
        lines.append(f"{indent}    'scores': _scores,")
        lines.append(f"{indent}    'loadings': _loadings,")
        lines.append(f"{indent}    'y_pred': _y_pred,")
        lines.append(f"{indent}    'r2': _r2,")
        lines.append(f"{indent}    'rmse': _rmse,")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute PCR regression.

        Args:
            X: Dataset containing spectral data (predictors)
            y: Target values (concentrations)

        Returns:
            PCR model with regression results
        """
        from sklearn.decomposition import PCA as SkPCA
        from sklearn.linear_model import LinearRegression
        from sklearn.metrics import mean_squared_error, r2_score
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (spectra)",
            dataset_error_message="X must be an dataset object",
            allow_array=True,
        )
        # Resolve target names BEFORE bind_y strips dataset metadata
        _resolved_target_names = resolve_target_names(y, X_ds)

        y_value = bind_y(
            y,
            X=X_ds,
            required=True,
            infer_from_X=True,
            dataset_as_data=True,
            missing_message=(
                "No target values found. Either:\n"
                "  1. Use a data source with embedded targets (e.g., Corn M5, sklearn)\n"
                "  2. Connect target values to the 'y' input port\n"
                "  3. Use 'Attach Target' node to add targets to your dataset"
            ),
        )

        X_data = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = to_numpy_1d(y_value, name="y", expected_length=X_data.shape[0], dtype=np.float64)

        n_components = self.parameters.get("n_components", 3)
        scale = self.parameters.get("scale", True)

        max_components = min(X_data.shape[0] - 1, X_data.shape[1])
        if n_components > max_components:
            raise ValueError(
                f"n_components must be <= min(n_samples - 1, n_features). Got {n_components} with max {max_components}."
            )

        logger.debug("[PCR Node] Executing with:")
        logger.debug("  - n_components: %s", n_components)
        logger.debug("  - scale: %s", scale)
        logger.debug("  - X shape: %s", X_data.shape)
        logger.debug("  - y shape: %s", y_array.shape)

        scaler = StandardScaler(with_mean=scale, with_std=scale)
        pca = SkPCA(n_components=n_components)
        regressor = LinearRegression()
        model = Pipeline(
            [
                ("scaler", scaler),
                ("pca", pca),
                ("regressor", regressor),
            ]
        )
        model.fit(X_data, y_array)

        y_pred = model.predict(X_data)
        r2 = r2_score(y_array, y_pred)
        rmse = float(np.sqrt(mean_squared_error(y_array, y_pred)))

        X_scores = model.named_steps["pca"].transform(model.named_steps["scaler"].transform(X_data))

        # Extract label_categories for categorical coloring
        label_categories = None
        _y_coord = X_ds.sample_axis
        if _y_coord is not None:
            try:
                if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, "tolist") else list(_y_coord.labels)
                    label_categories = sorted(set(str(l) for l in raw))
                elif hasattr(_y_coord, "data") and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, "tolist") else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # Get input coordinates for NDDataset creation
        _x_coord = X_ds.feature_axis

        # Build PC labels with explained variance ratio
        evr = pca.explained_variance_ratio_
        pc_labels = [f"PC{i+1} ({evr[i]*100:.1f}%)" for i in range(n_components)]

        # =====================================================================
        # Create proper NDDataset objects for scores and loadings with coordinate coupling
        # =====================================================================

        # Scores: shape (n_samples, n_components)
        scores_dataset = _create_spectral_dataset(
            data=X_scores,
            x_coord=_make_safe_coord(pc_labels, title="Principal Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="score",
            title="PCR Scores",
        )

        # Loadings: shape (n_components, n_features)
        loadings_dataset = _create_spectral_dataset(
            data=pca.components_,
            x_coord=_x_coord,
            y_coord=_make_safe_coord(pc_labels, title="Principal Component"),
            units="loading",
            title="PCR Loadings",
        )

        # Add processing history to NDDataset outputs
        copy_processing_history(X_ds, scores_dataset)
        copy_processing_history(X_ds, loadings_dataset)
        add_processing_step(
            scores_dataset,
            "model.pcr.scores",
            {"n_components": n_components},
            node_id=self.node_id,
        )
        add_processing_step(
            loadings_dataset,
            "model.pcr.loadings",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        target_names = _resolved_target_names

        # Store only scientific metadata that coordinates can't carry
        scores_dataset.meta.update(
            {
                "n_components": n_components,
                "explained_variance_ratio": evr.tolist(),
                "label_categories": label_categories,
                "r2": float(r2),
                "rmse": rmse,
                "coef": regressor.coef_.tolist(),
                "intercept": float(regressor.intercept_),
                "y_pred": [[v] for v in y_pred.tolist()],
                "y_true": [[v] for v in y_array.tolist()],
                "target_names": target_names,
                "r2_per_target": [float(r2)],
                "rmse_per_target": [rmse],
            }
        )
        attach_evaluation(
            scores_dataset,
            EvaluationResult(
                evaluation_id=str(uuid.uuid4()),
                model_type="PCR",
                n_components=n_components,
                r2=float(r2),
                rmse=rmse,
            ),
        )

        logger.debug("[PCR Node] Scores shape: %s, Loadings shape: %s", scores_dataset.shape, loadings_dataset.shape)

        return NodeResult(
            outputs={
                "default": scores_dataset,  # NDDataset: scores + sample labels (y) + PC coords (x)
                "scores": scores_dataset,  # Alias of default for the declared scores port
                "loadings": loadings_dataset,  # NDDataset: loadings + wavenumbers (x) + PC coords (y)
                "model": model,  # Model port for downstream use
            },
            diagnostics={
                "r2": float(r2),
                "rmse": rmse,
            },
        )


def _svr_post_fit(model, X_data, y_array, X_ds, params, node_id):
    """Extra outputs for SVR: support vectors, obs/pred data, metadata."""
    # Extract the raw SVR estimator from Pipeline or bare model
    svr = model.named_steps["estimator"] if hasattr(model, "named_steps") else model

    y_pred = model.predict(X_data)

    # Extract sample labels from input data for categorical coloring
    sample_labels = None
    label_categories = None
    n_observations = X_data.shape[0]

    sample_coord = X_ds.sample_axis

    if sample_coord is not None:
        if hasattr(sample_coord, "labels") and sample_coord.labels is not None:
            try:
                labels = sample_coord.labels
                raw = labels.tolist() if hasattr(labels, "tolist") else list(labels)
                sample_labels = [str(l) for l in raw]
                label_categories = sorted(set(sample_labels))
            except Exception:
                sample_labels = None
                label_categories = None

        if sample_labels is None and hasattr(sample_coord, "data") and sample_coord.data is not None:
            try:
                y_data = sample_coord.data
                raw = y_data.tolist() if hasattr(y_data, "tolist") else list(y_data)
                sample_labels = [str(l) for l in raw]
                unique_values = sorted(set(sample_labels))
                if len(unique_values) < 20 and not _is_sequential_numeric(raw):
                    label_categories = unique_values
            except Exception:
                sample_labels = None
                label_categories = None

    if sample_labels is None:
        sample_labels = [f"Sample {i+1}" for i in range(n_observations)]

    # Get target names from X_ds.target_context
    target_names = None
    tc = X_ds.target_context
    if tc is not None and tc.target_names:
        target_names = tc.target_names

    r2 = float(model.score(X_data, y_array)) if y_array is not None else None
    rmse = float(np.sqrt(np.mean((y_array - y_pred) ** 2))) if y_array is not None else None

    return {
        "support_vectors": svr.support_vectors_.tolist(),
        "data": [[float(yt), float(yh)] for yt, yh in zip(y_array, y_pred)],
        "metadata": {
            "type": "SVR",
            "output_type": "regression",
            "n_observations": n_observations,
            "n_features": X_data.shape[1],
            "kernel": params.get("kernel", "rbf"),
            "C": params.get("C", 1.0),
            "epsilon": params.get("epsilon", 0.1),
            "gamma": params.get("gamma", "scale"),
            "r2": r2,
            "rmse": rmse,
            "sample_labels": sample_labels,
            "label_categories": label_categories,
            "y_true": [[v] for v in y_array.tolist()],
            "y_pred": [[v] for v in y_pred.tolist()],
            "target_names": target_names,
            "r2_per_target": [r2],
            "rmse_per_target": [rmse],
        },
    }


@register_node
class SVRNode(EstimatorSpecNode):
    """
    Support Vector Regression (SVR) node.

    Performs SVR with optional scaling for calibration models.
    """

    metadata = NodeMetadata(
        node_type="model.svr",
        category="regression",
        label="SVR",
        description="Support Vector Regression for calibration",
        parameters=[
            NodeParameter(
                name="kernel",
                label="Kernel",
                param_type="select",
                default="rbf",
                options=["rbf", "linear", "poly", "sigmoid"],
                description="Kernel type for SVR",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="C",
                label="C",
                param_type="number",
                default=1.0,
                min_value=0.01,
                max_value=1000.0,
                step=0.1,
                description="Regularization parameter",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="epsilon",
                label="Epsilon",
                param_type="number",
                default=0.1,
                min_value=0.0,
                max_value=1.0,
                step=0.01,
                description="Epsilon-tube width",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="gamma",
                label="Gamma",
                param_type="select",
                default="scale",
                options=["scale", "auto"],
                description="Kernel coefficient for RBF/poly/sigmoid",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="degree",
                label="Polynomial Degree",
                param_type="number",
                default=3,
                min_value=1,
                max_value=6,
                step=1,
                description="Degree for polynomial kernel",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="coef0",
                label="Coef0",
                param_type="number",
                default=0.0,
                min_value=-1.0,
                max_value=1.0,
                step=0.1,
                description="Independent term for poly/sigmoid kernels",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="scale",
                label="Scale Data",
                param_type="boolean",
                default=True,
                description="Apply mean centering and scaling",
                required=False,
                category="basic",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Spectra (X)",
                description="Spectral data matrix (n_samples × n_wavenumbers)",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Targets (y)",
                description="Target values — optional if dataset has embedded target",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                required=True,
                label="SVR Model",
                description="Trained SVR model object",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Predictions",
                description="Predicted values (y_pred)",
            ),
            PortMetadata(
                name="residuals",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Residuals",
                description="Regression residuals (y_true - y_pred)",
            ),
        ],
    )

    spec = EstimatorSpec(
        estimator_class=SVR,
        scale=True,
        scale_param="scale",
        post_fit_fn=_svr_post_fit,
        estimator_import="from sklearn.svm import SVR",
    )


def _lr_post_fit(model, X_data, y_array, X_ds, params, node_id):
    fit_intercept = params.get("fit_intercept", True)
    return {
        "coef": model.coef_.tolist(),
        "intercept": model.intercept_ if fit_intercept else 0,
        "score": model.score(X_data, y_array),
    }


@register_node
class LinearRegressionNode(EstimatorSpecNode):
    """
    Simple Linear Regression node.

    Performs linear regression for calibration curves.
    """

    metadata = NodeMetadata(
        node_type="model.linear_regression",
        category="regression",
        label="Linear Regression",
        description="Simple linear regression for calibration",
        parameters=[
            NodeParameter(
                name="fit_intercept",
                label="Fit Intercept",
                param_type="boolean",
                default=True,
                description="Calculate intercept (if False, force through origin)",
                required=False,
            ),
        ],
        input_types=["array", "array"],
        output_type="dict",
        # Named input ports for multi-input node
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Features (X)",
                description="Feature matrix (predictors)",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Targets (y)",
                description="Target values — optional if dataset has embedded target",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/RegressionModel/1.0",
                required=True,
                label="Linear Model",
                description="Trained Linear Regression model",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Predictions",
                description="Predicted values (y_pred)",
            ),
            PortMetadata(
                name="residuals",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Residuals",
                description="Regression residuals (y_true - y_pred)",
            ),
        ],
    )

    spec = EstimatorSpec(
        estimator_class=LinearRegression,
        post_fit_fn=_lr_post_fit,
        estimator_import="from sklearn.linear_model import LinearRegression",
    )
