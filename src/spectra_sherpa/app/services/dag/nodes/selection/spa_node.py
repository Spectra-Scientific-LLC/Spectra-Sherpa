"""SPA — Successive Projections Algorithm.

Registered as ``selection.spa``.

Greedy forward selection that minimises collinearity among selected
variables by projecting each candidate onto the orthogonal complement
of already-selected variables.

Reference: Araújo et al., Chemometrics and Intelligent Laboratory Systems 57 (2001) 65-73.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ...io_contracts import bind_X, build_dataset_like, to_numpy_2d
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)


def _spa_projections(X: np.ndarray, n_select: int, start_var: int | None = None) -> np.ndarray:
    """Core SPA: select variables by successive orthogonal projections.

    Args:
        X: Mean-centered data matrix (n_samples, n_features).
        n_select: Number of variables to select.
        start_var: Starting variable index (None = try all, pick best).

    Returns:
        Array of selected variable indices.
    """
    n_samples, n_features = X.shape
    n_select = min(n_select, n_features, n_samples)

    def _run_from(start: int) -> list[int]:
        selected = [start]
        # Work with columns
        cols = X.T.copy()  # (n_features, n_samples)

        for _ in range(n_select - 1):
            # Project all columns onto orthogonal complement of last selected
            ref = cols[selected[-1]]
            norm_sq = float(ref @ ref)
            if norm_sq < 1e-12:
                break
            for j in range(n_features):
                if j not in selected:
                    proj = (cols[j] @ ref / norm_sq) * ref
                    cols[j] = cols[j] - proj

            # Pick variable with largest remaining norm
            norms = np.array([np.linalg.norm(cols[j]) if j not in selected else -1.0 for j in range(n_features)])
            best = int(np.argmax(norms))
            if norms[best] < 1e-12:
                break
            selected.append(best)

        return selected

    if start_var is not None:
        return np.array(_run_from(start_var), dtype=np.intp)

    # Try each variable as seed, pick chain with best condition number
    best_selected = None
    best_cond = np.inf
    # For efficiency, try a subset of starting variables
    n_tries = min(n_features, 50)
    candidates = np.linspace(0, n_features - 1, n_tries, dtype=int)

    for start in candidates:
        sel = _run_from(int(start))
        if len(sel) < n_select:
            continue
        X_sub = X[:, sel]
        try:
            cond = np.linalg.cond(X_sub.T @ X_sub)
        except np.linalg.LinAlgError:
            cond = np.inf
        if cond < best_cond:
            best_cond = cond
            best_selected = sel

    if best_selected is None:
        best_selected = _run_from(0)

    return np.array(best_selected[:n_select], dtype=np.intp)


@register_node
class SPANode(Node):
    """Successive Projections Algorithm (SPA).

    Selects variables that are maximally independent by iterative
    orthogonal projections.  Minimises collinearity in the selected
    variable set — complementary to VIP-based selection.
    """

    metadata = NodeMetadata(
        node_type="selection.spa",
        category="selection",
        label="SPA",
        description="Successive projections for minimum-collinearity variable selection",
        parameters=[
            NodeParameter(
                name="n_select",
                label="Variables to Select",
                param_type="number",
                default=20,
                min_value=2,
                step=1,
                description="Number of variables to select",
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
                required=False,
                label="Target Values (optional)",
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
                label="Selection Order Scores",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["n_selected", "condition_number"],
    )

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        params = self._resolve_params()
        n_select = int(params.get("n_select", 20))

        X_ds = bind_X(X, missing_message="SPA requires X", allow_array=True)
        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)

        n_features = X_array.shape[1]
        n_select = min(n_select, n_features)

        # Mean-center
        X_mc = X_array - X_array.mean(axis=0)

        selected_idx = _spa_projections(X_mc, n_select)
        n_actual = len(selected_idx)

        # Build mask and scores
        mask = np.zeros(n_features, dtype=bool)
        scores = np.zeros(n_features, dtype=np.float64)
        for rank, idx in enumerate(selected_idx):
            mask[idx] = True
            scores[idx] = 1.0 - rank / max(n_actual, 1)  # first selected = highest score

        # Condition number of selected set
        X_sub = X_array[:, selected_idx]
        try:
            cond_number = float(np.linalg.cond(X_sub.T @ X_sub))
        except np.linalg.LinAlgError:
            cond_number = float("inf")

        X_selected = build_dataset_like(X_array[:, mask], X_ds)
        fa = getattr(X_ds, "feature_axis", None)
        if fa is not None and fa.values is not None:
            fa.apply_mask(mask, method="spa", scores=scores)
            reduced_fa = type(fa)(
                values=np.asarray(fa.values)[mask],
                units=fa.units,
                title=fa.title,
                include_mask=np.ones(n_actual, dtype=bool),
                selection_method="spa",
                selection_scores=scores[mask],
            )
            X_selected.feature_axis = reduced_fa

        # Preserve the original feature mask so models trained on SPA outputs
        # remain deployable against full-spectrum inputs.
        X_selected.meta["feature_mask"] = mask.tolist()

        add_processing_step(
            X_selected,
            "selection.spa",
            {
                "n_select": n_select,
                "n_selected": n_actual,
            },
            self.node_id,
        )

        logger.info(f"SPA: {n_actual}/{n_features} variables, cond={cond_number:.1f}")

        return NodeResult(
            outputs={"default": X_selected, "X_selected": X_selected, "mask": mask, "scores": scores},
            diagnostics={"n_selected": n_actual, "n_total": n_features, "condition_number": cond_number},
        )
