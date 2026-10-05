"""One numerical authority for hierarchical cluster analysis (HCA)."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

import numpy as np
from scipy.cluster.hierarchy import dendrogram, fcluster, is_valid_linkage, linkage
from sklearn.metrics import davies_bouldin_score, silhouette_score

HCA_STATE_SERIALIZER = "spectrasherpa.model.hca-state/1"
HCA_PARAMETER_KEYS = frozenset({"n_clusters", "linkage", "metric"})
HCA_LINKAGES = frozenset({"ward", "average", "complete", "single"})
HCA_METRICS = frozenset({"euclidean", "manhattan", "cosine"})
HCA_LABEL_RULE = "zero_based_by_first_observation"
HCA_EMBEDDING_RULE = "centered_svd_two_components_canonical_sign"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_QUALITY_KEYS = frozenset(
    {
        "silhouette_score",
        "silhouette_reason",
        "davies_bouldin_score",
        "davies_bouldin_reason",
    }
)


def canonical_hca_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """Validate the closed scientist-controlled HCA parameter set."""

    if set(parameters) != HCA_PARAMETER_KEYS:
        raise ValueError("HCA parameters must use the exact current three-field schema")
    n_clusters = parameters["n_clusters"]
    if isinstance(n_clusters, bool) or not isinstance(n_clusters, int):
        raise ValueError("HCA n_clusters must be an integer")
    if not 2 <= n_clusters <= 500:
        raise ValueError("HCA n_clusters must be between 2 and 500")
    linkage_method = parameters["linkage"]
    if not isinstance(linkage_method, str) or linkage_method not in HCA_LINKAGES:
        raise ValueError("HCA linkage must be one of: average, complete, single, ward")
    metric = parameters["metric"]
    if not isinstance(metric, str) or metric not in HCA_METRICS:
        raise ValueError("HCA metric must be one of: cosine, euclidean, manhattan")
    if linkage_method == "ward" and metric != "euclidean":
        raise ValueError("Ward linkage requires euclidean metric")
    return {"n_clusters": n_clusters, "linkage": linkage_method, "metric": metric}


def _matrix(input_data: Any) -> np.ndarray:
    value = input_data.data if hasattr(input_data, "data") else input_data
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 1:
        raise ValueError("HCA input must be a two-dimensional matrix with at least two observations")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("HCA input must contain only finite values")
    return np.ascontiguousarray(matrix)


def _matrix_digest(matrix: np.ndarray) -> str:
    """Hash one platform-independent float64 representation of the cohort."""

    canonical = np.ascontiguousarray(matrix, dtype="<f8")
    return hashlib.sha256(canonical.tobytes(order="C")).hexdigest()


def _stable_labels(raw_labels: np.ndarray) -> np.ndarray:
    """Remove SciPy's incidental label numbers without changing the partition."""

    ordered = sorted(np.unique(raw_labels).tolist(), key=lambda label: int(np.flatnonzero(raw_labels == label)[0]))
    mapping = {label: index for index, label in enumerate(ordered)}
    return np.asarray([mapping[label] for label in raw_labels], dtype=np.int64)


def _presentation_embedding(matrix: np.ndarray) -> tuple[np.ndarray, str]:
    if matrix.shape[1] == 1:
        return np.column_stack((matrix[:, 0], np.zeros(matrix.shape[0]))), "single_feature_axis"
    if matrix.shape[1] == 2:
        return np.array(matrix, copy=True), "two_feature_axes"
    centered = matrix - np.mean(matrix, axis=0)
    u, singular_values, vt = np.linalg.svd(centered, full_matrices=False)
    scores = u[:, :2] * singular_values[:2]
    for component in range(scores.shape[1]):
        loading = vt[component]
        anchor = int(np.argmax(np.abs(loading)))
        if loading[anchor] < 0.0:
            scores[:, component] *= -1.0
    return scores, HCA_EMBEDDING_RULE


def _quality(matrix: np.ndarray, labels: np.ndarray, *, metric: str) -> dict[str, object]:
    observed = int(np.unique(labels).size)
    if observed < 2 or observed >= matrix.shape[0]:
        return {
            "silhouette_score": None,
            "silhouette_reason": "requires_between_two_and_n_minus_one_observed_clusters",
            "davies_bouldin_score": None,
            "davies_bouldin_reason": "requires_between_two_and_n_minus_one_observed_clusters",
        }
    sklearn_metric = "manhattan" if metric == "manhattan" else metric
    result: dict[str, object] = {
        "silhouette_score": float(silhouette_score(matrix, labels, metric=sklearn_metric)),
        "silhouette_reason": None,
    }
    if metric == "euclidean":
        result.update(
            {
                "davies_bouldin_score": float(davies_bouldin_score(matrix, labels)),
                "davies_bouldin_reason": None,
            }
        )
    else:
        result.update(
            {
                "davies_bouldin_score": None,
                "davies_bouldin_reason": "euclidean_geometry_only",
            }
        )
    return result


def fit_hca(input_data: Any, *, parameters: Mapping[str, object]) -> dict[str, Any]:
    """Fit one cohort hierarchy and return its closed, replayable state."""

    canonical = canonical_hca_parameters(parameters)
    matrix = _matrix(input_data)
    n_clusters = int(canonical["n_clusters"])
    if n_clusters > matrix.shape[0]:
        raise ValueError("HCA n_clusters may not exceed the number of observations")
    if canonical["metric"] == "cosine" and np.any(np.linalg.norm(matrix, axis=1) == 0.0):
        raise ValueError("HCA cosine distance is undefined for zero-norm observations")
    scipy_metric = "cityblock" if canonical["metric"] == "manhattan" else str(canonical["metric"])
    hierarchy = linkage(matrix, method=str(canonical["linkage"]), metric=scipy_metric)
    if not np.all(np.isfinite(hierarchy)):
        raise ValueError("HCA produced a non-finite linkage matrix")
    labels = _stable_labels(fcluster(hierarchy, t=n_clusters, criterion="maxclust"))
    embedding, embedding_method = _presentation_embedding(matrix)
    quality = _quality(matrix, labels, metric=str(canonical["metric"]))
    return {
        "schema_version": HCA_STATE_SERIALIZER,
        "parameters": canonical,
        "n_samples": int(matrix.shape[0]),
        "n_features": int(matrix.shape[1]),
        "input_sha256": _matrix_digest(matrix),
        "requested_clusters": n_clusters,
        "observed_clusters": int(np.unique(labels).size),
        "label_rule": HCA_LABEL_RULE,
        "embedding_method": embedding_method,
        "linkage_matrix": hierarchy.tolist(),
        "labels": labels.tolist(),
        "embedding": embedding.tolist(),
        "quality": quality,
    }


def validate_hca_state(state: object) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ValueError("HCA fitted state must be an object")
    required = {
        "schema_version",
        "parameters",
        "n_samples",
        "n_features",
        "input_sha256",
        "requested_clusters",
        "observed_clusters",
        "label_rule",
        "embedding_method",
        "linkage_matrix",
        "labels",
        "embedding",
        "quality",
    }
    if set(state) != required or state.get("schema_version") != HCA_STATE_SERIALIZER:
        raise ValueError("HCA fitted state must use the exact current schema")
    parameters = state["parameters"]
    if not isinstance(parameters, Mapping):
        raise ValueError("HCA fitted state parameters must be an object")
    canonical = canonical_hca_parameters(parameters)
    labels = np.asarray(state["labels"])
    hierarchy = np.asarray(state["linkage_matrix"], dtype=np.float64)
    embedding = np.asarray(state["embedding"], dtype=np.float64)
    n_samples = state["n_samples"]
    if isinstance(n_samples, bool) or not isinstance(n_samples, int) or n_samples < 2:
        raise ValueError("HCA fitted state has an invalid observation count")
    n_features = state["n_features"]
    if isinstance(n_features, bool) or not isinstance(n_features, int) or n_features < 1:
        raise ValueError("HCA fitted state has an invalid feature count")
    if not isinstance(state["input_sha256"], str) or _SHA256_PATTERN.fullmatch(state["input_sha256"]) is None:
        raise ValueError("HCA fitted state has an invalid cohort digest")
    if labels.shape != (n_samples,) or hierarchy.shape != (n_samples - 1, 4) or embedding.shape != (n_samples, 2):
        raise ValueError("HCA fitted state array shapes do not match its observation count")
    if not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("HCA fitted state labels must be integers")
    if not np.all(np.isfinite(hierarchy)) or not np.all(np.isfinite(embedding)):
        raise ValueError("HCA fitted state contains non-finite values")
    is_valid_linkage(hierarchy, throw=True, name="HCA fitted state linkage_matrix")
    requested = state["requested_clusters"]
    observed = state["observed_clusters"]
    if requested != canonical["n_clusters"] or isinstance(observed, bool) or not isinstance(observed, int):
        raise ValueError("HCA fitted state cluster counts do not match its parameters")
    unique_labels = np.unique(labels)
    if not 1 <= observed <= requested or unique_labels.tolist() != list(range(observed)):
        raise ValueError("HCA fitted state labels do not match its observed cluster count")
    expected_labels = _stable_labels(fcluster(hierarchy, t=requested, criterion="maxclust"))
    if not np.array_equal(labels, expected_labels):
        raise ValueError("HCA fitted state labels do not match its linkage hierarchy")
    first_occurrences = [int(np.flatnonzero(labels == label)[0]) for label in unique_labels]
    if first_occurrences != sorted(first_occurrences):
        raise ValueError("HCA fitted state labels do not follow the stable label convention")
    if state["label_rule"] != HCA_LABEL_RULE:
        raise ValueError("HCA fitted state uses an unknown label convention")
    expected_embedding = (
        "single_feature_axis" if n_features == 1 else "two_feature_axes" if n_features == 2 else HCA_EMBEDDING_RULE
    )
    if state["embedding_method"] != expected_embedding:
        raise ValueError("HCA fitted state uses an invalid presentation embedding")
    quality = state["quality"]
    if not isinstance(quality, dict) or set(quality) != _QUALITY_KEYS:
        raise ValueError("HCA fitted state quality must use the exact current schema")
    for score_name in ("silhouette_score", "davies_bouldin_score"):
        score = quality[score_name]
        reason = quality[score_name.replace("_score", "_reason")]
        if score is None:
            if not isinstance(reason, str) or not reason:
                raise ValueError("HCA unavailable quality scores require an explicit reason")
        elif (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not np.isfinite(score)
            or reason is not None
        ):
            raise ValueError("HCA available quality scores must be finite and have no unavailable reason")
    return state


def replay_hca_labels(input_data: Any, state: object) -> np.ndarray:
    """Replay labels only for the exact cohort that produced the hierarchy."""

    validated = validate_hca_state(state)
    matrix = _matrix(input_data)
    digest = _matrix_digest(matrix)
    if matrix.shape != (validated["n_samples"], validated["n_features"]) or digest != validated["input_sha256"]:
        raise ValueError("HCA hierarchy may only be replayed for its exact fitted cohort")
    return np.asarray(validated["labels"], dtype=np.int64)


def hca_dendrogram_payload(state: object, sample_labels: list[object] | None = None) -> dict[str, Any]:
    validated = validate_hca_state(state)
    hierarchy = np.asarray(validated["linkage_matrix"], dtype=np.float64)
    dend = dendrogram(hierarchy, no_plot=True)
    # SciPy emits one four-point branch for every merge.  Mapping each branch
    # to a Plotly trace exceeds the canonical 512-trace contract for ordinary
    # cohorts such as Breast Cancer (569 samples).  Group branches by their
    # exact SciPy colour and separate them with nulls.  Plotly preserves every
    # branch geometry while the trace count is bounded by the colour palette,
    # independent of sample count.
    grouped: dict[str, tuple[list[float | None], list[float | None]]] = {}
    for indices, distances, color in zip(dend["icoord"], dend["dcoord"], dend["color_list"]):
        x_values, y_values = grouped.setdefault(str(color), ([], []))
        if x_values:
            x_values.append(None)
            y_values.append(None)
        x_values.extend(float(value) for value in distances)
        y_values.extend(float(value) for value in indices)
    traces = [
        {
            "x": x_values,
            "y": y_values,
            "type": "scatter",
            "mode": "lines",
            "line": {"color": color, "width": 3},
            "showlegend": False,
        }
        for color, (x_values, y_values) in grouped.items()
    ]
    max_distance = max(float(np.max(row)) for row in dend["dcoord"])
    y_axis: dict[str, Any] = {
        "title": "Sample",
        "showgrid": False,
        "zeroline": False,
        "side": "right",
        "range": [0, validated["n_samples"] * 10],
    }
    if sample_labels is not None and len(sample_labels) == validated["n_samples"]:
        y_axis["ticktext"] = [str(sample_labels[index]) for index in dend["leaves"]]
        y_axis["tickvals"] = list(range(5, validated["n_samples"] * 10 + 5, 10))
    return {
        "data": traces,
        "layout": {
            "title": f"Hierarchical Clustering Dendrogram ({validated['parameters']['linkage']} linkage)",
            "xaxis": {"title": "Distance", "showgrid": True, "range": [0, max(1.0, max_distance) * 1.02]},
            "yaxis": y_axis,
            "hovermode": "closest",
            "height": max(1000, validated["n_samples"] * 15),
            "margin": {"l": 50, "r": 150},
        },
        "metadata": {
            "presentation": "exact_color_grouped_segments",
            "sample_count": int(validated["n_samples"]),
            "branch_count": len(dend["icoord"]),
            "trace_count": len(traces),
        },
    }


def hca_export_outputs(input_data: Any, *, parameters: Mapping[str, object]) -> dict[str, Any]:
    state = fit_hca(input_data, parameters=parameters)
    return hca_outputs_from_state(input_data, state)


def _source_labels(input_data: Any) -> list[object] | None:
    axis = getattr(input_data, "sample_axis", None)
    if axis is None:
        return None
    for attribute in ("labels", "data"):
        value = getattr(axis, attribute, None)
        if value is not None:
            return value.tolist() if hasattr(value, "tolist") else list(value)
    return None


def hca_outputs_from_state(input_data: Any, state: object) -> dict[str, Any]:
    """Project one validated HCA state into every scientist-facing output."""

    validated = validate_hca_state(state)
    source_labels = _source_labels(input_data)
    parameters = validated["parameters"]
    quality = validated["quality"]
    observed_clusters = int(validated["observed_clusters"])
    requested_clusters = int(validated["requested_clusters"])
    labels = list(validated["labels"])
    sample_labels = [str(label) for label in labels]
    dendrogram_payload = hca_dendrogram_payload(validated, source_labels)
    return {
        "default": labels,
        "model": validated,
        "labels": labels,
        "cluster_assignment": labels,
        "cluster_summary": cluster_summary(labels, source_labels),
        "linkage_matrix": validated["linkage_matrix"],
        "dendrogram_data": dendrogram_payload,
        "embedding": validated["embedding"],
        "n_clusters": observed_clusters,
        "plots": {"dendrogram": dendrogram_payload, "default": dendrogram_payload},
        "metadata": {
            "type": "HCA",
            "output_type": "clustering",
            "requested_clusters": requested_clusters,
            "observed_clusters": observed_clusters,
            "linkage": parameters["linkage"],
            "metric": parameters["metric"],
            "embedding": validated["embedding_method"],
            "sample_labels": sample_labels,
            "label_categories": sorted(set(sample_labels)),
            "source_labels": source_labels,
            "quality_summary": {
                "requested_clusters": requested_clusters,
                "observed_clusters": observed_clusters,
                "linkage": parameters["linkage"],
                "metric": parameters["metric"],
                "silhouette_score": quality["silhouette_score"],
                "davies_bouldin_score": quality["davies_bouldin_score"],
            },
        },
    }


def cluster_summary(labels: list[int], source_labels: list[object] | None = None) -> list[dict[str, Any]]:
    label_array = np.asarray(labels, dtype=np.int64)
    rows: list[dict[str, Any]] = []
    for label in sorted(np.unique(label_array).tolist()):
        indices = np.flatnonzero(label_array == label)
        row: dict[str, Any] = {
            "cluster": int(label),
            "count": int(indices.size),
            "fraction": float(indices.size / label_array.size),
        }
        if source_labels is not None:
            row["sample_preview"] = [str(source_labels[index]) for index in indices[:10]]
            row["preview_truncated"] = bool(indices.size > 10)
        rows.append(row)
    return rows
