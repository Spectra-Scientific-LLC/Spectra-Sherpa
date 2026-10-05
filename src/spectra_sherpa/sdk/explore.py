"""Exploratory analysis namespace for the public SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class PCAResult:
    """Lightweight SDK wrapper around GUI-compatible PCA outputs."""

    model: Any
    scores: Any
    loadings: Any
    explained_variance: np.ndarray
    diagnostics: dict[str, Any]
    workflow_digest: str
    dataset_content_digests: dict[str, str]
    artifacts: tuple[dict[str, Any], ...]
    outputs: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.outputs[key]

    def summary(self) -> dict[str, Any]:
        evr = np.asarray(self.explained_variance, dtype=np.float64).ravel()
        return {
            "model_type": "PCA",
            "n_components": int(evr.shape[0]),
            "explained_variance_ratio": evr.tolist(),
            "cumulative_variance": np.cumsum(evr).tolist(),
            "scores_shape": _shape_of(self.scores),
            "loadings_shape": _shape_of(self.loadings),
        }

    def manifest(self) -> dict[str, Any]:
        return {
            "sdk_function": "ss.explore.pca",
            "node_type": "model.pca",
            "workflow_digest": self.workflow_digest,
            "dataset_content_digests": dict(self.dataset_content_digests),
            "summary": self.summary(),
            "diagnostics": self.diagnostics,
            "outputs": sorted(k for k in self.outputs if not k.startswith("_")),
        }


def pca(
    ds: Any,
    *,
    n_components: int | str | float = 2,
    standardized: bool = False,
    scaled: bool = False,
) -> PCAResult:
    """Fit PCA using the same runtime path as the GUI ``model.pca`` node."""
    from .runtime import execute_operation

    execution = execute_operation(
        "model.pca",
        parameters={
            # PCANode stores this GUI parameter as text; preserve that node contract.
            "n_components": str(n_components),
            "standardized": bool(standardized),
            "scaled": bool(scaled),
        },
        inputs={"default": ds},
    )
    outputs = dict(execution.results["sdk.operation"])
    explained = np.asarray(outputs.get("explained_variance", []), dtype=np.float64)
    return PCAResult(
        model=outputs.get("model"),
        scores=outputs.get("scores", outputs.get("default")),
        loadings=outputs.get("loadings"),
        explained_variance=explained,
        diagnostics=dict(execution.diagnostics.get("sdk.operation", {})),
        workflow_digest=execution.workflow.workflow_digest,
        dataset_content_digests=dict(execution.dataset_content_digests),
        artifacts=tuple(dict(artifact) for artifact in execution.artifacts),
        outputs=outputs,
    )


def _shape_of(value: Any) -> list[int]:
    shape = getattr(value, "shape", None)
    if shape is not None:
        return list(shape)
    return list(np.asarray(value).shape)


__all__ = ["PCAResult", "pca"]
