"""Regression namespace for the public SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class PLSResult:
    """Lightweight SDK wrapper around GUI-compatible PLS outputs."""

    model: Any
    X_scores: Any
    X_loadings: Any
    y_pred: np.ndarray | None
    y_true: np.ndarray | None
    diagnostics: dict[str, Any]
    outputs: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.outputs[key]

    def summary(self) -> dict[str, Any]:
        return {
            "model_type": "PLS",
            "n_components": self.diagnostics.get("n_components"),
            "n_samples": self.diagnostics.get("n_samples"),
            "n_features": self.diagnostics.get("n_features"),
            "n_targets": self.diagnostics.get("n_targets"),
            "r2": self.diagnostics.get("r2"),
            "rmse": self.diagnostics.get("rmse"),
            "r2_cv": self.diagnostics.get("r2_cv"),
            "rmsecv": self.diagnostics.get("rmsecv"),
            "target_names": self.diagnostics.get("target_names"),
            "X_scores_shape": _shape_of(self.X_scores),
            "X_loadings_shape": _shape_of(self.X_loadings) if self.X_loadings is not None else None,
        }

    def manifest(self) -> dict[str, Any]:
        return {
            "sdk_function": "ss.regression.pls",
            "node_type": "model.pls",
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
    cv_method: str = "k-fold",
    cv_folds: int = 5,
) -> PLSResult:
    """Fit PLS regression using the same runtime path as the GUI ``model.pls`` node."""
    from spectra_sherpa.app.services.dag.nodes.modeling.pls_nodes import PLSNode

    node = PLSNode(
        node_id="sdk.model.pls",
        parameters={
            # PLSNode expects a numeric component count, unlike PCANode's text field.
            "n_components": int(n_components),
            "scale": bool(scale),
            "cv_method": cv_method,
            "cv_folds": int(cv_folds),
        },
    )
    try:
        result = _run_node_execute(node.execute(X=ds, y=_resolve_y(ds, y)))
    except ImportError as exc:
        raise ImportError(
            "ss.regression.pls requires spectra-sherpa[scp]; install with: pip install 'spectra-sherpa[scp]'"
        ) from exc
    outputs = dict(result.outputs)
    y_pred = outputs.get("y_pred")
    y_true = outputs.get("y_true")
    return PLSResult(
        model=outputs.get("model"),
        X_scores=outputs.get("X_scores", outputs.get("default")),
        X_loadings=outputs.get("X_loadings"),
        y_pred=np.asarray(y_pred, dtype=np.float64) if y_pred is not None else None,
        y_true=np.asarray(y_true, dtype=np.float64) if y_true is not None else None,
        diagnostics=dict(result.diagnostics or {}),
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


__all__ = ["PLSResult", "pls"]
