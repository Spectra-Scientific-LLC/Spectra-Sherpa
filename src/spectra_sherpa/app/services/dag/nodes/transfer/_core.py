"""Shared custody and admission for canonical spectral calibration transfer.

The equations for SWS, DS, and PDS remain owned by their individual node
modules.  This module owns only the cross-method invariants: paired-sample
identity, measured spectral axes, finite matrices, closed state envelopes,
application-axis verification, output reconstruction, and diagnostics.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.io_contracts import bind_X, build_dataset_like, to_numpy_2d
from spectra_sherpa.core.axis_semantics import AxisQuantity, axis_semantics, require_compatible_axis_semantics

_ENVELOPE_SCHEMA = "spectrasherpa.model-artifact.spectral-transfer-envelope/1"
_SHA256 = frozenset("0123456789abcdef")


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _digest(value: object, *, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in _SHA256 for character in value):
        raise ValueError(f"spectral transfer state has an invalid {name}")
    return value


def positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"spectral transfer state has an invalid {name}")
    return value


def finite_vector(value: object, *, name: str, size: int) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (size,) or not np.isfinite(array).all():
        raise ValueError(f"spectral transfer state has an invalid {name}")
    return np.array(array, copy=True)


def finite_matrix(
    value: object,
    *,
    name: str,
    rows: int | None = None,
    columns: int | None = None,
) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if (
        array.ndim != 2
        or (rows is not None and array.shape[0] != rows)
        or (columns is not None and array.shape[1] != columns)
        or not np.isfinite(array).all()
    ):
        raise ValueError(f"spectral transfer state has an invalid {name}")
    return np.array(array, copy=True)


def _axis_payload(dataset: Any, *, name: str, features: int) -> dict[str, object]:
    axis = getattr(dataset, "feature_axis", None)
    values = None if axis is None else getattr(axis, "values", None)
    title = None if axis is None else getattr(axis, "title", None)
    units = None if axis is None else getattr(axis, "units", None)
    quantity = None if axis is None else getattr(axis, "quantity", None)
    labels = None if axis is None else getattr(axis, "labels", None)
    coordinates = np.asarray(values, dtype=np.float64) if values is not None else np.asarray([])
    if coordinates.shape != (features,) or not np.isfinite(coordinates).all():
        raise ValueError(f"{name} requires one finite measured spectral coordinate per feature")
    differences = np.diff(coordinates)
    if differences.size and not (np.all(differences > 0.0) or np.all(differences < 0.0)):
        raise ValueError(f"{name} spectral coordinates must be strictly monotonic")
    if not isinstance(units, str) or not units.strip():
        raise ValueError(f"{name} requires declared spectral-axis units")
    semantics = axis_semantics(
        axis_class=type(axis).__name__,
        title=title,
        units=units,
        quantity=quantity,
    )
    if semantics.quantity is None:
        raise ValueError(f"{name} requires a declared spectral-axis quantity")
    normalized_labels: list[str] | None = None
    if labels is not None:
        if not isinstance(labels, list) or len(labels) != features or not all(isinstance(item, str) for item in labels):
            raise ValueError(f"{name} spectral labels must match its feature count")
        normalized_labels = list(labels)
    return {
        "values": coordinates.tolist(),
        "labels": normalized_labels,
        "title": title.strip() if isinstance(title, str) and title.strip() else None,
        "quantity": semantics.quantity.value,
        "units": semantics.units,
    }


def normalize_axis_payload(value: object, *, name: str, features: int) -> dict[str, object]:
    required = {"values", "labels", "title", "quantity", "units"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError(f"spectral transfer state has an invalid {name} axis")
    coordinates = finite_vector(value["values"], name=f"{name}.values", size=features)
    differences = np.diff(coordinates)
    if differences.size and not (np.all(differences > 0.0) or np.all(differences < 0.0)):
        raise ValueError(f"spectral transfer state has a non-monotonic {name} axis")
    title = value["title"]
    units = value["units"]
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError(f"spectral transfer state has invalid {name} axis display title")
    if not isinstance(units, str) or not units.strip():
        raise ValueError(f"spectral transfer state has incomplete {name} axis metadata")
    semantics = axis_semantics(
        axis_class="SpectralAxis",
        title=title,
        units=units,
        quantity=value["quantity"],
    )
    if semantics.quantity is None or semantics.units is None:
        raise ValueError(f"spectral transfer state has incomplete {name} axis semantics")
    labels = value["labels"]
    if labels is not None and (
        not isinstance(labels, list) or len(labels) != features or not all(isinstance(item, str) for item in labels)
    ):
        raise ValueError(f"spectral transfer state has invalid {name} axis labels")
    return {
        "values": coordinates.tolist(),
        "labels": None if labels is None else list(labels),
        "title": title.strip() if isinstance(title, str) else None,
        "quantity": semantics.quantity.value,
        "units": semantics.units,
    }


def _scientific_axis_identity(axis: Mapping[str, object]) -> dict[str, object]:
    """Exclude the human-facing title from fitted-state identity."""

    return {key: axis[key] for key in ("values", "labels", "quantity", "units")}


def _sample_identity(dataset: Any, *, name: str, samples: int) -> tuple[list[str], str]:
    sample_axis = getattr(dataset, "sample_axis", None)
    labels = None if sample_axis is None else getattr(sample_axis, "labels", None)
    if (
        not isinstance(labels, list)
        or len(labels) != samples
        or not all(isinstance(item, str) and item for item in labels)
        or len(set(labels)) != samples
    ):
        raise ValueError(f"{name} requires unique sample labels to prove paired transfer identity")
    normalized = list(labels)
    return normalized, sha256_json(normalized)


def _signal_units(dataset: Any, *, name: str) -> str | None:
    units = getattr(dataset, "units", None)
    if units is None or (isinstance(units, str) and not units.strip()):
        return None
    if not isinstance(units, str):
        raise ValueError(f"{name} has invalid signal units")
    return units.strip()


def admit_paired_spectra(
    X_primary: Any,
    X_secondary: Any,
    *,
    require_common_axis: bool,
) -> tuple[Any, Any, np.ndarray, np.ndarray, dict[str, object]]:
    """Admit exact paired transfer standards and return their closed binding."""

    primary = bind_X(X_primary, missing_message="calibration transfer requires primary spectra", allow_array=False)
    secondary = bind_X(
        X_secondary, missing_message="calibration transfer requires secondary spectra", allow_array=False
    )
    primary_matrix = to_numpy_2d(primary, name="X_primary", dtype=np.float64)
    secondary_matrix = to_numpy_2d(secondary, name="X_secondary", dtype=np.float64)
    if primary_matrix.shape[0] < 2 or secondary_matrix.shape[0] != primary_matrix.shape[0]:
        raise ValueError("calibration transfer requires at least two exactly paired primary/secondary samples")
    if not np.isfinite(primary_matrix).all() or not np.isfinite(secondary_matrix).all():
        raise ValueError("calibration transfer standards must be finite")
    primary_labels, primary_sample_digest = _sample_identity(
        primary,
        name="X_primary",
        samples=primary_matrix.shape[0],
    )
    secondary_labels, secondary_sample_digest = _sample_identity(
        secondary,
        name="X_secondary",
        samples=secondary_matrix.shape[0],
    )
    if primary_labels != secondary_labels or primary_sample_digest != secondary_sample_digest:
        raise ValueError("primary and secondary transfer standards do not have identical ordered sample identities")
    primary_axis = _axis_payload(primary, name="X_primary", features=primary_matrix.shape[1])
    secondary_axis = _axis_payload(secondary, name="X_secondary", features=secondary_matrix.shape[1])
    require_compatible_axis_semantics(
        axis_semantics(
            axis_class="SpectralAxis",
            title=primary_axis["title"],
            units=primary_axis["units"],
            quantity=primary_axis["quantity"],
        ),
        axis_semantics(
            axis_class="SpectralAxis",
            title=secondary_axis["title"],
            units=secondary_axis["units"],
            quantity=secondary_axis["quantity"],
        ),
        context="calibration transfer",
    )
    if require_common_axis and (
        primary_axis["values"] != secondary_axis["values"] or primary_axis["labels"] != secondary_axis["labels"]
    ):
        raise ValueError(
            "this calibration-transfer method requires an identical spectral grid; "
            "use preprocess.wavenumber_align before calibration transfer"
        )
    primary_units = _signal_units(primary, name="X_primary")
    secondary_units = _signal_units(secondary, name="X_secondary")
    if primary_units != secondary_units:
        raise ValueError("primary and secondary transfer standards require identical signal units")
    binding = {
        "reference_samples": primary_matrix.shape[0],
        "primary_features": primary_matrix.shape[1],
        "secondary_features": secondary_matrix.shape[1],
        "paired_sample_identity_sha256": primary_sample_digest,
        "primary_axis": primary_axis,
        "secondary_axis": secondary_axis,
        "primary_signal_units": primary_units,
        "secondary_signal_units": secondary_units,
    }
    return primary, secondary, primary_matrix, secondary_matrix, binding


def normalize_common_state(state: Mapping[str, object], *, method: str) -> dict[str, object]:
    reference_samples = positive_int(state["reference_samples"], name="reference_samples")
    primary_features = positive_int(state["primary_features"], name="primary_features")
    secondary_features = positive_int(state["secondary_features"], name="secondary_features")
    paired_digest = _digest(state["paired_sample_identity_sha256"], name="paired_sample_identity_sha256")
    primary_axis = normalize_axis_payload(state["primary_axis"], name="primary", features=primary_features)
    secondary_axis = normalize_axis_payload(state["secondary_axis"], name="secondary", features=secondary_features)
    primary_units = state["primary_signal_units"]
    secondary_units = state["secondary_signal_units"]
    if primary_units is not None and (not isinstance(primary_units, str) or not primary_units):
        raise ValueError("spectral transfer state has invalid signal units")
    if secondary_units is not None and (not isinstance(secondary_units, str) or not secondary_units):
        raise ValueError("spectral transfer state has invalid signal units")
    if primary_units != secondary_units:
        raise ValueError("spectral transfer state has inconsistent signal units")
    if state["method"] != method:
        raise ValueError(f"spectral transfer state is not a {method} state")
    return {
        "method": method,
        "reference_samples": reference_samples,
        "primary_features": primary_features,
        "secondary_features": secondary_features,
        "paired_sample_identity_sha256": paired_digest,
        "primary_axis": primary_axis,
        "secondary_axis": secondary_axis,
        "primary_signal_units": primary_units,
        "secondary_signal_units": secondary_units,
    }


def apply_input(input_data: Any, state: Mapping[str, object]) -> tuple[Any, np.ndarray]:
    source = bind_X(
        input_data, missing_message="spectral transfer application requires secondary spectra", allow_array=False
    )
    matrix = to_numpy_2d(source, name="X_secondary_new", dtype=np.float64)
    secondary_features = positive_int(state["secondary_features"], name="secondary_features")
    if matrix.shape[1] != secondary_features or not np.isfinite(matrix).all():
        raise ValueError("spectral transfer application input does not match the fitted secondary feature count")
    axis = _axis_payload(source, name="X_secondary_new", features=secondary_features)
    if _scientific_axis_identity(axis) != _scientific_axis_identity(state["secondary_axis"]):
        raise ValueError("spectral transfer application input does not match the fitted secondary spectral axis")
    if _signal_units(source, name="X_secondary_new") != state["secondary_signal_units"]:
        raise ValueError("spectral transfer application input does not match the fitted secondary signal units")
    return source, matrix


def build_primary_output(data: np.ndarray, source: Any, state: Mapping[str, object]):
    primary_features = positive_int(state["primary_features"], name="primary_features")
    matrix = finite_matrix(data, name="standardized output", columns=primary_features)
    result = build_dataset_like(matrix, source, units=state["primary_signal_units"])
    axis = normalize_axis_payload(state["primary_axis"], name="primary", features=primary_features)
    result.feature_axis = SpectralAxis(
        values=np.asarray(axis["values"], dtype=np.float64),
        labels=axis["labels"],
        title=axis["title"],
        units=str(axis["units"]),
        quantity=AxisQuantity(str(axis["quantity"])),
    )
    supervision_binding.rebind_sample_preserving_supervision(source, result)
    return result


def transfer_diagnostics(primary: np.ndarray, fitted_secondary: np.ndarray) -> dict[str, object]:
    primary_matrix = finite_matrix(primary, name="primary standards")
    fitted = finite_matrix(
        fitted_secondary,
        name="fitted secondary standards",
        rows=primary_matrix.shape[0],
        columns=primary_matrix.shape[1],
    )
    residuals = primary_matrix - fitted
    return {
        "rmse_transfer": float(np.sqrt(np.mean(residuals**2))),
        "max_error": float(np.max(np.abs(residuals))),
        "per_feature_rmse": np.sqrt(np.mean(residuals**2, axis=0)).tolist(),
        "reference_samples": primary_matrix.shape[0],
        "primary_features": primary_matrix.shape[1],
    }


def make_state_envelope(
    state: Mapping[str, object],
    *,
    source_operation_id: str,
    serializer: str,
    source_contract_digest: str,
    normalize: Callable[[object], dict[str, object]],
) -> dict[str, object]:
    normalized = normalize(state)
    return {
        "schema_version": _ENVELOPE_SCHEMA,
        "source_operation_id": source_operation_id,
        "serializer": serializer,
        "source_contract_digest": source_contract_digest,
        "state_content_digest": sha256_json(normalized),
        "state": normalized,
    }


def verify_state_envelope(
    value: object,
    *,
    source_operation_id: str,
    serializer: str,
    source_contract_digest: str,
    normalize: Callable[[object], dict[str, object]],
) -> dict[str, object]:
    required = {
        "schema_version",
        "source_operation_id",
        "serializer",
        "source_contract_digest",
        "state_content_digest",
        "state",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("spectral transfer state envelope does not use the closed schema")
    if (
        value["schema_version"] != _ENVELOPE_SCHEMA
        or value["source_operation_id"] != source_operation_id
        or value["serializer"] != serializer
        or value["source_contract_digest"] != source_contract_digest
    ):
        raise ValueError("spectral transfer state envelope has an unsupported producer identity")
    normalized = normalize(value["state"])
    if value["state_content_digest"] != sha256_json(normalized):
        raise ValueError("spectral transfer state envelope content digest does not match")
    return normalized


__all__ = [
    "admit_paired_spectra",
    "apply_input",
    "build_primary_output",
    "finite_matrix",
    "finite_vector",
    "make_state_envelope",
    "normalize_common_state",
    "positive_int",
    "sha256_json",
    "transfer_diagnostics",
    "verify_state_envelope",
]
