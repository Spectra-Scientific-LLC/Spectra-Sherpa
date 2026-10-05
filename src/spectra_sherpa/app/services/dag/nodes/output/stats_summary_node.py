"""
Adaptive Statistics node.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Dict, List, Optional, cast

import numpy as np

from spectra_sherpa.app.lib.data_roles import get_dataset_data_role
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, register_node


def _is_numeric_array(arr: np.ndarray) -> bool:
    """Return True when an array can support numeric reductions."""
    return np.issubdtype(arr.dtype, np.number) or np.issubdtype(arr.dtype, np.bool_)


def _is_measured_category(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (int, float, complex, np.number)):
        return bool(np.isfinite(value))
    try:
        return bool(value == value)
    except (TypeError, ValueError):
        return False


def _dataset_meta(dataset: Any) -> dict[str, Any]:
    meta = getattr(dataset, "meta", None)
    return meta if isinstance(meta, dict) else {}


_REFERENCE_CONTEXT_KEYS = (
    "reference.artifact_id",
    "reference.artifact_sha256",
    "reference.member_sha256",
    "reference.projection_id",
    "reference.package_id",
    "reference.view_id",
    "reference.instrument_view",
    "reference.cohort",
)
_SAMPLE_ROLE_COLUMNS = ("analysis_role", "source_partition", "cohort", "instrument")
_REFERENCE_DIGEST_KEYS = frozenset({"reference.artifact_sha256", "reference.member_sha256"})
_MAX_CONTEXT_TEXT = 256
_MAX_ROLE_CATEGORIES = 32
_MAX_ROLE_LABEL = 128
_MAX_ROLE_LABEL_BYTES = 4096


def _sequence_digest(values: list[str]) -> str:
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _bounded_text(value: Any, *, maximum: int = _MAX_CONTEXT_TEXT) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if len(value) > maximum or any(ord(character) < 32 for character in value):
        return None
    return value


def _reference_context(meta: dict[str, Any]) -> dict[str, str]:
    reference: dict[str, str] = {}
    for key in _REFERENCE_CONTEXT_KEYS:
        value = _bounded_text(meta.get(key))
        if value is None:
            continue
        if key in _REFERENCE_DIGEST_KEYS and re.fullmatch(r"[0-9a-f]{64}", value) is None:
            continue
        reference[key] = value
    return reference


def _role_token(value: Any) -> tuple[str, str | None]:
    if value is None:
        return "null", "null"
    if isinstance(value, bool):
        text = "true" if value else "false"
        return f"boolean:{text}", f"boolean:{text}"
    if isinstance(value, (int, np.integer)):
        text = str(int(value))
        return f"integer:{text}", f"integer:{text}"
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            return "number:<nonfinite>", "number:<nonfinite>"
        text = repr(number)
        return f"number:{text}", f"number:{text}"
    text = _bounded_text(value, maximum=_MAX_ROLE_LABEL)
    if text is not None:
        return f"text:{text}", f"text:{text}"
    return f"unsupported:{type(value).__name__}", None


def _role_summary(values: list[Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    token_digests: set[str] = set()
    sequence = hashlib.sha256()
    invalid_value_count = 0
    retained_label_bytes = 0
    overflow = False
    distinct_count_lower_bound = 0
    for value in values:
        token, display = _role_token(value)
        encoded = token.encode("utf-8")
        sequence.update(len(encoded).to_bytes(8, "big"))
        sequence.update(encoded)
        token_digest = hashlib.sha256(encoded).hexdigest()
        if display is None:
            invalid_value_count += 1
            overflow = True
            counts.clear()
        elif not overflow and token_digest in token_digests:
            counts[display] = counts.get(display, 0) + 1
        elif not overflow:
            encoded_label = json.dumps(display, ensure_ascii=False).encode("utf-8")
            would_exceed = len(token_digests) >= _MAX_ROLE_CATEGORIES or (
                retained_label_bytes + len(encoded_label) > _MAX_ROLE_LABEL_BYTES
            )
            if would_exceed:
                overflow = True
                distinct_count_lower_bound = len(token_digests) + 1
                counts.clear()
            else:
                token_digests.add(token_digest)
                retained_label_bytes += len(encoded_label)
                counts[display] = 1
        if overflow and distinct_count_lower_bound == 0:
            distinct_count_lower_bound = len(token_digests) + 1
    if not overflow and sum(counts.values()) != len(values):
        raise RuntimeError("bounded role summary lost sample membership")
    return {
        "counts": None if overflow else dict(sorted(counts.items())),
        "distinct_count": None if overflow else len(token_digests),
        "distinct_count_lower_bound": distinct_count_lower_bound if overflow else len(token_digests),
        "invalid_value_count": invalid_value_count,
        "total_count": len(values),
        "values_redacted": overflow,
        "values_sha256": sequence.hexdigest(),
    }


def build_dataset_source_context(dataset: SherpaDataset) -> dict[str, Any]:
    """Return bounded, auditable source and specimen custody for a result."""

    try:
        scientific_digest = dataset.scientific_digest
    except ValueError:
        # The canonical scientific digest deliberately refuses non-finite
        # metadata scalars. Missing target cells are valid for descriptive
        # summaries, so retain the finite X fingerprint and explicit target
        # missingness instead of making the result node fail.
        scientific_digest = None
    meta = _dataset_meta(dataset)
    reference = _reference_context(meta)
    source_identity = {
        key: text
        for key, value in dataset.source_identity.model_dump(mode="json", exclude_none=True).items()
        if (text := _bounded_text(value)) is not None
    }
    sample_axis = dataset.sample_axis
    raw_labels = None if sample_axis is None else sample_axis.labels
    labels = [] if raw_labels is None else [str(value) for value in raw_labels]
    table = {} if sample_axis is None or sample_axis.sample_table is None else sample_axis.sample_table
    role_counts = {
        key: _role_summary(list(table[key]))
        for key in _SAMPLE_ROLE_COLUMNS
        if key in table and len(table[key]) == dataset.n_samples
    }
    raw_columns = sorted(str(key) for key in table)
    safe_columns = [name for name in raw_columns if _bounded_text(name, maximum=_MAX_ROLE_LABEL) is not None]
    displayed_columns = safe_columns[:64]
    return {
        "dataset_title": _bounded_text(dataset.title),
        "scientific_digest": scientific_digest,
        "data_fingerprint": dataset.fingerprint,
        "source_identity": source_identity,
        "reference": reference,
        "sample_identity": {
            "count": dataset.n_samples,
            "labels_present": raw_labels is not None,
            "labels_unique": len(labels) == len(set(labels)) if labels else None,
            "labels_sha256": _sequence_digest(labels) if labels else None,
        },
        "sample_table_columns": displayed_columns,
        "sample_table_column_count": len(raw_columns),
        "sample_table_columns_truncated": len(displayed_columns) != len(raw_columns),
        "sample_table_columns_sha256": _sequence_digest(raw_columns),
        "sample_role_counts": role_counts,
    }


def _is_pca_score_dataset(dataset: SherpaDataset) -> bool:
    meta = _dataset_meta(dataset)
    if bool(meta.get("isPCA")) or str(meta.get("type", "")).upper() == "PCA":
        return True
    title = str(getattr(dataset, "title", "") or "").lower()
    axis_title = str(getattr(getattr(dataset, "feature_axis", None), "title", "") or "").lower()
    return "score" in title and "principal component" in axis_title


def _canonical_summary_parameters(raw: dict[str, object]) -> dict[str, object]:
    """Close the one scientist-controlled presentation bound."""

    unknown = sorted(set(raw) - {"max_samples"})
    if unknown:
        raise ValueError(f"stats.summary received unknown parameters: {', '.join(unknown)}")
    value = raw.get("max_samples", 100)
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError("stats.summary max_samples must be an integer")
    max_samples = int(value)
    if not 10 <= max_samples <= 10_000:
        raise ValueError("stats.summary max_samples must be between 10 and 10000")
    return {"max_samples": max_samples}


@register_node
class StatsSummaryNode(Node):
    """
    Adaptive Statistics node.

    Computes contextual statistics based on input type:
    - SherpaDataset: spectral statistics, per-sample/feature analysis
    - PCA results: scores/loadings stats, outlier detection
    - MCR results: concentration/spectra statistics
    - Generic arrays: basic descriptive statistics
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="stats.summary",
        category="validation",
        label="Statistics",
        description=(
            "Compute deterministic descriptive summaries for canonical datasets and "
            "typed scientific result payloads without fitting or inventing missing data"
        ),
        parameters=[
            NodeParameter(
                name="max_samples",
                label="Max Sample Rows",
                param_type="number",
                default=100,
                min_value=10,
                max_value=10000,
                max_value_reason=(
                    "Bounds the serialized per-sample table and workbench response size; "
                    "the result reports explicit truncation."
                ),
                description="Maximum rows in per-sample statistics table",
                required=False,
            ),
        ],
        input_types=["SherpaDataset", "dict", "array"],
        output_type="StatisticsSummary",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Input Data",
                description="Input data to process",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="statistics",
                type_ref="spectrasherpa://types/StatisticsSummary/1.0",
                required=True,
                label="Statistics",
                description="Computed statistics and summary",
            ),
        ],
        canonical_parameter_validator=_canonical_summary_parameters,
    )

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        """Generate the exact same summary call used by live execution."""
        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return [
            f"{indent}# --- Statistics ({self.node_id}) ---",
            (
                f"{indent}from spectra_sherpa.app.services.dag.nodes.output.stats_summary_node "
                "import build_statistics_result"
            ),
            f"{indent}results[{self.node_id!r}] = build_statistics_result(",
            f"{indent}    {input_expr}, max_samples={parameters['max_samples']!r},",
            f"{indent})",
        ]

    async def execute(self, input_data: Any) -> Dict[str, Any]:
        """
        Compute adaptive statistics based on input type.

        Args:
            input_data: SherpaDataset, PCA/MCR dict, or array data

        Returns:
            Dict with comprehensive statistics and visualization data
        """
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return build_statistics_result(input_data, max_samples=int(parameters["max_samples"]))

    def _compute(self, input_data: Any) -> Dict[str, Any]:
        """Detect one supported input shape and route to its deterministic summary."""

        if isinstance(input_data, dict):
            if isinstance(input_data.get("default"), SherpaDataset):
                return self._stats_dataset(input_data["default"])
            if "accuracy" in input_data or input_data.get("task_type") in ("classification", "regression"):
                return self._stats_evaluation(input_data)
            elif "scores" in input_data or "X_scores" in input_data or "isPCA" in input_data.get("metadata", {}):
                return self._stats_pca(input_data)
            elif "C" in input_data or "St" in input_data:
                return self._stats_mcr(input_data)
            elif "data" in input_data:
                meta = input_data.get("metadata") or {}
                if meta.get("type") == "PeakFinding":
                    return self._stats_peaks(input_data["data"], meta)
                return self._stats_array(input_data["data"], meta)
            for key in (
                "transformed",
                "result",
                "predictions",
                "labels",
                "cluster_assignment",
                "y_pred",
                "probabilities",
                "class_probabilities",
                "distances",
                "neighbor_indices",
                "class_distance_matrix",
            ):
                if key in input_data and input_data[key] is not None:
                    meta = dict(input_data.get("metadata") or {})
                    meta.setdefault("source_key", key)
                    return self._stats_array(input_data[key], meta)
            return self._stats_mapping(input_data)

        if isinstance(input_data, SherpaDataset):
            if _is_pca_score_dataset(input_data):
                return self._stats_pca({"data": input_data, "metadata": _dataset_meta(input_data)})
            return self._stats_dataset(input_data)

        # Fallback to array statistics
        return self._stats_array(np.array(input_data), None)

    def _stats_dataset(self, dataset: Any) -> Dict[str, Any]:
        """Compute per-wavelength mean and std for spectral data."""
        data = np.array(dataset.data)
        if data.ndim == 1:
            data = data.reshape(1, -1)
        if data.ndim != 2 or not _is_numeric_array(data):
            raise ValueError("stats.summary requires a numeric one- or two-dimensional canonical dataset")

        n_samples, n_features = data.shape
        data_role = get_dataset_data_role(dataset)
        is_feature_table = data_role == "X_features"
        data = data.astype(np.float64, copy=False)
        finite_mask = np.isfinite(data)
        nonfinite_count = int(data.size - np.count_nonzero(finite_mask))
        missing_count = int(np.count_nonzero(np.isnan(data))) if np.issubdtype(data.dtype, np.floating) else 0
        finite_data = data[finite_mask]

        # Per-feature statistics — wavelength/wavenumber when spectral,
        # categorical feature name when the source is X_features.
        feature_means: list[float | None] = []
        feature_stds: list[float | None] = []
        for feature_index in range(n_features):
            finite_values = data[finite_mask[:, feature_index], feature_index]
            feature_means.append(float(np.mean(finite_values)) if finite_values.size else None)
            feature_stds.append(float(np.std(finite_values)) if finite_values.size else None)

        # Get feature axis (wavelength, wavenumber, channel, etc.)
        x_coord = dataset.feature_axis
        if x_coord is not None:
            raw_labels = getattr(x_coord, "labels", None)
            if is_feature_table and raw_labels is not None and len(raw_labels) == n_features:
                feature_values = [str(label) for label in raw_labels]
            elif x_coord.data is not None:
                feature_values = np.array(x_coord.data).tolist()
            elif raw_labels is not None:
                feature_values = [str(label) for label in raw_labels]
            else:
                feature_values = list(range(n_features))
        else:
            feature_values = list(range(n_features))

        feature_key = "feature" if is_feature_table else "wavelength"

        # Build per-feature table rows for DataTable display
        table_rows = []
        for i in range(n_features):
            feature_values_i = data[:, i]
            feature_finite = np.isfinite(feature_values_i)
            table_rows.append(
                {
                    feature_key: feature_values[i],
                    "mean": feature_means[i],
                    "std": feature_stds[i],
                    "nonfinite": int(feature_values_i.size - np.count_nonzero(feature_finite)),
                }
            )

        sample_nonfinite = data.shape[1] - np.count_nonzero(finite_mask, axis=1)
        sample_quality = []
        for sample_index in range(min(n_samples, int(self.parameters.get("max_samples", 100)))):
            finite_values = data[sample_index, finite_mask[sample_index]]
            sample_quality.append(
                {
                    "sample": int(sample_index + 1),
                    "mean": float(np.mean(finite_values)) if finite_values.size else None,
                    "std": float(np.std(finite_values)) if finite_values.size else None,
                    "nonfinite": int(sample_nonfinite[sample_index]),
                }
            )
        target_summary: dict[str, Any] | None = None
        target = getattr(dataset, "target", None)
        if target is not None:
            target_arr = np.asarray(target)
            target_context = dataset.target_context
            target_summary = {
                "shape": list(target_arr.shape),
                "nonfinite": (
                    int(target_arr.size - np.count_nonzero(np.isfinite(target_arr)))
                    if np.issubdtype(target_arr.dtype, np.number)
                    else None
                ),
                "target_type": target_context.target_type,
                "target_units": target_context.target_units,
            }
            if target_context.target_type == "continuous" and target_arr.ndim in {1, 2}:
                if not np.issubdtype(target_arr.dtype, np.number) or np.issubdtype(
                    target_arr.dtype, np.complexfloating
                ):
                    raise ValueError("continuous target must contain real numeric values")
                columns = target_arr[:, None] if target_arr.ndim == 1 else target_arr
                names = target_context.target_names
                if names is None or len(names) != columns.shape[1]:
                    names = [target_context.target_name] if columns.shape[1] == 1 else [None] * columns.shape[1]
                target_summary["columns"] = []
                for index in range(columns.shape[1]):
                    values = columns[:, index]
                    finite = values[np.isfinite(values)].astype(np.float64, copy=False)
                    target_summary["columns"].append(
                        {
                            "name": names[index],
                            "measured": int(finite.size),
                            "missing": int(values.size - finite.size),
                            "min": float(np.min(finite)) if finite.size else None,
                            "max": float(np.max(finite)) if finite.size else None,
                            "mean": float(np.mean(finite)) if finite.size else None,
                        }
                    )
            elif target_context.target_type == "categorical" and target_arr.ndim == 1:
                measured_mask = (
                    np.isfinite(target_arr)
                    if np.issubdtype(target_arr.dtype, np.number)
                    else np.fromiter(
                        (_is_measured_category(value) for value in target_arr),
                        dtype=bool,
                        count=target_arr.size,
                    )
                )
                target_summary["missing"] = int(target_arr.size - np.count_nonzero(measured_mask))
                unique, counts = np.unique(target_arr[measured_mask].astype(str), return_counts=True)
                if 1 < len(unique) <= 30:
                    target_summary["class_counts"] = {
                        str(label): int(count) for label, count in zip(unique, counts, strict=True)
                    }

        dataset_meta = _dataset_meta(dataset)
        quality_summary = dataset_meta.get("quality_summary")
        if not isinstance(quality_summary, dict):
            quality_summary = None
        source_context = build_dataset_source_context(dataset)

        mean_plot = {
            "x": feature_values,
            "y": feature_means,
            "type": "bar" if is_feature_table else "scatter",
        }
        std_plot = {
            "x": feature_values,
            "y": feature_stds,
            "type": "bar" if is_feature_table else "scatter",
        }
        plots = {
            # Keep the historical plot keys as the frontend/render contract.
            # Data-role-specific names are aliases for callers that want
            # semantic labels without breaking existing chart consumers.
            "mean_spectrum": mean_plot,
            "std_spectrum": std_plot,
        }
        if is_feature_table:
            plots["mean_feature_response"] = mean_plot
            plots["std_feature_response"] = std_plot
        return {
            "statistics": {
                "input_type": "FeatureTable" if is_feature_table else "SherpaDataset",
                "summary": {
                    "n_samples": n_samples,
                    "n_features": n_features,
                    "global_mean": float(np.mean(finite_data)) if finite_data.size else None,
                    "global_std": float(np.std(finite_data)) if finite_data.size else None,
                    "missing_count": missing_count,
                    "nonfinite_count": nonfinite_count,
                    "finite_fraction": float(np.count_nonzero(finite_mask) / data.size) if data.size else None,
                    "sample_rows_returned": len(sample_quality),
                    "sample_rows_truncated": max(0, n_samples - len(sample_quality)),
                    "target": target_summary,
                    "quality": quality_summary,
                    "source_context": source_context,
                },
                "sample_quality": sample_quality,
                "plots": plots,
                "data": table_rows,
                "metadata": {
                    "type": "FeatureTable" if is_feature_table else "SherpaDataset",
                    "shape": [n_samples, n_features],
                    "has_wavenumbers": x_coord is not None,
                    "data_role": data_role,
                    "source_context": source_context,
                    "diagnostic_note": (
                        "Feature-table statistics are column-wise variable summaries."
                        if is_feature_table
                        else "Spectral statistics are wavelength/wavenumber-wise summaries."
                    ),
                },
            }
        }

    def _stats_pca(self, pca_data: dict) -> Dict[str, Any]:
        """Compute statistics for PCA results."""
        # Extract PCA components
        metadata = pca_data.get("metadata", {})
        scores_payload = pca_data.get("data")
        if scores_payload is None:
            scores_payload = pca_data.get("scores")
        if scores_payload is None:
            scores_payload = pca_data.get("X_scores")
        if isinstance(scores_payload, SherpaDataset):
            metadata = {**getattr(scores_payload, "meta", {}), **metadata}
            scores_data = np.array(scores_payload.data)
        else:
            scores_data = np.array(scores_payload if scores_payload is not None else [])

        if scores_data.ndim == 1:
            scores_data = scores_data.reshape(-1, 1)
        if scores_data.ndim != 2 or scores_data.size == 0 or not _is_numeric_array(scores_data):
            raise ValueError("stats.summary PCA input requires a non-empty numeric score matrix")
        scores_data = scores_data.astype(np.float64, copy=False)

        n_obs, n_comp = scores_data.shape

        # Scores statistics per PC
        pc_stats = []
        for i in range(n_comp):
            finite_values = scores_data[np.isfinite(scores_data[:, i]), i]
            pc_stats.append(
                {
                    "pc": i + 1,
                    "mean": float(np.mean(finite_values)) if finite_values.size else None,
                    "std": float(np.std(finite_values)) if finite_values.size else None,
                    "min": float(np.min(finite_values)) if finite_values.size else None,
                    "max": float(np.max(finite_values)) if finite_values.size else None,
                    "range": float(np.ptp(finite_values)) if finite_values.size else None,
                    "nonfinite": int(n_obs - finite_values.size),
                }
            )

        # This presentation node reports diagnostics produced by the PCA
        # authority; it does not invent a second outlier algorithm. The
        # dedicated diagnostics.outliers node owns thresholded decisions.
        evr_array = np.asarray(metadata.get("explained_variance_ratio", []), dtype=np.float64).reshape(-1)
        if evr_array.size and not np.all(np.isfinite(evr_array)):
            raise ValueError("stats.summary PCA explained variance must be finite")
        evr = [float(value) for value in evr_array]
        cumulative_var = np.cumsum(evr_array).tolist() if evr_array.size else []
        spe = pca_data.get("spe")
        if spe is None:
            spe = metadata.get("spe", [])
        t2 = pca_data.get("t2")
        if t2 is None:
            t2 = metadata.get("t2", [])
        spe_mean = metadata.get("spe_mean")
        spe_p95 = metadata.get("spe_p95")
        t2_mean = metadata.get("t2_mean")
        t2_p95 = metadata.get("t2_p95")

        return {
            "statistics": {
                "input_type": "PCA",
                "summary": {
                    "n_observations": n_obs,
                    "n_components": n_comp,
                    "total_variance_explained": float(sum(evr)) if evr else 0.0,
                    "nonfinite_score_count": int(scores_data.size - np.count_nonzero(np.isfinite(scores_data))),
                    "spe_mean": float(spe_mean) if spe_mean is not None else None,
                    "spe_p95": float(spe_p95) if spe_p95 is not None else None,
                    "t2_mean": float(t2_mean) if t2_mean is not None else None,
                    "t2_p95": float(t2_p95) if t2_p95 is not None else None,
                },
                "detailed": {
                    "by_pc": pc_stats,
                    "variance": {
                        "explained_variance_ratio": evr,
                        "cumulative": cumulative_var,
                    },
                    "diagnostics": {
                        "t2": t2,
                        "spe": spe,
                    },
                },
                "plots": {
                    "scree": {
                        "x": list(range(1, len(evr) + 1)),
                        "y": evr,
                        "type": "bar",
                    },
                    "cumulative_variance": {
                        "x": list(range(1, len(cumulative_var) + 1)),
                        "y": cumulative_var,
                        "type": "scatter",
                    },
                },
                "data": pc_stats,  # For DataTable
                "metadata": {
                    "type": "PCA",
                    "shape": [n_obs, n_comp],
                    "diagnostic_decisions_deferred_to": "diagnostics.outliers",
                },
            }
        }

    def _stats_mcr(self, mcr_data: dict) -> Dict[str, Any]:
        """Compute statistics for MCR-ALS results."""
        # Extract concentration (C) and spectra (St) matrices
        C = np.array(mcr_data.get("C", mcr_data.get("concentrations", {}).get("data", [])))
        St = np.array(mcr_data.get("St", mcr_data.get("spectra", {}).get("data", [])))

        if C.ndim != 2 or St.ndim != 2 or C.size == 0 or St.size == 0:
            raise ValueError("stats.summary MCR input requires non-empty 2D C and St matrices")
        if not _is_numeric_array(C) or not _is_numeric_array(St):
            raise ValueError("stats.summary MCR matrices must be numeric")
        C = C.astype(np.float64, copy=False)
        St = St.astype(np.float64, copy=False)
        if C.shape[1] != St.shape[0]:
            raise ValueError("stats.summary MCR component dimensions do not agree")
        if not np.all(np.isfinite(C)) or not np.all(np.isfinite(St)):
            raise ValueError("stats.summary MCR matrices must be finite")

        n_obs, n_comp = C.shape

        # Concentration statistics
        conc_stats = []
        for i in range(n_comp):
            conc_stats.append(
                {
                    "component": i + 1,
                    "mean_conc": float(np.mean(C[:, i])),
                    "max_conc": float(np.max(C[:, i])),
                    "min_conc": float(np.min(C[:, i])),
                    "range": float(np.ptp(C[:, i])),
                }
            )

        # Pure spectra statistics
        spectra_stats = []
        for i in range(n_comp):
            spectra_stats.append(
                {
                    "component": i + 1,
                    "max_response": float(np.max(St[i])),
                    "mean_response": float(np.mean(St[i])),
                }
            )

        return {
            "statistics": {
                "input_type": "MCR",
                "summary": {
                    "n_observations": n_obs,
                    "n_components": n_comp,
                    "n_features": St.shape[1],
                },
                "detailed": {
                    "concentrations": conc_stats,
                    "pure_spectra": spectra_stats,
                },
                "plots": {
                    "concentration_ranges": {
                        "components": [f"Comp {i + 1}" for i in range(n_comp)],
                        "max_values": [float(np.max(C[:, i])) for i in range(n_comp)],
                        "type": "bar",
                    },
                },
                "data": conc_stats,  # For DataTable
                "metadata": {
                    "type": "MCR",
                    "shape": [n_obs, n_comp],
                },
            }
        }

    def _stats_peaks(self, rows: list, metadata: dict) -> Dict[str, Any]:
        """Compute statistics for peak-finding consensus results.

        Each row carries distinct detection and sample counts, positional and
        height summaries, half-prominence widths, and absolute window
        integrals. Detection fraction is supplied by the canonical peak node;
        it is not reconstructed from the potentially larger detection count.

        Two axes of variation are reported:
        - **Horizontal (positional)**: within each cluster, how much do
          detected positions scatter across samples (std_pos, min-max range).
        - **Vertical (intensity)**: across clusters, how do median heights
          compare and how tight is the IQR (q1-q3).
        """
        n_peaks = len(rows)
        n_samples = metadata.get("n_samples", 0)
        x_title = metadata.get("x_title", "Position")
        x_units = metadata.get("x_units", "")
        unit_suffix = f" ({x_units})" if x_units else ""

        # Build per-peak table rows for DataTable display
        table_rows = []
        horizontal_stats = []  # positional scatter per cluster
        vertical_stats = []  # intensity variation per cluster

        for i, row in enumerate(rows):
            median_pos = float(row.get("median_pos", 0))
            std_pos = float(row.get("std_pos", 0))
            min_pos = float(row.get("min_pos", median_pos))
            max_pos = float(row.get("max_pos", median_pos))
            detection_count = int(row["detection_count"])
            sample_count = int(row["sample_count"])
            detection_fraction = float(row["detection_fraction"])
            fraction = f"{sample_count}/{n_samples}"
            med_h = float(row.get("median_height", 0))
            q1_h = float(row.get("q1_height", med_h))
            q3_h = float(row.get("q3_height", med_h))
            med_w = float(row["median_half_prominence_width"])
            q1_w = float(row["q1_half_prominence_width"])
            q3_w = float(row["q3_half_prominence_width"])
            med_a = float(row["median_absolute_window_integral"])
            q1_a = float(row["q1_absolute_window_integral"])
            q3_a = float(row["q3_absolute_window_integral"])

            label = f"Peak {i + 1}"

            table_rows.append(
                {
                    "peak": i + 1,
                    "consensus_peak_id": row.get("consensus_peak_id", f"peak-{i + 1:06d}"),
                    "position": median_pos,
                    "pos_std": std_pos,
                    "pos_range": f"{min_pos:.1f}\u2013{max_pos:.1f}",
                    "height": med_h,
                    "height_iqr": f"{q1_h:.4f}\u2013{q3_h:.4f}",
                    "half_prominence_width": med_w,
                    "half_prominence_width_iqr": f"{q1_w:.4f}\u2013{q3_w:.4f}",
                    "absolute_window_integral": med_a,
                    "absolute_window_integral_iqr": f"{q1_a:.4g}\u2013{q3_a:.4g}",
                    "detection_count": detection_count,
                    "sample_count": sample_count,
                    "detected": fraction,
                    "detection_rate": f"{detection_fraction * 100:.0f}%" if n_samples else "\u2013",
                    "member_sample_indices": list(row.get("member_sample_indices", [])),
                    "member_sample_labels": list(row.get("member_sample_labels", [])),
                    "constituent_detections": list(row.get("constituent_detections", [])),
                }
            )

            # Horizontal: positional scatter within this cluster
            horizontal_stats.append(
                {
                    "label": label,
                    "median_pos": median_pos,
                    "std_pos": std_pos,
                    "min_pos": min_pos,
                    "max_pos": max_pos,
                    "range": max_pos - min_pos,
                }
            )

            # Vertical: intensity variation within this cluster
            vertical_stats.append(
                {
                    "label": label,
                    "median_pos": median_pos,
                    "median_height": med_h,
                    "q1_height": q1_h,
                    "q3_height": q3_h,
                    "iqr": q3_h - q1_h,
                    "median_half_prominence_width": med_w,
                    "q1_half_prominence_width": q1_w,
                    "q3_half_prominence_width": q3_w,
                    "median_absolute_window_integral": med_a,
                    "q1_absolute_window_integral": q1_a,
                    "q3_absolute_window_integral": q3_a,
                }
            )

        # Global summary
        if n_peaks > 0:
            heights = [cast(float, v["median_height"]) for v in vertical_stats]
            pos_stds = [cast(float, h["std_pos"]) for h in horizontal_stats]
            summary = {
                "n_peaks": n_peaks,
                "n_samples": n_samples,
                "n_total_detections": metadata.get("n_total_detections", 0),
                "position_range": [horizontal_stats[0]["median_pos"], horizontal_stats[-1]["median_pos"]],
                "mean_height": float(np.mean(heights)),
                "std_height": float(np.std(heights)),
                "max_positional_std": float(max(pos_stds)),
                "mean_positional_std": float(np.mean(pos_stds)),
            }
        else:
            summary = {"n_peaks": 0}

        summary["x_label"] = f"{x_title}{unit_suffix}"

        return {
            "statistics": {
                "input_type": "PeakFinding",
                "summary": summary,
                "data": table_rows,
                "horizontal": horizontal_stats,
                "vertical": vertical_stats,
                "metadata": metadata,
            }
        }

    def _stats_evaluation(self, metrics: dict) -> Dict[str, Any]:
        """Summarize holdout evaluation metrics (classification or regression)."""
        task_type = metrics.get("task_type", "unknown")

        if task_type == "classification":
            table_rows = []
            per_class = metrics.get("per_class", [])
            for entry in per_class:
                table_rows.append(
                    {
                        "class": entry.get("class", "?"),
                        "sensitivity": round(float(entry.get("sensitivity", 0)), 4),
                        "specificity": round(float(entry.get("specificity", 0)), 4),
                        "precision": round(float(entry.get("precision", 0)), 4),
                        "f1": round(float(entry.get("f1", 0)), 4),
                    }
                )

            summary = {
                "task_type": "classification",
                "accuracy": metrics.get("accuracy"),
                "n_classes": metrics.get("n_classes"),
                "classes": metrics.get("classes"),
                "n_samples": metrics.get("n_samples"),
            }

            return {
                "statistics": {
                    "input_type": "EvaluationClassification",
                    "summary": summary,
                    "data": table_rows if table_rows else [summary],
                    "metadata": {"type": "EvaluationClassification"},
                }
            }
        else:
            # Regression metrics
            scalar_keys = (
                "RMSEP",
                "R2",
                "MAE",
                "bias",
                "SEP",
                "RER",
                "n_samples",
                "n_valid_samples",
                "n_invalid_predictions",
                "status",
            )
            summary = {k: metrics[k] for k in scalar_keys if k in metrics}
            summary["task_type"] = "regression"

            return {
                "statistics": {
                    "input_type": "EvaluationRegression",
                    "summary": summary,
                    "data": [summary],
                    "metadata": {"type": "EvaluationRegression"},
                }
            }

    def _stats_array(self, data: np.ndarray, metadata: Optional[dict]) -> Dict[str, Any]:
        """Compute basic statistics for generic array data."""
        raw = np.asarray(data)
        if raw.size == 0:
            summary = {"n_samples": 0, "n_features": 0, "n_values": 0}
            return {
                "statistics": {
                    "input_type": "array",
                    "summary": summary,
                    "data": [summary],
                    "metadata": metadata or {},
                }
            }

        if not _is_numeric_array(raw):
            flat = raw.reshape(-1)
            labels = [str(v) for v in flat.tolist()]
            values, counts = np.unique(np.asarray(labels, dtype=object), return_counts=True)
            order = np.argsort(counts)[::-1]
            rows = [
                {"value": str(values[i]), "count": int(counts[i]), "fraction": float(counts[i] / len(labels))}
                for i in order
            ]
            summary = {
                "n_samples": int(raw.shape[0]) if raw.ndim > 0 else 1,
                "n_features": int(raw.shape[1]) if raw.ndim > 1 else 1,
                "n_values": int(len(labels)),
                "n_unique": int(len(values)),
                "mode": rows[0]["value"] if rows else None,
                "mode_count": rows[0]["count"] if rows else 0,
            }
            return {
                "statistics": {
                    "input_type": "categorical_array",
                    "summary": summary,
                    "data": rows,
                    "metadata": metadata or {},
                }
            }

        data = raw.astype(np.float64, copy=False)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        if data.ndim != 2:
            raise ValueError("stats.summary arrays must be one- or two-dimensional")

        finite = data[np.isfinite(data)]
        nonfinite_count = int(data.size - finite.size)

        summary = {
            "n_samples": data.shape[0],
            "n_features": data.shape[1],
            "n_values": int(data.size),
            "nonfinite_count": nonfinite_count,
            "finite_fraction": float(finite.size / data.size) if data.size else None,
            "mean": float(np.mean(finite)) if finite.size else None,
            "std": float(np.std(finite)) if finite.size else None,
            "min": float(np.min(finite)) if finite.size else None,
            "max": float(np.max(finite)) if finite.size else None,
            "median": float(np.median(finite)) if finite.size else None,
        }

        return {
            "statistics": {
                "input_type": "array",
                "summary": summary,
                "data": [summary],  # For DataTable
                "metadata": metadata or {},
            }
        }

    def _stats_mapping(self, data: dict) -> Dict[str, Any]:
        """Summarize an otherwise unrecognized dict without numeric coercion."""
        unsupported = sorted(
            str(key)
            for key, value in data.items()
            if not isinstance(value, (str, int, float, bool, type(None), np.integer, np.floating, np.bool_))
        )
        if unsupported:
            raise ValueError(
                "stats.summary does not infer semantics for an untyped nested mapping; unsupported keys: "
                + ", ".join(unsupported)
            )
        rows = [{"key": str(k), "value": str(v)} for k, v in sorted(data.items(), key=lambda item: str(item[0]))]
        numeric_values: list[float] = []
        for value in data.values():
            if isinstance(value, (int, float, bool, np.integer, np.floating, np.bool_)):
                numeric_value = float(value)
                if np.isfinite(numeric_value):
                    numeric_values.append(numeric_value)

        summary: dict[str, Any] = {
            "n_keys": len(data),
            "n_numeric_values": len(numeric_values),
            "n_nonfinite_numeric_values": sum(
                1
                for value in data.values()
                if isinstance(value, (int, float, bool, np.integer, np.floating, np.bool_))
                and not np.isfinite(float(value))
            ),
        }
        if numeric_values:
            arr = np.asarray(numeric_values, dtype=np.float64)
            summary.update(
                {
                    "mean": float(np.mean(arr)),
                    "std": float(np.std(arr)),
                    "min": float(np.min(arr)),
                    "max": float(np.max(arr)),
                }
            )

        return {
            "statistics": {
                "input_type": "mapping",
                "summary": summary,
                "data": rows,
                "metadata": {"type": "mapping"},
            }
        }


def build_statistics_result(input_data: Any, *, max_samples: int = 100) -> dict[str, Any]:
    """Return the sole live/generated descriptive-summary result.

    Constructing the registered node here deliberately centralizes dispatch,
    numerical reductions, and result shape. Generated projects call this
    function directly; live DAG execution delegates to it as well.
    """

    node = StatsSummaryNode("canonical-statistics-authority", {"max_samples": max_samples})
    return node._compute(input_data)


bind_stable_execution_contract(
    StatsSummaryNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.stats.summary",
    implementation_version="1.1.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="aggregates_samples",
    feature_effect="transforms_features",
    axis_effect="removes_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 5, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/output.md",
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "NIST/SEMATECH e-Handbook of Statistical Methods, Exploratory Data Analysis, "
        "https://www.itl.nist.gov/div898/handbook/eda/eda.htm",
    ),
)


__all__ = ["StatsSummaryNode", "build_statistics_result"]
