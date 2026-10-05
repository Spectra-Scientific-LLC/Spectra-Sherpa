"""Canonical numerical authorities for K-means and DBSCAN clustering."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

import numpy as np
from sklearn.cluster import DBSCAN, KMeans
from sklearn.metrics import davies_bouldin_score, silhouette_score

KMEANS_STATE_SERIALIZER = "spectrasherpa.model.kmeans-state/1"
DBSCAN_STATE_SERIALIZER = "spectrasherpa.model.dbscan-state/1"
KMEANS_PARAMETER_KEYS = frozenset({"n_clusters", "n_init", "max_iter", "random_state"})
DBSCAN_PARAMETER_KEYS = frozenset({"eps", "min_samples", "metric"})
DBSCAN_METRICS = frozenset({"euclidean", "manhattan", "cosine"})
CLUSTER_LABEL_RULE = "zero_based_by_first_observation_noise_minus_one"
KMEANS_PREDICTION_RULE = "nearest_euclidean_centroid_lowest_canonical_label_on_tie"
DBSCAN_APPLICATION_SCOPE = "exact_fitted_cohort_only_no_out_of_sample_assignment"
PRESENTATION_EMBEDDING_RULE = "centered_svd_two_components_canonical_sign"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_QUALITY_KEYS = frozenset(
    {
        "population",
        "silhouette_score",
        "silhouette_reason",
        "davies_bouldin_score",
        "davies_bouldin_reason",
    }
)
_CLUSTER_COLORS = (
    "#2563eb",
    "#dc2626",
    "#16a34a",
    "#d97706",
    "#7c3aed",
    "#0891b2",
)


def canonical_kmeans_parameters(parameters: Mapping[str, object]) -> dict[str, int]:
    """Validate the exact scientist-controlled K-means parameter set."""

    if set(parameters) != KMEANS_PARAMETER_KEYS:
        raise ValueError("K-means parameters must use the exact current four-field schema")
    result: dict[str, int] = {}
    bounds = {
        "n_clusters": (2, 500),
        "n_init": (1, 100),
        "max_iter": (1, 10_000),
        "random_state": (0, 2**32 - 1),
    }
    for name, (lower, upper) in bounds.items():
        value = parameters[name]
        if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
            raise ValueError(f"K-means {name} must be an integer between {lower} and {upper}")
        result[name] = value
    return result


def canonical_dbscan_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """Validate the exact scientist-controlled DBSCAN parameter set."""

    if set(parameters) != DBSCAN_PARAMETER_KEYS:
        raise ValueError("DBSCAN parameters must use the exact current three-field schema")
    eps = parameters["eps"]
    if isinstance(eps, bool) or not isinstance(eps, (int, float)) or not np.isfinite(eps) or eps <= 0.0:
        raise ValueError("DBSCAN eps must be a finite positive number in the input feature units")
    min_samples = parameters["min_samples"]
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or not 2 <= min_samples <= 100_000:
        raise ValueError("DBSCAN min_samples must be an integer between 2 and 100000")
    metric = parameters["metric"]
    if not isinstance(metric, str) or metric not in DBSCAN_METRICS:
        raise ValueError("DBSCAN metric must be one of: cosine, euclidean, manhattan")
    return {"eps": float(eps), "min_samples": min_samples, "metric": metric}


def _matrix(input_data: Any, *, operation: str) -> np.ndarray:
    value = input_data.data if hasattr(input_data, "data") else input_data
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 1:
        raise ValueError(f"{operation} input must be a two-dimensional matrix with at least two observations")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{operation} input must contain only finite values")
    return np.ascontiguousarray(matrix)


def _matrix_digest(matrix: np.ndarray) -> str:
    canonical = np.ascontiguousarray(matrix, dtype="<f8")
    return hashlib.sha256(canonical.tobytes(order="C")).hexdigest()


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
    return scores, PRESENTATION_EMBEDDING_RULE


def _stable_labels(raw_labels: np.ndarray) -> tuple[np.ndarray, tuple[int, ...]]:
    cluster_labels = [int(label) for label in np.unique(raw_labels) if int(label) != -1]
    ordered = tuple(sorted(cluster_labels, key=lambda label: int(np.flatnonzero(raw_labels == label)[0])))
    mapping = {label: index for index, label in enumerate(ordered)}
    stable = np.asarray(
        [-1 if int(label) == -1 else mapping[int(label)] for label in raw_labels],
        dtype=np.int64,
    )
    return stable, ordered


def _cluster_map_visualization(
    *,
    embedding: object,
    labels: object,
    source_labels: list[object] | None,
    embedding_method: str,
    method_label: str,
) -> dict[str, Any]:
    coordinates = np.asarray(embedding, dtype=np.float64)
    assignments = np.asarray(labels, dtype=np.int64)
    plot_labels = (
        [str(label) for label in source_labels]
        if source_labels is not None and len(source_labels) == assignments.size
        else [f"Sample {index + 1}" for index in range(assignments.size)]
    )
    if embedding_method == PRESENTATION_EMBEDDING_RULE:
        axis_titles = ("Centered-SVD component 1", "Centered-SVD component 2")
    elif embedding_method == "two_feature_axes":
        axis_titles = ("Input feature 1", "Input feature 2")
    else:
        axis_titles = ("Input feature 1", "Zero reference")

    traces: list[dict[str, Any]] = []
    ordered_labels = sorted(np.unique(assignments).tolist())
    for color_index, cluster_label in enumerate(ordered_labels):
        mask = assignments == cluster_label
        display_label = "Noise" if cluster_label == -1 else f"Cluster {cluster_label + 1}"
        color = "#64748b" if cluster_label == -1 else _CLUSTER_COLORS[color_index % len(_CLUSTER_COLORS)]
        traces.append(
            {
                "type": "scatter",
                "mode": "markers",
                "name": display_label,
                "x": coordinates[mask, 0].tolist(),
                "y": coordinates[mask, 1].tolist(),
                "text": [plot_labels[index] for index in np.flatnonzero(mask)],
                "marker": {"color": color, "size": 8, "opacity": 0.8},
                "hovertemplate": ("%{text}<br>" + display_label + "<br>%{x:.4g}, %{y:.4g}<extra></extra>"),
            }
        )
    return {
        "data": traces,
        "layout": {
            "title": {
                "text": (
                    f"{method_label} assignment map"
                    "<br><sup>Projection is for inspection; clustering used the full input space.</sup>"
                ),
                "x": 0.02,
                "xanchor": "left",
            },
            "margin": {"t": 88},
            "xaxis": {"title": {"text": axis_titles[0]}},
            "yaxis": {"title": {"text": axis_titles[1]}},
            "showlegend": True,
            "legend": {"title": {"text": "Full-space assignment"}},
        },
        "metadata": {
            "embedding_method": embedding_method,
            "n_samples": int(assignments.size),
            "n_clusters": int(sum(label != -1 for label in ordered_labels)),
            "noise_count": int(np.count_nonzero(assignments == -1)),
        },
    }


def _quality(
    matrix: np.ndarray,
    labels: np.ndarray,
    *,
    metric: str,
    exclude_noise: bool,
) -> dict[str, object]:
    if exclude_noise:
        retained = labels != -1
        population = "non_noise_samples_only"
        quality_matrix = matrix[retained]
        quality_labels = labels[retained]
    else:
        population = "all_samples"
        quality_matrix = matrix
        quality_labels = labels
    observed = int(np.unique(quality_labels).size)
    if observed < 2 or observed >= quality_labels.size:
        reason = "requires_between_two_and_n_minus_one_clusters_in_quality_population"
        return {
            "population": population,
            "silhouette_score": None,
            "silhouette_reason": reason,
            "davies_bouldin_score": None,
            "davies_bouldin_reason": reason,
        }
    sklearn_metric = "manhattan" if metric == "manhattan" else metric
    result: dict[str, object] = {
        "population": population,
        "silhouette_score": float(silhouette_score(quality_matrix, quality_labels, metric=sklearn_metric)),
        "silhouette_reason": None,
    }
    if metric == "euclidean":
        result.update(
            {
                "davies_bouldin_score": float(davies_bouldin_score(quality_matrix, quality_labels)),
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


def _source_labels(input_data: Any) -> list[object] | None:
    axis = getattr(input_data, "sample_axis", None)
    if axis is None:
        return None
    for attribute in ("labels", "data"):
        value = getattr(axis, attribute, None)
        if value is not None:
            return value.tolist() if hasattr(value, "tolist") else list(value)
    return None


def _cluster_summary(labels: list[int], source_labels: list[object] | None) -> list[dict[str, object]]:
    array = np.asarray(labels, dtype=np.int64)
    rows: list[dict[str, object]] = []
    for label in sorted(np.unique(array).tolist()):
        indices = np.flatnonzero(array == label)
        row: dict[str, object] = {
            "cluster": int(label),
            "count": int(indices.size),
            "fraction": float(indices.size / array.size),
        }
        if source_labels is not None:
            row["sample_preview"] = [str(source_labels[index]) for index in indices[:10]]
            row["preview_truncated"] = bool(indices.size > 10)
        rows.append(row)
    return rows


def _validate_quality(value: object, *, expected_population: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _QUALITY_KEYS or value.get("population") != expected_population:
        raise ValueError("clustering fitted-state quality must use the exact current schema")
    for score_name in ("silhouette_score", "davies_bouldin_score"):
        score = value[score_name]
        reason = value[score_name.replace("_score", "_reason")]
        if score is None:
            if not isinstance(reason, str) or not reason:
                raise ValueError("unavailable clustering quality scores require an explicit reason")
        elif (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not np.isfinite(score)
            or reason is not None
        ):
            raise ValueError("available clustering quality scores must be finite and have no unavailable reason")
    return value


def fit_kmeans(input_data: Any, *, parameters: Mapping[str, object]) -> dict[str, Any]:
    """Fit deterministic K-means and return its closed centroid state."""

    canonical = canonical_kmeans_parameters(parameters)
    matrix = _matrix(input_data, operation="K-means")
    n_clusters = canonical["n_clusters"]
    if n_clusters > matrix.shape[0]:
        raise ValueError("K-means n_clusters may not exceed the number of observations")
    if np.unique(matrix, axis=0).shape[0] < n_clusters:
        raise ValueError("K-means requires at least n_clusters distinct observations")
    model = KMeans(
        n_clusters=n_clusters,
        n_init=canonical["n_init"],
        max_iter=canonical["max_iter"],
        random_state=canonical["random_state"],
        algorithm="lloyd",
        tol=1e-4,
    ).fit(matrix)
    labels, raw_order = _stable_labels(np.asarray(model.labels_, dtype=np.int64))
    centroids = np.asarray(model.cluster_centers_, dtype=np.float64)[list(raw_order)]
    embedding, embedding_method = _presentation_embedding(matrix)
    residual = matrix - centroids[labels]
    inertia = float(np.sum(np.square(residual), dtype=np.float64))
    return {
        "schema_version": KMEANS_STATE_SERIALIZER,
        "parameters": canonical,
        "n_samples": int(matrix.shape[0]),
        "n_features": int(matrix.shape[1]),
        "training_input_sha256": _matrix_digest(matrix),
        "label_rule": CLUSTER_LABEL_RULE,
        "prediction_rule": KMEANS_PREDICTION_RULE,
        "embedding_method": embedding_method,
        "labels": labels.tolist(),
        "centroids": centroids.tolist(),
        "inertia": inertia,
        "n_iter": int(model.n_iter_),
        "embedding": embedding.tolist(),
        "quality": _quality(matrix, labels, metric="euclidean", exclude_noise=False),
    }


def validate_kmeans_state(state: object) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ValueError("K-means fitted state must be an object")
    required = {
        "schema_version",
        "parameters",
        "n_samples",
        "n_features",
        "training_input_sha256",
        "label_rule",
        "prediction_rule",
        "embedding_method",
        "labels",
        "centroids",
        "inertia",
        "n_iter",
        "embedding",
        "quality",
    }
    if set(state) != required or state.get("schema_version") != KMEANS_STATE_SERIALIZER:
        raise ValueError("K-means fitted state must use the exact current schema")
    parameters = state["parameters"]
    if not isinstance(parameters, Mapping):
        raise ValueError("K-means fitted-state parameters must be an object")
    canonical = canonical_kmeans_parameters(parameters)
    n_samples = state["n_samples"]
    n_features = state["n_features"]
    if isinstance(n_samples, bool) or not isinstance(n_samples, int) or n_samples < 2:
        raise ValueError("K-means fitted state has an invalid observation count")
    if isinstance(n_features, bool) or not isinstance(n_features, int) or n_features < 1:
        raise ValueError("K-means fitted state has an invalid feature count")
    digest = state["training_input_sha256"]
    if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError("K-means fitted state has an invalid training digest")
    labels = np.asarray(state["labels"])
    centroids = np.asarray(state["centroids"], dtype=np.float64)
    embedding = np.asarray(state["embedding"], dtype=np.float64)
    if labels.shape != (n_samples,) or centroids.shape != (canonical["n_clusters"], n_features):
        raise ValueError("K-means fitted-state arrays do not match their declared dimensions")
    if embedding.shape != (n_samples, 2):
        raise ValueError("K-means fitted-state embedding does not match its observation count")
    if not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("K-means fitted-state labels must be integers")
    if np.unique(labels).tolist() != list(range(canonical["n_clusters"])):
        raise ValueError("K-means fitted-state labels must represent every canonical cluster")
    first_occurrences = [int(np.flatnonzero(labels == label)[0]) for label in range(canonical["n_clusters"])]
    if first_occurrences != sorted(first_occurrences):
        raise ValueError("K-means fitted-state labels do not follow the stable label convention")
    if not np.all(np.isfinite(centroids)) or not np.all(np.isfinite(embedding)):
        raise ValueError("K-means fitted state contains non-finite arrays")
    inertia = state["inertia"]
    if isinstance(inertia, bool) or not isinstance(inertia, (int, float)) or not np.isfinite(inertia) or inertia < 0:
        raise ValueError("K-means fitted state has invalid inertia")
    n_iter = state["n_iter"]
    if isinstance(n_iter, bool) or not isinstance(n_iter, int) or not 1 <= n_iter <= canonical["max_iter"]:
        raise ValueError("K-means fitted state has an invalid iteration count")
    if state["label_rule"] != CLUSTER_LABEL_RULE or state["prediction_rule"] != KMEANS_PREDICTION_RULE:
        raise ValueError("K-means fitted state uses an unknown assignment convention")
    expected_embedding = (
        "single_feature_axis"
        if n_features == 1
        else "two_feature_axes" if n_features == 2 else PRESENTATION_EMBEDDING_RULE
    )
    if state["embedding_method"] != expected_embedding:
        raise ValueError("K-means fitted state uses an invalid presentation embedding")
    _validate_quality(state["quality"], expected_population="all_samples")
    return state


def apply_kmeans(input_data: Any, state: object) -> np.ndarray:
    """Assign samples to the nearest canonical fitted centroid."""

    validated = validate_kmeans_state(state)
    matrix = _matrix(input_data, operation="K-means application")
    if matrix.shape[1] != validated["n_features"]:
        raise ValueError("K-means application feature count does not match the fitted centroids")
    centroids = np.asarray(validated["centroids"], dtype=np.float64)
    squared_distances = np.sum(np.square(matrix[:, None, :] - centroids[None, :, :]), axis=2)
    return np.argmin(squared_distances, axis=1).astype(np.int64)


def kmeans_outputs_from_state(input_data: Any, state: object) -> dict[str, Any]:
    validated = validate_kmeans_state(state)
    labels = list(validated["labels"])
    source_labels = _source_labels(input_data)
    quality = validated["quality"]
    n_clusters = int(validated["parameters"]["n_clusters"])
    return {
        "default": labels,
        "model": validated,
        "labels": labels,
        "cluster_assignment": labels,
        "cluster_summary": _cluster_summary(labels, source_labels),
        "centroids": validated["centroids"],
        "inertia": validated["inertia"],
        "n_clusters": n_clusters,
        "embedding": validated["embedding"],
        "visualization": _cluster_map_visualization(
            embedding=validated["embedding"],
            labels=labels,
            source_labels=source_labels,
            embedding_method=validated["embedding_method"],
            method_label="K-Means",
        ),
        "metadata": {
            "type": "KMeans",
            "output_type": "clustering",
            "n_clusters": n_clusters,
            "embedding": validated["embedding_method"],
            "sample_labels": source_labels,
            "label_categories": [str(label) for label in range(n_clusters)],
            "source_labels": source_labels,
            "prediction_rule": validated["prediction_rule"],
            "quality_summary": {
                "population": quality["population"],
                "silhouette_score": quality["silhouette_score"],
                "davies_bouldin_score": quality["davies_bouldin_score"],
                "inertia": validated["inertia"],
            },
        },
    }


def kmeans_export_outputs(input_data: Any, *, parameters: Mapping[str, object]) -> dict[str, Any]:
    return kmeans_outputs_from_state(input_data, fit_kmeans(input_data, parameters=parameters))


def fit_dbscan(input_data: Any, *, parameters: Mapping[str, object]) -> dict[str, Any]:
    """Fit one density partition and return its exact-cohort state."""

    canonical = canonical_dbscan_parameters(parameters)
    matrix = _matrix(input_data, operation="DBSCAN")
    if canonical["metric"] == "cosine" and np.any(np.linalg.norm(matrix, axis=1) == 0.0):
        raise ValueError("DBSCAN cosine distance is undefined for zero-norm observations")
    raw_model = DBSCAN(
        eps=canonical["eps"],
        min_samples=canonical["min_samples"],
        metric=canonical["metric"],
    ).fit(matrix)
    labels, _ = _stable_labels(np.asarray(raw_model.labels_, dtype=np.int64))
    embedding, embedding_method = _presentation_embedding(matrix)
    core_indices = np.asarray(raw_model.core_sample_indices_, dtype=np.int64)
    observed_clusters = len([label for label in np.unique(labels) if int(label) != -1])
    return {
        "schema_version": DBSCAN_STATE_SERIALIZER,
        "parameters": canonical,
        "n_samples": int(matrix.shape[0]),
        "n_features": int(matrix.shape[1]),
        "training_input_sha256": _matrix_digest(matrix),
        "label_rule": CLUSTER_LABEL_RULE,
        "application_scope": DBSCAN_APPLICATION_SCOPE,
        "embedding_method": embedding_method,
        "labels": labels.tolist(),
        "core_sample_indices": core_indices.tolist(),
        "observed_clusters": int(observed_clusters),
        "noise_count": int(np.sum(labels == -1)),
        "embedding": embedding.tolist(),
        "quality": _quality(
            matrix,
            labels,
            metric=str(canonical["metric"]),
            exclude_noise=True,
        ),
    }


def validate_dbscan_state(state: object) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ValueError("DBSCAN fitted state must be an object")
    required = {
        "schema_version",
        "parameters",
        "n_samples",
        "n_features",
        "training_input_sha256",
        "label_rule",
        "application_scope",
        "embedding_method",
        "labels",
        "core_sample_indices",
        "observed_clusters",
        "noise_count",
        "embedding",
        "quality",
    }
    if set(state) != required or state.get("schema_version") != DBSCAN_STATE_SERIALIZER:
        raise ValueError("DBSCAN fitted state must use the exact current schema")
    parameters = state["parameters"]
    if not isinstance(parameters, Mapping):
        raise ValueError("DBSCAN fitted-state parameters must be an object")
    canonical_dbscan_parameters(parameters)
    n_samples = state["n_samples"]
    n_features = state["n_features"]
    if isinstance(n_samples, bool) or not isinstance(n_samples, int) or n_samples < 2:
        raise ValueError("DBSCAN fitted state has an invalid observation count")
    if isinstance(n_features, bool) or not isinstance(n_features, int) or n_features < 1:
        raise ValueError("DBSCAN fitted state has an invalid feature count")
    digest = state["training_input_sha256"]
    if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError("DBSCAN fitted state has an invalid training digest")
    labels = np.asarray(state["labels"])
    raw_core_indices = state["core_sample_indices"]
    core_indices = (
        np.asarray([], dtype=np.int64)
        if isinstance(raw_core_indices, list) and not raw_core_indices
        else np.asarray(raw_core_indices)
    )
    embedding = np.asarray(state["embedding"], dtype=np.float64)
    if labels.shape != (n_samples,) or embedding.shape != (n_samples, 2):
        raise ValueError("DBSCAN fitted-state arrays do not match their declared dimensions")
    if labels.ndim != 1 or not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("DBSCAN fitted-state labels must be integers")
    if core_indices.ndim != 1 or not np.issubdtype(core_indices.dtype, np.integer):
        raise ValueError("DBSCAN fitted-state core indices must be integers")
    if core_indices.size and (
        np.any(core_indices < 0)
        or np.any(core_indices >= n_samples)
        or np.unique(core_indices).size != core_indices.size
        or not np.all(core_indices[:-1] < core_indices[1:])
        or np.any(labels[core_indices] == -1)
    ):
        raise ValueError("DBSCAN fitted-state core indices must be sorted unique non-noise observations")
    if not np.all(np.isfinite(embedding)):
        raise ValueError("DBSCAN fitted state contains a non-finite embedding")
    cluster_labels = [int(label) for label in np.unique(labels) if int(label) != -1]
    if cluster_labels != list(range(len(cluster_labels))):
        raise ValueError("DBSCAN fitted-state cluster labels must be contiguous from zero")
    first_occurrences = [int(np.flatnonzero(labels == label)[0]) for label in cluster_labels]
    if first_occurrences != sorted(first_occurrences):
        raise ValueError("DBSCAN fitted-state labels do not follow the stable label convention")
    observed_clusters = state["observed_clusters"]
    noise_count = state["noise_count"]
    if (
        isinstance(observed_clusters, bool)
        or not isinstance(observed_clusters, int)
        or observed_clusters != len(cluster_labels)
        or isinstance(noise_count, bool)
        or not isinstance(noise_count, int)
        or noise_count != int(np.sum(labels == -1))
    ):
        raise ValueError("DBSCAN fitted-state cluster and noise counts do not match its labels")
    if state["label_rule"] != CLUSTER_LABEL_RULE or state["application_scope"] != DBSCAN_APPLICATION_SCOPE:
        raise ValueError("DBSCAN fitted state uses an unknown assignment convention")
    expected_embedding = (
        "single_feature_axis"
        if n_features == 1
        else "two_feature_axes" if n_features == 2 else PRESENTATION_EMBEDDING_RULE
    )
    if state["embedding_method"] != expected_embedding:
        raise ValueError("DBSCAN fitted state uses an invalid presentation embedding")
    _validate_quality(state["quality"], expected_population="non_noise_samples_only")
    return state


def replay_dbscan_labels(input_data: Any, state: object) -> np.ndarray:
    """Replay DBSCAN labels only for the exact fitted cohort."""

    validated = validate_dbscan_state(state)
    matrix = _matrix(input_data, operation="DBSCAN replay")
    if (
        matrix.shape != (validated["n_samples"], validated["n_features"])
        or _matrix_digest(matrix) != validated["training_input_sha256"]
    ):
        raise ValueError("DBSCAN density partition may only be replayed for its exact fitted cohort")
    return np.asarray(validated["labels"], dtype=np.int64)


def dbscan_outputs_from_state(input_data: Any, state: object) -> dict[str, Any]:
    validated = validate_dbscan_state(state)
    labels = list(validated["labels"])
    source_labels = _source_labels(input_data)
    quality = validated["quality"]
    parameters = validated["parameters"]
    n_clusters = int(validated["observed_clusters"])
    noise_fraction = float(validated["noise_count"] / validated["n_samples"])
    return {
        "default": labels,
        "model": validated,
        "labels": labels,
        "cluster_assignment": labels,
        "cluster_summary": _cluster_summary(labels, source_labels),
        "n_clusters": n_clusters,
        "embedding": validated["embedding"],
        "visualization": _cluster_map_visualization(
            embedding=validated["embedding"],
            labels=labels,
            source_labels=source_labels,
            embedding_method=validated["embedding_method"],
            method_label="DBSCAN",
        ),
        "metadata": {
            "type": "DBSCAN",
            "output_type": "clustering",
            "n_clusters": n_clusters,
            "eps": parameters["eps"],
            "min_samples": parameters["min_samples"],
            "metric": parameters["metric"],
            "embedding": validated["embedding_method"],
            "sample_labels": source_labels,
            "label_categories": [str(label) for label in sorted(np.unique(labels).tolist())],
            "source_labels": source_labels,
            "application_scope": validated["application_scope"],
            "quality_summary": {
                "population": quality["population"],
                "n_clusters": n_clusters,
                "noise_fraction": noise_fraction,
                "silhouette_score": quality["silhouette_score"],
                "davies_bouldin_score": quality["davies_bouldin_score"],
            },
        },
    }


def dbscan_export_outputs(input_data: Any, *, parameters: Mapping[str, object]) -> dict[str, Any]:
    return dbscan_outputs_from_state(input_data, fit_dbscan(input_data, parameters=parameters))
