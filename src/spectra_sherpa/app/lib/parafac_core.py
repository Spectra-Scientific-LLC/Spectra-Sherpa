"""Deterministic native PARAFAC (CP-ALS) authority for multiway datasets.

Every mode remains separate throughout the fit; no matrix unfolding is
exposed as a scientific result. The first-mode factor is emitted as the score
view. For hyperspectral images, a binary spatial inclusion mask is honored in
every ALS update and reconstruction diagnostic rather than treating excluded
background pixels as observations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

PARAFAC_STATE_SERIALIZER = "spectrasherpa.model-artifact.parafac/2"
PARAFAC_STATE_SCHEMA = "spectrasherpa.parafac-state/2"
PARAFAC_INITIALIZATION = "per-mode-leading-left-singular-vectors"
PARAFAC_CANONICALIZATION = "descending-mode-1-score-norm;remaining-mode-anchor-positive"
PARAFAC_STORAGE_ORDER = "C"
PARAFAC_SPATIAL_MASK_POLICY = "binary-spatial-modes-0-1"

_PARAMETER_KEYS = frozenset({"n_components", "max_iter", "tol", "ridge"})
_MAX_COMPONENTS = 20
_MAX_ITERATIONS = 500
_MAX_NDIM = 6
_MAX_CELLS = 16_000_000


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _state_content_digest(metadata: Mapping[str, object], arrays: Mapping[str, np.ndarray]) -> str:
    projection = {
        "metadata": {key: value for key, value in metadata.items() if key != "state_content_digest"},
        "arrays": {name: np.asarray(value, dtype=np.float64).tolist() for name, value in sorted(arrays.items())},
    }
    return hashlib.sha256(_canonical_json(projection)).hexdigest()


def canonical_parafac_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """Validate and return the exact bounded PARAFAC parameter schema."""

    if set(parameters) != _PARAMETER_KEYS:
        raise ValueError("PARAFAC parameters must use the exact current four-field schema")
    n_components = parameters["n_components"]
    max_iter = parameters["max_iter"]
    tol = parameters["tol"]
    ridge = parameters["ridge"]
    if type(n_components) is not int or not 1 <= n_components <= _MAX_COMPONENTS:
        raise ValueError(f"PARAFAC n_components must be an integer in [1, {_MAX_COMPONENTS}]")
    if type(max_iter) is not int or not 1 <= max_iter <= _MAX_ITERATIONS:
        raise ValueError(f"PARAFAC max_iter must be an integer in [1, {_MAX_ITERATIONS}]")
    if isinstance(tol, bool) or not isinstance(tol, (int, float)) or not np.isfinite(tol):
        raise ValueError("PARAFAC tol must be finite")
    if not 1e-10 <= float(tol) <= 0.1:
        raise ValueError("PARAFAC tol must be in [1e-10, 0.1]")
    if isinstance(ridge, bool) or not isinstance(ridge, (int, float)) or not np.isfinite(ridge):
        raise ValueError("PARAFAC ridge must be finite")
    if not 0.0 <= float(ridge) <= 1.0:
        raise ValueError("PARAFAC ridge must be in [0, 1]")
    return {
        "n_components": n_components,
        "max_iter": max_iter,
        "tol": float(tol),
        "ridge": float(ridge),
    }


def _validate_tensor(values: Any, *, n_components: int) -> np.ndarray:
    source = np.asarray(values)
    if source.ndim < 3:
        raise ValueError("PARAFAC requires a multiway dataset with at least three dimensions")
    if source.ndim > _MAX_NDIM:
        raise ValueError(f"PARAFAC supports at most {_MAX_NDIM} dimensions")
    if any(dimension < 2 for dimension in source.shape):
        raise ValueError("PARAFAC requires at least two values in every mode")
    if source.size > _MAX_CELLS:
        raise ValueError(f"PARAFAC input exceeds the {_MAX_CELLS:,}-cell execution bound")
    if n_components > min(source.shape):
        raise ValueError("PARAFAC n_components cannot exceed the smallest input-mode length")
    if not np.issubdtype(source.dtype, np.number) or np.iscomplexobj(source):
        raise ValueError("PARAFAC requires a real numeric input tensor")
    tensor = np.asarray(source, dtype=np.float64, order="C")
    if not np.isfinite(tensor).all():
        raise ValueError("PARAFAC requires finite input values")
    return tensor


def _unfold(tensor: np.ndarray, mode: int) -> np.ndarray:
    return np.moveaxis(tensor, mode, 0).reshape(tensor.shape[mode], -1, order="C")


def _khatri_rao(factors: list[np.ndarray]) -> np.ndarray:
    if not factors:
        raise ValueError("PARAFAC Khatri-Rao product requires at least one factor")
    result = np.asarray(factors[0], dtype=np.float64)
    for factor in factors[1:]:
        result = np.einsum("ir,jr->ijr", result, factor, optimize=True).reshape(
            result.shape[0] * factor.shape[0],
            result.shape[1],
            order="C",
        )
    return result


def _mttkrp(tensor: np.ndarray, factors: list[np.ndarray], mode: int) -> np.ndarray:
    others = [factor for index, factor in enumerate(factors) if index != mode]
    return _unfold(tensor, mode) @ _khatri_rao(others)


def _hadamard_gram(factors: list[np.ndarray], *, skip: int) -> np.ndarray:
    rank = factors[0].shape[1]
    gram = np.ones((rank, rank), dtype=np.float64)
    for index, factor in enumerate(factors):
        if index != skip:
            gram *= factor.T @ factor
    return gram


def _solve_factor(tensor: np.ndarray, factors: list[np.ndarray], mode: int, ridge: float) -> np.ndarray:
    numerator = _mttkrp(tensor, factors, mode)
    gram = _hadamard_gram(factors, skip=mode)
    if ridge:
        gram = gram + ridge * np.eye(gram.shape[0], dtype=np.float64)
    return numerator @ np.linalg.pinv(gram, hermitian=True)


def _validate_spatial_mask(value: Any, tensor: np.ndarray) -> np.ndarray | None:
    if value is None:
        return None
    mask = np.asarray(value)
    if mask.dtype != np.bool_ or mask.shape != tensor.shape[:2]:
        raise ValueError("PARAFAC spatial mask must be an exact boolean projection over modes 1 and 2")
    if not np.any(mask):
        raise ValueError("PARAFAC spatial mask must retain at least one spatial cell")
    return np.asarray(mask, dtype=bool, order="C")


def _masked_tensor(tensor: np.ndarray, spatial_mask: np.ndarray) -> np.ndarray:
    return tensor * spatial_mask[..., np.newaxis]


def _solve_masked_factor_3d(
    observed_tensor: np.ndarray,
    spatial_mask: np.ndarray,
    factors: list[np.ndarray],
    mode: int,
    ridge: float,
) -> np.ndarray:
    """Solve one CP-ALS factor under a mask shared by the spectral mode."""

    numerator = _mttkrp(observed_tensor, factors, mode)
    rank = factors[0].shape[1]
    identity = np.eye(rank, dtype=np.float64)
    if mode == 0:
        row_grams = np.einsum(
            "ij,jr,js->irs",
            spatial_mask,
            factors[1],
            factors[1],
            optimize=True,
        )
        row_grams *= (factors[2].T @ factors[2])[np.newaxis, :, :]
        if ridge:
            row_grams = row_grams + ridge * identity[np.newaxis, :, :]
        inverses = np.linalg.pinv(row_grams, hermitian=True)
        return np.einsum("ir,irs->is", numerator, inverses, optimize=True)
    if mode == 1:
        row_grams = np.einsum(
            "ij,ir,is->jrs",
            spatial_mask,
            factors[0],
            factors[0],
            optimize=True,
        )
        row_grams *= (factors[2].T @ factors[2])[np.newaxis, :, :]
        if ridge:
            row_grams = row_grams + ridge * identity[np.newaxis, :, :]
        inverses = np.linalg.pinv(row_grams, hermitian=True)
        return np.einsum("ir,irs->is", numerator, inverses, optimize=True)
    if mode == 2:
        gram = np.einsum(
            "ij,ir,is,jr,js->rs",
            spatial_mask,
            factors[0],
            factors[0],
            factors[1],
            factors[1],
            optimize=True,
        )
        if ridge:
            gram = gram + ridge * identity
        return numerator @ np.linalg.pinv(gram, hermitian=True)
    raise ValueError("Masked PARAFAC currently requires an exact three-mode image cube")


def _normalize_non_observation_factors(factors: list[np.ndarray]) -> None:
    """Keep modes 1..N normalized and absorb scale into observation scores."""

    scale = np.ones(factors[0].shape[1], dtype=np.float64)
    for mode in range(1, len(factors)):
        norms = np.linalg.norm(factors[mode], axis=0)
        if not np.isfinite(norms).all() or np.any(norms <= np.finfo(np.float64).eps):
            raise ValueError("PARAFAC produced a degenerate non-observation factor")
        factors[mode] = factors[mode] / norms
        scale *= norms
    factors[0] = factors[0] * scale


def _relative_reconstruction_error(tensor: np.ndarray, factors: list[np.ndarray]) -> float:
    x_norm_sq = float(np.sum(tensor * tensor, dtype=np.float64))
    gram_product = np.ones((factors[0].shape[1], factors[0].shape[1]), dtype=np.float64)
    for factor in factors:
        gram_product *= factor.T @ factor
    model_norm_sq = float(np.sum(gram_product, dtype=np.float64))
    inner_product = float(np.sum(factors[0] * _mttkrp(tensor, factors, 0), dtype=np.float64))
    residual_sq = max(0.0, x_norm_sq - 2.0 * inner_product + model_norm_sq)
    denominator = max(np.sqrt(x_norm_sq), np.finfo(np.float64).eps)
    result = float(np.sqrt(residual_sq) / denominator)
    if not np.isfinite(result):
        raise ValueError("PARAFAC produced a non-finite reconstruction error")
    return result


def _masked_relative_reconstruction_error(
    observed_tensor: np.ndarray,
    spatial_mask: np.ndarray,
    factors: list[np.ndarray],
) -> float:
    x_norm_sq = float(np.sum(observed_tensor * observed_tensor, dtype=np.float64))
    spatial_gram = np.einsum(
        "ij,ir,is,jr,js->rs",
        spatial_mask,
        factors[0],
        factors[0],
        factors[1],
        factors[1],
        optimize=True,
    )
    model_norm_sq = float(np.sum(spatial_gram * (factors[2].T @ factors[2]), dtype=np.float64))
    inner_product = float(np.sum(factors[0] * _mttkrp(observed_tensor, factors, 0), dtype=np.float64))
    residual_sq = max(0.0, x_norm_sq - 2.0 * inner_product + model_norm_sq)
    denominator = max(np.sqrt(x_norm_sq), np.finfo(np.float64).eps)
    result = float(np.sqrt(residual_sq) / denominator)
    if not np.isfinite(result):
        raise ValueError("Masked PARAFAC produced a non-finite reconstruction error")
    return result


def _initial_factors(tensor: np.ndarray, rank: int) -> list[np.ndarray]:
    factors: list[np.ndarray] = []
    for mode in range(tensor.ndim):
        left, _singular_values, _right = np.linalg.svd(_unfold(tensor, mode), full_matrices=False)
        factor = np.asarray(left[:, :rank], dtype=np.float64)
        for component in range(rank):
            anchor = int(np.argmax(np.abs(factor[:, component])))
            if factor[anchor, component] < 0.0:
                factor[:, component] *= -1.0
        factors.append(factor)
    _normalize_non_observation_factors(factors)
    return factors


def _canonicalize_components(factors: list[np.ndarray]) -> tuple[np.ndarray, list[np.ndarray], np.ndarray]:
    sample_scores = factors[0].copy()
    non_observation = [factor.copy() for factor in factors[1:]]
    for component in range(sample_scores.shape[1]):
        for factor in non_observation:
            anchor = int(np.argmax(np.abs(factor[:, component])))
            if factor[anchor, component] < 0.0:
                factor[:, component] *= -1.0
                sample_scores[:, component] *= -1.0
    weights = np.linalg.norm(sample_scores, axis=0)
    order = np.lexsort((np.arange(weights.size), -weights))
    return sample_scores[:, order], [factor[:, order] for factor in non_observation], weights[order]


def fit_parafac(
    values: Any,
    *,
    parameters: Mapping[str, object],
    input_axis_identity_sha256: str,
    mode_roles: tuple[str, ...],
    source_contract_digest: str,
    spatial_mask: Any = None,
) -> dict[str, Any]:
    """Fit the bounded deterministic CP-ALS model and return closed state."""

    params = canonical_parafac_parameters(parameters)
    rank = int(params["n_components"])
    tensor = _validate_tensor(values, n_components=rank)
    mask = _validate_spatial_mask(spatial_mask, tensor)
    if mask is not None and tensor.ndim != 3:
        raise ValueError("Masked PARAFAC currently requires an exact three-mode image cube")
    if len(mode_roles) != tensor.ndim:
        raise ValueError("PARAFAC requires one canonical dimension role per input mode")
    if len(input_axis_identity_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in input_axis_identity_sha256
    ):
        raise ValueError("PARAFAC input axis identity is invalid")
    if (
        not isinstance(source_contract_digest, str)
        or len(source_contract_digest) != 64
        or any(character not in "0123456789abcdef" for character in source_contract_digest)
    ):
        raise ValueError("PARAFAC source contract digest is invalid")

    observed_tensor = _masked_tensor(tensor, mask) if mask is not None else tensor
    factors = _initial_factors(observed_tensor, rank)
    previous_error: float | None = None
    converged = False
    relative_error = (
        _masked_relative_reconstruction_error(observed_tensor, mask, factors)
        if mask is not None
        else _relative_reconstruction_error(tensor, factors)
    )
    iterations = 0
    for iterations in range(1, int(params["max_iter"]) + 1):
        for mode in range(tensor.ndim):
            factors[mode] = (
                _solve_masked_factor_3d(observed_tensor, mask, factors, mode, float(params["ridge"]))
                if mask is not None
                else _solve_factor(tensor, factors, mode, float(params["ridge"]))
            )
        _normalize_non_observation_factors(factors)
        relative_error = (
            _masked_relative_reconstruction_error(observed_tensor, mask, factors)
            if mask is not None
            else _relative_reconstruction_error(tensor, factors)
        )
        if previous_error is not None:
            change = abs(previous_error - relative_error) / max(previous_error, np.finfo(np.float64).eps)
            if change <= float(params["tol"]):
                converged = True
                break
        previous_error = relative_error

    _sample_scores, non_observation, _weights = _canonicalize_components(factors)
    arrays = {f"mode_{mode}_factor": factor for mode, factor in enumerate(non_observation, start=1)}
    metadata: dict[str, Any] = {
        "schema": PARAFAC_STATE_SCHEMA,
        "model_type": "parafac",
        "serializer": PARAFAC_STATE_SERIALIZER,
        "source_contract_digest": source_contract_digest,
        "n_components": rank,
        "training_shape": tuple(int(value) for value in tensor.shape),
        "non_observation_shape": tuple(int(value) for value in tensor.shape[1:]),
        "mode_roles": tuple(mode_roles),
        "input_axis_identity_sha256": input_axis_identity_sha256,
        "max_iter": int(params["max_iter"]),
        "tol": float(params["tol"]),
        "ridge": float(params["ridge"]),
        "n_iter": iterations,
        "converged": converged,
        "relative_reconstruction_error": relative_error,
        "initialization": PARAFAC_INITIALIZATION,
        "canonicalization": PARAFAC_CANONICALIZATION,
        "storage_order": PARAFAC_STORAGE_ORDER,
        "spatial_mask_policy": PARAFAC_SPATIAL_MASK_POLICY if mask is not None else "none",
        "included_spatial_cells": (
            int(np.count_nonzero(mask)) if mask is not None else int(tensor.shape[0] * tensor.shape[1])
        ),
        "excluded_spatial_cells": int(mask.size - np.count_nonzero(mask)) if mask is not None else 0,
    }
    metadata["state_content_digest"] = _state_content_digest(metadata, arrays)
    state = {"serializer": PARAFAC_STATE_SERIALIZER, "metadata": metadata, "arrays": arrays}
    validate_parafac_state(state)
    # Live scores and later observations must use one numerical authority.  The
    # ALS observation factor is not retained in the data-free state, so project
    # the training tensor through that state exactly as replay will project new
    # observations instead of exposing a subtly different fit-only quantity.
    sample_scores = apply_parafac(
        tensor,
        state,
        input_axis_identity_sha256=input_axis_identity_sha256,
        spatial_mask=mask,
    )
    weights = np.linalg.norm(sample_scores, axis=0)
    return {"state": state, "sample_scores": sample_scores, "component_weights": weights}


def validate_parafac_state(state: Any) -> dict[str, Any]:
    """Validate the exact data-free application state."""

    if not isinstance(state, Mapping) or set(state) != {"serializer", "metadata", "arrays"}:
        raise ValueError("PARAFAC state must contain exact serializer, metadata, and arrays")
    if state["serializer"] != PARAFAC_STATE_SERIALIZER:
        raise ValueError("PARAFAC state serializer is unsupported")
    metadata = state["metadata"]
    arrays = state["arrays"]
    expected_metadata = {
        "schema",
        "model_type",
        "serializer",
        "source_contract_digest",
        "state_content_digest",
        "n_components",
        "training_shape",
        "non_observation_shape",
        "mode_roles",
        "input_axis_identity_sha256",
        "max_iter",
        "tol",
        "ridge",
        "n_iter",
        "converged",
        "relative_reconstruction_error",
        "initialization",
        "canonicalization",
        "storage_order",
        "spatial_mask_policy",
        "included_spatial_cells",
        "excluded_spatial_cells",
    }
    if not isinstance(metadata, Mapping) or set(metadata) != expected_metadata:
        raise ValueError("PARAFAC state metadata is not closed")
    if metadata["schema"] != PARAFAC_STATE_SCHEMA or metadata["model_type"] != "parafac":
        raise ValueError("PARAFAC state schema is unsupported")
    if metadata["serializer"] != PARAFAC_STATE_SERIALIZER:
        raise ValueError("PARAFAC state metadata serializer is unsupported")
    source_contract_digest = metadata["source_contract_digest"]
    if (
        not isinstance(source_contract_digest, str)
        or len(source_contract_digest) != 64
        or any(character not in "0123456789abcdef" for character in source_contract_digest)
    ):
        raise ValueError("PARAFAC state source contract digest is invalid")
    params = canonical_parafac_parameters(
        {
            "n_components": metadata["n_components"],
            "max_iter": metadata["max_iter"],
            "tol": metadata["tol"],
            "ridge": metadata["ridge"],
        }
    )
    rank = int(params["n_components"])
    training_shape = tuple(metadata["training_shape"])
    non_observation_shape = tuple(metadata["non_observation_shape"])
    mode_roles = tuple(metadata["mode_roles"])
    if (
        not 3 <= len(training_shape) <= _MAX_NDIM
        or any(type(value) is not int or value < 2 for value in training_shape)
        or non_observation_shape != training_shape[1:]
        or len(mode_roles) != len(training_shape)
    ):
        raise ValueError("PARAFAC state shape or dimension roles are invalid")
    digest = metadata["input_axis_identity_sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("PARAFAC state axis identity is invalid")
    if type(metadata["n_iter"]) is not int or not 1 <= metadata["n_iter"] <= params["max_iter"]:
        raise ValueError("PARAFAC state iteration count is invalid")
    if type(metadata["converged"]) is not bool:
        raise ValueError("PARAFAC state convergence flag is invalid")
    error = metadata["relative_reconstruction_error"]
    if isinstance(error, bool) or not isinstance(error, (int, float)) or not np.isfinite(error) or error < 0.0:
        raise ValueError("PARAFAC state reconstruction error is invalid")
    if metadata["initialization"] != PARAFAC_INITIALIZATION:
        raise ValueError("PARAFAC state initialization is unsupported")
    if metadata["canonicalization"] != PARAFAC_CANONICALIZATION:
        raise ValueError("PARAFAC state canonicalization is unsupported")
    if metadata["storage_order"] != PARAFAC_STORAGE_ORDER:
        raise ValueError("PARAFAC state storage order is unsupported")
    mask_policy = metadata["spatial_mask_policy"]
    if mask_policy not in {"none", PARAFAC_SPATIAL_MASK_POLICY}:
        raise ValueError("PARAFAC state spatial-mask policy is unsupported")
    included_cells = metadata["included_spatial_cells"]
    excluded_cells = metadata["excluded_spatial_cells"]
    if (
        type(included_cells) is not int
        or type(excluded_cells) is not int
        or included_cells <= 0
        or excluded_cells < 0
        or included_cells + excluded_cells != training_shape[0] * training_shape[1]
        or (mask_policy == "none" and excluded_cells != 0)
    ):
        raise ValueError("PARAFAC state spatial-mask census is invalid")
    if not isinstance(arrays, Mapping):
        raise ValueError("PARAFAC state arrays must be a mapping")
    expected_arrays = {f"mode_{mode}_factor" for mode in range(1, len(training_shape))}
    if set(arrays) != expected_arrays:
        raise ValueError("PARAFAC state factor inventory is invalid")
    normalized_arrays: dict[str, np.ndarray] = {}
    for mode, dimension in enumerate(non_observation_shape, start=1):
        name = f"mode_{mode}_factor"
        factor = np.asarray(arrays[name], dtype=np.float64)
        if factor.shape != (dimension, rank) or not np.isfinite(factor).all():
            raise ValueError(f"PARAFAC {name} has invalid shape or values")
        norms = np.linalg.norm(factor, axis=0)
        if not np.allclose(norms, 1.0, rtol=1e-8, atol=1e-10):
            raise ValueError(f"PARAFAC {name} is not canonically normalized")
        normalized_arrays[name] = factor.copy()
    state_content_digest = metadata["state_content_digest"]
    if (
        not isinstance(state_content_digest, str)
        or len(state_content_digest) != 64
        or any(character not in "0123456789abcdef" for character in state_content_digest)
        or state_content_digest != _state_content_digest(metadata, normalized_arrays)
    ):
        raise ValueError("PARAFAC state content digest does not match")
    return {
        "serializer": PARAFAC_STATE_SERIALIZER,
        "metadata": dict(metadata),
        "arrays": normalized_arrays,
    }


def apply_parafac(
    values: Any,
    state: Any,
    *,
    input_axis_identity_sha256: str,
    spatial_mask: Any = None,
) -> np.ndarray:
    """Solve observation-mode scores for new data against frozen factors."""

    normalized = validate_parafac_state(state)
    metadata = normalized["metadata"]
    rank = int(metadata["n_components"])
    tensor = _validate_tensor(values, n_components=rank)
    mask = _validate_spatial_mask(spatial_mask, tensor)
    if tuple(tensor.shape[1:]) != tuple(metadata["non_observation_shape"]):
        raise ValueError("PARAFAC application requires the fitted non-observation shape")
    if input_axis_identity_sha256 != metadata["input_axis_identity_sha256"]:
        raise ValueError("PARAFAC application input axes differ from the fitted multiway axes")
    factors = [normalized["arrays"][f"mode_{mode}_factor"] for mode in range(1, tensor.ndim)]
    mask_policy = metadata["spatial_mask_policy"]
    if mask_policy == PARAFAC_SPATIAL_MASK_POLICY:
        if mask is None or tensor.ndim != 3:
            raise ValueError("PARAFAC application requires the fitted spatial-mask policy")
        design = _khatri_rao(factors)
        weighted = _masked_tensor(tensor, mask)
        numerator = _unfold(weighted, 0) @ design
        row_grams = np.einsum("ij,jr,js->irs", mask, factors[0], factors[0], optimize=True)
        if len(factors) != 2:
            raise ValueError("Masked PARAFAC application requires an exact three-mode image cube")
        row_grams *= (factors[1].T @ factors[1])[np.newaxis, :, :]
        ridge = float(metadata["ridge"])
        if ridge:
            row_grams = row_grams + ridge * np.eye(rank, dtype=np.float64)[np.newaxis, :, :]
        scores = np.einsum("ir,irs->is", numerator, np.linalg.pinv(row_grams, hermitian=True), optimize=True)
        if not np.isfinite(scores).all():
            raise ValueError("Masked PARAFAC application produced non-finite mode-1 scores")
        return scores
    if mask is not None:
        raise ValueError("PARAFAC application supplied a spatial mask to an unmasked fitted state")
    design = _khatri_rao(factors)
    gram = design.T @ design
    ridge = float(metadata["ridge"])
    if ridge:
        gram = gram + ridge * np.eye(rank, dtype=np.float64)
    scores = (_unfold(tensor, 0) @ design) @ np.linalg.pinv(gram, hermitian=True)
    if not np.isfinite(scores).all():
        raise ValueError("PARAFAC application produced non-finite observation scores")
    return scores


@dataclass(frozen=True)
class PARAFACExtract:
    """Artifact adapter for the data-free non-observation factor state."""

    state: Mapping[str, Any]

    def to_artifact(self) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        normalized = validate_parafac_state(self.state)
        return dict(normalized["metadata"]), {
            name: np.asarray(value, dtype=np.float64).copy() for name, value in normalized["arrays"].items()
        }


__all__ = [
    "PARAFAC_CANONICALIZATION",
    "PARAFAC_INITIALIZATION",
    "PARAFAC_STATE_SCHEMA",
    "PARAFAC_STATE_SERIALIZER",
    "PARAFAC_SPATIAL_MASK_POLICY",
    "PARAFACExtract",
    "apply_parafac",
    "canonical_parafac_parameters",
    "fit_parafac",
    "validate_parafac_state",
]
