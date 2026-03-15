"""Variable selection node — chemometric feature selection.

Registered as ``selection.variable_select``.

Consolidates interval, peak-window, VIP, coefficient-magnitude, and
selectivity-ratio methods into a single node.  All methods produce a
boolean feature mask written to ``FeatureAxis.include_mask``.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from scipy import signal

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ...io_contracts import bind_X, build_dataset_like, to_numpy_2d
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)


@register_node
class VariableSelectNode(Node):
    """Select informative spectral variables (wavelengths/features).

    Produces a boolean feature mask and optional importance scores.
    The mask is written to ``FeatureAxis.include_mask`` on the output
    dataset, establishing the feature selection contract.

    Methods:
    - **interval**: Select contiguous wavenumber region(s).
    - **peak_window**: Detect peaks and select +-window around each.
    - **vip**: Variable Importance in Projection from a PLS model.
    - **coef_abs**: Absolute regression coefficients from a PLS model.
    - **selectivity_ratio**: Target-projection selectivity ratio from PLS.
    """

    metadata = NodeMetadata(
        node_type="selection.variable_select",
        category="selection",
        label="Variable Selection",
        description="Select informative wavelengths using chemometric criteria",
        parameters=[
            NodeParameter(
                name="method",
                label="Selection Method",
                param_type="select",
                options=[
                    {"label": "Spectral Interval", "value": "interval"},
                    {"label": "Peak Window", "value": "peak_window"},
                    {"label": "VIP (PLS)", "value": "vip"},
                    {"label": "Coefficient Magnitude", "value": "coef_abs"},
                    {"label": "Selectivity Ratio", "value": "selectivity_ratio"},
                ],
                default="vip",
                description="Variable selection criterion",
                required=True,
            ),
            # --- Interval parameters ---
            NodeParameter(
                name="region_start",
                label="Region Start",
                param_type="number",
                default=None,
                description="Start of spectral region (in axis units, e.g. cm-1)",
                required=False,
                visible_when={"method": ["interval"]},
            ),
            NodeParameter(
                name="region_end",
                label="Region End",
                param_type="number",
                default=None,
                description="End of spectral region (in axis units)",
                required=False,
                visible_when={"method": ["interval"]},
            ),
            # --- Peak window parameters ---
            NodeParameter(
                name="peak_prominence",
                label="Peak Prominence",
                param_type="number",
                default=0.1,
                min_value=0.001,
                max_value=10.0,
                step=0.01,
                description="Minimum prominence for peak detection",
                required=False,
                visible_when={"method": ["peak_window"]},
            ),
            NodeParameter(
                name="peak_half_window",
                label="Half-Window (points)",
                param_type="number",
                default=10,
                min_value=1,
                max_value=200,
                step=1,
                description="Number of points on each side of a detected peak to include",
                required=False,
                visible_when={"method": ["peak_window"]},
            ),
            NodeParameter(
                name="include_negative_extrema",
                label="Include Negative Extrema",
                param_type="boolean",
                default=False,
                description="Detect troughs as well as peaks when using peak-window selection",
                required=False,
                visible_when={"method": ["peak_window"]},
                category="advanced",
            ),
            # --- VIP / coefficient parameters ---
            NodeParameter(
                name="threshold",
                label="Threshold",
                param_type="number",
                default=1.0,
                min_value=0.0,
                max_value=100.0,
                step=0.1,
                description="Selection threshold (VIP > 1.0 convention; coef/SR: top fraction or absolute)",
                required=False,
                visible_when={"method": ["vip", "coef_abs", "selectivity_ratio"]},
            ),
            # --- General ---
            NodeParameter(
                name="invert",
                label="Invert Selection",
                param_type="boolean",
                default=False,
                description="If true, exclude selected variables instead of keeping them",
                required=False,
                category="advanced",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Data",
                description="Spectral dataset to select variables from",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                required=False,
                label="PLS Model (optional)",
                description="Trained PLS/PLS-DA model dict for VIP, coef, or selectivity ratio methods",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_selected",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Selected Data",
                description="Dataset with feature_axis.include_mask applied",
            ),
            PortMetadata(
                name="mask",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Feature Mask",
                description="Boolean mask (True = selected variable)",
            ),
            PortMetadata(
                name="scores",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Importance Scores",
                description="Per-variable importance scores (VIP, coef, SR)",
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        diagnostics=["method", "n_selected", "n_total", "pct_selected"],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        params = self._resolve_params()
        method = params.get("method", "vip")
        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        model_expr = inputs.get("model")

        lines: list[str] = []
        lines.append(f"{indent}# --- Variable Selection ({self.node_id}) ---")
        lines.append(f"{indent}# Method: {method}")
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(
            f"{indent}_X_vs = np.asarray("
            f"_X_input.data if hasattr(_X_input, 'data') else _X_input, dtype=np.float64)"
        )
        lines.append(f"{indent}_fa_obj = getattr(_X_input, 'feature_axis', None)")
        lines.append(f"{indent}if _fa_obj is not None and getattr(_fa_obj, 'values', None) is not None:")
        lines.append(f"{indent}    _fa_vals = np.asarray(_fa_obj.values, dtype=np.float64)")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    _x_obj = getattr(_X_input, 'x', None)")
        lines.append(f"{indent}    if hasattr(_x_obj, 'values') and getattr(_x_obj, 'values', None) is not None:")
        lines.append(f"{indent}        _fa_vals = np.asarray(_x_obj.values, dtype=np.float64)")
        lines.append(f"{indent}    elif _x_obj is not None:")
        lines.append(f"{indent}        _fa_vals = np.asarray(_x_obj, dtype=np.float64)")
        lines.append(f"{indent}    else:")
        lines.append(f"{indent}        _fa_vals = np.arange(_X_vs.shape[1], dtype=np.float64)")
        lines.append(f"{indent}_scores = None")

        if method == "interval":
            rs = params.get("region_start", 0)
            re_ = params.get("region_end", 0)
            lines.append(f"{indent}# Interval selection: [{rs}, {re_}]")
            lines.append(f"{indent}_lo, _hi = min({rs}, {re_}), max({rs}, {re_})")
            lines.append(f"{indent}_mask = (_fa_vals >= _lo) & (_fa_vals <= _hi)")
        elif method == "vip":
            threshold = params.get("threshold", 1.0)
            lines.append(f"{indent}# VIP selection: threshold={threshold}")
            lines.append(f"{indent}if {model_expr} is None:")
            lines.append(f"{indent}    raise ValueError('VIP selection requires a connected PLS model')")
            lines.append(
                f"{indent}from spectra_sherpa.app.services.dag.nodes.selection._vip import extract_vip_from_pls_model"
            )
            lines.append(f"{indent}_scores = extract_vip_from_pls_model({model_expr}, _X_vs.shape[1])")
            lines.append(f"{indent}_mask = _scores >= {threshold}")
        elif method == "coef_abs":
            threshold = params.get("threshold", 1.0)
            lines.append(f"{indent}# Coefficient magnitude selection: threshold={threshold}")
            lines.append(f"{indent}if {model_expr} is None:")
            lines.append(f"{indent}    raise ValueError('Coefficient selection requires a connected PLS model')")
            lines.append(f"{indent}from spectra_sherpa.app.lib.adapters.scp_extractors import _safe_getattr")
            lines.append(f"{indent}_raw_coef = _safe_getattr({model_expr}, ('coef', 'coef_', 'coefficients', '_coef'))")
            lines.append(f"{indent}if _raw_coef is None:")
            lines.append(f"{indent}    raise ValueError('Could not extract coefficients from PLS model')")
            lines.append(
                f"{indent}_coef = np.asarray("
                f"_raw_coef.data if hasattr(_raw_coef, 'data') else _raw_coef, dtype=np.float64).reshape(-1)"
            )
            lines.append(f"{indent}if _coef.size != _X_vs.shape[1]:")
            lines.append(f"{indent}    _coef = _coef[:_X_vs.shape[1]]")
            lines.append(f"{indent}_scores = np.abs(_coef)")
            lines.append(f"{indent}_max_score = float(np.max(_scores)) if _scores.size else 0.0")
            lines.append(f"{indent}if _max_score > 0:")
            lines.append(f"{indent}    _scores = _scores / _max_score")
            lines.append(f"{indent}_mask = _scores >= {threshold}")
        elif method == "peak_window":
            prominence = params.get("peak_prominence", 0.1)
            hw = params.get("peak_half_window", 10)
            include_negative = bool(params.get("include_negative_extrema", False))
            lines.append(f"{indent}from scipy import signal")
            lines.append(f"{indent}_mean_spec = np.mean(_X_vs, axis=0)")
            lines.append(f"{indent}_centered = _mean_spec - float(np.median(_mean_spec))")
            lines.append(f"{indent}_pos_peaks, _ = signal.find_peaks(_centered, prominence={prominence})")
            if include_negative:
                lines.append(f"{indent}_neg_peaks, _ = signal.find_peaks(-_centered, prominence={prominence})")
                lines.append(f"{indent}_peaks = np.unique(np.concatenate([_pos_peaks, _neg_peaks])).astype(int)")
            else:
                lines.append(f"{indent}_peaks = _pos_peaks.astype(int)")
            lines.append(f"{indent}_mask = np.zeros(_X_vs.shape[1], dtype=bool)")
            lines.append(f"{indent}for _p in _peaks:")
            lines.append(f"{indent}    _mask[max(0, _p - {hw}):min(_X_vs.shape[1], _p + {hw} + 1)] = True")
            lines.append(f"{indent}_magnitude = np.abs(_centered)")
            lines.append(f"{indent}_max_mag = float(np.max(_magnitude)) if _magnitude.size else 0.0")
            lines.append(
                f"{indent}_scores = (_magnitude / _max_mag) if _max_mag > 0 else np.zeros(_X_vs.shape[1], dtype=np.float64)"
            )
            lines.append(f"{indent}if not np.any(_mask):")
            lines.append(f"{indent}    _strongest = int(np.argmax(_magnitude)) if _magnitude.size else 0")
            lines.append(
                f"{indent}    _mask[max(0, _strongest - {hw}):min(_X_vs.shape[1], _strongest + {hw} + 1)] = True"
            )
            lines.append(f"{indent}if len(_peaks) > 0:")
            lines.append(f"{indent}    _proximity = np.zeros(_X_vs.shape[1], dtype=np.float64)")
            lines.append(f"{indent}    for _i in range(_X_vs.shape[1]):")
            lines.append(f"{indent}        _proximity[_i] = float(np.min(np.abs(_peaks - _i)))")
            lines.append(f"{indent}    _max_dist = float(np.max(_proximity)) if _proximity.size else 0.0")
            lines.append(f"{indent}    if _max_dist > 0:")
            lines.append(f"{indent}        _proximity = 1.0 - _proximity / _max_dist")
            lines.append(f"{indent}    _scores = np.maximum(_scores, _proximity)")
        elif method == "selectivity_ratio":
            threshold = params.get("threshold", 1.0)
            lines.append(f"{indent}if {model_expr} is None:")
            lines.append(f"{indent}    raise ValueError('Selectivity-ratio selection requires a connected PLS model')")
            lines.append(f"{indent}from spectra_sherpa.app.lib.adapters.scp_extractors import _safe_getattr")
            lines.append(f"{indent}_raw_coef = _safe_getattr({model_expr}, ('coef', 'coef_', 'coefficients', '_coef'))")
            lines.append(f"{indent}if _raw_coef is None:")
            lines.append(f"{indent}    raise ValueError('Could not extract coefficients from PLS model')")
            lines.append(
                f"{indent}_coef = np.asarray("
                f"_raw_coef.data if hasattr(_raw_coef, 'data') else _raw_coef, dtype=np.float64).reshape(-1)"
            )
            lines.append(f"{indent}if _coef.size != _X_vs.shape[1]:")
            lines.append(f"{indent}    _coef = _coef[:_X_vs.shape[1]]")
            lines.append(f"{indent}_coef_norm_sq = float(_coef @ _coef)")
            lines.append(f"{indent}if _coef_norm_sq < 1e-12:")
            lines.append(f"{indent}    _scores = np.zeros(_X_vs.shape[1], dtype=np.float64)")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    _t_tp = _X_vs @ _coef / _coef_norm_sq")
            lines.append(f"{indent}    _X_explained = np.outer(_t_tp, _coef)")
            lines.append(f"{indent}    _X_residual = _X_vs - _X_explained")
            lines.append(f"{indent}    _var_explained = np.var(_X_explained, axis=0)")
            lines.append(f"{indent}    _var_residual = np.var(_X_residual, axis=0)")
            lines.append(f"{indent}    _scores = np.zeros(_X_vs.shape[1], dtype=np.float64)")
            lines.append(f"{indent}    _nz = _var_residual > 1e-12")
            lines.append(f"{indent}    _scores[_nz] = _var_explained[_nz] / _var_residual[_nz]")
            lines.append(f"{indent}_mask = _scores >= {threshold}")
        else:
            lines.append(f"{indent}# Method '{method}' — see SpectraSherpa docs")
            lines.append(f"{indent}_mask = np.ones(_X_vs.shape[1], dtype=bool)")

        invert = params.get("invert", False)
        if invert:
            lines.append(f"{indent}_mask = ~_mask")

        lines.append(f"{indent}_X_selected = _X_vs[:, _mask]")
        lines.append(f"{indent}_selected_target = getattr(_X_input, 'target', None)")
        if use_scp:
            lines.append(f"{indent}from spectra_sherpa.app.lib.axes import FeatureAxis, SpectralAxis")
            lines.append(f"{indent}from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset")
            lines.append(f"{indent}_reduced_fa = None")
            lines.append(
                f"{indent}if _fa_obj is not None and hasattr(_fa_obj, 'values')"
                f" and getattr(_fa_obj, 'values', None) is not None:"
            )
            lines.append(f"{indent}    _fa_cls = type(_fa_obj) if isinstance(_fa_obj, FeatureAxis) else SpectralAxis")
            lines.append(
                f"{indent}    _reduced_fa = _fa_cls("
                f"values=_fa_vals[_mask], units=getattr(_fa_obj, 'units', None), title=getattr(_fa_obj, 'title', None))"
            )
            lines.append(
                f"{indent}_X_selected_ds = SherpaDataset("
                f"X=_X_selected, feature_axis=_reduced_fa, target=_selected_target)"
            )
        else:
            lines.append(f"{indent}_selected_x = _fa_vals[_mask] if _fa_vals.shape[0] == _X_vs.shape[1] else None")
            lines.append(
                f"{indent}_X_selected_ds = _Result("
                f"_X_selected, x=_selected_x, target=_selected_target, "
                f"target_names=getattr(_X_input, 'target_names', None))"
            )
        lines.append(f'{indent}print(f"  Selected {{np.sum(_mask)}} / {{len(_mask)}} variables")')
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'X_selected': _X_selected_ds, 'mask': _mask,")
        lines.append(f"{indent}}}")
        lines.append(f"{indent}if _scores is not None:")
        lines.append(f"{indent}    results['{self.node_id}']['scores'] = _scores")

        return lines

    async def execute(self, X: Any = None, model: Any = None, **kwargs: Any) -> NodeResult:
        params = self._resolve_params()
        method = params.get("method", "vip")
        invert = bool(params.get("invert", False))

        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (dataset)",
            dataset_error_message="X must be an NDDataset or SherpaDataset",
            allow_array=True,
        )
        X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        n_features = X_array.shape[1]

        # Get feature axis values if available
        fa = getattr(X_ds, "feature_axis", None)
        fa_values = np.asarray(fa.values, dtype=np.float64) if (fa is not None and fa.values is not None) else None

        mask: np.ndarray
        scores: np.ndarray | None = None

        if method == "interval":
            mask, scores = self._select_interval(fa_values, n_features, params)

        elif method == "peak_window":
            mask, scores = self._select_peak_window(X_array, n_features, params)

        elif method == "vip":
            mask, scores = self._select_vip(model, n_features, params)

        elif method == "coef_abs":
            mask, scores = self._select_coef_abs(model, n_features, params)

        elif method == "selectivity_ratio":
            mask, scores = self._select_selectivity_ratio(model, X_array, n_features, params)

        else:
            raise ValueError(f"Unknown variable selection method: {method!r}")

        if invert:
            mask = ~mask

        n_selected = int(np.sum(mask))
        if n_selected == 0:
            raise ValueError(
                f"Variable selection ({method}) produced an empty mask. "
                "Try adjusting the threshold or region parameters."
            )

        # --- Build output dataset with mask on feature axis ---
        X_selected_array = X_array[:, mask]
        X_selected_ds = build_dataset_like(X_selected_array, X_ds)

        # Set feature axis with selected values + selection provenance on ORIGINAL dataset
        if fa is not None:
            fa_copy = fa.copy()
            fa_copy.apply_mask(mask, method=method, scores=scores)
            # The output dataset gets the reduced feature axis
            if fa_values is not None:
                from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SpectralAxis

                reduced_fa_cls = type(fa) if isinstance(fa, FeatureAxis) else SpectralAxis
                reduced_fa = reduced_fa_cls(
                    values=fa_values[mask],
                    units=fa.units,
                    title=fa.title,
                    include_mask=np.ones(n_selected, dtype=bool),
                    selection_method=method,
                    selection_scores=scores[mask] if scores is not None else None,
                )
                X_selected_ds.feature_axis = reduced_fa

        # Store the original feature mask on the output dataset's meta so that
        # downstream training nodes can include it in their model artifact.
        # This enables load_apply to auto-slice full-spectrum new data.
        X_selected_ds.meta["feature_mask"] = mask.tolist()

        # Provenance
        step_params: dict[str, Any] = {"method": method, "n_selected": n_selected, "n_total": n_features}
        if method in ("vip", "coef_abs", "selectivity_ratio"):
            step_params["threshold"] = params.get("threshold", 1.0)
        add_processing_step(X_selected_ds, "selection.variable_select", step_params, self.node_id)

        outputs: dict[str, Any] = {
            "X_selected": X_selected_ds,
            "mask": mask,
        }
        if scores is not None:
            outputs["scores"] = scores

        diagnostics = {
            "method": method,
            "n_selected": n_selected,
            "n_total": n_features,
            "pct_selected": round(100.0 * n_selected / n_features, 1),
        }

        logger.info(f"Variable selection ({method}): {n_selected}/{n_features} features selected")

        return NodeResult(outputs=outputs, diagnostics=diagnostics)

    # ── Selection methods ──────────────────────────────────────────────

    def _select_interval(
        self,
        fa_values: np.ndarray | None,
        n_features: int,
        params: dict,
    ) -> tuple[np.ndarray, np.ndarray | None]:
        """Select features within a contiguous spectral interval."""
        region_start = params.get("region_start")
        region_end = params.get("region_end")

        if region_start is None or region_end is None:
            raise ValueError("interval method requires region_start and region_end parameters")

        lo, hi = min(float(region_start), float(region_end)), max(float(region_start), float(region_end))

        if fa_values is not None:
            mask = (fa_values >= lo) & (fa_values <= hi)
        else:
            # Treat as index range
            mask = np.zeros(n_features, dtype=bool)
            mask[int(lo) : int(hi) + 1] = True

        return mask, None

    def _select_peak_window(
        self,
        X_array: np.ndarray,
        n_features: int,
        params: dict,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Detect positive and negative peaks, then select +-window around each."""
        prominence = float(params.get("peak_prominence", 0.1))
        half_window = int(params.get("peak_half_window", 10))
        include_negative = bool(params.get("include_negative_extrema", False))

        mean_spectrum = np.mean(X_array, axis=0)
        centered = mean_spectrum - float(np.median(mean_spectrum))
        pos_peaks, _ = signal.find_peaks(centered, prominence=prominence)
        if include_negative:
            neg_peaks, _ = signal.find_peaks(-centered, prominence=prominence)
            peaks = np.unique(np.concatenate([pos_peaks, neg_peaks])).astype(int)
        else:
            peaks = pos_peaks.astype(int)

        mask = np.zeros(n_features, dtype=bool)
        for p in peaks:
            lo = max(0, p - half_window)
            hi = min(n_features, p + half_window + 1)
            mask[lo:hi] = True

        magnitude = np.abs(centered)
        max_mag = float(np.max(magnitude)) if magnitude.size else 0.0
        scores = (magnitude / max_mag) if max_mag > 0 else np.zeros(n_features, dtype=np.float64)

        # Derivative spectra can have chemically meaningful troughs but no
        # positive maxima above threshold. Fall back to the strongest absolute
        # excursion so peak-guided workflows remain usable instead of failing
        # with an empty mask.
        if not np.any(mask):
            strongest = int(np.argmax(magnitude)) if magnitude.size else 0
            lo = max(0, strongest - half_window)
            hi = min(n_features, strongest + half_window + 1)
            mask[lo:hi] = True

        if len(peaks) > 0:
            proximity = np.zeros(n_features, dtype=np.float64)
            for i in range(n_features):
                proximity[i] = float(np.min(np.abs(peaks - i)))
            max_dist = float(proximity.max())
            if max_dist > 0:
                proximity = 1.0 - proximity / max_dist
            scores = np.maximum(scores, proximity)
        return mask, scores

    def _select_vip(
        self,
        model: Any,
        n_features: int,
        params: dict,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Select features using VIP scores from a PLS model."""
        threshold = float(params.get("threshold", 1.0))

        if model is None:
            raise ValueError(
                "VIP method requires a PLS/PLS-DA model. "
                "Connect the 'model' output port of a PLS node to this node's 'model' input."
            )

        # Extract PLS model object from the model dict
        pls_model = self._extract_pls_model(model)

        from ._vip import extract_vip_from_pls_model

        vip_scores = extract_vip_from_pls_model(pls_model, n_features)

        mask = vip_scores >= threshold
        return mask, vip_scores

    def _select_coef_abs(
        self,
        model: Any,
        n_features: int,
        params: dict,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Select features by absolute regression coefficient magnitude."""
        threshold = float(params.get("threshold", 1.0))

        if model is None:
            raise ValueError("coef_abs method requires a PLS model.")

        pls_model = self._extract_pls_model(model)

        # Extract coefficients
        from spectra_sherpa.app.lib.adapters.scp_extractors import _safe_getattr

        raw_coef = _safe_getattr(pls_model, ("coef", "coef_", "coefficients", "_coef"))
        if raw_coef is None:
            raise ValueError("Could not extract coefficients from PLS model")

        coef = np.asarray(raw_coef, dtype=np.float64).flatten()
        if len(coef) != n_features:
            # Some models store transposed
            if hasattr(raw_coef, "data"):
                coef = np.asarray(raw_coef.data, dtype=np.float64).flatten()
            if len(coef) != n_features:
                raise ValueError(f"Coefficient length ({len(coef)}) != n_features ({n_features})")

        abs_coef = np.abs(coef)
        # Normalise to max = 1 for interpretable threshold
        max_coef = abs_coef.max()
        if max_coef > 0:
            scores = abs_coef / max_coef
        else:
            scores = abs_coef

        mask = scores >= threshold
        return mask, scores

    def _select_selectivity_ratio(
        self,
        model: Any,
        X_array: np.ndarray,
        n_features: int,
        params: dict,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Select features by target-projection selectivity ratio.

        SR_j = var(t_TP * p_TP_j) / var(x_j - t_TP * p_TP_j)

        where t_TP and p_TP are the target-projected scores and loadings.
        """
        threshold = float(params.get("threshold", 1.0))

        if model is None:
            raise ValueError("selectivity_ratio method requires a PLS model.")

        pls_model = self._extract_pls_model(model)

        from spectra_sherpa.app.lib.adapters.scp_extractors import _safe_getattr

        # Get PLS components
        raw_w = _safe_getattr(pls_model, ("x_weights", "_x_weights", "x_weights_"))
        raw_coef = _safe_getattr(pls_model, ("coef", "coef_", "coefficients", "_coef"))

        if raw_w is None or raw_coef is None:
            raise ValueError("Could not extract weights/coefficients for selectivity ratio")

        W = np.asarray(raw_w, dtype=np.float64)
        if hasattr(raw_w, "data"):
            W = np.asarray(raw_w.data, dtype=np.float64)
        b = np.asarray(raw_coef, dtype=np.float64).flatten()
        if hasattr(raw_coef, "data"):
            b = np.asarray(raw_coef.data, dtype=np.float64).flatten()

        # Target projection vector
        # q = W * b (target projection direction)
        if W.shape[0] != n_features:
            W = W.T  # ensure (n_features, n_components)
        if len(b) != n_features:
            b = b[:n_features]

        # Target-projected scores: t_TP = X @ b / (b'b)
        b_norm_sq = b @ b
        if b_norm_sq < 1e-12:
            return np.zeros(n_features, dtype=bool), np.zeros(n_features, dtype=np.float64)

        t_tp = X_array @ b / b_norm_sq  # (n_samples,)
        p_tp = b  # target projection loadings = b (normalised)

        # Explained and residual variance per feature
        X_explained = np.outer(t_tp, p_tp)  # (n_samples, n_features)
        X_residual = X_array - X_explained

        var_explained = np.var(X_explained, axis=0)
        var_residual = np.var(X_residual, axis=0)

        # Selectivity ratio
        sr = np.zeros(n_features, dtype=np.float64)
        nonzero = var_residual > 1e-12
        sr[nonzero] = var_explained[nonzero] / var_residual[nonzero]

        mask = sr >= threshold
        return mask, sr

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _extract_pls_model(model_input: Any) -> Any:
        """Extract the underlying PLS model object from various input formats."""
        if isinstance(model_input, dict):
            # From PLS node output: dict with 'model' key
            if "model" in model_input:
                return model_input["model"]
            # From PLS-DA: may have 'pls_model'
            if "pls_model" in model_input:
                return model_input["pls_model"]
        # Direct model object
        return model_input
