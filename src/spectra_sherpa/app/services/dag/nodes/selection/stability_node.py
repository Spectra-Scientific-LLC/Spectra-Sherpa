"""Stability Selection meta-node.

Registered as ``selection.stability``.

Runs a base variable selector (VIP, coef_abs, or selectivity_ratio) on
many bootstrap resamples and retains only variables selected in at least
``threshold`` fraction of resamples.  This guards against overfitting
and produces robust, reproducible feature subsets.

Reference: Meinshausen & Bühlmann, JRSS-B 72 (2010) 417-473.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.cross_decomposition import PLSRegression

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ...io_contracts import bind_X, bind_y, build_dataset_like, to_numpy_2d, to_numpy_y
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)


def _stability_run(
    X: np.ndarray,
    y: np.ndarray,
    n_components: int,
    n_bootstrap: int,
    subsample_fraction: float,
    base_method: str,
    base_threshold: float,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Run stability selection.

    Returns:
        (selection_frequencies, importance_scores)
        selection_frequencies[j] = fraction of bootstrap resamples where
        variable j was selected by the base method.
    """
    n_samples, n_features = X.shape
    rng = np.random.RandomState(seed)
    selection_counts = np.zeros(n_features, dtype=np.float64)
    importance_accum = np.zeros(n_features, dtype=np.float64)
    n_valid = 0
    n_sub = max(2, int(n_samples * subsample_fraction))

    for _ in range(n_bootstrap):
        idx = rng.choice(n_samples, size=n_sub, replace=True)
        X_sub = X[idx]
        y_sub = y[idx]

        n_comp = min(n_components, n_sub - 1, n_features - 1)
        if n_comp < 1:
            continue

        try:
            pls = PLSRegression(n_components=n_comp, scale=False)
            pls.fit(X_sub, y_sub)
        except Exception:
            continue

        coef = np.abs(pls.coef_.flatten()[:n_features])

        if base_method == "vip":
            # VIP from sklearn PLS internals
            try:
                from ._vip import calculate_vip

                scores = calculate_vip(
                    pls.x_scores_,
                    pls.x_weights_.T,
                    pls.y_loadings_,
                    n_features,
                )
            except Exception:
                scores = coef
        elif base_method == "selectivity_ratio":
            # SR = explained variance / residual variance per variable
            t = pls.x_scores_
            p = pls.x_loadings_
            X_hat = t @ p.T
            X_res = X_sub - X_hat
            var_explained = np.var(X_hat, axis=0)
            var_residual = np.var(X_res, axis=0) + 1e-12
            scores = var_explained / var_residual
        else:
            # coef_abs
            scores = coef

        selected = scores >= base_threshold
        selection_counts += selected.astype(float)
        importance_accum += scores
        n_valid += 1

    if n_valid == 0:
        return np.zeros(n_features), np.zeros(n_features)

    frequencies = selection_counts / n_valid
    avg_importance = importance_accum / n_valid

    return frequencies, avg_importance


@register_node
class StabilitySelectionNode(Node):
    """Stability Selection — bootstrap-robust variable selection.

    Repeatedly fits a PLS model on random subsamples and tracks how
    often each variable passes the base selection criterion.  Only
    variables selected in at least ``threshold`` fraction of resamples
    are retained, yielding a stable, reproducible feature set.
    """

    metadata = NodeMetadata(
        node_type="selection.stability",
        category="selection",
        label="Stability Selection",
        description="Bootstrap-robust variable selection via repeated subsampling",
        parameters=[
            NodeParameter(
                name="base_method",
                label="Base Selector",
                param_type="select",
                options=[
                    {"label": "VIP", "value": "vip"},
                    {"label": "|Coefficient|", "value": "coef_abs"},
                    {"label": "Selectivity Ratio", "value": "selectivity_ratio"},
                ],
                default="vip",
                description="Variable scoring method applied in each bootstrap",
            ),
            NodeParameter(
                name="base_threshold",
                label="Base Threshold",
                param_type="number",
                default=1.0,
                min_value=0.01,
                max_value=10.0,
                step=0.1,
                description="Threshold for the base method (e.g. VIP >= 1.0)",
            ),
            NodeParameter(
                name="stability_threshold",
                label="Stability Threshold",
                param_type="number",
                default=0.6,
                min_value=0.1,
                max_value=1.0,
                step=0.05,
                description="Fraction of resamples a variable must be selected in to survive",
            ),
            NodeParameter(
                name="n_bootstrap",
                label="Bootstrap Resamples",
                param_type="number",
                default=100,
                min_value=20,
                max_value=500,
                step=10,
                description="Number of bootstrap iterations",
            ),
            NodeParameter(
                name="n_components",
                label="PLS Components",
                param_type="number",
                default=5,
                min_value=1,
                max_value=20,
                step=1,
            ),
            NodeParameter(
                name="subsample_fraction",
                label="Subsample Fraction",
                param_type="number",
                default=0.5,
                min_value=0.2,
                max_value=0.9,
                step=0.05,
                description="Fraction of samples used in each bootstrap",
                category="advanced",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Spectral Data",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Target Values",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_selected",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Selected Data",
            ),
            PortMetadata(
                name="mask",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Feature Mask",
            ),
            PortMetadata(
                name="scores",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Selection Frequencies",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["n_selected", "stability_threshold", "base_method", "n_bootstrap"],
    )

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        params = self._resolve_params()
        base_method = params.get("base_method", "vip")
        base_threshold = float(params.get("base_threshold", 1.0))
        stability_threshold = float(params.get("stability_threshold", 0.6))
        n_bootstrap = int(params.get("n_bootstrap", 100))
        n_components = int(params.get("n_components", 5))
        subsample_fraction = float(params.get("subsample_fraction", 0.5))

        X_ds = bind_X(X, missing_message="Stability selection requires X", allow_array=True)
        y_val = bind_y(y, X=X_ds, required=True, infer_from_X=True, dataset_as_data=False)
        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = to_numpy_y(y_val, name="y", expected_samples=X_array.shape[0])
        if y_array.ndim > 1:
            y_array = y_array[:, 0]

        n_features = X_array.shape[1]

        frequencies, importance = _stability_run(
            X_array,
            y_array,
            n_components,
            n_bootstrap,
            subsample_fraction,
            base_method,
            base_threshold,
        )

        mask = frequencies >= stability_threshold
        scores = frequencies  # selection frequency as the score

        n_selected = int(np.sum(mask))
        if n_selected == 0:
            raise ValueError(
                f"Stability selection eliminated all variables "
                f"(stability_threshold={stability_threshold}, base={base_method}>={base_threshold}). "
                "Try lowering stability_threshold or base_threshold."
            )

        X_selected = build_dataset_like(X_array[:, mask], X_ds)
        fa = getattr(X_ds, "feature_axis", None)
        if fa is not None and fa.values is not None:
            fa.apply_mask(mask, method="stability", scores=scores)
            reduced_fa = type(fa)(
                values=np.asarray(fa.values)[mask],
                units=fa.units,
                title=fa.title,
                include_mask=np.ones(n_selected, dtype=bool),
                selection_method="stability",
                selection_scores=scores[mask],
            )
            X_selected.feature_axis = reduced_fa

        # Preserve the original feature mask so downstream models keep the
        # deployment-time mapping back to the original spectrum.
        X_selected.meta["feature_mask"] = mask.tolist()

        add_processing_step(
            X_selected,
            "selection.stability",
            {
                "base_method": base_method,
                "base_threshold": base_threshold,
                "stability_threshold": stability_threshold,
                "n_bootstrap": n_bootstrap,
                "n_selected": n_selected,
            },
            self.node_id,
        )

        logger.info(
            f"Stability selection: {n_selected}/{n_features} variables survive "
            f"(freq >= {stability_threshold}, base={base_method})"
        )

        return NodeResult(
            outputs={"X_selected": X_selected, "mask": mask, "scores": scores},
            diagnostics={
                "n_selected": n_selected,
                "n_total": n_features,
                "stability_threshold": stability_threshold,
                "base_method": base_method,
                "n_bootstrap": n_bootstrap,
                "mean_frequency": float(np.mean(frequencies)),
            },
        )
