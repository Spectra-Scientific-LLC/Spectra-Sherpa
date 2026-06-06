"""
MCR-ALS decomposition node.
"""

from __future__ import annotations

import logging
from itertools import combinations, permutations
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import (
    add_processing_step,
    copy_processing_history,
    inherit_origin_flags,
    inherit_sample_flags,
)

from ...io_contracts import (
    bind_X,
    to_numpy_2d,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    register_node,
)
from .core_utils import (
    create_spectral_dataset as _create_spectral_dataset,
)
from .core_utils import (
    ensure_orientation as _ensure_orientation,
)
from .core_utils import (
    is_sequential_numeric as _is_sequential_numeric,
)
from .core_utils import (
    make_safe_coord as _make_safe_coord,
)

logger = logging.getLogger(__name__)

from spectra_sherpa.app.lib.adapters.scp_extractors import MCRExtract
from spectra_sherpa.app.lib.scp_compat import scp, to_nddataset


def _safe_correlation(a: np.ndarray, b: np.ndarray) -> float | None:
    mask = np.isfinite(a) & np.isfinite(b)
    if int(mask.sum()) < 2:
        return None
    av = np.asarray(a[mask], dtype=np.float64)
    bv = np.asarray(b[mask], dtype=np.float64)
    if float(np.std(av)) == 0.0 or float(np.std(bv)) == 0.0:
        return None
    return float(np.corrcoef(av, bv)[0, 1])


def _affine_fit_metrics(recovered: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    mask = np.isfinite(recovered) & np.isfinite(target)
    if int(mask.sum()) < 2:
        return {
            "scale": None,
            "offset": None,
            "rmse": None,
            "normalized_rmse": None,
            "r2": None,
            "aligned": None,
            "n_valid": int(mask.sum()),
        }
    x = np.asarray(recovered[mask], dtype=np.float64)
    y = np.asarray(target[mask], dtype=np.float64)
    design = np.column_stack([x, np.ones_like(x)])
    scale, offset = np.linalg.lstsq(design, y, rcond=None)[0]
    aligned_all = scale * np.asarray(recovered, dtype=np.float64) + offset
    fitted = aligned_all[mask]
    rmse = float(np.sqrt(np.mean((fitted - y) ** 2)))
    span = float(np.max(y) - np.min(y))
    normalized_rmse = float(rmse / span) if span > 0 else None
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else None
    return {
        "scale": float(scale),
        "offset": float(offset),
        "rmse": rmse,
        "normalized_rmse": normalized_rmse,
        "r2": r2,
        "aligned": aligned_all,
        "n_valid": int(mask.sum()),
    }


def _sample_labels(input_ds: Any, n_samples: int) -> list[str]:
    try:
        axis = input_ds.get_observation_axis()
    except Exception:
        axis = getattr(input_ds, "sample_axis", None)
    if axis is not None:
        for attr in ("labels", "data"):
            try:
                raw = getattr(axis, attr, None)
                if raw is not None:
                    values = raw.tolist() if hasattr(raw, "tolist") else list(raw)
                    if len(values) >= n_samples:
                        return [str(value) for value in values[:n_samples]]
            except Exception:
                continue
    return [f"Sample {index + 1}" for index in range(n_samples)]


def _compare_mcr_to_target(
    C_data: np.ndarray,
    input_ds: Any,
    *,
    selected_target_index: int = 0,
    selected_component_index: int = 0,
    component_labels: list[str] | None = None,
) -> dict[str, Any] | None:
    target = getattr(input_ds, "target", None)
    if target is None:
        return None
    target_data = np.asarray(target, dtype=np.float64)
    if target_data.ndim == 1:
        target_data = target_data.reshape(-1, 1)
    if target_data.ndim != 2 or target_data.shape[0] != C_data.shape[0]:
        return None

    n_components = C_data.shape[1]
    n_targets = target_data.shape[1]
    if n_components == 0 or n_targets == 0:
        return None

    corr = np.zeros((n_components, n_targets), dtype=np.float64)
    for i in range(n_components):
        for j in range(n_targets):
            value = _safe_correlation(C_data[:, i], target_data[:, j])
            corr[i, j] = 0.0 if value is None or not np.isfinite(value) else value

    target_context = getattr(input_ds, "target_context", None)
    target_names = getattr(target_context, "target_names", None) or []
    target_units = getattr(target_context, "target_units", None)
    target_labels = [
        (
            str(target_names[index])
            if isinstance(target_names, list) and index < len(target_names)
            else f"Target {index + 1}"
        )
        for index in range(n_targets)
    ]
    recovered_labels = component_labels or [f"Component {index + 1}" for index in range(n_components)]
    candidate_pairs: list[dict[str, Any]] = []
    for recovered_idx in range(n_components):
        for target_idx in range(n_targets):
            metrics = _affine_fit_metrics(C_data[:, recovered_idx], target_data[:, target_idx])
            aligned = metrics.get("aligned")
            actual_vector = target_data[:, target_idx]
            predicted_vector = aligned if isinstance(aligned, np.ndarray) else np.full(C_data.shape[0], np.nan)
            candidate_pairs.append(
                {
                    "component_index": recovered_idx,
                    "component_name": recovered_labels[recovered_idx],
                    "target_index": target_idx,
                    "target_name": target_labels[target_idx],
                    "correlation": float(corr[recovered_idx, target_idx]),
                    "r2": metrics["r2"],
                    "rmse": metrics["rmse"],
                    "normalized_rmse": metrics["normalized_rmse"],
                    "scale": metrics["scale"],
                    "offset": metrics["offset"],
                    "n_valid": metrics["n_valid"],
                    "actual": [
                        float(value) if np.isfinite(value) else None
                        for value in np.asarray(actual_vector, dtype=np.float64)
                    ],
                    "predicted": [
                        float(value) if np.isfinite(value) else None
                        for value in np.asarray(predicted_vector, dtype=np.float64)
                    ],
                }
            )

    # Suggested matches are advisory only.  The emitted validation rows below
    # use the user's selected target/component pair; chemometric component
    # assignment remains a user decision because MCR order, scale, and missing
    # components are inherently ambiguous.
    n_match = min(n_components, n_targets)
    if n_components <= 8 and n_targets <= 8:
        best_pairs: list[tuple[int, int]] | None = None
        best_score = -1.0
        for recovered_indices in combinations(range(n_components), n_match):
            for target_indices in permutations(range(n_targets), n_match):
                pairs = list(zip(recovered_indices, target_indices, strict=True))
                score = float(sum(abs(corr[recovered_idx, target_idx]) for recovered_idx, target_idx in pairs))
                if score > best_score:
                    best_pairs = pairs
                    best_score = score
        assignment = sorted(best_pairs or list(zip(range(n_match), range(n_match), strict=True)))
    else:
        remaining_components = set(range(n_components))
        remaining_targets = set(range(n_targets))
        assignment = []
        for _ in range(n_match):
            recovered_idx, target_idx = max(
                (
                    (component_idx, target_idx)
                    for component_idx in remaining_components
                    for target_idx in remaining_targets
                ),
                key=lambda pair: abs(corr[pair[0], pair[1]]),
            )
            assignment.append((recovered_idx, target_idx))
            remaining_components.remove(recovered_idx)
            remaining_targets.remove(target_idx)

    suggested_matches: list[dict[str, Any]] = []
    for recovered_idx, target_idx in assignment:
        target_name = (
            str(target_names[target_idx])
            if isinstance(target_names, list) and target_idx < len(target_names)
            else f"Target {target_idx + 1}"
        )
        metrics = _affine_fit_metrics(C_data[:, recovered_idx], target_data[:, target_idx])
        suggested_matches.append(
            {
                "component_index": recovered_idx,
                "component_name": recovered_labels[recovered_idx],
                "target_index": target_idx,
                "target_name": target_name,
                "correlation": float(corr[recovered_idx, target_idx]),
                "r2": metrics["r2"],
                "rmse": metrics["rmse"],
                "normalized_rmse": metrics["normalized_rmse"],
                "scale": metrics["scale"],
                "offset": metrics["offset"],
                "n_valid": metrics["n_valid"],
            }
        )

    if not 0 <= selected_target_index < n_targets:
        raise ValueError(
            f"Ground truth target index {selected_target_index + 1} is out of range for {n_targets} target(s)."
        )
    if not 0 <= selected_component_index < n_components:
        raise ValueError(
            f"Recovered component index {selected_component_index + 1} is out of range for {n_components} component(s)."
        )

    selected_metrics = _affine_fit_metrics(C_data[:, selected_component_index], target_data[:, selected_target_index])
    aligned = selected_metrics.pop("aligned")
    sample_labels = _sample_labels(input_ds, C_data.shape[0])
    target_vector = target_data[:, selected_target_index]
    recovered_vector = C_data[:, selected_component_index]
    rows: list[dict[str, Any]] = []
    actual: list[float] = []
    predicted: list[float] = []
    if isinstance(aligned, np.ndarray):
        for sample_idx, (target_value, recovered_value, inferred_value) in enumerate(
            zip(target_vector, recovered_vector, aligned, strict=True)
        ):
            if not (np.isfinite(target_value) and np.isfinite(inferred_value)):
                continue
            actual_value = float(target_value)
            predicted_value = float(inferred_value)
            actual.append(actual_value)
            predicted.append(predicted_value)
            rows.append(
                {
                    "sample_index": sample_idx,
                    "sample_label": sample_labels[sample_idx],
                    "target_component": target_labels[selected_target_index],
                    "recovered_component": recovered_labels[selected_component_index],
                    "target": actual_value,
                    "inferred": predicted_value,
                    "raw_recovered": float(recovered_value) if np.isfinite(recovered_value) else None,
                    "residual": float(predicted_value - actual_value),
                }
            )

    valid_correlations = [abs(item["correlation"]) for item in suggested_matches if np.isfinite(item["correlation"])]
    valid_rmse = [
        item["normalized_rmse"]
        for item in suggested_matches
        if item.get("normalized_rmse") is not None and np.isfinite(item["normalized_rmse"])
    ]
    return {
        "source": "target",
        "type": "predicted_vs_actual",
        "task_type": "mcr_ground_truth",
        "data": rows,
        "series": [
            {
                "name": target_labels[selected_target_index],
                "actual": actual,
                "predicted": predicted,
                "target_index": selected_target_index,
                "recovered_component_index": selected_component_index,
                "recovered_component": recovered_labels[selected_component_index],
            }
        ],
        "metrics": {
            "target": target_labels[selected_target_index],
            "recovered_component": recovered_labels[selected_component_index],
            "R2": selected_metrics["r2"],
            "RMSE": selected_metrics["rmse"],
            "normalized_RMSE": selected_metrics["normalized_rmse"],
            "correlation": float(corr[selected_component_index, selected_target_index]),
            "scale": selected_metrics["scale"],
            "offset": selected_metrics["offset"],
            "n_valid": selected_metrics["n_valid"],
        },
        "metadata": {
            "type": "MCRGroundTruthComparison",
            "target_units": target_units,
            "target_names": target_labels,
            "component_names": recovered_labels,
            "selected_target_index": selected_target_index,
            "selected_component_index": selected_component_index,
            "inferred_values": "affine_aligned_recovered_C",
            "sample_labels": sample_labels,
            "candidate_pairs": candidate_pairs,
            "suggested_matches": suggested_matches,
        },
        "target_units": target_units,
        "n_recovered_components": int(n_components),
        "n_target_components": int(n_targets),
        "matched_components": suggested_matches,
        "selected_match": {
            "target_index": selected_target_index,
            "target_name": target_labels[selected_target_index],
            "component_index": selected_component_index,
            "component_name": recovered_labels[selected_component_index],
            **selected_metrics,
            "correlation": float(corr[selected_component_index, selected_target_index]),
        },
        "mean_abs_correlation": float(np.mean(valid_correlations)) if valid_correlations else None,
        "mean_normalized_rmse": float(np.mean(valid_rmse)) if valid_rmse else None,
    }


def _ground_truth_spectra(input_ds: Any) -> tuple[np.ndarray, list[str], Any, Any, Any, Any] | None:
    extra = getattr(input_ds, "extra", None)
    if not isinstance(extra, dict):
        return None
    raw_spectra = extra.get("ground_truth.spectra")
    if raw_spectra is None:
        return None
    spectra = np.asarray(raw_spectra, dtype=np.float64)
    if spectra.ndim != 2 or spectra.size == 0:
        return None
    raw_names = extra.get("ground_truth.spectra_names")
    if isinstance(raw_names, list) and raw_names:
        names = [str(name) for name in raw_names]
    else:
        names = [f"Ground truth spectrum {index + 1}" for index in range(spectra.shape[0])]
    return (
        spectra,
        names,
        extra.get("ground_truth.spectra_units"),
        extra.get("ground_truth.spectra_x"),
        extra.get("ground_truth.spectra_x_title"),
        extra.get("ground_truth.spectra_x_units"),
    )


def _compare_mcr_spectra_to_truth(
    St_data: np.ndarray,
    input_ds: Any,
    *,
    selected_target_index: int = 0,
    selected_component_index: int = 0,
    component_labels: list[str] | None = None,
) -> dict[str, Any] | None:
    truth = _ground_truth_spectra(input_ds)
    if truth is None:
        return None
    truth_spectra, truth_labels, truth_units, truth_x, truth_x_title, truth_x_units = truth
    if truth_spectra.shape[1] != St_data.shape[1]:
        logger.debug(
            "Skipping MCR St-vs-S comparison: St has %s features but ground truth S has %s.",
            St_data.shape[1],
            truth_spectra.shape[1],
        )
        return None

    n_components = St_data.shape[0]
    n_truth = truth_spectra.shape[0]
    if n_components == 0 or n_truth == 0:
        return None

    recovered_labels = component_labels or [f"Component {index + 1}" for index in range(n_components)]
    corr = np.zeros((n_components, n_truth), dtype=np.float64)
    candidate_pairs: list[dict[str, Any]] = []
    for recovered_idx in range(n_components):
        for truth_idx in range(n_truth):
            value = _safe_correlation(St_data[recovered_idx], truth_spectra[truth_idx])
            corr[recovered_idx, truth_idx] = 0.0 if value is None or not np.isfinite(value) else value
            metrics = _affine_fit_metrics(St_data[recovered_idx], truth_spectra[truth_idx])
            candidate_pairs.append(
                {
                    "component_index": recovered_idx,
                    "component_name": recovered_labels[recovered_idx],
                    "truth_index": truth_idx,
                    "truth_name": truth_labels[truth_idx],
                    "correlation": float(corr[recovered_idx, truth_idx]),
                    "r2": metrics["r2"],
                    "rmse": metrics["rmse"],
                    "normalized_rmse": metrics["normalized_rmse"],
                    "scale": metrics["scale"],
                    "offset": metrics["offset"],
                    "n_valid": metrics["n_valid"],
                }
            )

    n_match = min(n_components, n_truth)
    if n_components <= 8 and n_truth <= 8:
        best_pairs: list[tuple[int, int]] | None = None
        best_score = -1.0
        for recovered_indices in combinations(range(n_components), n_match):
            for truth_indices in permutations(range(n_truth), n_match):
                pairs = list(zip(recovered_indices, truth_indices, strict=True))
                score = float(sum(abs(corr[recovered_idx, truth_idx]) for recovered_idx, truth_idx in pairs))
                if score > best_score:
                    best_pairs = pairs
                    best_score = score
        assignment = sorted(best_pairs or list(zip(range(n_match), range(n_match), strict=True)))
    else:
        remaining_components = set(range(n_components))
        remaining_truth = set(range(n_truth))
        assignment = []
        for _ in range(n_match):
            recovered_idx, truth_idx = max(
                ((component_idx, truth_idx) for component_idx in remaining_components for truth_idx in remaining_truth),
                key=lambda pair: abs(corr[pair[0], pair[1]]),
            )
            assignment.append((recovered_idx, truth_idx))
            remaining_components.remove(recovered_idx)
            remaining_truth.remove(truth_idx)

    suggested_matches: list[dict[str, Any]] = []
    for recovered_idx, truth_idx in assignment:
        metrics = _affine_fit_metrics(St_data[recovered_idx], truth_spectra[truth_idx])
        suggested_matches.append(
            {
                "component_index": recovered_idx,
                "component_name": recovered_labels[recovered_idx],
                "truth_index": truth_idx,
                "truth_name": truth_labels[truth_idx],
                "correlation": float(corr[recovered_idx, truth_idx]),
                "r2": metrics["r2"],
                "rmse": metrics["rmse"],
                "normalized_rmse": metrics["normalized_rmse"],
                "scale": metrics["scale"],
                "offset": metrics["offset"],
                "n_valid": metrics["n_valid"],
            }
        )

    selected_match = None
    if 0 <= selected_component_index < n_components and 0 <= selected_target_index < n_truth:
        selected_metrics = _affine_fit_metrics(St_data[selected_component_index], truth_spectra[selected_target_index])
        selected_match = {
            "truth_index": selected_target_index,
            "truth_name": truth_labels[selected_target_index],
            "component_index": selected_component_index,
            "component_name": recovered_labels[selected_component_index],
            "correlation": float(corr[selected_component_index, selected_target_index]),
            "r2": selected_metrics["r2"],
            "rmse": selected_metrics["rmse"],
            "normalized_rmse": selected_metrics["normalized_rmse"],
            "scale": selected_metrics["scale"],
            "offset": selected_metrics["offset"],
            "n_valid": selected_metrics["n_valid"],
        }

    valid_correlations = [abs(item["correlation"]) for item in suggested_matches if np.isfinite(item["correlation"])]
    valid_rmse = [
        item["normalized_rmse"]
        for item in suggested_matches
        if item.get("normalized_rmse") is not None and np.isfinite(item["normalized_rmse"])
    ]
    return {
        "type": "mcr_pure_spectra_ground_truth",
        "truth_units": truth_units,
        "truth_names": truth_labels,
        "truth_spectra": truth_spectra.tolist(),
        "truth_spectra_x": truth_x,
        "truth_spectra_x_title": truth_x_title,
        "truth_spectra_x_units": truth_x_units,
        "component_names": recovered_labels,
        "candidate_pairs": candidate_pairs,
        "suggested_matches": suggested_matches,
        "selected_match": selected_match,
        "mean_abs_correlation": float(np.mean(valid_correlations)) if valid_correlations else None,
        "mean_normalized_rmse": float(np.mean(valid_rmse)) if valid_rmse else None,
    }


@register_node
class MCRNode(Node):
    """
    Multivariate Curve Resolution - Alternating Least Squares (MCR-ALS) node.

    Performs MCR-ALS decomposition on spectral data to resolve mixtures
    into pure component spectra and concentration profiles.

    Uses SpectroChemPy's MCRALS implementation.
    """

    metadata = NodeMetadata(
        node_type="model.mcr_als",
        category="exploratory",
        label="Fit MCR-ALS Decomposition",
        description="Fit a Multivariate Curve Resolution model for mixture analysis",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=2,
                step=1,
                description="Number of pure components to resolve",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="non_negative_C",
                label="Non-negative Concentrations",
                param_type="boolean",
                default=True,
                description="Enforce non-negative concentration profiles",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="non_negative_St",
                label="Non-negative Spectra",
                param_type="boolean",
                default=True,
                description="Enforce non-negative spectra",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="max_iter",
                label="Maximum Iterations",
                param_type="number",
                default=200,
                min_value=10,
                step=10,
                description=(
                    "Maximum ALS iterations. Raised from 50 → 200 in v0.4.3 to give the "
                    "tighter default tolerance (1e-5) room to converge on typical spectra."
                ),
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=1e-5,
                min_value=1e-8,
                step=1e-6,
                description=(
                    "Relative change in St between successive ALS iterations at which the solver "
                    "stops. Lowered from 0.1 → 1e-5 in v0.4.3 to match mdatools / pyMCR convention; "
                    "values >1e-3 emit a 'loose-tolerance' warning. References: Tauler et al. "
                    "(Chemom. Intell. Lab. Syst. 1995); pyMCR uses 1e-5, mdatools `mcrals()` uses 1e-6."
                ),
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="normSpec",
                label="Spectra Normalization",
                param_type="select",
                default="euclid",
                options=[
                    {"label": "Euclidean norm", "value": "euclid"},
                    {"label": "Maximum intensity", "value": "max"},
                    {"label": "None", "value": "none"},
                ],
                description=(
                    "Normalize resolved pure spectra during MCR-ALS. Euclidean normalization "
                    "stabilizes the concentration/spectrum scale ambiguity for shape comparison."
                ),
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="validation_target_index",
                label="Validation Target",
                param_type="number",
                default=1,
                min_value=1,
                step=1,
                description=(
                    "1-based ground-truth concentration column to compare. "
                    "Only this user-selected target is emitted to ValidationResult."
                ),
                required=False,
                category="validation",
            ),
            NodeParameter(
                name="validation_component_index",
                label="Validation MCR Component",
                param_type="number",
                default=1,
                min_value=1,
                step=1,
                description=(
                    "1-based recovered MCR concentration profile to compare against the selected target. "
                    "MCR component matching is intentionally user-controlled."
                ),
                required=False,
                category="validation",
            ),
        ],
        input_types=["NDDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="Fitted MCR-ALS Decomposition",
                description="Fitted MCR-ALS model object",
            ),
            PortMetadata(
                name="C",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Concentrations",
                description="Resolved concentration profiles (C) with sample/component axes",
            ),
            PortMetadata(
                name="St",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Pure Spectra",
                description="Resolved pure component spectra (S^T)",
            ),
            PortMetadata(
                name="residuals",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=False,
                label="Residuals",
                description="Modeling residuals",
            ),
            PortMetadata(
                name="ground_truth_comparison",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=False,
                label="Ground Truth Comparison",
                description="Optional recovered-vs-target concentration matching metrics",
            ),
        ],
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.MCRALS.html",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for MCR-ALS decomposition."""
        if not use_scp:
            return [
                f"{indent}# --- MCR-ALS ({self.node_id}) ---",
                f"{indent}# MCR-ALS requires SpectroChemPy (pip install spectra-sherpa[scp])",
                f"{indent}raise ImportError('MCR-ALS requires spectrochempy')",
            ]

        params = self._resolve_params()
        n_components = params.get("n_components", 3)
        nn_C = "True" if params.get("non_negative_C", True) else "False"
        nn_St = "True" if params.get("non_negative_St", True) else "False"
        max_iter = params.get("max_iter", 200)
        tol = params.get("tol", 1e-5)
        norm_spec = params.get("normSpec", params.get("norm_spec", "euclid"))
        norm_spec_expr = "None" if norm_spec in (None, "", "none") else repr(norm_spec)

        X_expr = inputs.get("default", inputs.get("X", "input_data"))

        lines: list[str] = []
        lines.append(f"{indent}# --- MCR-ALS ({self.node_id}) ---")
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")
        lines.append(f"{indent}_X_ndd = scp.NDDataset(_X_data)")
        lines.append(f"{indent}# Initialize C from SVD")
        lines.append(f"{indent}_U, _S, _Vt = np.linalg.svd(_X_data, full_matrices=False)")
        lines.append(f"{indent}_C0 = np.abs(_U[:, :{n_components}] * _S[:{n_components}])")
        lines.append(f"{indent}_C0_ndd = scp.NDDataset(_C0)")
        lines.append(f"{indent}_mcr = scp.MCRALS(")
        lines.append(f"{indent}    _X_ndd, _C0_ndd,")
        lines.append(f"{indent}    nonnegConc=list(range({n_components})) if {nn_C} else [],")
        lines.append(f"{indent}    nonnegSpec=list(range({n_components})) if {nn_St} else [],")
        lines.append(f"{indent}    maxdiv={max_iter}, tol={tol},")
        lines.append(f"{indent}    normSpec={norm_spec_expr},")
        lines.append(f"{indent})")
        lines.append(f"{indent}_C = np.asarray(_mcr.C.data, dtype=np.float64)")
        lines.append(f"{indent}_St = np.asarray(_mcr.St.data, dtype=np.float64)")
        lines.append(f'{indent}print(f"  MCR-ALS ({n_components} components): C={{_C.shape}}, St={{_St.shape}}")')
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'model': _mcr,")
        lines.append(f"{indent}    'C': _C,")
        lines.append(f"{indent}    'St': _St,")
        lines.append(f"{indent}    'residuals': _C @ _St - _X_data,")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute MCR-ALS decomposition on input dataset.

        Args:
            input_data: Dataset containing spectral mixture data (D matrix)
                       Shape should be (n_samples, n_wavenumbers)

        Returns:
            Dict containing:
            - model: The MCRALS model object
            - C: Concentration profiles (n_samples, n_components) as SpectralResult
            - St: Pure spectra (n_components, n_wavenumbers) as SpectralResult
            - n_components: Number of resolved components
        """
        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (spectral mixtures)",
            dataset_error_message="input_data must be an dataset object",
            allow_array=False,
        )
        input_ndd = to_nddataset(input_ds)

        # Get parameters
        n_components = self.parameters.get("n_components", 3)
        max_iter = self.parameters.get("max_iter", 200)
        tol = self.parameters.get("tol", 1e-5)
        non_negative_C = self.parameters.get("non_negative_C", True)
        non_negative_St = self.parameters.get("non_negative_St", True)
        norm_spec = self.parameters.get("normSpec", self.parameters.get("norm_spec", "euclid"))
        if norm_spec in (None, "", "none"):
            norm_spec = None
        elif norm_spec not in {"euclid", "max"}:
            raise ValueError("normSpec must be one of: euclid, max, none")
        validation_target_index = int(self.parameters.get("validation_target_index", 1)) - 1
        validation_component_index = int(self.parameters.get("validation_component_index", 1)) - 1

        # Surface loose tolerances: the SCP/legacy default of 0.1 silently
        # produces under-converged solutions for serious work. mdatools
        # uses 1e-6 and pyMCR uses 1e-5 — anything looser than 1e-3 is a
        # numerical-correctness red flag worth flagging to the user.
        if tol > 1e-3:
            logger.warning(
                "[MCR-ALS Node] tol=%.4g is loose; chemometric convention is ≤1e-3 "
                "(mdatools 1e-6, pyMCR 1e-5). Results may be under-converged.",
                tol,
            )

        # Validate input shape
        if len(input_ds.shape) != 2:
            raise ValueError(f"Expected 2D input, got shape {input_ds.shape}")

        n_samples, n_features = input_ds.shape
        if n_components > min(n_samples, n_features):
            raise ValueError(
                f"n_components ({n_components}) cannot exceed min(n_samples, n_features) = {min(n_samples, n_features)}"
            )

        # Create initial guess for C using SVD
        # This provides a good starting point for ALS
        from numpy.linalg import svd

        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        U, S, Vt = svd(data, full_matrices=False)

        # Initial C estimate from first n_components of U*S.
        # Always take abs() for initialization regardless of the ALS non-negativity
        # setting: SVD left-singular vectors have arbitrary sign convention and the
        # leading column is frequently all-negative for non-negative data. SCP's
        # _guess_profile derives St0 from this C0 using NNLS when solverSpec="nnls"
        # (the default), and NNLS on an all-negative regressor returns exactly zero,
        # killing Component 0 before any ALS iteration runs. Applying abs() here is
        # initialization-only — the ALS solver constraints (solverConc/solverSpec)
        # govern non-negativity during the actual alternating least-squares loop.
        C0_data = np.abs(U[:, :n_components] @ np.diag(S[:n_components]))
        C0 = scp.NDDataset(C0_data)

        # Determine appropriate solvers based on constraints
        solver_c = "nnls" if non_negative_C else "lstsq"
        solver_s = "nnls" if non_negative_St else "lstsq"

        # Create and fit MCR-ALS model
        mcr = scp.MCRALS(max_iter=max_iter, tol=tol, solverConc=solver_c, solverSpec=solver_s, normSpec=norm_spec)
        mcr.fit(input_ndd, C0)

        # Extract results using typed extractor
        extracted = MCRExtract.from_scp(mcr)
        C_data = _ensure_orientation(
            extracted.C,
            expected_rows=n_samples,
            expected_cols=n_components,
            name="MCR.C",
        )
        St_data = _ensure_orientation(
            extracted.St,
            expected_rows=n_components,
            expected_cols=n_features,
            name="MCR.St",
        )
        effective_norm_spec = norm_spec or "none"
        st_scale_factors = np.ones(n_components, dtype=np.float64)
        if effective_norm_spec == "euclid":
            st_scale_factors = np.linalg.norm(St_data, axis=1)
        elif effective_norm_spec == "max":
            st_scale_factors = np.nanmax(np.abs(St_data), axis=1)
        if effective_norm_spec in {"euclid", "max"}:
            st_scale_factors = np.where(
                np.isfinite(st_scale_factors) & (st_scale_factors > 1e-12), st_scale_factors, 1.0
            )
            # Preserve the reconstruction exactly while fixing the MCR scale
            # ambiguity: D = C @ St = (C * scale) @ (St / scale).
            C_data = C_data * st_scale_factors.reshape(1, -1)
            St_data = St_data / st_scale_factors.reshape(-1, 1)

        if effective_norm_spec == "euclid":
            st_units = "euclidean-normalized response"
            st_normalization_label = "Euclidean norm"
        elif effective_norm_spec == "max":
            st_units = "peak-normalized response"
            st_normalization_label = "Maximum intensity"
        else:
            st_units = input_ds.units if hasattr(input_ds, "units") else None
            st_normalization_label = "None"

        # Get input coordinates for SherpaDataset creation
        # Use generic accessors to support all axis types (TimeAxis, SampleAxis, etc.)
        _x_coord = input_ds.get_feature_axis()
        _y_coord = input_ds.get_observation_axis()

        # Extract label_categories for categorical coloring
        label_categories = None
        if _y_coord is not None:
            try:
                if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, "tolist") else list(_y_coord.labels)
                    label_categories = sorted(set(str(l) for l in raw))
                elif hasattr(_y_coord, "data") and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, "tolist") else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # Try to extract species names from input metadata (from BlendNode ground truth)
        species_names = None
        if hasattr(input_ds, "meta") and input_ds.meta:
            spectra_meta = input_ds.meta.get("spectra", {})
            if isinstance(spectra_meta, dict):
                species_list = spectra_meta.get("species", [])
                if species_list and len(species_list) >= n_components:
                    try:
                        names: list[str] = []
                        for spec in species_list[:n_components]:
                            if isinstance(spec, dict):
                                names.append(spec.get("name", f"Species {len(names)+1}"))
                            elif hasattr(spec, "name"):
                                names.append(spec.name)
                            else:
                                names.append(f"Species {len(names)+1}")
                        species_names = names
                        logger.debug("[MCR-ALS Node] Extracted species names from input metadata: %s", species_names)
                    except Exception as e:
                        logger.warning("[MCR-ALS Node] Could not extract species names: %s", e, exc_info=True)

        # Use species names if available, otherwise use generic labels
        component_labels = species_names or [f"Component {i+1}" for i in range(n_components)]
        spectrum_labels = species_names or [f"Pure Spectrum {i+1}" for i in range(n_components)]
        ground_truth_comparison = _compare_mcr_to_target(
            C_data,
            input_ds,
            selected_target_index=validation_target_index,
            selected_component_index=validation_component_index,
            component_labels=component_labels,
        )
        spectra_recovery_comparison = _compare_mcr_spectra_to_truth(
            St_data,
            input_ds,
            selected_target_index=validation_target_index,
            selected_component_index=validation_component_index,
            component_labels=component_labels,
        )
        if ground_truth_comparison is not None and spectra_recovery_comparison is not None:
            ground_truth_comparison["spectra_recovery"] = spectra_recovery_comparison
            metadata = ground_truth_comparison.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata["spectra_recovery"] = spectra_recovery_comparison

        # =====================================================================
        # Create SherpaDataset objects for St and C with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        # St (Pure Spectra): shape (n_components, n_features)
        # X-axis = wavenumbers from input, Y-axis = component labels
        St_dataset = _create_spectral_dataset(
            data=St_data,
            x_coord=_x_coord,
            y_coord=_make_safe_coord(spectrum_labels, title="Component"),
            units=st_units,
            title="MCR-ALS Pure Component Spectra",
        )

        # C (Concentrations): shape (n_samples, n_components)
        # X-axis = component labels, Y-axis = sample labels/time
        C_dataset = _create_spectral_dataset(
            data=C_data,
            x_coord=_make_safe_coord(component_labels, title="Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="relative concentration",
            title="MCR-ALS Concentration Profiles",
        )

        # Compute residuals as SherpaDataset
        reconstructed = C_data @ St_data
        residuals_data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64) - reconstructed
        residuals_dataset = _create_spectral_dataset(
            data=residuals_data,
            x_coord=_x_coord,
            y_coord=_y_coord,  # Preserve sample labels from input
            units=input_ds.units if hasattr(input_ds, "units") else None,
            title="MCR-ALS Residuals",
        )

        # Add processing history to SherpaDataset outputs
        copy_processing_history(input_ds, C_dataset)
        add_processing_step(
            C_dataset,
            "model.mcr_als.concentrations",
            {"n_components": n_components, "normSpec": norm_spec},
            node_id=self.node_id,
        )

        copy_processing_history(input_ds, St_dataset)
        add_processing_step(
            St_dataset,
            "model.mcr_als.spectra",
            {"n_components": n_components, "normSpec": norm_spec},
            node_id=self.node_id,
        )

        copy_processing_history(input_ds, residuals_dataset)
        add_processing_step(
            residuals_dataset,
            "model.mcr_als.residuals",
            {"n_components": n_components, "normSpec": norm_spec},
            node_id=self.node_id,
        )

        # Propagate dataset-level flags. C (concentrations) and residuals are
        # sample-axis-preserved; St (pure spectra) rows are components.
        # Origin tags survive on every output.
        inherit_sample_flags(input_ds, C_dataset)
        inherit_origin_flags(input_ds, C_dataset)
        inherit_sample_flags(input_ds, residuals_dataset)
        inherit_origin_flags(input_ds, residuals_dataset)
        inherit_origin_flags(input_ds, St_dataset)

        # Store scientific metadata + embed St/wavenumber data for detailed view plots
        wavenumbers = None
        x_title = None
        x_units = None
        if _x_coord is not None:
            try:
                wavenumbers = np.array(_x_coord.data).tolist()
            except Exception:
                pass
            x_title = getattr(_x_coord, "title", None)
            x_units = str(_x_coord.units) if getattr(_x_coord, "units", None) else None
        if ground_truth_comparison is not None and 0 <= validation_component_index < St_data.shape[0]:
            selected_spectrum = np.asarray(St_data[validation_component_index], dtype=np.float64)
            max_abs = float(np.nanmax(np.abs(selected_spectrum))) if selected_spectrum.size else 0.0
            normalized_spectrum = selected_spectrum / max_abs if max_abs > 0 else selected_spectrum
            metadata = ground_truth_comparison.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata["selected_component_spectrum"] = normalized_spectrum.tolist()
                metadata["selected_component_spectrum_x"] = wavenumbers
                metadata["selected_component_spectrum_x_title"] = x_title
                metadata["selected_component_spectrum_x_units"] = x_units
                metadata["selected_component_spectrum_normalization"] = "max_abs"

        # NOTE: Keys "wavenumbers", "x_title", "x_units" are OVERWRITTEN by
        # _serialize_sherpa_dataset() with C_dataset's own feature axis (component
        # indices).  Use "spectral_" prefix so the original input wavenumbers
        # survive serialization and are available for St plots.
        C_dataset.meta.update(
            {
                "type": "MCR_ALS",
                "n_components": n_components,
                "normSpec": effective_norm_spec,
                "spectra_normalization": effective_norm_spec,
                "spectra_normalization_label": st_normalization_label,
                "spectra_scale_factors": st_scale_factors.tolist(),
                "mcr_spectra_y_units": st_units,
                "label_categories": label_categories,
                "species_names": species_names,
                "labels": component_labels,
                "St": St_data.tolist(),
                "St_labels": spectrum_labels,
                "spectral_wavenumbers": wavenumbers,
                "spectral_x_title": x_title,
                "spectral_x_units": x_units,
            }
        )
        St_dataset.meta.update(
            {
                "type": "MCR_ALS_St",
                "n_components": n_components,
                "normSpec": effective_norm_spec,
                "spectra_normalization": effective_norm_spec,
                "spectra_normalization_label": st_normalization_label,
                "spectra_scale_factors": st_scale_factors.tolist(),
                "mcr_spectra_y_units": st_units,
            }
        )
        if ground_truth_comparison is not None:
            C_dataset.meta["ground_truth_comparison"] = ground_truth_comparison

        # Build model artifact for persistence
        from ._artifact_builder import build_model_artifact

        artifact = build_model_artifact(
            extracted,
            input_ds,
            node_id=self.node_id,
        )

        # Compute diagnostics scalars for Sherpa advisor
        diagnostics: dict[str, Any] = {"n_components": int(n_components)}
        diagnostics["normSpec"] = norm_spec
        try:
            residual_rms = float(np.sqrt(np.mean(residuals_data**2)))
            diagnostics["residual_rms"] = residual_rms
            input_ss = float(np.sum(data**2))
            if input_ss > 0:
                lof_percent = float(100.0 * np.sqrt(np.sum(residuals_data**2) / input_ss))
                diagnostics["lof_percent"] = lof_percent
                diagnostics["lof_definition"] = "100 * sqrt(sum(residual^2) / sum(X^2))"
        except Exception:
            logger.debug("[MCR-ALS Node] Failed to compute residual diagnostics", exc_info=True)
        for attr, key in (("n_iter", "n_iter"), ("n_iter_", "n_iter")):
            if hasattr(mcr, attr):
                try:
                    diagnostics[key] = int(getattr(mcr, attr))
                    break
                except Exception:
                    pass
        for attr in ("converged", "converged_"):
            if hasattr(mcr, attr):
                try:
                    diagnostics["converged"] = bool(getattr(mcr, attr))
                    break
                except Exception:
                    pass

        quality_summary: dict = {
            "n_components": int(n_components),
            "method": "MCR-ALS",
            "normSpec": norm_spec,
        }
        if "n_iter" in diagnostics:
            quality_summary["n_iter"] = int(diagnostics["n_iter"])
        if "lof_percent" in diagnostics:
            quality_summary["lof_percent"] = float(diagnostics["lof_percent"])
        if "residual_rms" in diagnostics:
            quality_summary["residual_rms"] = float(diagnostics["residual_rms"])
        if ground_truth_comparison is not None:
            quality_summary["ground_truth_mean_abs_correlation"] = ground_truth_comparison.get("mean_abs_correlation")
            quality_summary["ground_truth_mean_normalized_rmse"] = ground_truth_comparison.get("mean_normalized_rmse")
            selected_metrics = ground_truth_comparison.get("metrics") or {}
            quality_summary["ground_truth_selected_r2"] = selected_metrics.get("R2")
            quality_summary["ground_truth_selected_rmse"] = selected_metrics.get("RMSE")
            diagnostics["ground_truth_comparison"] = ground_truth_comparison
        if spectra_recovery_comparison is not None:
            quality_summary["ground_truth_spectra_mean_abs_correlation"] = spectra_recovery_comparison.get(
                "mean_abs_correlation"
            )
            quality_summary["ground_truth_spectra_mean_normalized_rmse"] = spectra_recovery_comparison.get(
                "mean_normalized_rmse"
            )
            diagnostics["ground_truth_spectra_recovery"] = spectra_recovery_comparison
        C_dataset.meta.update({"quality_summary": quality_summary})

        return NodeResult(
            outputs={
                "default": C_dataset,  # SherpaDataset: concentration profiles (n_samples, n_components)
                "C": C_dataset,  # Alias for concentrations
                "St": St_dataset,  # SherpaDataset: pure spectra (n_components, n_features)
                "residuals": residuals_dataset,  # SherpaDataset: residuals (n_samples, n_features)
                "model": mcr,  # Model port
                "_model_artifact": artifact,
                "ground_truth_comparison": ground_truth_comparison,
            },
            diagnostics=diagnostics,
        )
