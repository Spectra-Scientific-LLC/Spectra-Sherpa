"""
PLS regression training and prediction nodes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import (
    EvaluationResult,
    SherpaDataset,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history

from ...io_contracts import (
    attach_evaluation,
    bind_X,
    bind_y,
    resolve_target_names,
    to_numpy_y,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    PortMetadata,
    register_node,
)
from .core_utils import (
    create_spectral_dataset as _create_spectral_dataset,
)
from .core_utils import (
    ensure_orientation as _ensure_orientation,
)
from .core_utils import (
    is_sequential_numeric as _is_sequential_numeric,
)
from .core_utils import (
    make_safe_coord as _make_safe_coord,
)

logger = logging.getLogger(__name__)

from spectra_sherpa.app.lib.adapters.scp_extractors import PLSExtract
from spectra_sherpa.app.lib.scp_compat import scp, to_nddataset


@register_node
class PLSNode(Node):
    """
    Partial Least Squares Regression node.

    Performs PLS regression using SpectroChemPy.
    """

    metadata = NodeMetadata(
        node_type="model.pls",
        category="regression",
        label="PLS",
        description="Partial Least Squares regression for calibration",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=1,
                max_value=20,
                step=1,
                description="Number of PLS components",
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
        # Named input ports for multi-input node
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
                label="Concentrations (y)",
                description="Target values — optional if dataset has embedded target",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/RegressionModel/1.0",
                required=True,
                label="PLS Model",
                description="Trained PLS regression model",
            ),
            PortMetadata(
                name="X_scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="X Scores",
                description="Scores for X block (samples × components) with sample labels",
            ),
            PortMetadata(
                name="Y_scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="Y Scores",
                description="Scores for Y block (samples × components) with sample labels",
            ),
            PortMetadata(
                name="X_loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="X Loadings",
                description="Loadings for X block (components × features) with wavenumber axis",
            ),
            PortMetadata(
                name="Y_loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="Y Loadings",
                description="Loadings for Y block (targets × components)",
            ),
        ],
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for PLS regression.

        Emits code that fits a PLS model, computes in-sample predictions,
        and reports R²/RMSE per target.  The result is stored as a dict
        to support multi-port access by downstream nodes.
        """
        if not use_scp:
            return [
                f"{indent}# --- PLS Regression ({self.node_id}) ---",
                f"{indent}# PLS requires SpectroChemPy (pip install spectra-sherpa[scp])",
                f"{indent}raise ImportError('PLS requires spectrochempy')",
            ]

        params = self._resolve_params()
        n_components = params.get("n_components", 3)
        scale = params.get("scale", True)

        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y")

        lines: list[str] = []
        lines.append(f"{indent}# --- PLS Regression ({self.node_id}) ---")

        # Extract X data
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")

        # Extract y data
        if y_expr:
            lines.append(f"{indent}_y_input = {y_expr}")
            lines.append(f"{indent}_y_data = np.array(")
            lines.append(f"{indent}    _y_input.data if hasattr(_y_input, 'data') else _y_input,")
            lines.append(f"{indent}    dtype=np.float64,")
            lines.append(f"{indent})")
        else:
            lines.append(f"{indent}# No explicit y port — extract embedded target from dataset")
            lines.append(f"{indent}_y_data = np.array(")
            lines.append(f"{indent}    _X_input.target if hasattr(_X_input, 'target') and _X_input.target is not None")
            lines.append(f"{indent}    else _X_input.meta.get('target'),")
            lines.append(f"{indent}    dtype=np.float64,")
            lines.append(f"{indent})")

        lines.append(f"{indent}if _y_data.ndim == 1:")
        lines.append(f"{indent}    _y_data = _y_data.reshape(-1, 1)")

        # Fit PLS
        lines.append(f"{indent}_X_ndd = scp.NDDataset(_X_data)")
        lines.append(f"{indent}_Y_ndd = scp.NDDataset(_y_data)")
        scale_str = "True" if scale else "False"
        lines.append(f"{indent}_pls = scp.PLSRegression(n_components={n_components}, scale={scale_str})")
        lines.append(f"{indent}_pls.fit(_X_ndd, _Y_ndd)")

        # Predict and compute metrics
        lines.append(f"{indent}_y_pred = np.asarray(")
        lines.append(f"{indent}    _pls.predict(_X_ndd).data, dtype=np.float64,")
        lines.append(f"{indent})")
        lines.append(f"{indent}# SCP may squeeze single-target predictions to 1D; reshape to match _y_data")
        lines.append(f"{indent}if _y_pred.ndim == 1:")
        lines.append(f"{indent}    _y_pred = _y_pred.reshape(-1, 1)")
        lines.append(f"{indent}_ss_res = np.sum((_y_data - _y_pred) ** 2, axis=0)")
        lines.append(f"{indent}_ss_tot = np.sum((_y_data - np.mean(_y_data, axis=0)) ** 2, axis=0)")
        lines.append(f"{indent}_r2 = np.where(_ss_tot > 0, 1.0 - _ss_res / _ss_tot, np.nan)")
        lines.append(f"{indent}_rmse = np.sqrt(np.mean((_y_data - _y_pred) ** 2, axis=0))")
        lines.append(
            f'{indent}print(f"  PLS ({{_y_data.shape[1]}} target(s), {n_components} LVs, scale={scale_str}):")'
        )
        lines.append(f"{indent}for _i, (_r, _m) in enumerate(zip(_r2.flat, _rmse.flat)):")
        lines.append(f'{indent}    print(f"    Target {{_i}}: R²={{_r:.6f}}  RMSE={{_m:.6f}}")')

        # Extract model components for multi-port output
        lines.append(f"{indent}# Extract scores and loadings")
        lines.append(f"{indent}def _safe_extract(obj, *attrs):")
        lines.append(f"{indent}    for a in attrs:")
        lines.append(f"{indent}        try:")
        lines.append(f"{indent}            v = getattr(obj, a)")
        lines.append(f"{indent}            return np.asarray(v.data if hasattr(v, 'data') else v, dtype=np.float64)")
        lines.append(f"{indent}        except Exception:")
        lines.append(f"{indent}            pass")
        lines.append(f"{indent}    return None")
        lines.append(f"{indent}_x_scores = _safe_extract(_pls, 'x_scores', '_x_scores', 'x_scores_')")
        lines.append(f"{indent}if _x_scores is None:")
        lines.append(f"{indent}    _x_scores = np.asarray(_pls.transform(_X_ndd).data, dtype=np.float64)")
        lines.append(f"{indent}_x_loadings = _safe_extract(_pls, 'x_loadings', '_x_loadings', 'x_loadings_')")
        lines.append(f"{indent}_y_scores = _safe_extract(_pls, 'y_scores', '_y_scores', 'y_scores_')")
        lines.append(f"{indent}_y_loadings = _safe_extract(_pls, 'y_loadings', '_y_loadings', 'y_loadings_')")

        # Store multi-port output as dict
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'default': _x_scores,")
        lines.append(f"{indent}    'X_scores': _x_scores,")
        lines.append(f"{indent}    'X_loadings': _x_loadings,")
        lines.append(f"{indent}    'Y_scores': _y_scores,")
        lines.append(f"{indent}    'Y_loadings': _y_loadings,")
        lines.append(f"{indent}    'model': _pls,")
        lines.append(f"{indent}    'y_pred': _y_pred,")
        lines.append(f"{indent}    'y_true': _y_data,")
        lines.append(f"{indent}    'r2': _r2,")
        lines.append(f"{indent}    'rmse': _rmse,")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute PLS regression.

        Args:
            X: Dataset containing spectral data (predictors)
            y: Target values (concentrations)

        Returns:
            PLS model with regression results
        """
        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (spectra)",
            dataset_error_message="X must be an dataset or array-like object",
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

        y_array = to_numpy_y(y_value, name="y", expected_samples=X_ds.shape[0], dtype=np.float64)
        # PLS expects 2D y: (n_samples, n_targets)
        y_2d = y_array.reshape(-1, 1) if y_array.ndim == 1 else y_array
        n_targets = y_2d.shape[1]

        # Drop rows where the target contains NaN (e.g. diesel_nir partial properties)
        nan_mask = np.isnan(y_2d).any(axis=1)
        if nan_mask.any():
            valid = ~nan_mask
            n_dropped = int(nan_mask.sum())
            logger.warning(
                "[PLS Node] Dropped %d/%d samples with NaN target values. "
                "If your dataset has multiple property columns, consider selecting a specific "
                "y_column to avoid partial data loss.",
                n_dropped,
                y_2d.shape[0],
            )
            y_2d = y_2d[valid]
            # Rebuild X_ds with valid rows so sample_axis stays consistent with scores shape
            _prev_meta = X_ds.meta.copy() if X_ds.meta else {}
            X_ds = SherpaDataset(X=X_ds.X[valid], feature_axis=X_ds.get_feature_axis(), extra=_prev_meta)

        X_ndd = to_nddataset(X_ds)
        y_dataset = scp.NDDataset(y_2d)

        n_components = self.parameters.get("n_components", 3)
        scale = self.parameters.get("scale", True)

        # Validate n_components
        max_components = min(X_ds.shape[0] - 1, X_ds.shape[1])
        if n_components > max_components:
            raise ValueError(
                f"n_components must be <= min(n_samples - 1, n_features). Got {n_components} with max {max_components}."
            )

        logger.debug("[PLS Node] Executing with:")
        logger.debug("  - n_components: %s", n_components)
        logger.debug("  - scale: %s", scale)
        logger.debug("  - X shape: %s", X_ds.shape)
        logger.debug("  - y shape: %s (n_targets=%s)", y_dataset.shape, n_targets)

        # Perform PLS using SpectroChemPy
        pls = scp.PLSRegression(n_components=n_components, scale=scale)
        pls.fit(X_ndd, y_dataset)

        # Extract results using typed extractor — all defensive unwrapping
        # and version-specific fallback logic lives in PLSExtract.from_scp()
        extracted = PLSExtract.from_scp(pls, X_ndd, Y_ndd=y_dataset)

        X_scores_data = extracted.x_scores
        Y_scores_data = extracted.y_scores
        X_loadings_data = extracted.x_loadings
        Y_loadings_data = extracted.y_loadings
        coef_data = extracted.coef

        # In-sample calibration quality metrics for Phase 2 quality wiring.
        pls_r2 = None
        pls_rmse = None
        regression_meta: dict | None = None
        try:
            y_pred_raw = pls.predict(X_ndd)
            y_pred = np.asarray(
                y_pred_raw.data if hasattr(y_pred_raw, "data") else y_pred_raw,
                dtype=np.float64,
            )
            if y_pred.ndim > 1 and y_2d.shape[1] == 1:
                y_pred = y_pred.ravel()
            if y_2d.shape[1] == 1:
                # Single-target: flatten for metrics
                y_flat = y_2d.ravel()
                y_pred_flat = y_pred.ravel() if y_pred.ndim > 1 else y_pred
                residual = y_flat - y_pred_flat
                ss_res = float(np.sum(residual**2))
                ss_tot = float(np.sum((y_flat - np.mean(y_flat)) ** 2))
                pls_r2 = (1.0 - (ss_res / ss_tot)) if ss_tot > 0 else None
                pls_rmse = float(np.sqrt(np.mean(residual**2)))
                # Store 2D for frontend consistency
                regression_meta = {
                    "y_true": y_2d.tolist(),
                    "y_pred": y_pred_flat.reshape(-1, 1).tolist(),
                    "r2_per_target": [pls_r2],
                    "rmse_per_target": [pls_rmse],
                }
            else:
                # Multi-target: per-target R2, then average
                if y_pred.ndim == 1:
                    y_pred = y_pred.reshape(-1, n_targets)
                residual = y_2d - y_pred
                ss_res = np.sum(residual**2, axis=0)
                ss_tot = np.sum((y_2d - np.mean(y_2d, axis=0)) ** 2, axis=0)
                r2_per_target = np.where(ss_tot > 0, 1.0 - ss_res / ss_tot, np.nan)
                pls_r2 = float(np.nanmean(r2_per_target))
                pls_rmse = float(np.sqrt(np.mean(residual**2)))
                rmse_per_target = [float(np.sqrt(np.mean(residual[:, j] ** 2))) for j in range(n_targets)]
                regression_meta = {
                    "y_true": y_2d.tolist(),
                    "y_pred": y_pred.tolist(),
                    "r2_per_target": [float(v) for v in r2_per_target],
                    "rmse_per_target": rmse_per_target,
                }
            if _resolved_target_names:
                regression_meta["target_names"] = _resolved_target_names
        except Exception:
            logger.debug("[PLS Node] Could not compute calibration R2/RMSE from predictions", exc_info=True)

        logger.debug("[PLS Node] PLS model fitted successfully")
        logger.debug("  - X_scores shape: %s", X_scores_data.shape if X_scores_data is not None else "N/A")
        logger.debug("  - Coefficients shape: %s", coef_data.shape if coef_data is not None else "N/A")

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

        # Get input x_coord for loadings dataset
        _x_coord = X_ds.feature_axis

        # Build LV labels with physical quantity context for scientific traceability
        x_data_quantity = None
        if hasattr(X_ds, "units") and X_ds.units:
            x_data_quantity = str(X_ds.units) if str(X_ds.units) != "dimensionless" else None
        if x_data_quantity is None and hasattr(X_ds, "title") and X_ds.title:
            x_data_quantity = str(X_ds.title)

        # =====================================================================
        # Create SherpaDataset objects for scores and loadings with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        # Build LV labels with physical quantity context for scientific traceability
        # Example: "LV1 [Absorbance]" instead of just "LV1"
        quantity_suffix = f" [{x_data_quantity}]" if x_data_quantity else ""
        lv_labels = [f"LV{i+1}{quantity_suffix}" for i in range(n_components)]

        # X_scores: shape (n_samples, n_components)
        X_scores_dataset = None
        if X_scores_data is not None:
            X_scores_dataset = _create_spectral_dataset(
                data=X_scores_data,
                x_coord=_make_safe_coord(lv_labels, title="Latent Variable"),
                y_coord=_y_coord,  # Preserve sample labels from input
                units="score",
                title="PLS X Scores",
            )

        # Y_scores: shape (n_samples, n_components)
        Y_scores_dataset = None
        if Y_scores_data is not None:
            Y_scores_dataset = _create_spectral_dataset(
                data=Y_scores_data,
                x_coord=_make_safe_coord(lv_labels, title="Latent Variable"),
                y_coord=_y_coord,  # Preserve sample labels from input
                units="score",
                title="PLS Y Scores",
            )

        # X_loadings: canonical (n_components, n_features) with y=LV labels, x=wavenumbers
        X_loadings_dataset = None
        if X_loadings_data is not None:
            xl = _ensure_orientation(
                X_loadings_data,
                expected_rows=n_components,
                expected_cols=X_ds.shape[1],
                name="X_loadings",
            )
            X_loadings_dataset = _create_spectral_dataset(
                data=xl,
                x_coord=_x_coord,
                y_coord=_make_safe_coord(lv_labels, title="Latent Variable"),
                units="loading",
                title="PLS X Loadings",
            )

        # Y_loadings: canonical (n_targets, n_components) with y=target names, x=LV labels
        Y_loadings_dataset = None
        if Y_loadings_data is not None:
            yl = _ensure_orientation(
                Y_loadings_data,
                expected_rows=n_targets,
                expected_cols=n_components,
                name="Y_loadings",
            )
            if _resolved_target_names and len(_resolved_target_names) == yl.shape[0]:
                y_target_coord = _make_safe_coord(_resolved_target_names, title="Target")
            else:
                y_target_coord = _make_safe_coord([f"Target {i+1}" for i in range(yl.shape[0])], title="Target")
            Y_loadings_dataset = _create_spectral_dataset(
                data=yl,
                x_coord=_make_safe_coord(lv_labels, title="Latent Variable"),
                y_coord=y_target_coord,
                units="loading",
                title="PLS Y Loadings",
            )

        # Add processing history to SherpaDataset outputs
        if X_scores_dataset is not None:
            copy_processing_history(X_ds, X_scores_dataset)
            add_processing_step(
                X_scores_dataset,
                "model.pls.x_scores",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        if Y_scores_dataset is not None:
            copy_processing_history(X_ds, Y_scores_dataset)
            add_processing_step(
                Y_scores_dataset,
                "model.pls.y_scores",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        if X_loadings_dataset is not None:
            copy_processing_history(X_ds, X_loadings_dataset)
            add_processing_step(
                X_loadings_dataset,
                "model.pls.x_loadings",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        if Y_loadings_dataset is not None:
            copy_processing_history(X_ds, Y_loadings_dataset)
            add_processing_step(
                Y_loadings_dataset,
                "model.pls.y_loadings",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        # Store scientific metadata in X_scores SherpaDataset meta
        if X_scores_dataset is not None:
            meta_dict = {
                "type": "PLS",
                "n_components": n_components,
                "pc_labels": lv_labels,  # LV labels (no EVR for PLS, so store explicitly)
                "label_categories": label_categories,
                "r2": pls_r2,
                "rmse": pls_rmse,
            }
            if regression_meta is not None:
                meta_dict.update(regression_meta)
            X_scores_dataset.meta.update(meta_dict)
            attach_evaluation(
                X_scores_dataset,
                EvaluationResult(
                    evaluation_id=str(uuid.uuid4()),
                    model_type="PLS",
                    n_components=n_components,
                    r2=pls_r2,
                    rmse=pls_rmse,
                ),
            )

        # Build model artifact for persistence
        from ._artifact_builder import build_model_artifact

        artifact_metrics = {}
        if pls_r2 is not None:
            artifact_metrics["r2"] = pls_r2
        if pls_rmse is not None:
            artifact_metrics["rmse"] = pls_rmse

        return {
            "default": X_scores_dataset,  # SherpaDataset: X scores (n_samples, n_components)
            "X_loadings": X_loadings_dataset,  # SherpaDataset: loadings (n_components, n_features)
            "Y_scores": Y_scores_dataset,  # SherpaDataset: Y scores (n_samples, n_components)
            "Y_loadings": Y_loadings_dataset,  # SherpaDataset: Y loadings (n_targets, n_components)
            "model": pls,  # SCP PLSRegression for Apply PLS Model
            "coef": coef_data,  # ndarray: regression coefficients (n_features, n_targets)
            "_model_artifact": build_model_artifact(
                extracted,
                X_ds,
                node_id=self.node_id,
                metrics=artifact_metrics or None,
            ),
        }


@register_node
class PLSPredictNode(Node):
    """
    Apply trained PLS model to predict new samples.

    Takes a trained PLS model and new data, returns predictions.
    Critical for train/test validation and production inference.
    """

    metadata = NodeMetadata(
        node_type="model.pls_predict",
        category="regression",
        label="Apply PLS Model",
        description="Apply trained PLS model to predict concentrations for new spectra",
        parameters=[],
        input_ports=[
            PortMetadata(
                name="X_new",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="New Spectra",
                description="Spectral data to predict (preprocessed same as training data)",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/RegressionModel/1.0",
                required=True,
                label="PLS Model",
                description="Trained PLS model from PLS training node",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="y_pred",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Predictions",
                description="Predicted values (1D for single response, 2D for multi-response)",
            ),
        ],
        input_types=["NDDataset", "dict"],
        output_type="array",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for PLS prediction."""
        X_expr = inputs.get("X_new", inputs.get("default", "input_data"))
        model_expr = inputs.get("model", "model")

        lines: list[str] = []
        lines.append(f"{indent}# --- PLS Predict ({self.node_id}) ---")

        # Extract X data
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")

        # Get model
        lines.append(f"{indent}_model_input = {model_expr}")
        lines.append(
            f"{indent}_pls_model = _model_input.get('model') if isinstance(_model_input, dict) else _model_input"
        )

        if use_scp:
            lines.append(f"{indent}_X_ndd = scp.NDDataset(_X_data)")
            lines.append(f"{indent}_y_pred_raw = _pls_model.predict(_X_ndd)")
            lines.append(f"{indent}_y_pred = np.asarray(")
            lines.append(f"{indent}    _y_pred_raw.data if hasattr(_y_pred_raw, 'data') else _y_pred_raw,")
            lines.append(f"{indent}    dtype=np.float64,")
            lines.append(f"{indent})")
        else:
            lines.append(f"{indent}_y_pred = _pls_model.predict(_X_data)")
            lines.append(f"{indent}_y_pred = np.asarray(_y_pred, dtype=np.float64)")

        lines.append(f"{indent}if _y_pred.ndim == 2 and _y_pred.shape[1] == 1:")
        lines.append(f"{indent}    _y_pred = _y_pred.ravel()")

        lines.append(f"{indent}results['{self.node_id}'] = {{'y_pred': _y_pred}}")
        lines.append(f'{indent}print(f"  PLS Predict: {{_y_pred.shape[0]}} samples predicted")')

        return lines

    async def execute(self, X_new: Any = None, model: Any = None, **kwargs: Any) -> dict[str, Any]:
        """
        Apply PLS model to new data.

        Args:
            X_new: New spectral data (dataset)
            model: Trained PLS model dict from PLS node

        Returns:
            dict with 'y_pred' key containing predictions (1D or 2D)
        """
        if X_new is None or model is None:
            raise ValueError("Both X_new and model inputs are required")
        X_new_ds = bind_X(
            X_new,
            missing_message="Missing required input: X_new (new spectra)",
            dataset_error_message="X_new must be an dataset object",
            allow_array=True,
        )

        # Extract model from result dict
        if isinstance(model, dict):
            pls_model = model.get("model")
            if pls_model is None:
                raise ValueError("Model dict must contain 'model' key with trained PLS object")
        else:
            pls_model = model

        # Make predictions - SpectroChemPy PLSRegression can accept NDDataset or array
        try:
            X_ndd = to_nddataset(X_new_ds)
            y_pred_raw = pls_model.predict(X_ndd)
            y_pred_array = np.asarray(
                y_pred_raw.data if hasattr(y_pred_raw, "data") else y_pred_raw,
                dtype=np.float64,
            )
            # Squeeze single-target predictions to 1D for backward compat
            if y_pred_array.ndim == 2 and y_pred_array.shape[1] == 1:
                y_pred_array = y_pred_array.ravel()

            logger.debug("[PLS Predict] Generated predictions with shape %s", y_pred_array.shape)

            return {"y_pred": y_pred_array}

        except Exception as e:
            raise RuntimeError(f"PLS prediction failed: {str(e)}") from e
