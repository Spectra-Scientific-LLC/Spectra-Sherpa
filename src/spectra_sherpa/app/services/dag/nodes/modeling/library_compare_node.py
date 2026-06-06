"""Compare sample spectra against selected library spectra."""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from scipy.interpolate import PchipInterpolator

from spectra_sherpa.app.services.dag.io_contracts import bind_X, to_numpy_2d

from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node


def _axis_values(dataset: Any) -> np.ndarray | None:
    axis = getattr(dataset, "feature_axis", None)
    values = getattr(axis, "values", None) if axis is not None else None
    if values is not None:
        return np.asarray(values, dtype=float)
    x = getattr(dataset, "x", None)
    data = getattr(x, "data", None) if x is not None else None
    return np.asarray(data, dtype=float) if data is not None else None


def _axis_label(dataset: Any) -> str:
    axis = getattr(dataset, "feature_axis", None)
    title = getattr(axis, "title", None) if axis is not None else None
    units = getattr(axis, "units", None) if axis is not None else None
    if title and units:
        return f"{title} ({units})"
    return str(title or "Feature")


def _xaxis_layout(dataset: Any) -> dict[str, Any]:
    axis = getattr(dataset, "feature_axis", None)
    title = str(getattr(axis, "title", "") or "").lower() if axis is not None else ""
    units = str(getattr(axis, "units", "") or "").lower() if axis is not None else ""
    layout: dict[str, Any] = {"title": _axis_label(dataset)}
    if "wavenumber" in title or "raman shift" in title or "cm" in units:
        layout["autorange"] = "reversed"
    return layout


def _sample_labels(dataset: Any, prefix: str) -> list[str]:
    n_samples = int(getattr(dataset, "n_samples", np.asarray(dataset.data).shape[0]))
    axis = getattr(dataset, "sample_axis", None)
    labels = getattr(axis, "labels", None) if axis is not None else None
    if labels and len(labels) == n_samples:
        return [str(label) for label in labels]
    return [f"{prefix} {index + 1}" for index in range(n_samples)]


def _canonical_label(label: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(label).lower())


def _known_components_by_sample(dataset: Any, n_samples: int) -> list[dict[str, dict[str, Any]]] | None:
    """Return per-sample known concentration components when embedded targets name species."""
    target = getattr(dataset, "target", None)
    target_context = getattr(dataset, "target_context", None)
    target_names = list(getattr(target_context, "target_names", None) or []) if target_context is not None else []
    if target is None or not target_names:
        return None
    target_array = np.asarray(target, dtype=float)
    if target_array.ndim == 1:
        target_array = target_array.reshape(-1, 1)
    if target_array.ndim != 2 or target_array.shape[0] != n_samples or target_array.shape[1] != len(target_names):
        return None

    known_by_sample: list[dict[str, dict[str, Any]]] = []
    for sample_values in target_array:
        sample_known: dict[str, dict[str, Any]] = {}
        for component_name, concentration in zip(target_names, sample_values, strict=True):
            if not np.isfinite(concentration):
                continue
            canonical = _canonical_label(component_name)
            if not canonical:
                continue
            sample_known[canonical] = {
                "known_component": str(component_name),
                "known_concentration": float(concentration),
                "known_present": bool(float(concentration) > 0.0),
            }
        known_by_sample.append(sample_known)
    return known_by_sample


def _normalize_rows(X: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(X, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return X / norm


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a_centered = a - np.nanmean(a)
    b_centered = b - np.nanmean(b)
    denom = float(np.linalg.norm(a_centered) * np.linalg.norm(b_centered))
    return float(np.dot(a_centered, b_centered) / denom) if denom > 0 else 0.0


def _hqi_band(score: float) -> str:
    if score >= 900:
        return "excellent"
    if score >= 750:
        return "strong"
    if score >= 500:
        return "moderate"
    return "weak"


def _cap_hqi_band(band: str, *, caveat: bool) -> str:
    if caveat and band in {"excellent", "strong"}:
        return "moderate"
    return band


def _median_spacing(axis: np.ndarray) -> float | None:
    unique = np.unique(np.asarray(axis, dtype=float))
    if unique.size < 2:
        return None
    diffs = np.diff(unique)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return None
    return float(np.nanmedian(diffs))


def _covered_span(axis: np.ndarray) -> float:
    """Return the summed finite x-span without counting large missing gaps."""
    axis = np.asarray(axis, dtype=float)
    if axis.size < 2:
        return 0.0
    diffs = np.diff(axis)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return 0.0
    nominal = float(np.nanmedian(diffs))
    if nominal <= 0:
        return 0.0
    contiguous = diffs[diffs <= nominal * 1.5]
    return float(np.sum(contiguous))


def _finite_segments(axis: np.ndarray, values: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """Split a spectrum into finite, contiguous x-axis bands."""
    axis = np.asarray(axis, dtype=float)
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(axis) & np.isfinite(values)
    if int(np.count_nonzero(finite)) < 2:
        return []
    finite_axis = axis[finite]
    finite_values = values[finite]
    order = np.argsort(finite_axis)
    finite_axis = finite_axis[order]
    finite_values = finite_values[order]
    unique_axis, unique_inverse = np.unique(finite_axis, return_inverse=True)
    if unique_axis.size < 2:
        return []
    if unique_axis.size != finite_axis.size:
        summed = np.zeros(unique_axis.size, dtype=float)
        counts = np.zeros(unique_axis.size, dtype=float)
        for idx, value in zip(unique_inverse, finite_values, strict=True):
            summed[idx] += value
            counts[idx] += 1.0
        finite_axis = unique_axis
        finite_values = summed / np.maximum(counts, 1.0)

    nominal = _median_spacing(finite_axis)
    gap_threshold = nominal * 1.5 if nominal and nominal > 0 else None
    boundaries = [0]
    if gap_threshold is not None:
        gap_indices = np.flatnonzero(np.diff(finite_axis) > gap_threshold)
        boundaries.extend((gap_indices + 1).tolist())
    boundaries.append(finite_axis.size)
    segments: list[tuple[np.ndarray, np.ndarray]] = []
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
        if end - start >= 2:
            segments.append((finite_axis[start:end], finite_values[start:end]))
    return segments


def _plot_values_with_gaps(axis: np.ndarray, values: np.ndarray) -> tuple[list[float | None], list[float | None]]:
    """Insert None separators so plots do not draw lines across missing spectral bands."""
    segments = _finite_segments(axis, values)
    if not segments:
        return [], []
    x_out: list[float | None] = []
    y_out: list[float | None] = []
    for segment_idx, (seg_axis, seg_values) in enumerate(segments):
        if segment_idx > 0:
            x_out.append(None)
            y_out.append(None)
        x_out.extend(float(value) for value in seg_axis)
        y_out.extend(float(value) for value in seg_values)
    return x_out, y_out


def _thin_plot_values(
    x_values: list[float | None],
    y_values: list[float | None],
    *,
    max_points: int = 800,
) -> tuple[list[float | None], list[float | None]]:
    """Bound interactive plot payloads while preserving segment breaks."""
    if len(x_values) <= max_points or max_points < 10:
        return x_values, y_values

    segments: list[tuple[list[float], list[float]]] = []
    current_x: list[float] = []
    current_y: list[float] = []
    for x_value, y_value in zip(x_values, y_values, strict=False):
        if x_value is None or y_value is None:
            if current_x:
                segments.append((current_x, current_y))
                current_x = []
                current_y = []
            continue
        current_x.append(float(x_value))
        current_y.append(float(y_value))
    if current_x:
        segments.append((current_x, current_y))
    if not segments:
        return [], []

    points_per_segment = max(2, max_points // len(segments))
    out_x: list[float | None] = []
    out_y: list[float | None] = []
    for segment_index, (seg_x, seg_y) in enumerate(segments):
        if segment_index > 0:
            out_x.append(None)
            out_y.append(None)
        if len(seg_x) <= points_per_segment:
            out_x.extend(seg_x)
            out_y.extend(seg_y)
            continue
        # Uniform decimation can erase narrow gas-phase lines entirely. Keep
        # endpoints plus the strongest absolute response in each bin so the
        # review overlay still shows the spectral features that drove HQI.
        if points_per_segment <= 3:
            indices = np.linspace(0, len(seg_x) - 1, points_per_segment).round().astype(int)
        else:
            n_bins = max(1, points_per_segment // 3)
            edges = np.linspace(0, len(seg_x), n_bins + 1).round().astype(int)
            selected: list[int] = [0, len(seg_x) - 1]
            for left, right in zip(edges[:-1], edges[1:], strict=True):
                right = max(right, left + 1)
                bin_y = np.asarray(seg_y[left:right], dtype=float)
                finite = np.isfinite(bin_y)
                if not np.any(finite):
                    continue
                finite_indices = np.flatnonzero(finite)
                local_peak = int(finite_indices[np.argmax(np.abs(bin_y[finite_indices]))])
                selected.extend([left, left + local_peak, right - 1])
            indices = np.asarray(selected, dtype=int)
        indices = np.unique(np.clip(indices, 0, len(seg_x) - 1))
        out_x.extend(seg_x[int(index)] for index in indices)
        out_y.extend(seg_y[int(index)] for index in indices)
    return out_x, out_y


def _split_label_filter(raw: Any) -> set[str]:
    if raw in (None, ""):
        return set()
    return {part.strip().lower() for part in str(raw).split(",") if part.strip()}


def _pchip_to_grid(source_axis: np.ndarray, source_values: np.ndarray, target_axis: np.ndarray) -> np.ndarray:
    if source_axis.size < 2:
        return np.full(target_axis.shape, np.nan, dtype=float)
    interpolator = PchipInterpolator(source_axis, source_values, extrapolate=False)
    return np.asarray(interpolator(target_axis), dtype=float)


def _comparison_grid(sample_axis: np.ndarray, library_axis: np.ndarray) -> np.ndarray:
    """Build one scoring grid for all sample-library pairs in a node run."""
    sample_axis = np.asarray(sample_axis, dtype=float)
    library_axis = np.asarray(library_axis, dtype=float)
    sample_finite = sample_axis[np.isfinite(sample_axis)]
    library_finite = library_axis[np.isfinite(library_axis)]
    if sample_finite.size < 2 or library_finite.size < 2:
        return np.array([], dtype=float)
    sample_finite = np.unique(np.sort(sample_finite))
    library_finite = np.unique(np.sort(library_finite))
    x_min = max(float(sample_finite[0]), float(library_finite[0]))
    x_max = min(float(sample_finite[-1]), float(library_finite[-1]))
    if not x_min < x_max:
        return np.array([], dtype=float)

    sample_grid = sample_finite[(sample_finite >= x_min) & (sample_finite <= x_max)]
    if sample_grid.size >= 2:
        return sample_grid

    spacing = _median_spacing(sample_finite) or _median_spacing(library_finite)
    if not spacing or spacing <= 0:
        return np.array([], dtype=float)
    return np.arange(x_min, x_max + spacing * 0.5, spacing, dtype=float)


def _align_matrix_to_grid(axis: np.ndarray, X: np.ndarray, target_grid: np.ndarray) -> np.ndarray:
    """Interpolate every spectrum once onto the shared comparison grid.

    Each finite contiguous source band is interpolated independently so NaN
    gaps remain gaps instead of becoming artificial straight-line bridges.
    """
    aligned = np.full((X.shape[0], target_grid.size), np.nan, dtype=float)
    if target_grid.size < 2:
        return aligned
    for row_index, values in enumerate(np.asarray(X, dtype=float)):
        for source_axis, source_values in _finite_segments(axis, values):
            x_min = max(float(target_grid[0]), float(source_axis[0]))
            x_max = min(float(target_grid[-1]), float(source_axis[-1]))
            if not x_min < x_max:
                continue
            mask = (target_grid >= x_min) & (target_grid <= x_max)
            if int(np.count_nonzero(mask)) < 2:
                continue
            aligned[row_index, mask] = _pchip_to_grid(source_axis, source_values, target_grid[mask])
    return aligned


def _aligned_values_on_grid(
    grid: np.ndarray,
    sample_values: np.ndarray,
    library_values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    finite_pair = np.isfinite(sample_values) & np.isfinite(library_values)
    if int(np.count_nonzero(finite_pair)) < 2:
        return np.array([]), np.array([]), np.array([])
    return grid[finite_pair], sample_values[finite_pair], library_values[finite_pair]


def _cosine_and_hqi(sample_values: np.ndarray, library_values: np.ndarray) -> tuple[float, float]:
    sample_norm = _normalize_rows(sample_values.reshape(1, -1))[0]
    library_norm = _normalize_rows(library_values.reshape(1, -1))[0]
    cosine = float(np.dot(sample_norm, library_norm))
    return cosine, float(1000.0 * max(cosine, 0.0) ** 2)


def _band_limited_vectors(
    grid: np.ndarray,
    sample_values: np.ndarray,
    library_values: np.ndarray,
    *,
    threshold_fraction: float,
    min_points: int,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Build library-diagnostic, band-peak-scaled vectors for mixture search.

    Bands are selected from regions where the library signal is at least a
    fraction of that library spectrum's maximum absolute intensity. Each band
    is scaled by the library peak in that band before concatenation. This keeps
    strong library bands from dominating weaker but diagnostic bands while not
    normalizing absent/noisy sample bands up to unit height.
    """
    finite = np.isfinite(grid) & np.isfinite(sample_values) & np.isfinite(library_values)
    if int(np.count_nonzero(finite)) < 2:
        return np.array([]), np.array([]), 0, 0

    library_abs = np.abs(library_values[finite])
    library_max = float(np.nanmax(library_abs)) if library_abs.size else 0.0
    if not np.isfinite(library_max) or library_max <= 0:
        sample_vec = sample_values[finite]
        library_vec = library_values[finite]
        return sample_vec, library_vec, 1, int(sample_vec.size)

    threshold = max(0.0, min(1.0, threshold_fraction)) * library_max
    informative = finite & (np.abs(library_values) >= threshold)
    if int(np.count_nonzero(informative)) < min_points:
        sample_vec = sample_values[finite] / library_max
        library_vec = library_values[finite] / library_max
        return sample_vec, library_vec, 1, int(sample_vec.size)

    indices = np.flatnonzero(informative)
    informative_grid = grid[indices]
    nominal = _median_spacing(informative_grid)
    gap_threshold = nominal * 1.5 if nominal and nominal > 0 else None
    boundaries = [0]
    if gap_threshold is not None:
        boundaries.extend((np.flatnonzero(np.diff(informative_grid) > gap_threshold) + 1).tolist())
    boundaries.append(indices.size)

    sample_parts: list[np.ndarray] = []
    library_parts: list[np.ndarray] = []
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
        segment_indices = indices[start:end]
        if segment_indices.size < min_points:
            continue
        band_library = library_values[segment_indices]
        band_sample = sample_values[segment_indices]
        band_scale = float(np.nanmax(np.abs(band_library)))
        if not np.isfinite(band_scale) or band_scale <= 0:
            continue
        sample_parts.append(band_sample / band_scale)
        library_parts.append(band_library / band_scale)

    if not sample_parts:
        sample_vec = sample_values[finite] / library_max
        library_vec = library_values[finite] / library_max
        return sample_vec, library_vec, 1, int(sample_vec.size)

    sample_vec = np.concatenate(sample_parts)
    library_vec = np.concatenate(library_parts)
    return sample_vec, library_vec, len(sample_parts), int(sample_vec.size)


@register_node
class CompareVsLibraryNode(Node):
    """Rank sample spectra against a library My Dataset by spectral similarity."""

    metadata = NodeMetadata(
        node_type="analysis.compare_library",
        category="exploratory",
        label="Compare vs. Library",
        description="Rank spectra against selected library reference spectra using HQI and cosine similarity",
        parameters=[
            NodeParameter(
                name="top_n",
                label="Top Species Per Sample",
                param_type="number",
                default=10,
                min_value=1,
                step=1,
                description="Number of ranked library species to report for each sample spectrum",
                required=False,
            ),
            NodeParameter(
                name="library_filter",
                label="Library Labels",
                param_type="text",
                default="",
                description="Optional comma-separated library labels to compare; blank compares all library spectra",
                required=False,
            ),
            NodeParameter(
                name="hqi_mode",
                label="HQI Mode",
                param_type="select",
                default="whole_spectrum",
                options=["whole_spectrum", "band_limited"],
                description=(
                    "Whole-spectrum uses conventional full-overlap HQI. Band-limited uses library diagnostic "
                    "bands scaled by each band peak, which is better for multi-component mixture screening."
                ),
                required=False,
            ),
            NodeParameter(
                name="diagnostic_band_threshold",
                label="Diagnostic Band Threshold",
                param_type="number",
                default=0.2,
                min_value=0,
                step=0.01,
                description="Library relative peak threshold used to define band-limited HQI regions",
                required=False,
            ),
            NodeParameter(
                name="hqi_accept_threshold",
                label="Auto-select HQI Threshold",
                param_type="number",
                default=750,
                min_value=0,
                step=1,
                description="Mark candidates at or above this HQI as auto-selected for review",
                required=False,
            ),
            NodeParameter(
                name="hqi_reject_threshold",
                label="Auto-reject Best-Below HQI",
                param_type="number",
                default=500,
                min_value=0,
                step=1,
                description=(
                    "If a sample's best HQI is below this value, mark every candidate for that sample as rejected"
                ),
                required=False,
            ),
            NodeParameter(
                name="min_overlap_coverage",
                label="Minimum Overlap Coverage",
                param_type="number",
                default=0.5,
                min_value=0,
                step=0.05,
                description=(
                    "Minimum fraction of both spectra's x-axis span required before strong or excellent HQI labels "
                    "are allowed"
                ),
                required=False,
            ),
            NodeParameter(
                name="min_overlap_points",
                label="Minimum Overlap Points",
                param_type="number",
                default=20,
                min_value=2,
                step=1,
                description="Minimum matched x-axis points required before strong or excellent HQI labels are allowed",
                required=False,
            ),
            NodeParameter(
                name="baseline_gap_threshold",
                label="Baseline Warning Gap",
                param_type="number",
                default=0.25,
                min_value=0,
                step=0.05,
                description=(
                    "Flag matches where uncentered cosine exceeds Pearson correlation by this amount, suggesting "
                    "baseline or offset dominance"
                ),
                required=False,
            ),
        ],
        input_ports=[
            PortMetadata(
                name="sample",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="Sample Spectra",
                description="Unknown or experimental spectra from My Dataset",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="library",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="Library Spectra",
                description="Reference library spectra from My Dataset",
                accepted_data_roles=["X_spectra"],
            ),
        ],
        output_type="dict",
        diagnostics=[
            "top_hqi",
            "best_match",
            "hqi_band",
            "overlap_points",
            "overlap_sufficient",
            "coverage_fraction",
            "baseline_suspected",
            "resample_warning",
            "n_auto_selected",
            "n_auto_rejected",
            "known_answer_available",
            "best_match_known_present_rate",
            "auto_selected_known_present_rate",
            "n_query_spectra",
            "n_library_spectra",
        ],
    )

    async def execute(self, sample: Any = None, library: Any = None, **_: Any) -> NodeResult:
        sample_ds = bind_X(sample, missing_message="Compare vs. Library requires sample spectra")
        library_ds = bind_X(library, missing_message="Compare vs. Library requires library spectra")
        X_sample = to_numpy_2d(sample_ds, name="sample", dtype=np.float64)
        X_library = to_numpy_2d(library_ds, name="library", dtype=np.float64)
        sample_axis = _axis_values(sample_ds)
        library_axis = _axis_values(library_ds)
        if sample_axis is None or library_axis is None:
            raise ValueError("Compare vs. Library requires numeric x-axes on both inputs")
        if sample_axis.size != X_sample.shape[1] or library_axis.size != X_library.shape[1]:
            raise ValueError("Compare vs. Library input axis lengths do not match the data matrices")

        sample_labels = _sample_labels(sample_ds, "Sample")
        library_labels = _sample_labels(library_ds, "Library")
        known_components = _known_components_by_sample(sample_ds, X_sample.shape[0])
        label_filter = _split_label_filter(self.parameters.get("library_filter"))
        if label_filter:
            keep = [i for i, label in enumerate(library_labels) if label.lower() in label_filter]
            if not keep:
                raise ValueError("Library label filter did not match any library spectra")
            X_library = X_library[keep]
            library_labels = [library_labels[i] for i in keep]

        sample_order = np.argsort(sample_axis)
        library_order = np.argsort(library_axis)
        sample_axis_sorted = sample_axis[sample_order]
        library_axis_sorted = library_axis[library_order]
        accept_threshold = float(self.parameters.get("hqi_accept_threshold", 750) or 750)
        reject_threshold = float(self.parameters.get("hqi_reject_threshold", 500) or 500)
        accept_threshold = min(1000.0, max(0.0, accept_threshold))
        reject_threshold = min(1000.0, max(0.0, reject_threshold))
        hqi_mode = str(self.parameters.get("hqi_mode", "whole_spectrum") or "whole_spectrum")
        if hqi_mode not in {"whole_spectrum", "band_limited"}:
            hqi_mode = "whole_spectrum"
        diagnostic_band_threshold = float(self.parameters.get("diagnostic_band_threshold", 0.2) or 0.0)
        diagnostic_band_threshold = min(1.0, max(0.0, diagnostic_band_threshold))
        min_overlap_coverage = float(self.parameters.get("min_overlap_coverage", 0.5) or 0.0)
        min_overlap_coverage = min(1.0, max(0.0, min_overlap_coverage))
        min_overlap_points = max(2, int(float(self.parameters.get("min_overlap_points", 20) or 20)))
        baseline_gap_threshold = float(self.parameters.get("baseline_gap_threshold", 0.25) or 0.25)
        baseline_gap_threshold = max(0.0, baseline_gap_threshold)
        sample_spacing = _median_spacing(sample_axis_sorted)
        library_spacing = _median_spacing(library_axis_sorted)
        resample_ratio = None
        if sample_spacing and library_spacing:
            resample_ratio = max(sample_spacing, library_spacing) / min(sample_spacing, library_spacing)
        resample_warning = bool(resample_ratio is not None and resample_ratio >= 4.0)
        alignment_grid = _comparison_grid(sample_axis_sorted, library_axis_sorted)
        if alignment_grid.size < 2:
            raise ValueError("Sample and library spectra have no comparable finite x-axis overlap")
        X_sample_aligned = _align_matrix_to_grid(sample_axis_sorted, X_sample[:, sample_order], alignment_grid)
        X_library_aligned = _align_matrix_to_grid(library_axis_sorted, X_library[:, library_order], alignment_grid)
        interpolation_label = "single_pass_pchip_to_sample_grid"
        alignment_spacing = _median_spacing(alignment_grid)
        grid_aligned = bool(alignment_grid.size >= 2)

        rows: list[dict[str, Any]] = []
        max_plot_points = 800
        sample_plot_traces: dict[int, dict[str, Any]] = {}
        library_plot_traces: dict[int, dict[str, Any]] = {}
        for sample_idx, sample_label in enumerate(sample_labels):
            sample_row_sorted = X_sample[sample_idx, sample_order]
            sample_row_aligned = X_sample_aligned[sample_idx]
            sample_finite_axis = sample_axis_sorted[np.isfinite(sample_row_sorted)]
            if sample_finite_axis.size < 2:
                continue
            if sample_idx not in sample_plot_traces:
                sample_plot_x, sample_plot_y = _plot_values_with_gaps(
                    alignment_grid,
                    sample_row_aligned,
                )
                sample_plot_x, sample_plot_y = _thin_plot_values(
                    sample_plot_x,
                    sample_plot_y,
                    max_points=max_plot_points,
                )
                sample_plot_traces[sample_idx] = {
                    "sample_index": sample_idx,
                    "sample": sample_label,
                    "x": sample_plot_x,
                    "y": sample_plot_y,
                }
            sample_span = _covered_span(sample_finite_axis)
            sample_known = known_components[sample_idx] if known_components is not None else {}
            for lib_idx, lib_label in enumerate(library_labels):
                library_row_sorted = X_library[lib_idx, library_order]
                library_row_aligned = X_library_aligned[lib_idx]
                library_finite_axis = library_axis_sorted[np.isfinite(library_row_sorted)]
                if library_finite_axis.size < 2:
                    continue
                if lib_idx not in library_plot_traces:
                    library_plot_x, library_plot_y = _plot_values_with_gaps(
                        alignment_grid,
                        library_row_aligned,
                    )
                    library_plot_x, library_plot_y = _thin_plot_values(
                        library_plot_x,
                        library_plot_y,
                        max_points=max_plot_points,
                    )
                    library_plot_traces[lib_idx] = {
                        "library_index": lib_idx,
                        "library": lib_label,
                        "x": library_plot_x,
                        "y": library_plot_y,
                    }
                known_match = sample_known.get(_canonical_label(lib_label))
                grid_pair, sample_pair, library_pair = _aligned_values_on_grid(
                    alignment_grid,
                    sample_row_aligned,
                    library_row_aligned,
                )
                if grid_pair.size < 2:
                    continue
                whole_cosine, whole_hqi = _cosine_and_hqi(sample_pair, library_pair)
                band_sample, band_library, diagnostic_band_count, diagnostic_points = _band_limited_vectors(
                    grid_pair,
                    sample_pair,
                    library_pair,
                    threshold_fraction=diagnostic_band_threshold,
                    min_points=2,
                )
                if band_sample.size >= 2 and band_library.size >= 2:
                    band_cosine, band_hqi = _cosine_and_hqi(band_sample, band_library)
                    band_pearson = _pearson(band_sample, band_library)
                else:
                    band_cosine, band_hqi = whole_cosine, whole_hqi
                    band_pearson = _pearson(sample_pair, library_pair)
                    diagnostic_band_count = 0
                    diagnostic_points = 0
                whole_pearson = _pearson(sample_pair, library_pair)
                if hqi_mode == "band_limited":
                    cos_value = band_cosine
                    hqi = band_hqi
                    pearson = band_pearson
                else:
                    cos_value = whole_cosine
                    hqi = whole_hqi
                    pearson = whole_pearson
                baseline_suspected = (cos_value - pearson) >= baseline_gap_threshold
                overlap_min = float(grid_pair[0])
                overlap_max = float(grid_pair[-1])
                overlap_span = _covered_span(grid_pair)
                library_span = _covered_span(library_finite_axis)
                sample_coverage = overlap_span / sample_span if sample_span > 0 else 0.0
                library_coverage = overlap_span / library_span if library_span > 0 else 0.0
                coverage_fraction = min(sample_coverage, library_coverage)
                overlap_sufficient = grid_pair.size >= min_overlap_points and coverage_fraction >= min_overlap_coverage
                raw_hqi_band = _hqi_band(hqi)
                caveats = []
                if not overlap_sufficient:
                    caveats.append("thin_overlap")
                if baseline_suspected:
                    caveats.append("baseline_offset")
                if resample_warning:
                    caveats.append("grid_mismatch")
                band_caveat = not overlap_sufficient or baseline_suspected
                rows.append(
                    {
                        "sample_index": sample_idx,
                        "library_index": lib_idx,
                        "sample": sample_label,
                        "library": lib_label,
                        "hqi": hqi,
                        "whole_hqi": whole_hqi,
                        "band_limited_hqi": band_hqi,
                        "hqi_mode": hqi_mode,
                        "raw_hqi_band": raw_hqi_band,
                        "hqi_band": _cap_hqi_band(raw_hqi_band, caveat=band_caveat),
                        "cosine": cos_value,
                        "whole_cosine": whole_cosine,
                        "band_limited_cosine": band_cosine,
                        "pearson": pearson,
                        "whole_pearson": whole_pearson,
                        "band_limited_pearson": band_pearson,
                        "baseline_suspected": baseline_suspected,
                        "baseline_gap": cos_value - pearson,
                        "diagnostic_band_count": diagnostic_band_count,
                        "diagnostic_points": diagnostic_points,
                        "diagnostic_band_threshold": diagnostic_band_threshold,
                        "overlap_min": overlap_min,
                        "overlap_max": overlap_max,
                        "overlap_points": int(grid_pair.size),
                        "overlap_span": overlap_span,
                        "sample_coverage": sample_coverage,
                        "library_coverage": library_coverage,
                        "coverage_fraction": coverage_fraction,
                        "overlap_sufficient": overlap_sufficient,
                        "sample_spacing": sample_spacing,
                        "library_spacing": library_spacing,
                        "alignment_spacing": alignment_spacing,
                        "grid_aligned": grid_aligned,
                        "resample_ratio": resample_ratio,
                        "resample_warning": resample_warning,
                        "interpolation": interpolation_label,
                        "confidence_caveats": ", ".join(caveats),
                        "known_component": known_match["known_component"] if known_match else None,
                        "known_concentration": known_match["known_concentration"] if known_match else None,
                        "known_present": known_match["known_present"] if known_match else None,
                    }
                )
        if not rows:
            raise ValueError("Sample and library spectra have no comparable finite x-axis overlap")
        rows.sort(key=lambda row: (row["hqi"], row["cosine"]), reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["global_rank"] = rank
            row["rank"] = rank
        rows_by_sample: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            rows_by_sample.setdefault(int(row["sample_index"]), []).append(row)
        for sample_rows in rows_by_sample.values():
            sample_rows.sort(key=lambda row: (row["hqi"], row["cosine"]), reverse=True)
            for sample_rank, row in enumerate(sample_rows, start=1):
                row["sample_rank"] = sample_rank
        top_n = max(1, int(float(self.parameters.get("top_n", 10) or 10)))
        ranked = [row for sample_rows in rows_by_sample.values() for row in sample_rows[:top_n]]
        ranked.sort(key=lambda row: (int(row["sample_index"]), int(row["sample_rank"])))
        global_ranked = rows[:top_n]
        best_by_sample: dict[int, dict[str, Any]] = {}
        for row in rows:
            sample_index = int(row["sample_index"])
            if sample_index not in best_by_sample:
                best_by_sample[sample_index] = row
                row["best_for_sample"] = True
            else:
                row["best_for_sample"] = False
        for row in rows:
            sample_index = int(row["sample_index"])
            best_hqi = float(best_by_sample[sample_index]["hqi"])
            hqi = float(row["hqi"])
            if best_hqi < reject_threshold:
                status = "rejected"
            elif hqi >= accept_threshold and row["overlap_sufficient"] and not row["baseline_suspected"]:
                status = "auto_selected"
            else:
                status = "review"
            row["candidate_status"] = status
            row["auto_selected"] = status == "auto_selected"
            row["auto_rejected"] = status == "rejected"
        for row in ranked:
            row["hqi_report"] = (
                f"HQI {float(row['hqi']):.1f}/1000 ({row['hqi_band']}, {row['candidate_status']}); "
                f"mode {row['hqi_mode']}; cosine {float(row['cosine']):.4f}; "
                f"Pearson {float(row['pearson']):.4f}; "
                f"coverage {float(row['coverage_fraction']):.2f}; {int(row['overlap_points'])} matched points from "
                f"{float(row['overlap_min']):.6g} to {float(row['overlap_max']):.6g}"
            )
            if row["hqi_mode"] == "band_limited":
                row["hqi_report"] += (
                    f"; diagnostic bands {int(row['diagnostic_band_count'])}, "
                    f"{int(row['diagnostic_points'])} band points"
                )
            if row["confidence_caveats"]:
                row["hqi_report"] += f"; caveats: {row['confidence_caveats']}"
            if row["known_present"] is not None:
                status = "known present" if row["known_present"] else "known absent"
                concentration = row["known_concentration"]
                if concentration is not None:
                    row["hqi_report"] += f"; ground truth: {status} ({float(concentration):.6g})"
                else:
                    row["hqi_report"] += f"; ground truth: {status}"
        report_rows = [
            {
                "sample": row["sample"],
                "sample_index": row["sample_index"],
                "rank": row["sample_rank"],
                "sample_rank": row["sample_rank"],
                "global_rank": row["global_rank"],
                "library": row["library"],
                "library_index": row["library_index"],
                "hqi": row["hqi"],
                "whole_hqi": row["whole_hqi"],
                "band_limited_hqi": row["band_limited_hqi"],
                "hqi_mode": row["hqi_mode"],
                "hqi_band": row["hqi_band"],
                "raw_hqi_band": row["raw_hqi_band"],
                "cosine": row["cosine"],
                "whole_cosine": row["whole_cosine"],
                "band_limited_cosine": row["band_limited_cosine"],
                "pearson": row["pearson"],
                "whole_pearson": row["whole_pearson"],
                "band_limited_pearson": row["band_limited_pearson"],
                "baseline_suspected": row["baseline_suspected"],
                "baseline_gap": row["baseline_gap"],
                "diagnostic_band_count": row["diagnostic_band_count"],
                "diagnostic_points": row["diagnostic_points"],
                "diagnostic_band_threshold": row["diagnostic_band_threshold"],
                "candidate_status": row["candidate_status"],
                "auto_selected": row["auto_selected"],
                "auto_rejected": row["auto_rejected"],
                "best_for_sample": row["best_for_sample"],
                "overlap_min": row["overlap_min"],
                "overlap_max": row["overlap_max"],
                "overlap_points": row["overlap_points"],
                "overlap_span": row["overlap_span"],
                "coverage_fraction": row["coverage_fraction"],
                "sample_coverage": row["sample_coverage"],
                "library_coverage": row["library_coverage"],
                "overlap_sufficient": row["overlap_sufficient"],
                "sample_spacing": row["sample_spacing"],
                "library_spacing": row["library_spacing"],
                "alignment_spacing": row["alignment_spacing"],
                "grid_aligned": row["grid_aligned"],
                "resample_warning": row["resample_warning"],
                "interpolation": row["interpolation"],
                "confidence_caveats": row["confidence_caveats"],
                "known_component": row["known_component"],
                "known_concentration": row["known_concentration"],
                "known_present": row["known_present"],
                "hqi_report": row["hqi_report"],
            }
            for row in ranked
        ]
        sample_reports = [
            {
                "sample": sample_label,
                "library": best_by_sample[sample_index]["library"],
                "hqi": best_by_sample[sample_index]["hqi"],
                "whole_hqi": best_by_sample[sample_index]["whole_hqi"],
                "band_limited_hqi": best_by_sample[sample_index]["band_limited_hqi"],
                "hqi_mode": best_by_sample[sample_index]["hqi_mode"],
                "hqi_band": best_by_sample[sample_index]["hqi_band"],
                "raw_hqi_band": best_by_sample[sample_index]["raw_hqi_band"],
                "cosine": best_by_sample[sample_index]["cosine"],
                "whole_cosine": best_by_sample[sample_index]["whole_cosine"],
                "band_limited_cosine": best_by_sample[sample_index]["band_limited_cosine"],
                "pearson": best_by_sample[sample_index]["pearson"],
                "whole_pearson": best_by_sample[sample_index]["whole_pearson"],
                "band_limited_pearson": best_by_sample[sample_index]["band_limited_pearson"],
                "baseline_suspected": best_by_sample[sample_index]["baseline_suspected"],
                "diagnostic_band_count": best_by_sample[sample_index]["diagnostic_band_count"],
                "diagnostic_points": best_by_sample[sample_index]["diagnostic_points"],
                "candidate_status": best_by_sample[sample_index]["candidate_status"],
                "auto_selected": best_by_sample[sample_index]["auto_selected"],
                "auto_rejected": best_by_sample[sample_index]["auto_rejected"],
                "overlap_min": best_by_sample[sample_index]["overlap_min"],
                "overlap_max": best_by_sample[sample_index]["overlap_max"],
                "overlap_points": best_by_sample[sample_index]["overlap_points"],
                "overlap_span": best_by_sample[sample_index]["overlap_span"],
                "coverage_fraction": best_by_sample[sample_index]["coverage_fraction"],
                "overlap_sufficient": best_by_sample[sample_index]["overlap_sufficient"],
                "confidence_caveats": best_by_sample[sample_index]["confidence_caveats"],
                "known_component": best_by_sample[sample_index]["known_component"],
                "known_concentration": best_by_sample[sample_index]["known_concentration"],
                "known_present": best_by_sample[sample_index]["known_present"],
            }
            for sample_index, sample_label in enumerate(sample_labels)
            if sample_index in best_by_sample
        ]
        overlay_candidates: list[dict[str, Any]] = []
        for row in ranked:
            sample_idx = int(row["sample_index"])
            library_idx = int(row["library_index"])
            overlay_candidates.append(
                {
                    "rank": row["sample_rank"],
                    "sample_rank": row["sample_rank"],
                    "global_rank": row["global_rank"],
                    "sample_index": sample_idx,
                    "library_index": library_idx,
                    "sample": row["sample"],
                    "library": row["library"],
                    "hqi": row["hqi"],
                    "whole_hqi": row["whole_hqi"],
                    "band_limited_hqi": row["band_limited_hqi"],
                    "hqi_mode": row["hqi_mode"],
                    "hqi_band": row["hqi_band"],
                    "raw_hqi_band": row["raw_hqi_band"],
                    "candidate_status": row["candidate_status"],
                    "auto_selected": row["auto_selected"],
                    "auto_rejected": row["auto_rejected"],
                    "overlap_sufficient": row["overlap_sufficient"],
                    "coverage_fraction": row["coverage_fraction"],
                    "baseline_suspected": row["baseline_suspected"],
                    "known_component": row["known_component"],
                    "known_concentration": row["known_concentration"],
                    "known_present": row["known_present"],
                    "confidence_caveats": row["confidence_caveats"],
                    "sample_trace_index": sample_idx,
                    "library_trace_index": library_idx,
                    "sample_spacing": row["sample_spacing"],
                    "library_spacing": row["library_spacing"],
                    "alignment_spacing": row["alignment_spacing"],
                    "grid_aligned": row["grid_aligned"],
                    "interpolation": row["interpolation"],
                    "y_units": "Sample response; library scaled",
                }
            )

        top_library_indices: list[int] = []
        for row in global_ranked:
            library_idx = int(row["library_index"])
            if library_idx not in top_library_indices:
                top_library_indices.append(library_idx)
            if len(top_library_indices) >= min(5, len(library_labels)):
                break
        first_sample_index = int(global_ranked[0]["sample_index"]) if global_ranked else 0
        first_sample_trace = sample_plot_traces.get(first_sample_index, {"x": [], "y": []})
        traces: list[dict[str, Any]] = [
            {
                "type": "scatter",
                "mode": "lines",
                "x": first_sample_trace["x"],
                "y": first_sample_trace["y"],
                "name": sample_labels[first_sample_index],
                "line": {"color": "#f8fafc", "width": 2},
            }
        ]
        for idx in top_library_indices:
            label = library_labels[idx]
            best = next((row for row in global_ranked if int(row["library_index"]) == idx), {})
            library_trace = library_plot_traces.get(idx, {"x": [], "y": []})
            traces.append(
                {
                    "type": "scatter",
                    "mode": "lines",
                    "x": library_trace["x"],
                    "y": library_trace["y"],
                    "name": f"{label} (HQI {float(best.get('hqi', 0.0)):.1f})",
                }
            )

        layout = {
            "title": "Sample vs. Top Library Matches",
            "xaxis": _xaxis_layout(sample_ds),
            "yaxis": {"title": "Sample response; library scaled"},
            "showlegend": True,
        }
        known_available = known_components is not None
        best_known_present = [
            bool(best_by_sample[sample_index]["known_present"])
            for sample_index in best_by_sample
            if best_by_sample[sample_index]["known_present"] is not None
        ]
        auto_selected_known_present = [
            bool(row["known_present"]) for row in rows if row["auto_selected"] and row["known_present"] is not None
        ]
        metadata = {
            "type": "LibraryComparison",
            "n_query_spectra": int(X_sample.shape[0]),
            "n_library_spectra": int(X_library.shape[0]),
            "ranked_by": "HQI",
            "hqi_mode": hqi_mode,
            "hqi_scale": (
                "0-1000, squared non-negative uncentered cosine similarity"
                if hqi_mode == "whole_spectrum"
                else (
                    "0-1000, squared non-negative cosine on library diagnostic bands, "
                    "with diagnostic regions selected from the library peak threshold and scaled per band"
                )
            ),
            "hqi_interpretation": {
                "excellent": ">= 900",
                "strong": "750-899",
                "moderate": "500-749",
                "weak": "< 500",
                "note": "Strong/excellent labels are capped at moderate when overlap or baseline caveats apply.",
            },
            "hqi_accept_threshold": accept_threshold,
            "hqi_reject_threshold": reject_threshold,
            "diagnostic_band_threshold": diagnostic_band_threshold,
            "min_overlap_coverage": min_overlap_coverage,
            "min_overlap_points": min_overlap_points,
            "baseline_gap_threshold": baseline_gap_threshold,
            "n_auto_selected": int(sum(1 for row in rows if row["auto_selected"])),
            "n_auto_rejected": int(sum(1 for row in rows if row["auto_rejected"])),
            "n_report_rows": len(report_rows),
            "top_species_per_sample": top_n,
            "x_overlap": [global_ranked[0]["overlap_min"], global_ranked[0]["overlap_max"]],
            "overlap_points": int(global_ranked[0]["overlap_points"]),
            "overlap_span": float(global_ranked[0]["overlap_span"]),
            "sample_coverage": float(global_ranked[0]["sample_coverage"]),
            "library_coverage": float(global_ranked[0]["library_coverage"]),
            "coverage_fraction": float(global_ranked[0]["coverage_fraction"]),
            "overlap_sufficient": bool(global_ranked[0]["overlap_sufficient"]),
            "overlap_scope": "per sample-library pair",
            "sample_spacing": sample_spacing,
            "library_spacing": library_spacing,
            "alignment_spacing": alignment_spacing,
            "grid_aligned": grid_aligned,
            "resample_ratio": resample_ratio,
            "resample_warning": resample_warning,
            "alignment_grid": {
                "mode": interpolation_label,
                "n_points": int(alignment_grid.size),
                "wavenumber_min": float(alignment_grid[0]),
                "wavenumber_max": float(alignment_grid[-1]),
                "spacing": _median_spacing(alignment_grid),
            },
            "n_baseline_suspected": int(sum(1 for row in rows if row["baseline_suspected"])),
            "known_answer_available": known_available,
            "best_match_known_present_rate": (float(np.mean(best_known_present)) if best_known_present else None),
            "auto_selected_known_present_rate": (
                float(np.mean(auto_selected_known_present)) if auto_selected_known_present else None
            ),
            "plot_payload": {
                "trace_mode": "indexed_sample_library_traces",
                "max_points_per_trace": max_plot_points,
                "n_sample_traces": len(sample_plot_traces),
                "n_library_traces": len(library_plot_traces),
            },
        }
        return NodeResult(
            outputs={
                "data": report_rows,
                "metadata": metadata,
                "ranking": {"data": report_rows, "metadata": metadata},
                "hqi_report": {
                    "data": report_rows,
                    "metadata": {
                        **metadata,
                        "description": "Top library species ranked within each sample spectrum.",
                        "column_names": [
                            "sample",
                            "sample_index",
                            "sample_rank",
                            "global_rank",
                            "library",
                            "hqi",
                            "whole_hqi",
                            "band_limited_hqi",
                            "hqi_mode",
                            "hqi_band",
                            "candidate_status",
                            "cosine",
                            "pearson",
                            "coverage_fraction",
                            "overlap_points",
                            "sample_spacing",
                            "library_spacing",
                            "alignment_spacing",
                            "grid_aligned",
                            "diagnostic_band_count",
                            "diagnostic_points",
                            "known_component",
                            "known_concentration",
                            "known_present",
                            "confidence_caveats",
                        ],
                    },
                },
                "best_matches": {
                    "data": sample_reports,
                    "metadata": {
                        **metadata,
                        "description": "Best HQI match for each sample spectrum.",
                    },
                },
                "plots": {
                    "library_compare": {"data": traces, "layout": layout},
                    "library_compare_candidates": {
                        "data": overlay_candidates,
                        "samples": list(sample_plot_traces.values()),
                        "libraries": list(library_plot_traces.values()),
                        "layout": {
                            "title": "Full Sample Spectrum vs. Library Candidate",
                            "xaxis": _xaxis_layout(sample_ds),
                            "yaxis": {"title": "Sample response; library scaled"},
                            "showlegend": True,
                        },
                        "metadata": metadata,
                    },
                },
            },
            diagnostics={
                "top_hqi": float(global_ranked[0]["hqi"]) if global_ranked else 0.0,
                "top_whole_hqi": float(global_ranked[0]["whole_hqi"]) if global_ranked else 0.0,
                "top_band_limited_hqi": float(global_ranked[0]["band_limited_hqi"]) if global_ranked else 0.0,
                "hqi_mode": hqi_mode,
                "best_match": str(global_ranked[0]["library"]) if global_ranked else "",
                "hqi_band": str(global_ranked[0]["hqi_band"]) if global_ranked else "",
                "raw_hqi_band": str(global_ranked[0]["raw_hqi_band"]) if global_ranked else "",
                "overlap_points": int(metadata["overlap_points"]),
                "overlap_sufficient": bool(metadata["overlap_sufficient"]),
                "coverage_fraction": float(metadata["coverage_fraction"]),
                "sample_coverage": float(metadata["sample_coverage"]),
                "library_coverage": float(metadata["library_coverage"]),
                "grid_aligned": grid_aligned,
                "alignment_spacing": alignment_spacing,
                "resample_warning": resample_warning,
                "n_baseline_suspected": metadata["n_baseline_suspected"],
                "baseline_suspected": bool(global_ranked[0]["baseline_suspected"]) if global_ranked else False,
                "n_auto_selected": metadata["n_auto_selected"],
                "n_auto_rejected": metadata["n_auto_rejected"],
                "known_answer_available": metadata["known_answer_available"],
                "best_match_known_present_rate": metadata["best_match_known_present_rate"],
                "auto_selected_known_present_rate": metadata["auto_selected_known_present_rate"],
                "n_query_spectra": int(X_sample.shape[0]),
                "n_library_spectra": int(X_library.shape[0]),
            },
        )
