"""
PCA training and transform nodes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from spectra_sherpa.app.lib import pca as pca_authority
from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis
from spectra_sherpa.app.lib.pca import PCAExtract, fit_pca
from spectra_sherpa.app.lib.sherpa_dataset import (
    EvaluationResult,
    SherpaDataset,
)
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers
from spectra_sherpa.app.services.dag.feature_axis_identity import (
    feature_axis_identity as _canonical_feature_axis_identity,
)
from spectra_sherpa.app.services.dag.feature_axis_identity import (
    validated_axis_quantity,
)
from spectra_sherpa.app.services.dag.meta_helpers import (
    add_processing_step,
    copy_processing_history,
    inherit_origin_context,
    inherit_sample_flags,
)
from spectra_sherpa.app.services.dag.nodes._chemometric_diagnostics import (
    hotelling_t2_per_sample,
    q_residuals_per_sample,
)
from spectra_sherpa.app.services.dag.presentation_contract import (
    NodePresentationContract,
    ScientificPresentation,
)
from spectra_sherpa.app.services.dag.rank_projection import (
    input_axis_identity,
    project_mode_1_to_2d,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import (
    bind_stable_execution_contract,
    execution_contract_digest,
)
from spectra_sherpa.execution_contract_vocabulary import (
    DatasetRankPolicy,
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    TargetAccess,
    WorkerCapability,
)

from ...io_contracts import (
    attach_evaluation,
    bind_X,
    to_numpy_2d,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from . import _artifact_builder
from .core_utils import (
    is_sequential_numeric as _is_sequential_numeric,
)

logger = logging.getLogger(__name__)

PCA_FITTED_STATE_SERIALIZER = PCAExtract.SERIALIZER
PCA_FITTED_STATE_SCHEMA = "spectrasherpa.model.pca-state/4"
PCA_SIGN_RULE = "largest_absolute_loading_positive"
_PCA_PARAMETER_KEYS = {"n_components", "standardized", "scaled"}


@dataclass
class PCARuntimeBundle:
    input_data: Any
    input_ds: Any
    extracted: PCAExtract
    scores_dataset: Any
    loadings_dataset: Any
    actual_n_components: int
    evr_ratio: np.ndarray
    eigenvalues: np.ndarray
    n_observations: int
    n_features: int
    n_components_parsed: int | str | float
    fitted_state: dict[str, object]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_pca_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """Return the exact three-field PCA parameter contract."""

    if set(parameters) != _PCA_PARAMETER_KEYS:
        raise ValueError("PCA parameters must use the exact current three-field schema")
    raw_components = parameters["n_components"]
    if not isinstance(raw_components, str):
        raise ValueError("PCA n_components must be a positive integer, 'mle', or a fraction in (0, 1)")
    text = raw_components.strip().lower()
    if text == "mle":
        components = "mle"
    else:
        try:
            numeric = float(text)
        except ValueError as exc:
            raise ValueError("PCA n_components must be a positive integer, 'mle', or a fraction in (0, 1)") from exc
        if numeric.is_integer() and numeric >= 1:
            components = str(int(numeric))
        elif np.isfinite(numeric) and 0.0 < numeric < 1.0:
            components = repr(numeric)
        else:
            raise ValueError("PCA n_components must be a positive integer, 'mle', or a fraction in (0, 1)")
    standardized = parameters["standardized"]
    scaled = parameters["scaled"]
    if not isinstance(standardized, bool) or not isinstance(scaled, bool):
        raise ValueError("PCA standardized and scaled parameters must be booleans")
    if standardized and scaled:
        raise ValueError("PCA standardized and scaled modes are mutually exclusive")
    return {"n_components": components, "standardized": standardized, "scaled": scaled}


def _feature_axis_identity(dataset: Any, *, features: int) -> tuple[str | None, str | None, str | None, str | None]:
    return _canonical_feature_axis_identity(dataset, features=features, context="PCA")


def _canonicalize_pca_sign(extract: PCAExtract) -> None:
    """Resolve component sign without changing the fitted PCA subspace."""

    for component in range(extract.n_components):
        loading = extract.loadings[component]
        anchor = int(np.argmax(np.abs(loading)))
        if not np.isfinite(loading[anchor]) or loading[anchor] == 0.0:
            raise ValueError("PCA produced a degenerate loading vector")
        if loading[anchor] < 0.0:
            extract.loadings[component] *= -1.0
            extract.scores[:, component] *= -1.0


def _state_vector(value: object, *, name: str, length: int, required: bool) -> np.ndarray | None:
    if value is None:
        if required:
            raise ValueError(f"PCA fitted state is missing {name}")
        return None
    vector = np.asarray(value, dtype=np.float64)
    if vector.shape != (length,) or not np.isfinite(vector).all():
        raise ValueError(f"PCA fitted state has an invalid {name}")
    return np.array(vector, copy=True)


def _pca_state_from_extract(
    extract: PCAExtract,
    dataset: Any,
    *,
    input_shape: tuple[int, ...],
    input_axis_identity_sha256: str,
    rank_projection_strategy: str,
) -> dict[str, object]:
    _canonicalize_pca_sign(extract)
    features = int(extract.loadings.shape[1])
    axis_values, axis_labels, axis_units, axis_quantity = _feature_axis_identity(dataset, features=features)
    metadata: dict[str, object] = {
        "n_components": int(extract.n_components),
        "n_features": features,
        "reference_samples": int(extract.scores.shape[0]),
        "standardized": extract.scale_mode == "standard",
        "scaled": extract.scale_mode == "minmax",
        "scale_mode": extract.scale_mode,
        "sign_rule": PCA_SIGN_RULE,
        "feature_axis_values_sha256": axis_values,
        "feature_axis_labels_sha256": axis_labels,
        "feature_axis_units": axis_units,
        "feature_axis_quantity": axis_quantity,
        "input_shape": list(input_shape),
        "input_axis_identity_sha256": input_axis_identity_sha256,
        "rank_projection_strategy": rank_projection_strategy,
    }
    arrays: dict[str, object] = {
        "loadings": np.asarray(extract.loadings, dtype=np.float64).tolist(),
        "explained_variance_ratio": np.asarray(extract.explained_variance_ratio, dtype=np.float64).tolist(),
        "explained_variance": np.asarray(extract.explained_variance, dtype=np.float64).tolist(),
        "mean": None if extract.mean is None else np.asarray(extract.mean, dtype=np.float64).tolist(),
        "scale": None if extract.scale is None else np.asarray(extract.scale, dtype=np.float64).tolist(),
        "offset": None if extract.offset is None else np.asarray(extract.offset, dtype=np.float64).tolist(),
        "center": None if extract.center is None else np.asarray(extract.center, dtype=np.float64).tolist(),
    }
    content = {"metadata": metadata, "arrays": arrays}
    return {
        "schema_version": PCA_FITTED_STATE_SCHEMA,
        "serializer": PCA_FITTED_STATE_SERIALIZER,
        "source_contract_digest": execution_contract_digest(PCANode.metadata),
        "state_content_digest": hashlib.sha256(_canonical_json(content)).hexdigest(),
        **content,
    }


def validate_pca_fitted_state(state: object) -> dict[str, object]:
    """Validate and normalize the sole portable PCA state boundary."""

    expected = {
        "schema_version",
        "serializer",
        "source_contract_digest",
        "state_content_digest",
        "metadata",
        "arrays",
    }
    if not isinstance(state, Mapping) or set(state) != expected:
        raise ValueError("PCA fitted state does not use the closed schema")
    if state["schema_version"] != PCA_FITTED_STATE_SCHEMA or state["serializer"] != PCA_FITTED_STATE_SERIALIZER:
        raise ValueError("PCA fitted state has an unsupported identity")
    if state["source_contract_digest"] != execution_contract_digest(PCANode.metadata):
        raise ValueError("PCA fitted state producer contract is not current")
    metadata = state["metadata"]
    arrays = state["arrays"]
    metadata_fields = {
        "n_components",
        "n_features",
        "reference_samples",
        "standardized",
        "scaled",
        "scale_mode",
        "sign_rule",
        "feature_axis_values_sha256",
        "feature_axis_labels_sha256",
        "feature_axis_units",
        "feature_axis_quantity",
        "input_shape",
        "input_axis_identity_sha256",
        "rank_projection_strategy",
    }
    array_fields = {"loadings", "explained_variance_ratio", "explained_variance", "mean", "scale", "offset", "center"}
    if not isinstance(metadata, Mapping) or set(metadata) != metadata_fields:
        raise ValueError("PCA fitted-state metadata is not closed")
    if not isinstance(arrays, Mapping) or set(arrays) != array_fields:
        raise ValueError("PCA fitted-state arrays are not closed")
    for field in ("n_components", "n_features", "reference_samples"):
        value = metadata[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"PCA fitted state has invalid {field}")
    components = int(metadata["n_components"])
    features = int(metadata["n_features"])
    reference_samples = int(metadata["reference_samples"])
    if components > min(features, reference_samples):
        raise ValueError("PCA fitted state retains more components than its fitted matrix permits")
    standardized = metadata["standardized"]
    scaled = metadata["scaled"]
    if not isinstance(standardized, bool) or not isinstance(scaled, bool) or (standardized and scaled):
        raise ValueError("PCA fitted state has invalid preprocessing flags")
    scale_mode = metadata["scale_mode"]
    expected_mode = "standard" if standardized else "minmax" if scaled else None
    if scale_mode != expected_mode or metadata["sign_rule"] != PCA_SIGN_RULE:
        raise ValueError("PCA fitted state has invalid preprocessing or sign semantics")
    for name in ("feature_axis_values_sha256", "feature_axis_labels_sha256"):
        digest = metadata[name]
        if digest is not None and (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"PCA fitted state has invalid {name}")
    if metadata["feature_axis_units"] is not None and not isinstance(metadata["feature_axis_units"], str):
        raise ValueError("PCA fitted state has invalid feature-axis units")
    axis_quantity = validated_axis_quantity(metadata["feature_axis_quantity"], context="PCA fitted")
    input_shape_value = metadata["input_shape"]
    if (
        not isinstance(input_shape_value, list)
        or len(input_shape_value) < 2
        or len(input_shape_value) > 16
        or any(type(value) is not int or value < 1 for value in input_shape_value)
    ):
        raise ValueError("PCA fitted state has invalid input_shape")
    if int(np.prod(input_shape_value[1:], dtype=np.int64)) != features:
        raise ValueError("PCA fitted-state input shape does not reproduce its feature count")
    input_axis_digest = metadata["input_axis_identity_sha256"]
    if (
        not isinstance(input_axis_digest, str)
        or len(input_axis_digest) != 64
        or any(character not in "0123456789abcdef" for character in input_axis_digest)
    ):
        raise ValueError("PCA fitted state has invalid input-axis identity")
    projection_strategy = metadata["rank_projection_strategy"]
    if projection_strategy not in {"none", "mode_1_samples_by_composite_features_c_order"}:
        raise ValueError("PCA fitted state has an unsupported rank projection")
    if (len(input_shape_value) == 2) != (projection_strategy == "none"):
        raise ValueError("PCA fitted-state rank projection contradicts its input shape")
    loadings = np.asarray(arrays["loadings"], dtype=np.float64)
    variance_ratio = np.asarray(arrays["explained_variance_ratio"], dtype=np.float64)
    eigenvalues = np.asarray(arrays["explained_variance"], dtype=np.float64)
    if loadings.shape != (components, features) or not np.isfinite(loadings).all():
        raise ValueError("PCA fitted state has invalid loadings")
    if not np.allclose(loadings @ loadings.T, np.eye(components), rtol=1e-7, atol=1e-7):
        raise ValueError("PCA fitted-state loadings are not orthonormal")
    for loading in loadings:
        anchor = int(np.argmax(np.abs(loading)))
        if loading[anchor] <= 0.0:
            raise ValueError("PCA fitted-state loadings violate the declared sign convention")
    if (
        variance_ratio.shape != (components,)
        or not np.isfinite(variance_ratio).all()
        or np.any(variance_ratio < 0.0)
        or np.any(variance_ratio > 1.0)
        or float(np.sum(variance_ratio)) > 1.0 + 1e-8
        or np.any(np.diff(variance_ratio) > 1e-10)
    ):
        raise ValueError("PCA fitted state has invalid explained-variance ratios")
    if (
        eigenvalues.shape != (components,)
        or not np.isfinite(eigenvalues).all()
        or np.any(eigenvalues <= 0.0)
        or np.any(np.diff(eigenvalues) > 1e-10)
    ):
        raise ValueError("PCA fitted state has invalid eigenvalues")
    mean = _state_vector(arrays["mean"], name="mean", length=features, required=not scaled)
    scale = _state_vector(arrays["scale"], name="scale", length=features, required=standardized or scaled)
    offset = _state_vector(arrays["offset"], name="offset", length=features, required=scaled)
    center = _state_vector(arrays["center"], name="center", length=features, required=standardized or scaled)
    if scale is not None and np.any(scale <= 0.0):
        raise ValueError("PCA fitted-state scale must be positive")
    if scaled and mean is not None:
        raise ValueError("min-max PCA state cannot also carry a raw-space mean")
    if standardized and offset is not None:
        raise ValueError("standardized PCA state cannot carry a min-max offset")
    if not standardized and not scaled and (scale is not None or offset is not None or center is not None):
        raise ValueError("mean-centered PCA state cannot carry scaling state")
    normalized_metadata = dict(metadata)
    normalized_metadata["feature_axis_quantity"] = axis_quantity
    normalized_metadata["input_shape"] = list(input_shape_value)
    normalized_arrays = {
        "loadings": loadings.tolist(),
        "explained_variance_ratio": variance_ratio.tolist(),
        "explained_variance": eigenvalues.tolist(),
        "mean": None if mean is None else mean.tolist(),
        "scale": None if scale is None else scale.tolist(),
        "offset": None if offset is None else offset.tolist(),
        "center": None if center is None else center.tolist(),
    }
    content = {"metadata": normalized_metadata, "arrays": normalized_arrays}
    if state["state_content_digest"] != hashlib.sha256(_canonical_json(content)).hexdigest():
        raise ValueError("PCA fitted-state content digest does not match")
    return {
        "schema_version": PCA_FITTED_STATE_SCHEMA,
        "serializer": PCA_FITTED_STATE_SERIALIZER,
        "source_contract_digest": state["source_contract_digest"],
        "state_content_digest": state["state_content_digest"],
        **content,
    }


def _pca_extract_from_state(state: object) -> PCAExtract:
    normalized = validate_pca_fitted_state(state)
    metadata = normalized["metadata"]
    arrays = normalized["arrays"]
    assert isinstance(metadata, dict) and isinstance(arrays, dict)
    artifact_metadata = {
        "model_type": "pca",
        "serializer": PCA_FITTED_STATE_SERIALIZER,
        "n_components": metadata["n_components"],
        "n_features": metadata["n_features"],
        "standardized": metadata["standardized"],
        "scaled": metadata["scaled"],
        "scale_mode": metadata["scale_mode"],
    }
    return PCAExtract.from_artifact(
        artifact_metadata,
        {name: np.asarray(value, dtype=np.float64) for name, value in arrays.items() if value is not None},
    )


def _project_pca_application_input(
    dataset: SherpaDataset,
    metadata: Mapping[str, object],
) -> SherpaDataset:
    expected_shape = tuple(int(value) for value in metadata["input_shape"])  # type: ignore[union-attr]
    if dataset.ndim != len(expected_shape) or tuple(dataset.shape[1:]) != expected_shape[1:]:
        raise ValueError("PCA application data does not match the fitted input rank and non-sample shape")
    if input_axis_identity(dataset) != metadata["input_axis_identity_sha256"]:
        raise ValueError("PCA application data does not match the fitted feature axis, inner axes, or rank identity")
    projected, projection = project_mode_1_to_2d(dataset, operation_id="model.pca.application_unfold")
    if projection.strategy != metadata["rank_projection_strategy"]:
        raise ValueError("PCA application data does not reproduce the fitted rank projection")
    return projected


def apply_pca_fitted_state(input_data: Any, state: object) -> np.ndarray:
    normalized = validate_pca_fitted_state(state)
    metadata = normalized["metadata"]
    assert isinstance(metadata, dict)
    dataset = bind_X(
        input_data,
        missing_message="Missing required PCA application data",
        dataset_error_message="PCA application data must be a dataset or finite matrix",
        allow_array=True,
    )
    projected = _project_pca_application_input(dataset, metadata)
    features = int(metadata["n_features"])
    if _feature_axis_identity(projected, features=features) != (
        metadata["feature_axis_values_sha256"],
        metadata["feature_axis_labels_sha256"],
        metadata["feature_axis_units"],
        metadata["feature_axis_quantity"],
    ):
        raise ValueError("PCA application data does not match the fitted feature axis")
    return _pca_extract_from_state(normalized).transform(to_numpy_2d(projected, name="input_data", dtype=np.float64))


def reconstruct_pca_fitted_state(scores: Any, state: object) -> np.ndarray:
    """Reconstruct observations from scores through the same closed state."""

    normalized = validate_pca_fitted_state(state)
    metadata = normalized["metadata"]
    arrays = normalized["arrays"]
    assert isinstance(metadata, dict) and isinstance(arrays, dict)
    components = int(metadata["n_components"])
    score_matrix = to_numpy_2d(scores, name="scores", dtype=np.float64)
    if score_matrix.shape[1] != components or not np.isfinite(score_matrix).all():
        raise ValueError("PCA reconstruction scores do not match the fitted component count")
    reconstructed = score_matrix @ np.asarray(arrays["loadings"], dtype=np.float64)
    center = arrays["center"]
    if center is not None:
        reconstructed = reconstructed + np.asarray(center, dtype=np.float64)
    scale = arrays["scale"]
    if scale is not None:
        reconstructed = reconstructed * np.asarray(scale, dtype=np.float64)
    if metadata["scale_mode"] == "minmax":
        reconstructed = reconstructed + np.asarray(arrays["offset"], dtype=np.float64)
    else:
        reconstructed = reconstructed + np.asarray(arrays["mean"], dtype=np.float64)
    return np.asarray(reconstructed, dtype=np.float64)


def pca_q_residuals_in_fitted_space(input_data: Any, scores: Any, state: object) -> np.ndarray:
    """Compute PCA Q/SPE in the centered, optionally scaled model space."""

    normalized = validate_pca_fitted_state(state)
    metadata = normalized["metadata"]
    arrays = normalized["arrays"]
    assert isinstance(metadata, dict) and isinstance(arrays, dict)
    features = int(metadata["n_features"])
    components = int(metadata["n_components"])
    input_matrix = to_numpy_2d(input_data, name="input_data", dtype=np.float64)
    score_matrix = to_numpy_2d(scores, name="scores", dtype=np.float64)
    if input_matrix.shape[1] != features or score_matrix.shape != (input_matrix.shape[0], components):
        raise ValueError("PCA fitted-space Q inputs do not match the fitted sample and feature dimensions")

    fitted_input = input_matrix.copy()
    mean = arrays["mean"]
    if mean is not None:
        fitted_input -= np.asarray(mean, dtype=np.float64)
    offset = arrays["offset"]
    if offset is not None:
        fitted_input -= np.asarray(offset, dtype=np.float64)
    scale = arrays["scale"]
    if scale is not None:
        fitted_input /= np.asarray(scale, dtype=np.float64)
    center = arrays["center"]
    if center is not None:
        fitted_input -= np.asarray(center, dtype=np.float64)

    fitted_reconstruction = score_matrix @ np.asarray(arrays["loadings"], dtype=np.float64)
    return q_residuals_per_sample(fitted_input, fitted_reconstruction)


def _set_pca_score_semantics(dataset: SherpaDataset, pc_labels: list[str]) -> None:
    """Apply algorithm-owned score axes and units after generic provenance copying."""

    dataset.title = "PCA Scores"
    dataset.feature_axis = FeatureAxis(
        values=np.arange(len(pc_labels), dtype=np.float64),
        labels=pc_labels,
        units="dimensionless",
        title="Principal Component",
    )
    dataset.units = "dimensionless"
    domain = dataset.domain.model_copy(deep=True)
    domain.data_quantity = "PCA score"
    domain.expected_units = "dimensionless"
    dataset.domain = domain
    dataset.meta.update(
        {
            "data_quantity": "PCA score",
            "value_units": "dimensionless",
            "x_title": "Principal Component",
            "x_units": "dimensionless",
        }
    )


def _set_pca_loading_semantics(
    dataset: SherpaDataset,
    source: SherpaDataset,
    pc_labels: list[str],
) -> None:
    """Apply algorithm-owned loading orientation while retaining the source feature axis."""

    source_feature_axis = source.feature_axis
    if source_feature_axis is not None:
        dataset.feature_axis = source_feature_axis
    dataset.sample_axis = SampleAxis(
        values=np.arange(len(pc_labels), dtype=np.float64),
        labels=pc_labels,
        title="Principal Component",
    )
    dataset.units = "dimensionless"
    domain = dataset.domain.model_copy(deep=True)
    domain.data_quantity = "PCA loading"
    domain.expected_units = "dimensionless"
    dataset.domain = domain
    dataset.meta.update({"data_quantity": "PCA loading", "value_units": "dimensionless"})


def _pca_diagnostic_state(
    *,
    model: Any,
    scores: Any,
    eigenvalues: Any,
    input_data: Any,
) -> dict[str, Any]:
    """Build the typed PCA state consumed by diagnostic evaluators."""

    score_matrix = to_numpy_2d(scores, name="scores", dtype=np.float64)
    eigenvalue_vector = np.asarray(eigenvalues, dtype=np.float64).reshape(-1)
    if eigenvalue_vector.shape != (score_matrix.shape[1],):
        raise ValueError("PCA diagnostic eigenvalues must match the retained score columns")
    if not np.isfinite(eigenvalue_vector).all():
        raise ValueError("PCA diagnostic eigenvalues must be finite")
    t2 = hotelling_t2_per_sample(score_matrix, eigenvalues=eigenvalue_vector)
    q = pca_q_residuals_in_fitted_space(input_data, score_matrix, model)
    sample_labels: list[str] = []
    if isinstance(scores, SherpaDataset):
        sample_axis = scores.get_observation_axis()
        raw_labels = getattr(sample_axis, "labels", None) if sample_axis is not None else None
        if raw_labels is not None and len(raw_labels) == score_matrix.shape[0]:
            sample_labels = [str(value) for value in raw_labels]
    return {
        "model": model,
        "scores": scores,
        "n_components": int(score_matrix.shape[1]),
        "n_observations": int(score_matrix.shape[0]),
        "eigenvalues": eigenvalue_vector.tolist(),
        "T2": t2.tolist(),
        "Q": q.tolist(),
        "sample_labels": sample_labels,
        "_internal": {"input_data": input_data},
    }


def _parse_pca_n_components(raw_value: Any, shape: tuple[int, int]) -> int | str | float:
    """Parse and validate PCA n_components using the same rules as GUI execution."""
    n_observations, n_features = shape
    canonical = _canonical_pca_parameters({"n_components": raw_value, "standardized": False, "scaled": False})[
        "n_components"
    ]
    assert isinstance(canonical, str)
    if canonical == "mle":
        n_components_parsed: int | str | float = canonical
    else:
        numeric = float(canonical)
        n_components_parsed = int(numeric) if numeric.is_integer() else numeric

    if n_components_parsed == "mle" and n_observations < n_features:
        raise ValueError(
            f"n_components='mle' requires n_observations >= n_features. "
            f"Got {n_observations} observations and {n_features} features. "
            "Consider using a specific number of components or a variance threshold (0-1)."
        )

    return n_components_parsed


def run_pca_runtime(
    input_data: Any,
    *,
    n_components_param: Any = "5",
    standardized: bool = False,
    scaled: bool = False,
    node_id: str | None = None,
) -> PCARuntimeBundle:
    """Run PCA through the same runtime path used by the GUI and export code."""
    parameters = _canonical_pca_parameters(
        {"n_components": n_components_param, "standardized": standardized, "scaled": scaled}
    )
    source_ds = bind_X(
        input_data,
        missing_message="Missing required input: input_data (X)",
        dataset_error_message="input_data must be an dataset or array-like object",
        allow_array=True,
    )
    input_ds, rank_projection = project_mode_1_to_2d(
        source_ds,
        operation_id="model.pca.mode_1_unfold",
        node_id=node_id,
    )
    n_observations, n_features = input_ds.shape
    n_components_parsed = _parse_pca_n_components(parameters["n_components"], input_ds.shape)

    logger.debug("[PCA Node] Executing with:")
    logger.debug("  - n_components parsed: %s (type: %s)", n_components_parsed, type(n_components_parsed).__name__)
    logger.debug("  - Data shape: %s observations x %s features", n_observations, n_features)

    raw_matrix = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
    extracted = fit_pca(
        raw_matrix,
        n_components=n_components_parsed,
        standardized=bool(parameters["standardized"]),
        scaled=bool(parameters["scaled"]),
    )

    actual_n_components = extracted.n_components
    evr_ratio = extracted.explained_variance_ratio
    eigenvalues = extracted.explained_variance
    fitted_state = _pca_state_from_extract(
        extracted,
        input_ds,
        input_shape=rank_projection.input_shape,
        input_axis_identity_sha256=rank_projection.input_axis_identity_sha256,
        rank_projection_strategy=rank_projection.strategy,
    )
    validate_pca_fitted_state(fitted_state)
    replayed_scores = apply_pca_fitted_state(source_ds, fitted_state)
    if not np.allclose(replayed_scores, extracted.scores, rtol=1e-10, atol=1e-10):
        raise RuntimeError("PCA fitted state does not reproduce the fitted scores")
    scores_dataset = input_ds.with_data(extracted.scores)
    loadings_dataset = SherpaDataset(
        X=extracted.loadings,
        feature_axis=input_ds.feature_axis,
        data_role="X_features",
        title="PCA Loadings",
    )

    return PCARuntimeBundle(
        input_data=input_data,
        input_ds=input_ds,
        extracted=extracted,
        scores_dataset=scores_dataset,
        loadings_dataset=loadings_dataset,
        actual_n_components=actual_n_components,
        evr_ratio=evr_ratio,
        eigenvalues=eigenvalues,
        n_observations=n_observations,
        n_features=n_features,
        n_components_parsed=n_components_parsed,
        fitted_state=fitted_state,
    )


@register_node
class PCANode(Node):
    """
    Principal Component Analysis node.

    Performs exact full-SVD PCA decomposition through Sherpa's native authority.
    """

    metadata = NodeMetadata(
        node_type="model.pca",
        category="exploratory",
        label="Fit PCA Transform",
        description=(
            "Reduces spectral data to a small set of orthogonal principal components that capture "
            "the most variance, enabling visualisation, outlier detection, and feature compression. "
            "For most spectral datasets leave both scaling options off — PCA mean-centers "
            "by default, which is the correct preprocessing for spectroscopy. "
            "Use '0.95' as n_components to automatically retain enough PCs for 95% variance, "
            "or check the Explained Variance output to choose the elbow point. "
            "The 'mle' option uses Minka's automatic dimensionality method and requires "
            "at least as many observations as features."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="text",
                default="2",
                description=(
                    "Number of components: integer (e.g., '2'), 'mle'"
                    " (Minka maximum-likelihood automatic selection), or float 0-1"
                    " (e.g., '0.95' for 95% variance)"
                ),
                required=True,
                category="basic",
                hint=(
                    "Must be ≤ min(n_samples, n_features). "
                    "The 'mle' choice additionally requires n_samples ≥ n_features. "
                    "This is checked at execution time — a value that is too large will raise an error. "
                    "Use '0.95' to automatically retain enough components for 95% explained variance."
                ),
            ),
            NodeParameter(
                name="standardized",
                label="Mean Center + Unit Variance",
                param_type="boolean",
                default=False,
                description=(
                    "Subtract the column mean AND divide by column standard deviation before PCA "
                    "(full standardization). Use when variables have different units or scales, "
                    "e.g. mixing spectral and non-spectral predictors."
                ),
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="scaled",
                label="Min-Max Scale + Center",
                param_type="boolean",
                default=False,
                description=(
                    "Apply min-max scaling, (X - column minimum) / column range, "
                    "then center the scaled variables before PCA. Rarely appropriate for spectral data — "
                    "prefer 'Mean Center + Unit Variance' or leave both off to use mean-centering only "
                    "(the spectroscopy default)."
                ),
                required=False,
                category="advanced",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description="Spectral dataset or multivariate feature table for PCA decomposition",
                accepted_data_roles=["X_spectra", "X_features"],
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="PC Scores",
                description="Alias of scores for ordinary DAG wiring",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="Fitted PCA Transform",
                description="Closed replayable PCA fitted state",
            ),
            PortMetadata(
                name="fitted_state",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="Replayable PCA State",
                description="Contract-bound fitted state for local or artifact application",
            ),
            PortMetadata(
                name="scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="Scores",
                description="Transformed scores (n_samples × n_components) with sample labels",
            ),
            PortMetadata(
                name="X_scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="X Scores",
                description="Alias of scores for cross-technique wiring",
            ),
            PortMetadata(
                name="loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="Loadings",
                description="Principal component loadings (n_components × n_features) with wavenumber axis",
            ),
            PortMetadata(
                name="X_loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="X Loadings",
                description="Alias of loadings for cross-technique wiring",
            ),
            PortMetadata(
                name="explained_variance",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Explained Variance",
                description="Fraction of total variance explained by each component",
            ),
            PortMetadata(
                name="eigenvalues",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="PCA Eigenvalues",
                description="Absolute variance of each retained principal component",
            ),
            PortMetadata(
                name="diagnostic_state",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="PCA Diagnostic State",
                description=(
                    "Fitted PCA state, scores, eigenvalues, and fitted-space observations for transparent "
                    "Hotelling T² and Q/SPE diagnostics"
                ),
            ),
        ],
        presentation_contract=NodePresentationContract(
            default_presentation="scores",
            presentations=(
                ScientificPresentation(
                    "scores",
                    "Scores",
                    "pca_scores",
                    ("scores",),
                    ("plot", "table"),
                    "Sample positions in principal-component space, with admitted sample metadata.",
                ),
                ScientificPresentation(
                    "loadings",
                    "Loadings",
                    "pca_loadings",
                    ("loadings",),
                    ("plot", "table"),
                    "Variable contributions for each retained principal component.",
                ),
                ScientificPresentation(
                    "explained_variance",
                    "Explained Variance (Scree)",
                    "pca_explained_variance",
                    ("explained_variance",),
                    ("plot", "table"),
                    "Per-component and cumulative explained variance used to inspect model dimensionality.",
                ),
                ScientificPresentation(
                    "diagnostics",
                    "T² and Q Diagnostics",
                    "t2_q_diagnostics",
                    ("diagnostic_state",),
                    ("plot", "table"),
                    "Hotelling T² and Q/SPE observations for multivariate outlier review.",
                ),
            ),
        ),
        diagnostics=[
            "explained_variance_ratio",
            "cumulative_variance",
            "n_components_95pct",
        ],
        help_url="https://scikit-learn.org/stable/modules/decomposition.html#pca",
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="none",
        ),
        canonical_parameter_validator=_canonical_pca_parameters,
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for PCA decomposition.

        Emits code that fits PCA, extracts scores/loadings/explained variance,
        and stores as a multi-port dict.
        """
        del use_scp
        input_expression = inputs.get("default", inputs.get("X", "input_data"))
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import execute_pca_node",
            f"{indent}results[{self.node_id!r}] = execute_pca_node(",
            f"{indent}    {input_expression}, node_id={self.node_id!r}, parameters={self._resolve_params()!r},",
            f"{indent}).outputs",
        ]

    def _execute_sync(self, input_data: Any = None) -> NodeResult:
        """
        Execute PCA on input dataset.

        Args:
            input_data: Dataset containing spectral data

        Returns:
            PCA model object with scores, loadings, and explained variance
        """
        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (X)",
            dataset_error_message="input_data must be an dataset or array-like object",
            allow_array=True,
        )

        # Get parameters
        n_components_str = self.parameters.get("n_components", "5")
        standardized = self.parameters.get("standardized", False)
        scaled = self.parameters.get("scaled", False)
        bundle = run_pca_runtime(
            input_data,
            n_components_param=n_components_str,
            standardized=standardized,
            scaled=scaled,
            node_id=self.node_id,
        )
        input_ds = bundle.input_ds
        extracted = bundle.extracted
        scores_dataset = bundle.scores_dataset
        loadings_dataset = bundle.loadings_dataset
        actual_n_components = bundle.actual_n_components
        evr_ratio = bundle.evr_ratio
        eigenvalues = bundle.eigenvalues
        fitted_state = bundle.fitted_state
        n_observations = bundle.n_observations
        n_features = bundle.n_features

        pc_labels = [f"PC{i + 1} ({evr_ratio[i] * 100:.1f}%)" for i in range(actual_n_components)]

        # Extract label_categories for categorical coloring
        label_categories = None
        _y_coord = input_ds.sample_axis
        if _y_coord is not None:
            try:

                def _label_to_string(label: Any) -> str:
                    if label is None:
                        return ""
                    if isinstance(label, (list, tuple)):
                        for item in reversed(label):
                            if isinstance(item, str) and item.strip():
                                return item.strip()
                        return " | ".join(part for part in (_label_to_string(item) for item in label) if part)
                    if isinstance(label, np.ndarray):
                        if label.ndim == 0:
                            return _label_to_string(label.item())
                        return _label_to_string(label.tolist())
                    if hasattr(label, "isoformat"):
                        try:
                            return str(label.isoformat())
                        except Exception:
                            pass
                    return str(label)

                if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, "tolist") else list(_y_coord.labels)
                    str_labels = [_label_to_string(l) for l in raw]
                    unique_labels = sorted(set(str_labels))
                    # Keep categories only when they provide real grouping signal.
                    # If almost every sample is unique, treat as unlabeled for coloring.
                    if 1 < len(unique_labels) <= 12 and len(unique_labels) <= max(3, int(0.5 * len(str_labels))):
                        label_categories = unique_labels
                elif hasattr(_y_coord, "data") and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, "tolist") else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # Add processing history for provenance tracking.
        copy_processing_history(input_ds, scores_dataset)
        add_processing_step(
            scores_dataset,
            "model.pca.scores",
            {"n_components": actual_n_components},
            node_id=self.node_id,
        )

        copy_processing_history(input_ds, loadings_dataset)
        add_processing_step(
            loadings_dataset,
            "model.pca.loadings",
            {"n_components": actual_n_components},
            node_id=self.node_id,
        )

        # Store only scientific metadata that coordinates can't carry.
        evr_list = evr_ratio.tolist()
        total_variance_explained = float(np.sum(evr_ratio))
        quality_summary = {
            "explained_variance_ratio": evr_list,
            "total_variance_explained": total_variance_explained,
            "n_components": actual_n_components,
        }

        scores_dataset.meta.update(
            {
                "type": "PCA",
                "isPCA": True,
                "pc_labels": pc_labels,
                "explained_variance_ratio": evr_list,
                "n_components": actual_n_components,
                "label_categories": label_categories,
                "quality_summary": quality_summary,
            }
        )

        # PCA scores are a latent feature table, not an ordered spectrum.
        # This keeps spectrum-only preprocessing from accepting them while
        # still allowing scores to feed KNN/PLS-DA/HCA as X_features.
        scores_dataset.data_role = "X_features"

        inherit_sample_flags(input_ds, scores_dataset)
        inherit_origin_context(input_ds, scores_dataset)
        inherit_origin_context(input_ds, loadings_dataset, preserve_feature_axis=True)

        # Generic provenance inheritance is shape-based.  PCA axes and value
        # units are algorithm-owned and therefore must be applied last: a
        # square/full-rank fit does not make wavelengths into components or
        # samples into loading rows.
        _set_pca_score_semantics(scores_dataset, pc_labels)
        _set_pca_loading_semantics(loadings_dataset, input_ds, pc_labels)

        # Defensive shape check protects the declared score/loading orientation.
        if scores_dataset.data.shape != (n_observations, actual_n_components):
            raise RuntimeError("PCA backend score orientation differs from the current contract")
        if loadings_dataset.data.shape != (actual_n_components, n_features):
            raise RuntimeError("PCA backend loading orientation differs from the current contract")

        attach_evaluation(
            scores_dataset,
            EvaluationResult(
                evaluation_id=str(uuid.uuid4()),
                model_type="PCA",
                n_components=actual_n_components,
            ),
        )

        logger.debug(
            "[PCA Node] Requested n_components=%s, fitted with %s components",
            bundle.n_components_parsed,
            actual_n_components,
        )
        logger.debug("[PCA Node] Scores shape: %s, Loadings shape: %s", scores_dataset.shape, loadings_dataset.shape)

        cumulative_variance_per_pc = np.cumsum(evr_ratio).tolist()
        n_components_95pct = None
        above_95 = np.where(np.cumsum(evr_ratio) >= 0.95)[0]
        if len(above_95) > 0:
            n_components_95pct = int(above_95[0]) + 1

        diagnostics = {
            "explained_variance_ratio": evr_ratio.tolist(),
            "cumulative_variance": cumulative_variance_per_pc,
            "n_components_95pct": n_components_95pct,
        }

        # Build model artifact for persistence
        artifact = _artifact_builder.build_model_artifact(
            extracted,
            input_ds,
            node_id=self.node_id,
            metrics={
                "explained_variance_ratio": evr_ratio.tolist(),
                "cumulative_variance": cumulative_variance_per_pc,
            },
        )

        return NodeResult(
            outputs={
                "default": scores_dataset,  # Backwards-compatible default port
                "scores": scores_dataset,
                "X_scores": scores_dataset,
                "loadings": loadings_dataset,
                "X_loadings": loadings_dataset,
                "model": fitted_state,
                "fitted_state": fitted_state,
                "explained_variance": evr_ratio.tolist(),
                "eigenvalues": eigenvalues.tolist(),
                "diagnostic_state": _pca_diagnostic_state(
                    model=fitted_state,
                    scores=scores_dataset,
                    eigenvalues=eigenvalues,
                    input_data=input_ds,
                ),
                "_internal": {
                    "input_data": input_data,
                    "input_data_ds": input_ds,
                },
                "_model_artifact": artifact,
            },
            diagnostics=diagnostics,
        )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        return self._execute_sync(input_data)

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, object]:
        del target
        parameters = self._resolve_params()
        return run_pca_runtime(
            input_data,
            n_components_param=parameters["n_components"],
            standardized=bool(parameters["standardized"]),
            scaled=bool(parameters["scaled"]),
            node_id=self.node_id,
        ).fitted_state

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        return apply_pca_fitted_state(input_data, state)


def execute_pca_node(
    input_data: Any,
    *,
    node_id: str,
    parameters: Mapping[str, object],
) -> NodeResult:
    """Execute PCA through the same authority used by the live node."""

    return PCANode(node_id, dict(parameters))._execute_sync(input_data)


@register_node
class PCATransformNode(Node):
    """
    Transform new data using trained PCA model.

    Projects new samples into the principal component space
    defined by a trained PCA model.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="model.pca_transform",
        category="exploratory",
        label="Apply PCA Transform",
        description=(
            "Project new observations through the exact closed PCA state emitted by Fit PCA Transform. "
            "Feature count, coordinates, labels, units, preprocessing, and producer contract must match."
        ),
        parameters=[],
        input_ports=[
            PortMetadata(
                name="X_new",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Application Data",
                description="Spectral data or feature table to transform",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="Fitted PCA Transform",
                description="Closed contract-bound state from a Fit PCA Transform node",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="PC Scores",
                description="Alias of scores for ordinary DAG wiring",
            ),
            PortMetadata(
                name="scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="PC Scores",
                description="Scores in principal component space",
            ),
        ],
        input_types=["SherpaDataset", "dict"],
        output_type="dict",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        del use_scp
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import execute_pca_transform",
            f"{indent}results[{self.node_id!r}] = execute_pca_transform(",
            f"{indent}    {inputs.get('X_new', 'input_data')}, {inputs.get('model', 'pca_state')},",
            f"{indent}    node_id={self.node_id!r},",
            f"{indent}).outputs",
        ]

    def _execute_sync(self, X_new: Any = None, model: Any = None) -> NodeResult:
        """
        Transform new data using PCA model.

        Args:
            X_new: New spectral data (dataset)
            model: Trained PCA model dict from PCA node

        Returns:
            dict with 'scores' key containing PC scores
        """
        X_new_ds = bind_X(
            X_new,
            missing_message="Missing required input: X_new (new spectra)",
            dataset_error_message="X_new must be an dataset object",
            allow_array=True,
        )
        normalized = validate_pca_fitted_state(model)
        metadata = normalized["metadata"]
        assert isinstance(metadata, dict)
        scores = apply_pca_fitted_state(X_new_ds, normalized)
        projected_X_new = _project_pca_application_input(X_new_ds, metadata)
        score_dataset = projected_X_new.with_data(scores)
        score_dataset.feature_axis = FeatureAxis(
            values=np.arange(scores.shape[1], dtype=np.float64),
            labels=[f"PC{index + 1}" for index in range(scores.shape[1])],
            title="Principal Component",
        )
        score_dataset.data_role = "X_features"
        _set_pca_score_semantics(score_dataset, [f"PC{index + 1}" for index in range(scores.shape[1])])
        add_processing_step(
            score_dataset,
            "model.pca_transform.scores",
            {
                "n_components": metadata["n_components"],
                "source_contract_digest": normalized["source_contract_digest"],
                "state_content_digest": normalized["state_content_digest"],
            },
            node_id=self.node_id,
        )
        diagnostics = {
            "n_samples": int(scores.shape[0]),
            "n_components": int(scores.shape[1]),
            "source_contract_digest": normalized["source_contract_digest"],
            "state_content_digest": normalized["state_content_digest"],
        }
        return NodeResult(outputs={"default": score_dataset, "scores": score_dataset}, diagnostics=diagnostics)

    async def execute(self, X_new: Any = None, model: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        return self._execute_sync(X_new, model)


def execute_pca_transform(input_data: Any, state: object, *, node_id: str) -> NodeResult:
    """Apply one closed PCA state through the live application node."""

    return PCATransformNode(node_id, {})._execute_sync(input_data, state)


bind_stable_execution_contract(
    PCANode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.model.pca",
    implementation_version="2.0.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/exploratory.md",
    implementation_modules=(pca_authority, dag_io_contracts, meta_helpers, _artifact_builder),
    implementation_distributions=("numpy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0")),
    citations=(
        "Jolliffe & Cadima, Principal component analysis: a review and recent developments, "
        "Philosophical Transactions of the Royal Society A 374 (2016) 20150202",
        "scikit-learn PCA exact full-SVD implementation (svd_solver='full')",
        "Minka, Automatic choice of dimensionality for PCA, Advances in Neural Information Processing "
        "Systems 13 (2000)",
    ),
    fitted_state_serializer=PCA_FITTED_STATE_SERIALIZER,
    deterministic=True,
    target_access=TargetAccess.NONE,
    group_access="none",
    input_rank_policy=DatasetRankPolicy.PROJECTS_TO_2D,
)

bind_stable_execution_contract(
    PCATransformNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.ARTIFACT_APPLICATION,
    implementation_id="spectrasherpa.model.pca_transform",
    implementation_version="2.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/exploratory.md",
    implementation_modules=(pca_authority, dag_io_contracts, meta_helpers),
    implementation_distributions=("numpy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0")),
    citations=(
        "Jolliffe & Cadima, Principal component analysis: a review and recent developments, "
        "Philosophical Transactions of the Royal Society A 374 (2016) 20150202",
    ),
    fitted_state_serializer=PCA_FITTED_STATE_SERIALIZER,
    deterministic=True,
    target_access=TargetAccess.NONE,
    group_access="none",
    input_rank_policy=DatasetRankPolicy.PROJECTS_TO_2D,
)


__all__ = [
    "PCANode",
    "PCATransformNode",
    "PCA_FITTED_STATE_SCHEMA",
    "PCA_FITTED_STATE_SERIALIZER",
    "PCA_SIGN_RULE",
    "_canonical_pca_parameters",
    "apply_pca_fitted_state",
    "execute_pca_node",
    "execute_pca_transform",
    "pca_q_residuals_in_fitted_space",
    "reconstruct_pca_fitted_state",
    "validate_pca_fitted_state",
]
