"""Interval PLS (iPLS) variable selection node.

Registered as ``selection.ipls``.

Exhaustive search over contiguous spectral intervals to find the
region (or combination of regions) that minimises RMSECV.

Reference: Nørgaard et al., Applied Spectroscopy 54 (2000) 413-419.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import KFold

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ...io_contracts import bind_X, bind_y, build_dataset_like, to_numpy_2d, to_numpy_y
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)


def _rmsecv_interval(
    X: np.ndarray,
    y: np.ndarray,
    idx: np.ndarray,
    n_components: int,
    cv_folds: int,
) -> float:
    """Compute RMSECV for a single variable interval."""
    X_sub = X[:, idx]
    n_comp = min(n_components, X_sub.shape[1], X_sub.shape[0] - 1)
    if n_comp < 1 or X_sub.shape[1] < 1:
        return np.inf

    kf = KFold(n_splits=cv_folds, shuffle=True, random_state=42)
    errors = []
    for train_ix, val_ix in kf.split(X_sub):
        try:
            pls = PLSRegression(n_components=n_comp, scale=False)
            pls.fit(X_sub[train_ix], y[train_ix])
            y_pred = pls.predict(X_sub[val_ix]).flatten()
            errors.append(np.mean((y[val_ix].flatten() - y_pred) ** 2))
        except Exception:
            errors.append(np.inf)

    return float(np.sqrt(np.mean(errors)))


@register_node
class IPLSNode(Node):
    """Interval PLS — find optimal contiguous spectral interval(s).

    Divides the spectrum into equally-spaced intervals and evaluates
    each via cross-validated PLS.  Reports the best single interval
    and optionally the best combination (forward iPLS).
    """

    metadata = NodeMetadata(
        node_type="selection.ipls",
        category="selection",
        label="Interval PLS (iPLS)",
        description="Find optimal spectral interval(s) by exhaustive cross-validated PLS search",
        parameters=[
            NodeParameter(
                name="n_intervals",
                label="Number of Intervals",
                param_type="number",
                default=20,
                min_value=3,
                max_value=200,
                step=1,
                description="Number of equal-width intervals to divide the spectrum into",
            ),
            NodeParameter(
                name="n_components",
                label="PLS Components",
                param_type="number",
                default=5,
                min_value=1,
                max_value=20,
                step=1,
                description="Maximum number of PLS latent variables",
            ),
            NodeParameter(
                name="cv_folds",
                label="CV Folds",
                param_type="number",
                default=5,
                min_value=2,
                max_value=20,
                step=1,
                description="Number of cross-validation folds",
            ),
            NodeParameter(
                name="n_best",
                label="Best Intervals to Combine",
                param_type="number",
                default=1,
                min_value=1,
                max_value=10,
                step=1,
                description="Number of top intervals to combine (1 = single best, >1 = synergy iPLS)",
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
                label="Interval RMSECV Scores",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["n_intervals", "best_interval", "best_rmsecv", "global_rmsecv"],
    )

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        params = self._resolve_params()
        n_intervals = int(params.get("n_intervals", 20))
        n_components = int(params.get("n_components", 5))
        cv_folds = int(params.get("cv_folds", 5))
        n_best = int(params.get("n_best", 1))

        X_ds = bind_X(X, missing_message="iPLS requires X", allow_array=True)
        y_val = bind_y(y, X=X_ds, required=True, infer_from_X=True, dataset_as_data=False)

        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = to_numpy_y(y_val, name="y", expected_samples=X_array.shape[0])
        if y_array.ndim > 1:
            y_array = y_array[:, 0]  # iPLS works on single target

        n_features = X_array.shape[1]

        # Build interval boundaries
        boundaries = np.linspace(0, n_features, n_intervals + 1, dtype=int)
        intervals = [(boundaries[i], boundaries[i + 1]) for i in range(n_intervals)]

        # Evaluate each interval
        rmsecv_per_interval = np.full(n_intervals, np.inf)
        for k, (lo, hi) in enumerate(intervals):
            idx = np.arange(lo, hi)
            if len(idx) < 1:
                continue
            rmsecv_per_interval[k] = _rmsecv_interval(X_array, y_array, idx, n_components, cv_folds)

        # Global RMSECV (full spectrum)
        global_rmsecv = _rmsecv_interval(X_array, y_array, np.arange(n_features), n_components, cv_folds)

        # Select best n_best intervals (forward combination)
        ranked = np.argsort(rmsecv_per_interval)
        selected_intervals = ranked[:n_best]

        # Build combined mask
        mask = np.zeros(n_features, dtype=bool)
        for k in selected_intervals:
            lo, hi = intervals[k]
            mask[lo:hi] = True

        n_selected = int(np.sum(mask))
        if n_selected == 0:
            raise ValueError("iPLS produced empty selection — try fewer intervals or more components")

        # Per-feature scores (lower RMSECV = better, invert for scoring)
        scores = np.zeros(n_features, dtype=np.float64)
        for k, (lo, hi) in enumerate(intervals):
            if rmsecv_per_interval[k] < np.inf:
                scores[lo:hi] = 1.0 / (1.0 + rmsecv_per_interval[k])

        # Build output
        X_selected = build_dataset_like(X_array[:, mask], X_ds)
        fa = getattr(X_ds, "feature_axis", None)
        if fa is not None and fa.values is not None:
            fa_copy = fa.copy()
            fa_copy.apply_mask(mask, method="ipls", scores=scores)
            reduced_fa = type(fa)(
                values=np.asarray(fa.values)[mask],
                units=fa.units,
                title=fa.title,
                include_mask=np.ones(n_selected, dtype=bool),
                selection_method="ipls",
                selection_scores=scores[mask],
            )
            X_selected.feature_axis = reduced_fa

        # Preserve the original feature mask so downstream training nodes can
        # persist deployable artifacts from this reduced dataset.
        X_selected.meta["feature_mask"] = mask.tolist()

        add_processing_step(
            X_selected,
            "selection.ipls",
            {
                "n_intervals": n_intervals,
                "n_components": n_components,
                "n_best": n_best,
                "n_selected": n_selected,
            },
            self.node_id,
        )

        best_k = int(ranked[0])
        diagnostics = {
            "n_intervals": n_intervals,
            "best_interval": best_k,
            "best_interval_range": list(intervals[best_k]),
            "best_rmsecv": float(rmsecv_per_interval[best_k]),
            "global_rmsecv": float(global_rmsecv),
            "n_selected": n_selected,
            "rmsecv_per_interval": rmsecv_per_interval.tolist(),
        }

        logger.info(
            f"iPLS: best interval {best_k} RMSECV={rmsecv_per_interval[best_k]:.4f} "
            f"(global={global_rmsecv:.4f}), {n_selected}/{n_features} selected"
        )

        return NodeResult(
            outputs={"X_selected": X_selected, "mask": mask, "scores": scores},
            diagnostics=diagnostics,
        )
