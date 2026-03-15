"""UVE — Uninformative Variable Elimination.

Registered as ``selection.uve``.

Adds noise (random) variables to the data and builds PLS models.
Real variables must have regression coefficients that are significantly
more stable than the noise variables across Monte Carlo resamples.

Reference: Centner et al., Analytical Chemistry 68 (1996) 3851-3858.
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


def _uve_mc(
    X: np.ndarray,
    y: np.ndarray,
    n_components: int,
    n_resamples: int,
    test_fraction: float,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Monte Carlo UVE.

    Returns:
        (reliability, stability_scores) where reliability = mean(coef) / std(coef)
        for each variable.  Noise variables provide the cutoff threshold.
    """
    n_samples, n_features = X.shape
    rng = np.random.RandomState(seed)

    # Add noise variables (same scale as X)
    noise = rng.randn(n_samples, n_features) * np.std(X, axis=0, keepdims=True) * 0.01
    X_aug = np.hstack([X, noise])  # (n_samples, 2*n_features)
    n_aug = X_aug.shape[1]

    # Collect coefficients over MC resamples
    coef_matrix = np.zeros((n_resamples, n_aug), dtype=np.float64)
    n_test = max(1, int(n_samples * test_fraction))

    for i in range(n_resamples):
        idx = rng.permutation(n_samples)
        train_idx = idx[n_test:]
        if len(train_idx) < n_components + 1:
            continue

        n_comp = min(n_components, len(train_idx) - 1, n_aug - 1)
        try:
            pls = PLSRegression(n_components=n_comp, scale=False)
            pls.fit(X_aug[train_idx], y[train_idx])
            coef_matrix[i] = pls.coef_.flatten()[:n_aug]
        except Exception:
            continue

    # Reliability: mean / std (stability measure)
    mean_coef = np.mean(coef_matrix, axis=0)
    std_coef = np.std(coef_matrix, axis=0)
    std_coef = np.maximum(std_coef, 1e-12)
    reliability = np.abs(mean_coef / std_coef)

    # Split into real and noise reliabilities
    real_reliability = reliability[:n_features]
    noise_reliability = reliability[n_features:]

    return real_reliability, noise_reliability


@register_node
class UVENode(Node):
    """Uninformative Variable Elimination (MC-UVE).

    Benchmarks each variable's PLS coefficient stability against added
    noise variables over Monte Carlo resamples.  Variables whose
    reliability is no better than noise are eliminated.
    """

    metadata = NodeMetadata(
        node_type="selection.uve",
        category="selection",
        label="UVE (MC-UVE)",
        description="Eliminate uninformative variables by Monte Carlo stability benchmarking",
        parameters=[
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
                name="n_resamples",
                label="MC Resamples",
                param_type="number",
                default=100,
                min_value=20,
                max_value=500,
                step=10,
                description="Number of Monte Carlo resampling iterations",
            ),
            NodeParameter(
                name="test_fraction",
                label="Test Fraction per Resample",
                param_type="number",
                default=0.2,
                min_value=0.05,
                max_value=0.5,
                step=0.05,
                description="Fraction of samples held out in each MC iteration",
                category="advanced",
            ),
            NodeParameter(
                name="cutoff_percentile",
                label="Noise Cutoff Percentile",
                param_type="number",
                default=95.0,
                min_value=50.0,
                max_value=99.9,
                step=0.5,
                description="Percentile of noise reliability used as threshold (higher = more conservative)",
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
                label="Reliability Scores",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["n_selected", "noise_threshold", "n_resamples"],
    )

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        params = self._resolve_params()
        n_components = int(params.get("n_components", 5))
        n_resamples = int(params.get("n_resamples", 100))
        test_fraction = float(params.get("test_fraction", 0.2))
        cutoff_pct = float(params.get("cutoff_percentile", 95.0))

        X_ds = bind_X(X, missing_message="UVE requires X", allow_array=True)
        y_val = bind_y(y, X=X_ds, required=True, infer_from_X=True, dataset_as_data=False)
        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = to_numpy_y(y_val, name="y", expected_samples=X_array.shape[0])
        if y_array.ndim > 1:
            y_array = y_array[:, 0]

        n_features = X_array.shape[1]

        real_reliability, noise_reliability = _uve_mc(
            X_array,
            y_array,
            n_components,
            n_resamples,
            test_fraction,
        )

        # Threshold: percentile of noise reliability
        noise_threshold = float(np.percentile(noise_reliability, cutoff_pct))
        mask = real_reliability > noise_threshold
        scores = real_reliability

        n_selected = int(np.sum(mask))
        if n_selected == 0:
            raise ValueError(
                f"UVE eliminated all variables (threshold={noise_threshold:.3f}). "
                "Try lowering cutoff_percentile or increasing n_resamples."
            )

        X_selected = build_dataset_like(X_array[:, mask], X_ds)
        fa = getattr(X_ds, "feature_axis", None)
        if fa is not None and fa.values is not None:
            fa.apply_mask(mask, method="uve", scores=scores)
            reduced_fa = type(fa)(
                values=np.asarray(fa.values)[mask],
                units=fa.units,
                title=fa.title,
                include_mask=np.ones(n_selected, dtype=bool),
                selection_method="uve",
                selection_scores=scores[mask],
            )
            X_selected.feature_axis = reduced_fa

        # Preserve the original feature mask so artifact persistence can
        # recover the full-spectrum selection contract.
        X_selected.meta["feature_mask"] = mask.tolist()

        add_processing_step(
            X_selected,
            "selection.uve",
            {
                "n_components": n_components,
                "n_resamples": n_resamples,
                "noise_threshold": noise_threshold,
                "n_selected": n_selected,
            },
            self.node_id,
        )

        logger.info(f"UVE: {n_selected}/{n_features} variables survive " f"(noise threshold={noise_threshold:.3f})")

        return NodeResult(
            outputs={"X_selected": X_selected, "mask": mask, "scores": scores},
            diagnostics={
                "n_selected": n_selected,
                "n_total": n_features,
                "noise_threshold": noise_threshold,
                "n_resamples": n_resamples,
            },
        )
