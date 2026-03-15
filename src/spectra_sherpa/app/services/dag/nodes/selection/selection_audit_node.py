"""Selection Audit Trail node.

Registered as ``selection.audit``.

Inspects an input dataset's provenance and feature axis to produce a
structured audit report of all variable selection steps applied, including
methods used, number of variables at each stage, scores, and the
surviving feature indices.

This enables reproducible, inspectable chemometric workflows where
every selection decision is documented.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import get_processing_history

from ...io_contracts import bind_X, to_numpy_2d
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)

# Selection node types that we recognise in provenance
_SELECTION_OPS = frozenset(
    {
        "selection.variable_select",
        "selection.ipls",
        "selection.cars",
        "selection.spa",
        "selection.uve",
        "selection.stability",
        "selection.sample_partition",
    }
)


@register_node
class SelectionAuditNode(Node):
    """Selection Audit Trail — inspect and document all selection decisions.

    Reads the provenance chain and feature axis of the input dataset to
    produce a structured report of every selection step:
    - Method name and parameters
    - Number of variables before and after
    - Selection scores (if available)
    - Surviving feature indices/wavelengths

    Outputs a summary dict and the original dataset (pass-through).
    """

    metadata = NodeMetadata(
        node_type="selection.audit",
        category="selection",
        label="Selection Audit",
        description="Inspect and document all variable selection decisions in the pipeline",
        parameters=[
            NodeParameter(
                name="include_scores",
                label="Include Scores",
                param_type="boolean",
                default=True,
                description="Include per-variable scores in the audit report",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Data",
                description="Dataset with selection provenance to audit",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_out",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Pass-through Data",
            ),
            PortMetadata(
                name="audit",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Audit Report",
                description="Structured dict with selection audit trail",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["n_selection_steps", "final_n_features", "methods_applied"],
    )

    async def execute(self, X: Any = None, **kwargs: Any) -> NodeResult:
        params = self._resolve_params()
        include_scores = bool(params.get("include_scores", True))

        X_ds = bind_X(X, missing_message="Selection audit requires X", allow_array=True)
        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)

        # Extract provenance
        history = get_processing_history(X_ds)

        # Filter to selection-related steps
        selection_steps = []
        for step in history:
            op_id = step.get("op_id", "")
            if op_id.startswith("selection.") or op_id in _SELECTION_OPS:
                step_info = {
                    "method": op_id,
                    "parameters": step.get("parameters", {}),
                    "node_id": step.get("node_id"),
                    "input_shape": step.get("input_shape"),
                    "output_shape": step.get("output_shape"),
                    "timestamp": step.get("timestamp"),
                }
                # Extract selection-specific params
                p = step.get("parameters", {})
                if "n_selected" in p:
                    step_info["n_selected"] = p["n_selected"]
                if "noise_threshold" in p:
                    step_info["noise_threshold"] = p["noise_threshold"]
                if "n_components" in p:
                    step_info["n_components"] = p["n_components"]

                selection_steps.append(step_info)

        # Feature axis info
        fa = getattr(X_ds, "feature_axis", None)
        feature_info = {}
        if fa is not None:
            feature_info["n_features"] = len(fa.values) if fa.values is not None else X_array.shape[1]
            feature_info["units"] = fa.units
            feature_info["selection_method"] = fa.selection_method

            if fa.include_mask is not None:
                feature_info["n_included"] = int(np.sum(fa.include_mask))
                feature_info["n_excluded"] = int(np.sum(~fa.include_mask))

            if include_scores and fa.selection_scores is not None:
                scores = np.asarray(fa.selection_scores)
                feature_info["scores_summary"] = {
                    "min": float(np.min(scores)),
                    "max": float(np.max(scores)),
                    "mean": float(np.mean(scores)),
                    "std": float(np.std(scores)),
                }

            if fa.values is not None:
                vals = np.asarray(fa.values)
                feature_info["feature_range"] = [float(vals.min()), float(vals.max())]
        else:
            feature_info["n_features"] = X_array.shape[1]

        # Compile methods applied
        methods_applied = [s["method"] for s in selection_steps]

        audit_report = {
            "selection_steps": selection_steps,
            "n_selection_steps": len(selection_steps),
            "methods_applied": methods_applied,
            "feature_axis": feature_info,
            "final_shape": list(X_array.shape),
            "total_provenance_steps": len(history),
        }

        logger.info(
            f"Selection audit: {len(selection_steps)} selection steps, "
            f"{X_array.shape[1]} final features, methods={methods_applied}"
        )

        return NodeResult(
            outputs={"X_out": X_ds, "audit": audit_report},
            diagnostics={
                "n_selection_steps": len(selection_steps),
                "final_n_features": X_array.shape[1],
                "methods_applied": methods_applied,
            },
        )
