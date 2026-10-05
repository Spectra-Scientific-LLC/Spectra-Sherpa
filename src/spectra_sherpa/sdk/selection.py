"""Variable-selection journeys backed by canonical DAG operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class IPLSResult:
    """Scientist-facing projection of the canonical iPLS node result."""

    selected: Any
    mask: np.ndarray
    scores: np.ndarray
    diagnostics: dict[str, Any]
    workflow_digest: str
    dataset_content_digests: dict[str, str]

    def summary(self) -> dict[str, Any]:
        """Return the compact scientific decision record for this fit."""

        return {
            "method": "iPLS",
            "best_interval": self.diagnostics["best_interval"],
            "best_components": self.diagnostics["best_components"],
            "best_rmsecv": self.diagnostics["best_rmsecv"],
            "global_rmsecv": self.diagnostics["global_rmsecv"],
            "beats_global_rmsecv": self.diagnostics["beats_global_rmsecv"],
            "n_selected": int(self.mask.sum()),
            "n_total": int(self.mask.size),
            "workflow_digest": self.workflow_digest,
        }


def ipls(
    X: Any,
    y: Any,
    *,
    n_intervals: int = 20,
    max_components: int = 5,
    cv_folds: int = 5,
    cv_order: str = "sorted_target",
    random_seed: int = 42,
) -> IPLSResult:
    """Select one contiguous interval through canonical ``selection.ipls``.

    The result describes calibration-set selection, not an unbiased estimate
    of predictive performance. Use a fold-local or nested validation graph for
    the latter claim.
    """

    from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa

    from .deployment import DEPLOYMENT_INPUT_SCHEMA
    from .runtime import execute_workflow
    from .workflow import workflow_spec

    dataset = coerce_to_sherpa(X, input_name="X", allow_array=True).copy()
    target = np.asarray(y)
    if target.ndim == 1:
        target = target.reshape(-1, 1)
    if target.ndim != 2 or target.shape[1] != 1:
        raise ValueError("ss.selection.ipls requires one target value per sample")
    if target.shape[0] != dataset.shape[0]:
        raise ValueError("ss.selection.ipls requires one target value per sample")
    dataset.target = target

    workflow = workflow_spec(
        nodes=[
            {
                "node_id": "sdk.source",
                "node_type": "deploy.input",
                "parameters": {"stream_name": "ipls-calibration", "schema_version": DEPLOYMENT_INPUT_SCHEMA},
            },
            {
                "node_id": "sdk.operation",
                "node_type": "selection.ipls",
                "parameters": {
                    "n_intervals": int(n_intervals),
                    "max_components": int(max_components),
                    "cv_folds": int(cv_folds),
                    "cv_order": cv_order,
                    "random_seed": int(random_seed),
                },
            },
        ],
        edges=[
            {
                "from_node_id": "sdk.source",
                "to_node_id": "sdk.operation",
                "from_output": "default",
                "to_input": "X",
            },
            {
                "from_node_id": "sdk.source",
                "to_node_id": "sdk.operation",
                "from_output": "target",
                "to_input": "y",
            },
        ],
    )
    execution = execute_workflow(workflow, deployment_inputs={"ipls-calibration": dataset})
    outputs = dict(execution.results["sdk.operation"])
    return IPLSResult(
        selected=outputs["X_selected"],
        mask=np.asarray(outputs["mask"], dtype=bool),
        scores=np.asarray(outputs["scores"], dtype=np.float64),
        diagnostics=dict(execution.diagnostics["sdk.operation"]),
        workflow_digest=execution.workflow.workflow_digest,
        dataset_content_digests=dict(execution.dataset_content_digests),
    )


__all__ = ["IPLSResult", "ipls"]
