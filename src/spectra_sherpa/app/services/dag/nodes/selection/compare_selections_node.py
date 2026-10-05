"""Deterministic agreement record for existing feature-selection masks.

Registered as ``selection.compare``.

This operation does not rank selection algorithms and does not estimate
predictive performance. It compares two to four already-computed boolean
feature masks with the Jaccard coefficient and retains features meeting a
declared, inclusive fraction-of-methods vote rule.

Reference:

* Jaccard, Bulletin de la Societe Vaudoise des Sciences Naturelles 37
  (1901) 547-579, doi:10.5169/seals-266450.
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    TargetAccess,
    WorkerCapability,
)

from ...io_contracts import bind_X, build_dataset_like, to_numpy_2d
from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)

_REPORT_SCHEMA = "spectrasherpa.selection.compare.report/1"
_MASK_PORTS = ("mask_1", "mask_2", "mask_3", "mask_4")


def _canonical_compare_parameters(parameters: Mapping[str, Any]) -> dict[str, float]:
    """Return the exact closed parameter representation."""

    if set(parameters) - {"consensus_threshold"}:
        raise ValueError("selection.compare accepts only consensus_threshold")
    value = parameters.get("consensus_threshold", 0.5)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("consensus_threshold must be numeric")
    threshold = float(value)
    if not math.isfinite(threshold) or not 0.0 < threshold <= 1.0:
        raise ValueError("consensus_threshold must be greater than 0 and at most 1")
    return {"consensus_threshold": threshold}


def _mask_digest(mask: np.ndarray) -> str:
    """Digest the feature count and exact boolean mask bytes."""

    payload = np.asarray(mask, dtype=np.uint8)
    return hashlib.sha256(len(payload).to_bytes(8, "big") + payload.tobytes(order="C")).hexdigest()


def _bind_mask(value: Any, *, name: str, features: int) -> np.ndarray:
    """Admit one exact one-dimensional boolean feature mask."""

    if not isinstance(value, (list, tuple, np.ndarray)):
        raise ValueError(f"{name} must be a one-dimensional boolean mask")
    array = np.asarray(value)
    if array.dtype.kind != "b" or array.ndim != 1:
        raise ValueError(f"{name} must be a one-dimensional boolean mask")
    if array.shape != (features,):
        raise ValueError(f"{name} has {array.shape[0]} elements but X has {features} features")
    return np.array(array, dtype=bool, copy=True)


def _jaccard(a: np.ndarray, b: np.ndarray) -> float:
    """Return the Jaccard coefficient for two admitted boolean masks."""

    intersection = int(np.count_nonzero(a & b))
    union = int(np.count_nonzero(a | b))
    # Two empty selections agree on no selected feature; reporting zero avoids
    # turning mutual absence into scientific agreement.
    return 0.0 if union == 0 else float(intersection / union)


def _compare_dispatch(masks: Sequence[np.ndarray], *, consensus_threshold: float) -> dict[str, Any]:
    """Compute the exact Jaccard matrix and inclusive consensus vote."""

    consensus_threshold = _canonical_compare_parameters({"consensus_threshold": consensus_threshold})[
        "consensus_threshold"
    ]
    if not 2 <= len(masks) <= 4:
        raise ValueError("selection.compare requires between two and four masks")
    features = masks[0].shape[0]
    if any(mask.dtype.kind != "b" or mask.shape != (features,) for mask in masks):
        raise ValueError("selection.compare requires equal-length one-dimensional boolean masks")

    vote_matrix = np.stack(masks, axis=0)
    vote_counts = np.count_nonzero(vote_matrix, axis=0)
    required_votes = int(math.ceil(consensus_threshold * len(masks)))
    consensus = vote_counts >= required_votes
    union = np.any(vote_matrix, axis=0)
    intersection = np.all(vote_matrix, axis=0)

    jaccard = np.empty((len(masks), len(masks)), dtype=np.float64)
    for left in range(len(masks)):
        for right in range(len(masks)):
            jaccard[left, right] = _jaccard(masks[left], masks[right])
    pairwise = jaccard[np.triu_indices(len(masks), k=1)]
    return {
        "vote_counts": vote_counts,
        "agreement_fraction": vote_counts.astype(np.float64) / len(masks),
        "required_votes": required_votes,
        "consensus_mask": consensus,
        "union_mask": union,
        "intersection_mask": intersection,
        "jaccard_matrix": jaccard,
        "mean_pairwise_jaccard": float(np.mean(pairwise)),
    }


def _reduced_feature_axis(dataset: Any, mask: np.ndarray, scores: np.ndarray) -> Any:
    """Copy and subset a structured feature axis without mutating the input."""

    axis = getattr(dataset, "feature_axis", None)
    if axis is None:
        return None
    values = None
    if axis.values is not None:
        source_values = np.asarray(axis.values)
        if source_values.ndim != 1 or source_values.shape != mask.shape:
            raise ValueError("selection.compare feature-axis values must match X")
        values = source_values[mask]
    labels = None
    if axis.labels is not None:
        if not isinstance(axis.labels, list) or len(axis.labels) != len(mask):
            raise ValueError("selection.compare feature-axis labels must match X")
        labels = [label for label, retain in zip(axis.labels, mask) if retain]
    return type(axis)(
        values=values,
        labels=labels,
        units=axis.units,
        title=axis.title,
        include_mask=np.ones(int(np.count_nonzero(mask)), dtype=bool),
        selection_method="inclusive_consensus_vote",
        selection_scores=scores[mask],
    )


def _compare_selections_execute(
    X: Any,
    mask_1: Any,
    mask_2: Any,
    mask_3: Any = None,
    mask_4: Any = None,
    *,
    node_id: str,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute the one shared live/export comparison operation."""

    canonical = _canonical_compare_parameters(parameters)
    dataset = bind_X(X, missing_message="Compare selections requires X", allow_array=True)
    matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
    if not np.isfinite(matrix).all():
        raise ValueError("selection.compare requires finite X")

    supplied = (mask_1, mask_2, mask_3, mask_4)
    if any(value is None for value in supplied[:2]):
        raise ValueError("selection.compare requires mask_1 and mask_2")
    masks: list[np.ndarray] = []
    labels: list[str] = []
    for name, value in zip(_MASK_PORTS, supplied):
        if value is not None:
            masks.append(_bind_mask(value, name=name, features=matrix.shape[1]))
            labels.append(name)

    decision = _compare_dispatch(masks, consensus_threshold=canonical["consensus_threshold"])
    consensus = decision["consensus_mask"]
    if not np.any(consensus):
        raise ValueError(
            "selection.compare consensus retained no variables; lower the declared threshold "
            "or inspect disagreement among the input masks"
        )

    selected = build_dataset_like(matrix[:, consensus], dataset)
    selected.feature_axis = _reduced_feature_axis(dataset, consensus, decision["agreement_fraction"])
    selected.meta["feature_mask"] = consensus.tolist()

    method_stats = []
    input_masks = []
    for label, mask in zip(labels, masks):
        digest = _mask_digest(mask)
        input_masks.append({"label": label, "mask": mask.tolist(), "mask_sha256": digest})
        method_stats.append(
            {
                "label": label,
                "mask_sha256": digest,
                "selected_count": int(np.count_nonzero(mask)),
                "selected_fraction": float(np.mean(mask)),
                "jaccard_with_consensus": _jaccard(mask, consensus),
            }
        )
    report = {
        "schema_version": _REPORT_SCHEMA,
        "decision_rule": "selected_votes_greater_than_or_equal_to_ceiling_of_threshold_times_methods",
        "consensus_threshold": canonical["consensus_threshold"],
        "method_count": len(masks),
        "required_votes": decision["required_votes"],
        "feature_count": matrix.shape[1],
        "input_masks": input_masks,
        "method_stats": method_stats,
        "vote_counts": decision["vote_counts"].tolist(),
        "agreement_fraction": decision["agreement_fraction"].tolist(),
        "jaccard_matrix": decision["jaccard_matrix"].tolist(),
        "mean_pairwise_jaccard": decision["mean_pairwise_jaccard"],
        "consensus_mask": consensus.tolist(),
        "consensus_mask_sha256": _mask_digest(consensus),
        "consensus_count": int(np.count_nonzero(consensus)),
        "union_mask": decision["union_mask"].tolist(),
        "union_count": int(np.count_nonzero(decision["union_mask"])),
        "intersection_mask": decision["intersection_mask"].tolist(),
        "intersection_count": int(np.count_nonzero(decision["intersection_mask"])),
        "scope": "selector_agreement_record_not_predictive_performance_evidence",
    }
    add_processing_step(
        selected,
        "selection.compare",
        canonical,
        node_id,
        input_shape=matrix.shape,
        impact={
            "schema_version": _REPORT_SCHEMA,
            "method_count": len(masks),
            "required_votes": decision["required_votes"],
            "consensus_count": report["consensus_count"],
            "consensus_mask_sha256": report["consensus_mask_sha256"],
        },
    )
    diagnostics = {
        "n_methods": len(masks),
        "n_consensus": report["consensus_count"],
        "n_total": matrix.shape[1],
        "required_votes": decision["required_votes"],
        "mean_jaccard": decision["mean_pairwise_jaccard"],
        "scope": report["scope"],
    }
    return {
        "default": selected,
        "X_consensus": selected,
        "consensus_mask": np.array(consensus, copy=True),
        "report": report,
    }, diagnostics


@register_node
class CompareSelectionsNode(Node):
    """Compare two to four boolean feature selections without ranking them."""

    metadata = NodeMetadata(
        node_type="selection.compare",
        category="selection",
        label="Compare Feature Selections",
        description=(
            "Record pairwise Jaccard overlap and retain features meeting an inclusive, declared "
            "fraction-of-methods vote; this is agreement evidence, not predictive evidence"
        ),
        parameters=[
            NodeParameter(
                name="consensus_threshold",
                label="Inclusive Vote Fraction",
                param_type="number",
                default=0.5,
                # NodeParameter bounds are inclusive.  Admit zero through the
                # generic parameter layer, then reject it in the canonical
                # validator so every execution path enforces the scientific
                # contract's exact open lower bound: 0 < fraction <= 1.
                min_value=0.0,
                max_value=1.0,
                max_value_reason="A vote fraction cannot exceed all admitted methods.",
                step=0.05,
                description=(
                    "Retain a feature when selected by at least ceil(fraction x method count) methods; "
                    "0.5 means at least half, not strictly more than half"
                ),
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description="Original finite spectral dataset or feature table",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="mask_1",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Selection Mask 1",
                description="Exact boolean feature mask from the first selector",
            ),
            PortMetadata(
                name="mask_2",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Selection Mask 2",
                description="Exact boolean feature mask from the second selector",
            ),
            PortMetadata(
                name="mask_3",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Selection Mask 3 (optional)",
            ),
            PortMetadata(
                name="mask_4",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Selection Mask 4 (optional)",
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
                label="Closed Agreement Report",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="dict",
        diagnostics=["n_methods", "n_consensus", "n_total", "required_votes", "mean_jaccard", "scope"],
        policy=NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="none",
            required_worker_capabilities=[WorkerCapability.READ_DATASET.value],
        ),
    )

    def generate_python(
        self,
        inputs: Mapping[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        masks = [inputs.get(name, "None") for name in _MASK_PORTS]
        parameters = self._resolve_params()
        return [
            f"{indent}# --- Canonical feature-selection comparison ({self.node_id}) ---",
            (
                f"{indent}from spectra_sherpa.app.services.dag.nodes.selection.compare_selections_node "
                "import _compare_selections_execute"
            ),
            f"{indent}_compare_outputs, _compare_diagnostics = _compare_selections_execute(",
            f"{indent}    {X_expression}, {', '.join(masks)},",
            f"{indent}    node_id={self.node_id!r}, parameters={parameters!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _compare_outputs",
        ]

    async def execute(
        self,
        X: Any = None,
        mask_1: Any = None,
        mask_2: Any = None,
        mask_3: Any = None,
        mask_4: Any = None,
        **kwargs: Any,
    ) -> NodeResult:
        del kwargs
        outputs, diagnostics = _compare_selections_execute(
            X,
            mask_1,
            mask_2,
            mask_3,
            mask_4,
            node_id=self.node_id,
            parameters=self._resolve_params(),
        )
        logger.info(
            "Compare selections: %s methods, %s/%s consensus, mean Jaccard=%.3f",
            diagnostics["n_methods"],
            diagnostics["n_consensus"],
            diagnostics["n_total"],
            diagnostics["mean_jaccard"],
        )
        return NodeResult(outputs=outputs, diagnostics=diagnostics)


bind_stable_execution_contract(
    CompareSelectionsNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.selection.compare",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="filters_features",
    axis_effect="changes_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 15, "cpu_seconds": 15, "memory_bytes": 268_435_456},
    license_id="Apache-2.0",
    help_reference="docs/nodes/selection-validation.md",
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "Jaccard, Bulletin de la Societe Vaudoise des Sciences Naturelles 37 (1901) 547-579, doi:10.5169/seals-266450",
    ),
    deterministic=True,
    seed_parameter=None,
    target_access=TargetAccess.NONE,
    group_access="none",
)


__all__ = [
    "CompareSelectionsNode",
    "_canonical_compare_parameters",
    "_compare_dispatch",
    "_compare_selections_execute",
    "_jaccard",
]
