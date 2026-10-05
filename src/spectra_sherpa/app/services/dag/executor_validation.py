"""Port-type and spectral-unit validation for the DAG executor."""

from __future__ import annotations

import warnings
from typing import Any

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset


def _is_dataset(obj: Any) -> bool:
    """Return whether *obj* is the canonical dataset transport."""

    return isinstance(obj, SherpaDataset)


def _is_estimator_like(obj: Any) -> bool:
    """Return True for bare fitted/transformer-style model objects."""
    return hasattr(obj, "fit") or hasattr(obj, "transform") or hasattr(obj, "predict")


def _is_model_payload(obj: Any) -> bool:
    """Return True for built-in model artifacts passed between nodes.

    Runtime workflows use both bare estimators and wrapped model dicts. The
    wrapped forms are intentionally narrow here so plain config dicts do not
    silently validate as models.
    """
    if _is_estimator_like(obj):
        return True

    if not isinstance(obj, dict):
        return False

    nested_model = obj.get("model")
    if nested_model is not None and _is_estimator_like(nested_model):
        return True
    if isinstance(nested_model, dict):
        nested_serializer = nested_model.get("serializer")
        if isinstance(nested_serializer, str) and nested_serializer.startswith("spectrasherpa.model-artifact."):
            return True

    class_models = obj.get("class_models")
    if isinstance(class_models, dict) and class_models:
        return True

    model_id = obj.get("model_id")
    if isinstance(model_id, str) and model_id.strip():
        return True

    # Canonical fitted states are deliberately data-only mappings rather than
    # live estimator objects.  The receiving application node performs the
    # serializer-specific closed-schema validation; this runtime category
    # check only needs to distinguish an artifact state from an arbitrary
    # configuration mapping.
    serializer = obj.get("serializer")
    if isinstance(serializer, str) and serializer.startswith("spectrasherpa.model-artifact."):
        return True

    # Native fitted-model families may use a closed serializer-owned state
    # before the durable model-artifact envelope is built. The consumer owns
    # full schema validation; this check only recognizes the narrow transport.
    if (
        set(obj) == {"serializer", "metadata", "arrays"}
        and isinstance(serializer, str)
        and serializer.startswith("spectrasherpa.")
        and "-state/" in serializer
        and isinstance(obj.get("metadata"), dict)
        and isinstance(obj.get("arrays"), dict)
    ):
        return True

    # Some fitted families use a closed outer envelope so the producer
    # contract identity and the inner state serializer are both bound.  The
    # receiving node still performs full closed-schema and digest validation;
    # this category check merely recognizes that envelope as model data.
    schema_version = obj.get("schema_version")
    if (
        schema_version == "spectrasherpa.local-regression-application/1"
        and set(obj)
        == {
            "schema_version",
            "operation_id",
            "source_contract_digest",
            "input_identity",
            "response_identity",
            "metadata",
            "arrays",
            "state_content_digest",
        }
        and isinstance(obj.get("metadata"), dict)
        and isinstance(obj.get("arrays"), dict)
    ):
        return True  # Predictor still verifies the schema, digest, axes and producer.
    if (
        set(obj) == {"serializer", "operation_id", "input_identity", "state"}
        and obj.get("operation_id") in {"model.fitted_pcr", "model.fitted_svr", "model.fitted_linear_regression"}
        and serializer == f"spectrasherpa.{obj['operation_id']}/1"
        and isinstance(obj.get("state"), dict)
    ):
        return True
    if isinstance(schema_version, str) and schema_version.startswith("spectrasherpa.model-artifact."):
        return True

    # Local fit/apply nodes exchange one closed, data-only fitted-state
    # envelope.  Recognize that exact transport as model data so the runtime
    # category check agrees with the producer and consumer port contracts;
    # serializer-specific semantic validation remains the consumer's job.
    if (
        set(obj) == {"schema_version", "serializer", "source_contract_digest", "state_content_digest", "state"}
        and isinstance(schema_version, str)
        and schema_version.startswith("spectrasherpa.fitted-")
        and isinstance(obj.get("serializer"), str)
        and isinstance(obj.get("state"), dict)
        and all(
            isinstance(obj.get(field), str)
            and len(obj[field]) == 64
            and all(character in "0123456789abcdef" for character in obj[field])
            for field in ("source_contract_digest", "state_content_digest")
        )
    ):
        return True

    return False


def _category_from_type_ref(type_ref: str) -> str:
    """Derive the visual category from a type_ref URI.

    Resolves through the loaded type registry when available, otherwise
    infers a conservative category from the URI name instead of treating
    everything as a dataset. ``Any`` ports skip validation entirely.
    """
    if "Any" in type_ref:
        return "any"  # Not in type_checks → validation skipped
    try:
        from spectra_sherpa.app.types import type_registry

        td = type_registry.resolve(type_ref)
        return td.category
    except Exception:
        pass

    try:
        type_name = type_ref.split("/types/", 1)[1].split("/", 1)[0]
    except Exception:
        return "any"

    if type_name in {"TargetMatrix", "Categorical"}:
        return "target"
    if type_name in {"Scalar", "Array1D", "Array2D", "ConfusionMatrix"}:
        return "array"
    if type_name in {
        "FittedModel",
        "RegressionModel",
        "ClassificationModel",
        "DecompositionResult",
        "ModelReference",
    } or type_name.endswith("Model"):
        return "model"
    if type_name in {
        "ValidationResult",
        "StatisticsSummary",
        "Visualization",
        "Comparison",
        "WorkflowSnapshot",
    }:
        return "config"
    if (
        "Dataset" in type_name
        or "Spectrum" in type_name
        or type_name in {"ScoreMatrix", "LoadingMatrix", "SpectralImage", "TimeSeries", "Chromatogram", "Voltammogram"}
    ):
        return "dataset"
    return "any"


def _validate_port_type(
    data: Any,
    expected_type: str,
    port_name: str,
    source_node_id: str,
    target_node_id: str,
    strict: bool = False,
) -> None:
    """
    Validate that data matches the expected port type.

    Port types:
    - "dataset": Expects the canonical SherpaDataset
    - "array": Expects list, tuple, or numpy array
    - "model": Expects fitted model object
    - "target": Expects array-like (concentrations, labels)
    - "config": Expects dict

    Args:
        data: The data to validate
        expected_type: The expected port type
        port_name: Name of the port for error messages
        source_node_id: ID of the node providing the data
        target_node_id: ID of the node receiving the data
        strict: If True, raise error on mismatch. If False, warn only.

    Raises:
        TypeError: If strict=True and type doesn't match
    """
    import numpy as np

    type_checks = {
        "dataset": lambda d: _is_dataset(d),
        "array": lambda d: isinstance(d, (list, tuple, np.ndarray)) or _is_dataset(d),
        "model": _is_model_payload,
        "target": lambda d: isinstance(d, (list, tuple, np.ndarray, dict)) or _is_dataset(d),
        "config": lambda d: isinstance(d, dict),
    }

    # Skip validation for unknown types
    if expected_type not in type_checks:
        return

    # Check type
    is_valid = type_checks[expected_type](data)

    if not is_valid:
        actual_type = type(data).__name__
        msg = (
            f"Port type mismatch: '{port_name}' on node '{target_node_id}' "
            f"expects '{expected_type}' but received '{actual_type}' from node '{source_node_id}'. "
        )

        if expected_type == "dataset":
            msg += (
                "Upstream node should return SherpaDataset with coordinates attached, "
                "not raw arrays. This ensures X-axis (wavenumbers) stays coupled with data."
            )

        if strict:
            raise TypeError(msg)
        else:
            warnings.warn(msg, UserWarning, stacklevel=3)

    # Additional coordinate validation for datasets
    # This catches mismatched axes that could cause cryptic errors downstream
    if is_valid and expected_type == "dataset" and _is_dataset(data):
        coord_issues = []

        try:
            # Check X-axis (spectral dimension) exists and matches data shape.
            # Coordinate internals can occasionally be malformed (e.g., coord.data is None),
            # so this validation must never raise and block execution.
            x_coord = data.feature_axis
            data_shape = tuple(data.shape) if hasattr(data, "shape") else ()
            data_spectral_dim = data_shape[-1] if len(data_shape) > 0 else 0

            if x_coord is not None:
                x_len = None
                try:
                    x_data = getattr(x_coord, "values")
                except Exception:
                    x_data = None

                if x_data is not None:
                    try:
                        x_len = len(x_data)
                    except Exception:
                        try:
                            x_arr = np.asarray(x_data)
                            x_len = int(x_arr.shape[0]) if x_arr.ndim > 0 else 1
                        except Exception:
                            x_len = None

                if x_len is None:
                    try:
                        x_len = len(x_coord)
                    except Exception:
                        x_len = None

                if x_len is None:
                    coord_issues.append("X-axis coordinates exist but length could not be determined")
                elif data_spectral_dim > 0 and x_len != data_spectral_dim:
                    coord_issues.append(
                        f"X-axis length ({x_len}) doesn't match spectral dimension ({data_spectral_dim})"
                    )
            elif data_spectral_dim > 1:
                # Missing X-axis on multi-point data is a warning
                coord_issues.append("No X-axis coordinates defined (wavenumbers will be unavailable for display)")

            # Check for NaN in data (best effort; ignore non-numeric payloads)
            try:
                data_values = getattr(data, "data", None)
                if data_values is not None and np.any(np.isnan(np.asarray(data_values, dtype=float))):
                    coord_issues.append("Data contains NaN values")
            except Exception:
                pass
        except Exception as coord_err:
            warnings.warn(
                f"Data integrity validation failed on '{port_name}' from node '{source_node_id}': {coord_err}",
                UserWarning,
                stacklevel=3,
            )

        # Warn about coordinate issues (don't block execution)
        for issue in coord_issues:
            warnings.warn(
                f"Data integrity warning on '{port_name}' from node '{source_node_id}': {issue}",
                UserWarning,
                stacklevel=3,
            )
