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
    from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode

    node = PCANode(
        node_id="sdk.model.pca",
        parameters={
            # PCANode stores this GUI parameter as text; preserve that node contract.
            "n_components": str(n_components),
            "standardized": bool(standardized),
            "scaled": bool(scaled),
        },
    )
    try:
        result = _run_node_execute(node.execute(input_data=ds))
    except ImportError as exc:
        raise ImportError(
            "ss.explore.pca requires spectra-sherpa[scp]; install with: pip install 'spectra-sherpa[scp]'"
        ) from exc
    outputs = dict(result.outputs)
    explained = np.asarray(outputs.get("explained_variance", []), dtype=np.float64)
    return PCAResult(
        model=outputs.get("model"),
        scores=outputs.get("scores", outputs.get("default")),
        loadings=outputs.get("loadings"),
        explained_variance=explained,
        diagnostics=dict(result.diagnostics or {}),
        outputs=outputs,
    )


def _run_node_execute(coro):
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


def _shape_of(value: Any) -> list[int]:
    shape = getattr(value, "shape", None)
    if shape is not None:
        return list(shape)
    return list(np.asarray(value).shape)


__all__ = ["PCAResult", "pca"]
