"""Comparative Selection Dashboard node.

Registered as ``selection.compare``.

Accepts multiple boolean masks (from different selection methods) and
produces agreement metrics, overlap analysis, and a consensus mask.

Use this to compare iPLS vs CARS vs VIP vs SPA etc. and decide which
variable subset to carry forward — or combine them via consensus.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ...io_contracts import bind_X, build_dataset_like, to_numpy_2d
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)


def _jaccard(a: np.ndarray, b: np.ndarray) -> float:
    """Jaccard similarity between two boolean masks."""
    intersection = np.sum(a & b)
    union = np.sum(a | b)
    if union == 0:
        return 0.0
    return float(intersection / union)


@register_node
class CompareSelectionsNode(Node):
    """Compare Variable Selections — agreement analysis and consensus.

    Takes up to 4 boolean selection masks from different methods and
    computes:
    - Pairwise Jaccard similarity (overlap)
    - Per-variable selection frequency (how many methods agree)
    - Consensus mask (variables selected by >= threshold methods)
    - Union and intersection masks

    Outputs a consensus-selected dataset, the consensus mask, and
    a detailed comparison report.
    """

    metadata = NodeMetadata(
        node_type="selection.compare",
        category="selection",
        label="Compare Feature Selections",
        description="Compare multiple variable selection masks and build consensus",
        parameters=[
            NodeParameter(
                name="consensus_threshold",
                label="Consensus Threshold",
                param_type="number",
                default=0.5,
                min_value=0.0,
                step=0.1,
                description="Fraction of methods that must agree for consensus (0.5 = majority vote)",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description="Original spectral dataset or feature table before selection",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="mask_1",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Mask 1",
                description="Boolean mask from first selection method",
            ),
            PortMetadata(
                name="mask_2",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Mask 2",
                description="Boolean mask from second selection method",
            ),
            PortMetadata(
                name="mask_3",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Mask 3 (optional)",
            ),
            PortMetadata(
                name="mask_4",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Mask 4 (optional)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_consensus",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Consensus-Selected Data",
            ),
            PortMetadata(
                name="consensus_mask",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Consensus Mask",
            ),
            PortMetadata(
                name="report",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Comparison Report",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["n_methods", "n_consensus", "mean_jaccard"],
    )

    async def execute(
        self,
        X: Any = None,
        mask_1: Any = None,
        mask_2: Any = None,
        mask_3: Any = None,
        mask_4: Any = None,
        **kwargs: Any,
    ) -> NodeResult:
        params = self._resolve_params()
        consensus_threshold = float(params.get("consensus_threshold", 0.5))

        X_ds = bind_X(X, missing_message="Compare selections requires X", allow_array=True)
        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        n_features = X_array.shape[1]

        # Collect masks
        masks: list[np.ndarray] = []
        labels: list[str] = []
        for i, m in enumerate([mask_1, mask_2, mask_3, mask_4], start=1):
            if m is not None:
                arr = np.asarray(m, dtype=bool).flatten()
                if arr.shape[0] != n_features:
                    raise ValueError(f"mask_{i} has {arr.shape[0]} elements but X has {n_features} features")
                masks.append(arr)
                labels.append(f"mask_{i}")

        if len(masks) < 2:
            raise ValueError("At least 2 masks are required for comparison")

        n_methods = len(masks)

        # Per-variable selection frequency
        vote_matrix = np.stack(masks, axis=0)  # (n_methods, n_features)
        frequency = vote_matrix.sum(axis=0).astype(float) / n_methods

        # Consensus mask
        consensus_mask = frequency >= consensus_threshold
        n_consensus = int(np.sum(consensus_mask))

        # Pairwise Jaccard similarity
        jaccard_matrix = np.zeros((n_methods, n_methods), dtype=np.float64)
        for i in range(n_methods):
            for j in range(n_methods):
                jaccard_matrix[i, j] = _jaccard(masks[i], masks[j])

        mean_jaccard = float(np.mean(jaccard_matrix[np.triu_indices(n_methods, k=1)]))

        # Per-method stats
        method_stats = []
        for i, (m, label) in enumerate(zip(masks, labels)):
            method_stats.append(
                {
                    "label": label,
                    "n_selected": int(np.sum(m)),
                    "fraction_selected": float(np.mean(m)),
                    "overlap_with_consensus": float(_jaccard(m, consensus_mask)) if n_consensus > 0 else 0.0,
                }
            )

        # Union and intersection
        union_mask = np.any(vote_matrix, axis=0)
        intersection_mask = np.all(vote_matrix, axis=0)

        if n_consensus == 0:
            raise ValueError(
                f"Consensus threshold {consensus_threshold} eliminates all variables. "
                "Lower the threshold or check that input masks overlap."
            )

        # Build output
        X_consensus = build_dataset_like(X_array[:, consensus_mask], X_ds)
        fa = getattr(X_ds, "feature_axis", None)
        if fa is not None and fa.values is not None:
            reduced_fa = type(fa)(
                values=np.asarray(fa.values)[consensus_mask],
                units=fa.units,
                title=fa.title,
                include_mask=np.ones(n_consensus, dtype=bool),
                selection_method="consensus",
                selection_scores=frequency[consensus_mask],
            )
            X_consensus.feature_axis = reduced_fa

        # Preserve the original feature mask so consensus-selected datasets can
        # also participate in deployable model training.
        X_consensus.meta["feature_mask"] = consensus_mask.tolist()

        report = {
            "n_methods": n_methods,
            "method_stats": method_stats,
            "jaccard_matrix": jaccard_matrix.tolist(),
            "mean_jaccard": mean_jaccard,
            "consensus_threshold": consensus_threshold,
            "n_consensus": n_consensus,
            "n_union": int(np.sum(union_mask)),
            "n_intersection": int(np.sum(intersection_mask)),
            "n_total_features": n_features,
            "frequency_histogram": {
                "bins": list(range(n_methods + 1)),
                "counts": [int(np.sum(vote_matrix.sum(axis=0) == k)) for k in range(n_methods + 1)],
            },
        }

        logger.info(
            f"Compare selections: {n_methods} methods, {n_consensus}/{n_features} consensus, "
            f"mean Jaccard={mean_jaccard:.3f}"
        )

        return NodeResult(
            outputs={"X_consensus": X_consensus, "consensus_mask": consensus_mask, "report": report},
            diagnostics={
                "n_methods": n_methods,
                "n_consensus": n_consensus,
                "n_total": n_features,
                "mean_jaccard": mean_jaccard,
            },
        )
