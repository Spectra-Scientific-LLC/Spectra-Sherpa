"""Canonical numerical authority for non-negative matrix factorization."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

import numpy as np
from sklearn.decomposition import non_negative_factorization

NMF_STATE_SERIALIZER = "spectrasherpa.model.nmf-state/1"
NMF_PARAMETER_KEYS = frozenset({"n_components", "solver", "max_iter", "tol", "random_state"})
NMF_SOLVERS = frozenset({"mu", "cd"})
NMF_INITIALIZATION = "nndsvda"
NMF_LOSS = "frobenius"
NMF_COMPONENT_ORDER = "dominant_feature_then_weighted_feature_center_then_original_ordinal"
NMF_APPLICATION_RULE = "fixed_basis_nonnegative_transform_reestimates_concentrations"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def canonical_nmf_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """Validate the exact scientist-controlled NMF parameter set."""

    if set(parameters) != NMF_PARAMETER_KEYS:
        raise ValueError("NMF parameters must use the exact current five-field schema")
    n_components = parameters["n_components"]
    max_iter = parameters["max_iter"]
    random_state = parameters["random_state"]
    if isinstance(n_components, bool) or not isinstance(n_components, int) or not 2 <= n_components <= 500:
        raise ValueError("NMF n_components must be an integer between 2 and 500")
    if isinstance(max_iter, bool) or not isinstance(max_iter, int) or not 1 <= max_iter <= 10_000:
        raise ValueError("NMF max_iter must be an integer between 1 and 10000")
    if isinstance(random_state, bool) or not isinstance(random_state, int) or not 0 <= random_state <= 2**32 - 1:
        raise ValueError("NMF random_state must be an unsigned 32-bit integer")
    solver = parameters["solver"]
    if not isinstance(solver, str) or solver not in NMF_SOLVERS:
        raise ValueError("NMF solver must be one of: cd, mu")
    tolerance = parameters["tol"]
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not np.isfinite(tolerance)
        or not 1e-12 <= float(tolerance) <= 0.1
    ):
        raise ValueError("NMF tol must be finite and between 1e-12 and 0.1")
    return {
        "n_components": n_components,
        "solver": solver,
        "max_iter": max_iter,
        "tol": float(tolerance),
        "random_state": random_state,
    }


def _matrix(input_data: Any, *, operation: str) -> np.ndarray:
    value = input_data.data if hasattr(input_data, "data") else input_data
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 2:
        raise ValueError(f"{operation} input must have at least two observations and two features")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{operation} input must contain only finite values")
    minimum = float(np.min(matrix))
    if minimum < 0.0:
        raise ValueError(
            f"{operation} requires non-negative input data, but found minimum value {minimum:.4g}; "
            "apply an explicit scientifically justified correction before NMF"
        )
    if not np.any(matrix > 0.0):
        raise ValueError(f"{operation} input must contain at least one positive value")
    return np.ascontiguousarray(matrix)


def _matrix_digest(matrix: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(matrix, dtype="<f8").tobytes(order="C")).hexdigest()


def _feature_axis_identity(input_data: Any, *, features: int) -> tuple[str | None, str | None, str | None]:
    feature_axis = getattr(input_data, "feature_axis", None)
    values = None if feature_axis is None else getattr(feature_axis, "values", None)
    labels = None if feature_axis is None else getattr(feature_axis, "labels", None)
    units = None if feature_axis is None else getattr(feature_axis, "units", None)
    values_digest = None
    if values is not None:
        axis = np.asarray(values, dtype="<f8")
        if axis.shape != (features,) or not np.isfinite(axis).all():
            raise ValueError("NMF feature-axis values must be finite and match the feature count")
        values_digest = hashlib.sha256(axis.tobytes(order="C")).hexdigest()
    labels_digest = None
    if labels is not None:
        normalized = np.asarray(labels, dtype=object).reshape(-1).tolist()
        if len(normalized) != features or not all(isinstance(item, str) for item in normalized):
            raise ValueError("NMF feature-axis labels must match the feature count")
        encoded = json.dumps(normalized, separators=(",", ":"), ensure_ascii=False).encode()
        labels_digest = hashlib.sha256(encoded).hexdigest()
    return values_digest, labels_digest, None if units is None else str(units)


def _canonical_component_order(components: np.ndarray) -> np.ndarray:
    feature_index = np.arange(components.shape[1], dtype=np.float64)
    dominant = np.argmax(components, axis=1)
    totals = np.sum(components, axis=1)
    centers = np.divide(
        components @ feature_index,
        totals,
        out=np.full(components.shape[0], np.inf, dtype=np.float64),
        where=totals > 0.0,
    )
    ordinal = np.arange(components.shape[0])
    return np.lexsort((ordinal, centers, dominant))


def fit_nmf(input_data: Any, *, parameters: Mapping[str, object]) -> dict[str, Any]:
    """Fit deterministic NMF and return a closed, serializable factor state."""

    canonical = canonical_nmf_parameters(parameters)
    matrix = _matrix(input_data, operation="NMF")
    n_components = int(canonical["n_components"])
    if n_components > min(matrix.shape):
        raise ValueError("NMF n_components may not exceed the smaller input dimension")
    concentrations, components, n_iter = non_negative_factorization(
        matrix,
        n_components=n_components,
        init=NMF_INITIALIZATION,
        update_H=True,
        solver=str(canonical["solver"]),
        beta_loss=NMF_LOSS,
        tol=float(canonical["tol"]),
        max_iter=int(canonical["max_iter"]),
        random_state=int(canonical["random_state"]),
        alpha_W=0.0,
        alpha_H=0.0,
        l1_ratio=0.0,
        shuffle=False,
    )
    order = _canonical_component_order(components)
    concentrations = np.asarray(concentrations[:, order], dtype=np.float64)
    components = np.asarray(components[order, :], dtype=np.float64)
    reconstruction_error = float(np.linalg.norm(matrix - concentrations @ components, ord="fro"))
    axis_values, axis_labels, axis_units = _feature_axis_identity(input_data, features=matrix.shape[1])
    return {
        "schema_version": NMF_STATE_SERIALIZER,
        "parameters": canonical,
        "initialization": NMF_INITIALIZATION,
        "loss": NMF_LOSS,
        "component_order": NMF_COMPONENT_ORDER,
        "application_rule": NMF_APPLICATION_RULE,
        "n_samples": int(matrix.shape[0]),
        "n_features": int(matrix.shape[1]),
        "training_input_sha256": _matrix_digest(matrix),
        "feature_axis_values_sha256": axis_values,
        "feature_axis_labels_sha256": axis_labels,
        "feature_axis_units": axis_units,
        "concentrations": concentrations.tolist(),
        "components": components.tolist(),
        "reconstruction_error": reconstruction_error,
        "n_iter": int(n_iter),
        "convergence_status": "converged" if int(n_iter) < int(canonical["max_iter"]) else "max_iter_reached",
    }


def validate_nmf_state(state: object) -> dict[str, Any]:
    """Validate the exact current NMF fitted-state schema."""

    required = {
        "schema_version",
        "parameters",
        "initialization",
        "loss",
        "component_order",
        "application_rule",
        "n_samples",
        "n_features",
        "training_input_sha256",
        "feature_axis_values_sha256",
        "feature_axis_labels_sha256",
        "feature_axis_units",
        "concentrations",
        "components",
        "reconstruction_error",
        "n_iter",
        "convergence_status",
    }
    if not isinstance(state, dict) or set(state) != required or state.get("schema_version") != NMF_STATE_SERIALIZER:
        raise ValueError("NMF fitted state must use the exact current schema")
    parameters = state["parameters"]
    if not isinstance(parameters, Mapping):
        raise ValueError("NMF fitted-state parameters must be an object")
    canonical = canonical_nmf_parameters(parameters)
    n_samples = state["n_samples"]
    n_features = state["n_features"]
    if isinstance(n_samples, bool) or not isinstance(n_samples, int) or n_samples < 2:
        raise ValueError("NMF fitted state has an invalid observation count")
    if isinstance(n_features, bool) or not isinstance(n_features, int) or n_features < 2:
        raise ValueError("NMF fitted state has an invalid feature count")
    digest = state["training_input_sha256"]
    if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError("NMF fitted state has an invalid training digest")
    for key in ("feature_axis_values_sha256", "feature_axis_labels_sha256"):
        value = state[key]
        if value is not None and (not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None):
            raise ValueError("NMF fitted state has an invalid feature-axis digest")
    if state["feature_axis_units"] is not None and not isinstance(state["feature_axis_units"], str):
        raise ValueError("NMF fitted state has invalid feature-axis units")
    concentrations = np.asarray(state["concentrations"], dtype=np.float64)
    components = np.asarray(state["components"], dtype=np.float64)
    expected_components = int(canonical["n_components"])
    if concentrations.shape != (n_samples, expected_components):
        raise ValueError("NMF concentration state does not match its declared dimensions")
    if components.shape != (expected_components, n_features):
        raise ValueError("NMF component state does not match its declared dimensions")
    if not np.all(np.isfinite(concentrations)) or not np.all(np.isfinite(components)):
        raise ValueError("NMF fitted state contains non-finite factors")
    if np.any(concentrations < 0.0) or np.any(components < 0.0):
        raise ValueError("NMF fitted-state factors must be non-negative")
    reconstruction_error = state["reconstruction_error"]
    if (
        isinstance(reconstruction_error, bool)
        or not isinstance(reconstruction_error, (int, float))
        or not np.isfinite(reconstruction_error)
        or reconstruction_error < 0.0
    ):
        raise ValueError("NMF fitted state has an invalid reconstruction error")
    n_iter = state["n_iter"]
    if isinstance(n_iter, bool) or not isinstance(n_iter, int) or not 1 <= n_iter <= int(canonical["max_iter"]):
        raise ValueError("NMF fitted state has an invalid iteration count")
    expected_status = "converged" if n_iter < int(canonical["max_iter"]) else "max_iter_reached"
    if state["convergence_status"] != expected_status:
        raise ValueError("NMF convergence status does not match its iteration evidence")
    if (
        state["initialization"] != NMF_INITIALIZATION
        or state["loss"] != NMF_LOSS
        or state["component_order"] != NMF_COMPONENT_ORDER
        or state["application_rule"] != NMF_APPLICATION_RULE
    ):
        raise ValueError("NMF fitted state uses an unknown numerical convention")
    if not np.array_equal(_canonical_component_order(components), np.arange(expected_components)):
        raise ValueError("NMF components do not follow the canonical ordering rule")
    return state


def apply_nmf(input_data: Any, state: object) -> np.ndarray:
    """Estimate non-negative concentrations against a frozen component basis."""

    validated = validate_nmf_state(state)
    matrix = _matrix(input_data, operation="NMF application")
    if matrix.shape[1] != validated["n_features"]:
        raise ValueError("NMF application feature count does not match the fitted basis")
    if _feature_axis_identity(input_data, features=matrix.shape[1]) != (
        validated["feature_axis_values_sha256"],
        validated["feature_axis_labels_sha256"],
        validated["feature_axis_units"],
    ):
        raise ValueError("NMF application data does not match the fitted feature axis")
    parameters = validated["parameters"]
    return apply_nmf_basis(
        matrix,
        components=np.asarray(validated["components"], dtype=np.float64),
        parameters=parameters,
    )


def apply_nmf_basis(
    input_data: Any,
    *,
    components: Any,
    parameters: Mapping[str, object],
) -> np.ndarray:
    """Estimate concentrations against one frozen basis with the canonical solver."""

    matrix = _matrix(input_data, operation="NMF application")
    canonical = canonical_nmf_parameters(parameters)
    basis = np.asarray(components, dtype=np.float64)
    if basis.shape != (int(canonical["n_components"]), matrix.shape[1]):
        raise ValueError("NMF application basis does not match the declared component and feature counts")
    if not np.all(np.isfinite(basis)) or np.any(basis < 0.0):
        raise ValueError("NMF application basis must contain only finite non-negative values")
    concentrations, _, _ = non_negative_factorization(
        matrix,
        H=basis,
        n_components=int(canonical["n_components"]),
        init="custom",
        update_H=False,
        solver=str(canonical["solver"]),
        beta_loss=NMF_LOSS,
        tol=float(canonical["tol"]),
        max_iter=int(canonical["max_iter"]),
        random_state=int(canonical["random_state"]),
        alpha_W=0.0,
        alpha_H=0.0,
        l1_ratio=0.0,
        shuffle=False,
    )
    return np.asarray(concentrations, dtype=np.float64)


def nmf_numeric_outputs(input_data: Any, *, parameters: Mapping[str, object]) -> dict[str, Any]:
    """Return the common raw numerical projection used by live and exported execution."""

    state = fit_nmf(input_data, parameters=parameters)
    return {
        "default": np.asarray(state["concentrations"], dtype=np.float64),
        "concentrations": np.asarray(state["concentrations"], dtype=np.float64),
        "spectra": np.asarray(state["components"], dtype=np.float64),
        "model": state,
        "reconstruction_error": state["reconstruction_error"],
    }
