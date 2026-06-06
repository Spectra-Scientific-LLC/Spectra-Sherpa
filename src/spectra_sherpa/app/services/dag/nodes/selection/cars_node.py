"""CARS — Competitive Adaptive Reweighted Sampling.

Registered as ``selection.cars``.

Iterative variable selection that uses exponentially decreasing function
to progressively remove variables with small PLS regression coefficients.

Reference: Li et al., Analytica Chimica Acta 648 (2009) 77-84.
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


def _cars_run(
    X: np.ndarray,
    y: np.ndarray,
    n_components: int,
    cv_folds: int,
    n_iterations: int,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """Run CARS algorithm.

    Returns:
        (best_mask, importance_scores, rmsecv_trace)
    """
    n_samples, n_features = X.shape
    rng = np.random.RandomState(seed)

    # Exponential decay schedule: fraction of variables to retain at each step
    # Starts at 1.0 (all), decays to ~2/n_features
    ratio = np.exp(np.linspace(np.log(1.0), np.log(max(2, n_components + 1) / n_features), n_iterations))

    # Track which variables survive each round
    surviving = np.ones(n_features, dtype=bool)
    surviving_history: list[np.ndarray] = []
    rmsecv_trace: list[float] = []
    importance = np.zeros(n_features, dtype=np.float64)
    cv = KFold(n_splits=min(cv_folds, n_samples), shuffle=True, random_state=seed)
    cv_splits = list(cv.split(X))

    for iteration in range(n_iterations):
        active_idx = np.where(surviving)[0]
        n_active = len(active_idx)
        if n_active < max(2, n_components + 1):
            break

        X_sub = X[:, active_idx]
        n_comp = min(n_components, n_active - 1, n_samples - 1)

        # Fit PLS on full data to get coefficients
        try:
            pls = PLSRegression(n_components=n_comp, scale=False)
            pls.fit(X_sub, y)
            coef = np.abs(pls.coef_.flatten())
        except Exception:
            break

        # Cross-validate on fixed folds so RMSECV values are comparable across
        # the exponentially shrinking variable subsets.
        cv_errors = []
        for train_ix, val_ix in cv_splits:
            try:
                pls_cv = PLSRegression(n_components=n_comp, scale=False)
                pls_cv.fit(X_sub[train_ix], y[train_ix])
                pred = pls_cv.predict(X_sub[val_ix]).flatten()
                cv_errors.append(np.mean((y[val_ix].flatten() - pred) ** 2))
            except Exception:
                cv_errors.append(np.inf)

        rmsecv = float(np.sqrt(np.mean(cv_errors)))
        rmsecv_trace.append(rmsecv)

        # Accumulate importance
        importance[active_idx] += coef / max(coef.max(), 1e-12)

        # Exponentially Decreasing Function (EDF): first keep the highest
        # absolute-coefficient variables, then apply Adaptive Reweighted
        # Sampling (ARS) within that ranked subset.
        n_keep = max(int(np.round(n_features * ratio[iteration])), max(2, n_components + 1))
        n_keep = min(n_keep, n_active)
        ranked_local = np.argsort(coef)[::-1]
        edf_local = ranked_local[:n_keep]

        edf_coef = coef[edf_local]
        weights = edf_coef / edf_coef.sum() if edf_coef.sum() > 0 else np.ones(len(edf_local)) / len(edf_local)
        try:
            sampled = rng.choice(len(edf_local), size=n_keep, replace=True, p=weights)
            keep_local = np.unique(edf_local[sampled])
            if keep_local.size < max(2, n_components + 1):
                fill = [idx for idx in edf_local if idx not in set(keep_local)]
                needed = max(2, n_components + 1) - keep_local.size
                keep_local = np.unique(np.concatenate([keep_local, np.asarray(fill[:needed], dtype=int)]))
        except ValueError:
            keep_local = edf_local

        new_surviving = np.zeros(n_features, dtype=bool)
        new_surviving[active_idx[keep_local]] = True
        surviving = new_surviving
        surviving_history.append(surviving.copy())

    # Find iteration with minimum RMSECV
    if not rmsecv_trace:
        return np.ones(n_features, dtype=bool), importance, []

    best_iter = int(np.argmin(rmsecv_trace))
    best_mask = surviving_history[best_iter] if best_iter < len(surviving_history) else surviving

    return best_mask, importance, rmsecv_trace


@register_node
class CARSNode(Node):
    """Competitive Adaptive Reweighted Sampling (CARS).

    Iteratively removes variables with small PLS coefficients using
    exponentially decaying sampling.  Selects the variable subset that
    minimises RMSECV across all iterations.
    """

    metadata = NodeMetadata(
        node_type="selection.cars",
        category="selection",
        label="CARS",
        description="Competitive adaptive reweighted sampling for variable selection",
        parameters=[
            NodeParameter(
                name="n_iterations",
                label="Iterations",
                param_type="number",
                default=50,
                min_value=10,
                step=5,
                description="Number of sampling iterations",
            ),
            NodeParameter(
                name="n_components",
                label="PLS Components",
                param_type="number",
                default=5,
                min_value=1,
                step=1,
                description="Number of PLS latent variables",
            ),
            NodeParameter(
                name="cv_folds",
                label="CV Folds",
                param_type="number",
                default=5,
                min_value=2,
                step=1,
                description="Cross-validation folds",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description="Spectral dataset or multivariate feature table",
                accepted_data_roles=["X_spectra", "X_features"],
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
                label="Importance Scores",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["n_selected", "best_rmsecv", "n_iterations_run"],
    )

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        params = self._resolve_params()
        n_iterations = int(params.get("n_iterations", 50))
        n_components = int(params.get("n_components", 5))
        cv_folds = int(params.get("cv_folds", 5))

        X_ds = bind_X(X, missing_message="CARS requires X", allow_array=True)
        y_val = bind_y(y, X=X_ds, required=True, infer_from_X=True, dataset_as_data=False)
        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = to_numpy_y(y_val, name="y", expected_samples=X_array.shape[0])
        if y_array.ndim > 1:
            y_array = y_array[:, 0]

        n_features = X_array.shape[1]

        mask, scores, rmsecv_trace = _cars_run(
            X_array,
            y_array,
            n_components,
            cv_folds,
            n_iterations,
        )

        n_selected = int(np.sum(mask))
        if n_selected == 0:
            raise ValueError("CARS eliminated all variables — try fewer iterations or more components")

        X_selected = build_dataset_like(X_array[:, mask], X_ds)
        fa = getattr(X_ds, "feature_axis", None)
        if fa is not None and fa.values is not None:
            fa.apply_mask(mask, method="cars", scores=scores)
            reduced_fa = type(fa)(
                values=np.asarray(fa.values)[mask],
                units=fa.units,
                title=fa.title,
                include_mask=np.ones(n_selected, dtype=bool),
                selection_method="cars",
                selection_scores=scores[mask],
            )
            X_selected.feature_axis = reduced_fa

        # Preserve the original feature mask so training nodes can emit
        # selection-aware model artifacts for deployment.
        X_selected.meta["feature_mask"] = mask.tolist()

        add_processing_step(
            X_selected,
            "selection.cars",
            {
                "n_iterations": n_iterations,
                "n_components": n_components,
                "n_selected": n_selected,
            },
            self.node_id,
        )

        best_rmsecv = float(min(rmsecv_trace)) if rmsecv_trace else float("inf")

        logger.info(f"CARS: {n_selected}/{n_features} variables, best RMSECV={best_rmsecv:.4f}")

        return NodeResult(
            outputs={"default": X_selected, "X_selected": X_selected, "mask": mask, "scores": scores},
            diagnostics={
                "n_selected": n_selected,
                "n_total": n_features,
                "best_rmsecv": best_rmsecv,
                "n_iterations_run": len(rmsecv_trace),
                "rmsecv_trace": rmsecv_trace,
            },
        )
