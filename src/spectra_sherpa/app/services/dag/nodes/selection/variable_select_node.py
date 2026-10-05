"""Closed, target-free variable-rule application for canonical DAGs.

Registered as ``selection.variable_select``.  This node does not search or
validate a model.  It applies one declared feature rule to one matrix: an
explicit interval, a detected-peak window, an exact external mask, or a
threshold over one of three established PLS importance measures.

PLS importance semantics follow the mdatools variable-selection reference.
Peak locations use SciPy's documented prominence definition.  Predictive
validity remains the responsibility of leakage-safe validation downstream.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

import numpy as np
from scipy import signal

from spectra_sherpa.app.lib import fitted_state
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
from . import _selectivity_ratio

logger = logging.getLogger(__name__)

_METHODS = {"interval", "peak_window", "apply_mask", "vip", "coef_abs", "selectivity_ratio"}
_REPORT_SCHEMA = "spectrasherpa.selection.variable_select.report/1"
_SCOPE = "target_free_feature_rule_not_predictive_validation"


def _finite_number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        raise ValueError(f"selection.variable_select {name} must be finite and numeric")
    return float(value)


def _canonical_variable_select_parameters(parameters: Mapping[str, Any]) -> dict[str, object]:
    """Close parameters around the selected rule; irrelevant fields fail."""

    method = parameters.get("method", "vip")
    if method not in _METHODS:
        raise ValueError(f"selection.variable_select method must be one of: {', '.join(sorted(_METHODS))}")
    allowed_by_method = {
        "interval": {"method", "region_start", "region_end", "invert"},
        "peak_window": {"method", "peak_prominence", "peak_half_window", "include_negative_extrema", "invert"},
        "apply_mask": {"method", "invert"},
        "vip": {"method", "threshold", "invert"},
        "coef_abs": {"method", "threshold", "invert"},
        "selectivity_ratio": {"method", "threshold", "invert"},
    }
    allowed = allowed_by_method[str(method)]
    defaults = {
        "region_start": None,
        "region_end": None,
        "peak_prominence": 0.1,
        "peak_half_window": 10,
        "include_negative_extrema": False,
        "threshold": 1.0,
    }
    unknown = sorted(name for name in parameters if name not in allowed and name not in defaults)
    if unknown:
        raise ValueError(f"selection.variable_select method {method!r} does not accept: {', '.join(unknown)}")
    contradictory = sorted(
        name
        for name, default in defaults.items()
        if name not in allowed and name in parameters and parameters[name] != default
    )
    if contradictory:
        raise ValueError(
            f"selection.variable_select method {method!r} does not accept non-default values for: "
            f"{', '.join(contradictory)}"
        )
    invert = parameters.get("invert", False)
    if not isinstance(invert, bool):
        raise ValueError("selection.variable_select invert must be boolean")
    resolved: dict[str, object] = {"method": method, "invert": invert}
    if method == "interval":
        if "region_start" not in parameters or "region_end" not in parameters:
            raise ValueError("selection.variable_select interval requires region_start and region_end")
        start = _finite_number(parameters["region_start"], name="region_start")
        end = _finite_number(parameters["region_end"], name="region_end")
        if start == end:
            raise ValueError("selection.variable_select interval endpoints must differ")
        resolved.update(region_start=start, region_end=end)
    elif method == "peak_window":
        prominence = _finite_number(parameters.get("peak_prominence", 0.1), name="peak_prominence")
        if prominence <= 0.0 or prominence > 1.0:
            raise ValueError("selection.variable_select peak_prominence must be a relative value in (0, 1]")
        half_window = parameters.get("peak_half_window", 10)
        if isinstance(half_window, bool) or not isinstance(half_window, int) or not 1 <= half_window <= 10_000:
            raise ValueError("selection.variable_select peak_half_window must be an integer in [1, 10000]")
        include_negative = parameters.get("include_negative_extrema", False)
        if not isinstance(include_negative, bool):
            raise ValueError("selection.variable_select include_negative_extrema must be boolean")
        resolved.update(
            peak_prominence=prominence,
            peak_half_window=half_window,
            include_negative_extrema=include_negative,
        )
    elif method in {"vip", "coef_abs", "selectivity_ratio"}:
        threshold = _finite_number(parameters.get("threshold", 1.0), name="threshold")
        upper = 1.0 if method == "coef_abs" else 1_000_000.0
        if threshold <= 0.0 or threshold > upper:
            raise ValueError(f"selection.variable_select {method} threshold must be in (0, {upper:g}]")
        resolved["threshold"] = threshold
    return resolved


def _digest_vector(values: np.ndarray, *, dtype: str) -> str:
    return hashlib.sha256(np.asarray(values, dtype=dtype).tobytes(order="C")).hexdigest()


def _extract_pls_model(model_input: Any) -> Any:
    if isinstance(model_input, Mapping):
        if "schema_version" in model_input:
            from ..modeling.fitted_pls_node import verify_fitted_pls_state_envelope

            state = verify_fitted_pls_state_envelope(model_input)
            # Existing coefficient selection owns the vector/single-target check.
            from types import SimpleNamespace

            return SimpleNamespace(coef_=np.asarray(state["coefficients"], dtype=float))
        for key in ("model", "pls_model"):
            if key in model_input:
                return model_input[key]
    return model_input


def _model_coefficients(model: Any, *, features: int) -> np.ndarray:
    if model is None:
        raise ValueError("The selected PLS importance rule requires a connected fitted PLS model")
    fitted = _extract_pls_model(model)
    raw = fitted_state._safe_getattr(fitted, ("coef", "coef_", "coefficients", "_coef"))
    if raw is None:
        raise ValueError("Could not extract regression coefficients from the fitted PLS model")
    raw_value = raw.data if hasattr(raw, "data") else raw
    coefficients = np.asarray(raw_value, dtype=np.float64).reshape(-1)
    if coefficients.shape != (features,) or not np.isfinite(coefficients).all():
        raise ValueError("PLS coefficient vector must be finite and match the feature count exactly")
    return coefficients


def _vip_scores(value: Any, *, features: int) -> np.ndarray:
    if value is None:
        raise ValueError("VIP selection requires connected producer-owned importance scores")
    scores = np.asarray(value, dtype=np.float64)
    if scores.shape != (features,) or not np.isfinite(scores).all() or np.any(scores < 0.0):
        raise ValueError("PLS VIP scores must be finite, non-negative, and match the feature count")
    return scores


def _strict_mask(value: Any, *, features: int) -> np.ndarray:
    raw = value.data if hasattr(value, "data") else value
    array = np.asarray(raw)
    if array.ndim != 1 or array.shape != (features,) or array.dtype.kind != "b":
        raise ValueError("Connected mask must be a one-dimensional boolean vector matching the feature count")
    return np.array(array, dtype=bool, copy=True)


def _rule_mask(
    matrix: np.ndarray,
    axis_values: np.ndarray | None,
    *,
    model: Any,
    supplied_mask: Any,
    importance_scores: Any,
    parameters: Mapping[str, object],
) -> tuple[np.ndarray, np.ndarray | None, list[int]]:
    method = str(parameters["method"])
    features = matrix.shape[1]
    scores: np.ndarray | None = None
    selected_landmarks: list[int] = []
    if method == "interval":
        start, end = float(parameters["region_start"]), float(parameters["region_end"])
        lo, hi = min(start, end), max(start, end)
        coordinates = axis_values if axis_values is not None else np.arange(features, dtype=np.float64)
        mask = (coordinates >= lo) & (coordinates <= hi)
    elif method == "peak_window":
        centered = np.mean(matrix, axis=0) - float(np.median(np.mean(matrix, axis=0)))
        magnitude = np.abs(centered)
        maximum = float(np.max(magnitude))
        if maximum <= np.finfo(np.float64).eps:
            raise ValueError("Peak-window selection found no extrema in a constant mean spectrum")
        normalized = centered / maximum
        positive, _ = signal.find_peaks(normalized, prominence=float(parameters["peak_prominence"]))
        peaks = positive
        if bool(parameters["include_negative_extrema"]):
            negative, _ = signal.find_peaks(-normalized, prominence=float(parameters["peak_prominence"]))
            peaks = np.unique(np.concatenate((positive, negative)))
        if peaks.size == 0:
            raise ValueError("Peak-window selection found no extrema at the declared prominence")
        selected_landmarks = np.asarray(peaks, dtype=int).tolist()
        mask = np.zeros(features, dtype=bool)
        half_window = int(parameters["peak_half_window"])
        for peak in peaks:
            mask[max(0, int(peak) - half_window) : min(features, int(peak) + half_window + 1)] = True
        scores = magnitude / maximum
    elif method == "apply_mask":
        if supplied_mask is None:
            raise ValueError("apply_mask requires a connected boolean mask")
        mask = _strict_mask(supplied_mask, features=features)
        scores = mask.astype(np.float64)
    elif method == "vip":
        scores = _vip_scores(importance_scores, features=features)
        mask = scores >= float(parameters["threshold"])
    elif method == "coef_abs":
        scores = np.abs(_model_coefficients(model, features=features))
        maximum = float(np.max(scores))
        if maximum <= np.finfo(np.float64).eps:
            raise ValueError("Coefficient-magnitude selection requires a non-zero coefficient vector")
        scores = scores / maximum
        mask = scores >= float(parameters["threshold"])
    else:
        coefficients = _model_coefficients(model, features=features)
        scores = _selectivity_ratio.target_projection_selectivity_ratio(matrix, coefficients)
        mask = scores >= float(parameters["threshold"])
    mask = np.asarray(mask, dtype=bool)
    if bool(parameters["invert"]):
        mask = ~mask
    if mask.shape != (features,) or not np.any(mask):
        raise ValueError(f"Variable-selection rule {method!r} retained no variables")
    if scores is not None and (scores.shape != (features,) or not np.isfinite(scores).all()):
        raise ValueError(f"Variable-selection rule {method!r} produced invalid scores")
    return mask, scores, selected_landmarks


def _feature_axis(dataset: Any, *, features: int) -> tuple[Any, np.ndarray | None, str | None]:
    axis = getattr(dataset, "feature_axis", None)
    values = None if axis is None else getattr(axis, "values", None)
    if values is None:
        return axis, None, None
    array = np.asarray(values, dtype=np.float64)
    if array.shape != (features,) or not np.isfinite(array).all():
        raise ValueError("Feature-axis values must be finite and match the feature count")
    return axis, array, _digest_vector(array, dtype="<f8")


def _variable_select_execute(
    X: Any,
    model: Any = None,
    mask: Any = None,
    importance_scores: Any = None,
    *,
    node_id: str,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    canonical = _canonical_variable_select_parameters(parameters)
    dataset = bind_X(X, missing_message="Variable selection requires X", allow_array=True)
    matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
    if isinstance(model, Mapping) and "schema_version" in model:
        from ...fitted_input_identity import require_fitted_input_identity
        from ..modeling.fitted_pls_node import verify_fitted_pls_state_envelope

        state = verify_fitted_pls_state_envelope(model)
        require_fitted_input_identity(dataset, state["input_identity"], features=matrix.shape[1])
    if matrix.shape[0] < 1 or matrix.shape[1] < 2 or not np.isfinite(matrix).all():
        raise ValueError("Variable selection requires a finite matrix with at least two features")
    axis, axis_values, axis_digest = _feature_axis(dataset, features=matrix.shape[1])
    selected, scores, landmarks = _rule_mask(
        matrix,
        axis_values,
        model=model,
        supplied_mask=mask,
        importance_scores=importance_scores,
        parameters=canonical,
    )
    reduced = build_dataset_like(matrix[:, selected], dataset)
    selected_count = int(selected.sum())
    if axis is not None and axis_values is not None:
        from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SpectralAxis

        axis_class = type(axis) if isinstance(axis, FeatureAxis) else SpectralAxis
        labels = getattr(axis, "labels", None)
        reduced.feature_axis = axis_class(
            values=axis_values[selected],
            labels=list(np.asarray(labels)[selected]) if labels is not None else None,
            units=getattr(axis, "units", None),
            title=getattr(axis, "title", None),
            include_mask=np.ones(selected_count, dtype=bool),
            selection_method=str(canonical["method"]),
            selection_scores=scores[selected] if scores is not None else None,
        )
    reduced.meta["feature_mask"] = selected.tolist()
    report = {
        "schema": _REPORT_SCHEMA,
        "method": canonical["method"],
        "parameters": dict(canonical),
        "selection_scope": _SCOPE,
        "predictive_performance_claimed": False,
        "reference_samples": matrix.shape[0],
        "reference_features": matrix.shape[1],
        "selected_features": selected_count,
        "feature_axis_values_sha256": axis_digest,
        "feature_mask_sha256": _digest_vector(selected, dtype="?"),
        "score_sha256": None if scores is None else _digest_vector(scores, dtype="<f8"),
        "detected_extrema_indices": landmarks,
    }
    add_processing_step(
        reduced,
        "selection.variable_select",
        {"selection_report": report, "feature_mask": selected.tolist()},
        node_id,
    )
    outputs: dict[str, Any] = {
        "default": reduced,
        "X_selected": reduced,
        "mask": selected,
        "selection_report": report,
    }
    if scores is not None:
        outputs["scores"] = scores
    diagnostics = {
        "method": canonical["method"],
        "n_selected": selected_count,
        "n_total": matrix.shape[1],
        "pct_selected": round(100.0 * selected_count / matrix.shape[1], 1),
        "selection_scope": _SCOPE,
    }
    return outputs, diagnostics


@register_node
class VariableSelectNode(Node):
    """Apply one declared, target-free feature-selection rule."""

    metadata = NodeMetadata(
        node_type="selection.variable_select",
        category="selection",
        label="Variable Selection Rule",
        description="Apply an explicit interval, peak, mask, or fitted-PLS importance rule",
        parameters=[
            NodeParameter(
                name="method",
                label="Selection Method",
                param_type="select",
                options=[
                    {"label": "Spectral Interval", "value": "interval"},
                    {"label": "Peak Window", "value": "peak_window"},
                    {"label": "Apply Existing Mask", "value": "apply_mask"},
                    {"label": "VIP (PLS)", "value": "vip"},
                    {"label": "Normalized Coefficient Magnitude", "value": "coef_abs"},
                    {"label": "Target-Projection Selectivity Ratio", "value": "selectivity_ratio"},
                ],
                default="vip",
                required=True,
            ),
            NodeParameter(
                name="region_start",
                label="Region Start",
                param_type="number",
                default=None,
                visible_when={"method": ["interval"]},
                required=False,
            ),
            NodeParameter(
                name="region_end",
                label="Region End",
                param_type="number",
                default=None,
                visible_when={"method": ["interval"]},
                required=False,
            ),
            NodeParameter(
                name="peak_prominence",
                label="Peak Prominence",
                param_type="number",
                default=0.1,
                min_value=0.001,
                step=0.01,
                visible_when={"method": ["peak_window"]},
            ),
            NodeParameter(
                name="peak_half_window",
                label="Half-Window (points)",
                param_type="number",
                default=10,
                min_value=1,
                step=1,
                visible_when={"method": ["peak_window"]},
            ),
            NodeParameter(
                name="include_negative_extrema",
                label="Include Negative Extrema",
                param_type="boolean",
                default=False,
                visible_when={"method": ["peak_window"]},
                category="advanced",
            ),
            NodeParameter(
                name="threshold",
                label="Declared Score Threshold",
                param_type="number",
                default=1.0,
                min_value=0.0,
                step=0.1,
                visible_when={"method": ["vip", "coef_abs", "selectivity_ratio"]},
            ),
            NodeParameter(
                name="invert", label="Invert Selection", param_type="boolean", default=False, category="advanced"
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="model", type_ref="spectrasherpa://types/FittedModel/1.0", required=False, label="Fitted PLS Model"
            ),
            PortMetadata(
                name="mask", type_ref="spectrasherpa://types/Array1D/1.0", required=False, label="Existing Boolean Mask"
            ),
            PortMetadata(
                name="importance_scores",
                type_ref="spectrasherpa://types/VariableImportance/1.0",
                required=False,
                label="Producer-Owned Importance Scores",
                description="VIP scores emitted by the exact upstream fitted PLS producer.",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Selected Data",
            ),
            PortMetadata(
                name="X_selected",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Selected Data",
            ),
            PortMetadata(
                name="mask", type_ref="spectrasherpa://types/Array1D/1.0", required=True, label="Feature Mask"
            ),
            PortMetadata(
                name="scores", type_ref="spectrasherpa://types/Array1D/1.0", required=False, label="Rule Scores"
            ),
            PortMetadata(
                name="selection_report",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Selection Evidence",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="dict",
        diagnostics=["method", "n_selected", "n_total", "pct_selected", "selection_scope"],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_variable_select_parameters,
    )

    def generate_python(self, inputs: Mapping[str, str], indent: str = "    ", use_scp: bool = True) -> list[str]:
        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        return [
            f"{indent}# --- Canonical variable-selection rule ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node "
            "import _variable_select_execute",
            f"{indent}_vs_outputs, _vs_diagnostics = _variable_select_execute(",
            f"{indent}    {X_expression}, {inputs.get('model', 'None')}, {inputs.get('mask', 'None')}, "
            f"{inputs.get('importance_scores', 'None')},",
            f"{indent}    node_id={self.node_id!r}, parameters={self._resolve_params()!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _vs_outputs",
        ]

    async def execute(
        self,
        X: Any = None,
        model: Any = None,
        mask: Any = None,
        importance_scores: Any = None,
        **kwargs: Any,
    ) -> NodeResult:
        # The managed fold lifecycle supplies the canonical chained dataset as
        # ``input_data``.  The Workbench continues to bind the declared ``X``
        # port.  Both names enter the same implementation and ambiguous dual
        # binding is refused instead of choosing an authority by accident.
        chained = kwargs.pop("input_data", None)
        managed_chain = X is None and chained is not None
        if kwargs:
            raise ValueError("Variable selection received unsupported inputs")
        if X is not None and chained is not None:
            raise ValueError("Variable selection received both X and input_data")
        if X is None:
            X = chained
        outputs, diagnostics = _variable_select_execute(
            X, model, mask, importance_scores, node_id=self.node_id, parameters=self._resolve_params()
        )
        logger.info(
            "Variable-selection rule %s retained %s/%s features",
            diagnostics["method"],
            diagnostics["n_selected"],
            diagnostics["n_total"],
        )
        return NodeResult(
            outputs={"default": outputs["default"]} if managed_chain else outputs,
            diagnostics=diagnostics,
        )


bind_stable_execution_contract(
    VariableSelectNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.selection.variable_select",
    implementation_version="2.1.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(
        ManagedOptimizationEligibility.LOCAL,
        ManagedOptimizationEligibility.DEVELOPMENT,
        ManagedOptimizationEligibility.FULL_REFIT,
    ),
    managed_optimization_profiles=("first_party_pls",),
    sample_effect="preserves_samples",
    feature_effect="filters_features",
    axis_effect="changes_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/selection-validation.md",
    implementation_modules=(_selectivity_ratio, fitted_state),
    implementation_distributions=("numpy", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1")),
    citations=(
        "mdatools PLS variable-selection reference, https://mda.tools/docs/pls--variable-selection.html",
        "Chong and Jun, Chemometrics and Intelligent Laboratory Systems 78 (2005) 103-112",
        "Kvalheim, Journal of Chemometrics 24 (2010) 496-504, doi:10.1002/cem.1289",
        "Virtanen et al., Nature Methods 17 (2020) 261-272, doi:10.1038/s41592-019-0686-2",
    ),
    deterministic=True,
    target_access=TargetAccess.NONE,
    group_access="none",
)


__all__ = ["VariableSelectNode", "_canonical_variable_select_parameters", "_variable_select_execute"]
