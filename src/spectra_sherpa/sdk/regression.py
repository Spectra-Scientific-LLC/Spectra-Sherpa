"""Regression namespace for the public SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class PLSResult:
    """SDK projection of the canonical fitted-PLS lifecycle."""

    predictions: np.ndarray
    fitted_state: dict[str, Any]
    vip_scores: np.ndarray
    diagnostics: dict[str, Any]
    workflow_digest: str
    dataset_content_digests: dict[str, str]
    artifacts: tuple[dict[str, Any], ...]
    outputs: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.outputs[key]

    def summary(self) -> dict[str, Any]:
        state = self.fitted_state["state"]
        return {
            "model_type": "PLS",
            "n_components": state["n_components"],
            "n_samples": state["reference_samples"],
            "n_features": state["features"],
            "n_targets": state["targets"],
            "predictions_shape": _shape_of(self.predictions),
            "vip_scores_shape": _shape_of(self.vip_scores),
            "state_content_digest": self.fitted_state["state_content_digest"],
        }

    def manifest(self) -> dict[str, Any]:
        return {
            "sdk_function": "ss.regression.pls",
            "node_type": "model.fitted_pls",
            "workflow_digest": self.workflow_digest,
            "dataset_content_digests": dict(self.dataset_content_digests),
            "summary": self.summary(),
            "diagnostics": self.diagnostics,
            "outputs": sorted(k for k in self.outputs if not k.startswith("_")),
        }


def pls(
    ds: Any,
    *,
    y: Any = None,
    n_components: int = 3,
    scale: bool = False,
) -> PLSResult:
    """Fit PLS through the same typed lifecycle used by the canonical DAG."""
    from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa

    from .runtime import execute_operation

    dataset = coerce_to_sherpa(ds, input_name="dataset", allow_array=True)
    target = _resolve_y(dataset, y)
    if target is not None:
        dataset = dataset.copy()
        dataset.target = np.asarray(target)
    execution = execute_operation(
        "model.fitted_pls",
        parameters={"n_components": int(n_components), "scale": bool(scale)},
        inputs={"default": dataset},
    )
    outputs = dict(execution.results["sdk.operation"])
    return PLSResult(
        predictions=np.asarray(outputs["default"], dtype=np.float64),
        fitted_state=dict(outputs["fitted_state"]),
        vip_scores=np.asarray(outputs["vip_scores"], dtype=np.float64),
        diagnostics=dict(execution.diagnostics.get("sdk.operation", {})),
        workflow_digest=execution.workflow.workflow_digest,
        dataset_content_digests=dict(execution.dataset_content_digests),
        artifacts=tuple(dict(artifact) for artifact in execution.artifacts),
        outputs=outputs,
    )


def _resolve_y(ds: Any, y: Any) -> Any:
    if not isinstance(y, str):
        return y

    target = getattr(ds, "target", None)
    if target is None:
        return y

    target_arr = np.asarray(target)
    target_context = getattr(ds, "target_context", None)
    target_names = list(getattr(target_context, "target_names", None) or [])
    target_name = getattr(target_context, "target_name", None)
    selected_target = getattr(target_context, "selected_target", None)
    if y == target_name or y == selected_target:
        return target
    if y in target_names:
        index = target_names.index(y)
        if target_arr.ndim == 1:
            return target
        if target_arr.ndim == 2:
            return target_arr[:, index]
    return y


def _shape_of(value: Any) -> list[int]:
    shape = getattr(value, "shape", None)
    if shape is not None:
        return list(shape)
    return list(np.asarray(value).shape)


__all__ = ["PLSResult", "pls"]
