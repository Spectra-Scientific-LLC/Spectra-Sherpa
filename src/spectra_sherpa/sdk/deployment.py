"""Canonical data admission and response formatting for deployed DAGs.

The headless API, the live DAG executor, and exported Python call these exact
functions.  Deployment transport is deliberately not a scientific algorithm:
it admits one finite raw matrix or an explicitly modeled finite SherpaDataset
and serializes one result without changing either value or shape.
"""

from __future__ import annotations

# Define transport identities before importing DAG-bound data helpers.  The
# deploy nodes bind these constants while the registry initializes; keeping
# them above that import boundary makes ``import spectra_sherpa.sdk.deployment``
# safe from a clean interpreter as well as through the full SDK facade.
DEPLOYMENT_INPUT_SCHEMA = "spectrasherpa.deploy-input/1"
DEPLOYMENT_RESPONSE_SCHEMA = "spectrasherpa.deploy-response/1"

import csv
import hashlib
import io
import json
from collections.abc import Mapping
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.class_labels import prepare_declared_class_labels
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa
from spectra_sherpa.app.services.dag.transport import reject_spectrochempy_transport, require_raw_matrix_container
from spectra_sherpa.execution_contract_vocabulary import is_portable_identifier

_FORMATS = frozenset({"json", "csv", "plain_text"})
_SEPARATORS = frozenset({"=", ":", "\t"})
_ENDINGS = {"": "", "\\n": "\n", "\\r\\n": "\r\n"}


def validate_deployment_input_set(
    payload: Any,
    *,
    expected_streams: tuple[str, ...],
) -> Mapping[str, Any]:
    """Require exactly the named deployment streams, with no implicit inputs.

    This set-level admission rule is shared by the HTTP boundary and exported
    Python. Individual matrix admission remains the responsibility of
    :func:`admit_deployment_input`.
    """

    if not isinstance(payload, Mapping) or not all(isinstance(key, str) for key in payload):
        raise ValueError("deployment inputs must be a mapping keyed by stream name")
    if not expected_streams:
        raise ValueError("deployment workflow must declare at least one input stream")
    if len(set(expected_streams)) != len(expected_streams):
        raise ValueError("deployment workflow contains duplicate input stream names")
    if not all(is_portable_identifier(stream) for stream in expected_streams):
        raise ValueError("deployment workflow contains a non-portable input stream name")

    missing = sorted(set(expected_streams) - set(payload))
    unexpected = sorted(set(payload) - set(expected_streams))
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        raise ValueError("deployment stream set does not match workflow (" + "; ".join(details) + ")")
    return payload


def admit_deployment_input(
    payload: Any,
    *,
    stream_name: str,
    schema_version: str = DEPLOYMENT_INPUT_SCHEMA,
) -> SherpaDataset:
    """Admit one exact external dataset for a named DAG source.

    Raw containers remain limited to two-dimensional matrices because they do
    not carry dimension semantics.  A native SherpaDataset may be multiway
    only when every dimension has an explicit canonical role; this preserves
    governed image and batch tensors without guessing an unfolding.
    """

    if schema_version != DEPLOYMENT_INPUT_SCHEMA:
        raise ValueError(f"unsupported deployment input schema: {schema_version!r}")
    if not is_portable_identifier(stream_name):
        raise ValueError("deployment stream_name must be a portable identifier")

    reject_spectrochempy_transport(payload, boundary=f"deployment stream {stream_name!r} admission")
    if isinstance(payload, SherpaDataset):
        dataset = payload
    else:
        try:
            require_raw_matrix_container(payload, input_name=f"deployment stream {stream_name!r}")
            array = np.asarray(payload, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"deployment stream {stream_name!r} must contain a numeric matrix") from exc
        if array.ndim != 2:
            raise ValueError(f"deployment stream {stream_name!r} must be a two-dimensional matrix")
        dataset = coerce_to_sherpa(array, input_name=stream_name, allow_array=True)

    matrix = np.asarray(dataset.X, dtype=np.float64)
    if matrix.ndim < 2 or matrix.ndim > 4 or any(dimension < 1 for dimension in matrix.shape):
        raise ValueError(f"deployment stream {stream_name!r} must be a non-empty two- to four-dimensional dataset")
    if matrix.ndim > 2 and len(dataset.layout.mode_roles) != matrix.ndim:
        raise ValueError(
            f"deployment stream {stream_name!r} multiway dataset requires one explicit dimension role per mode"
        )
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"deployment stream {stream_name!r} contains non-finite values")
    return dataset


def deployment_target_output(dataset: SherpaDataset, *, required: bool = True) -> np.ndarray | None:
    """Expose the declared target on a deploy source's typed target port.

    Categorical models emit canonical text labels. Match the split node at this
    explicit graph boundary so a separately admitted held-out target can be
    compared with those predictions without guessing a numeric/text mapping in
    the evaluator. Preserve the admitted dataset and all continuous targets.
    """

    target = dataset.target
    if target is None:
        return None
    if dataset.target_context.target_type == "categorical":
        context = dataset.target_context
        try:
            return prepare_declared_class_labels(
                target,
                dataset.n_samples,
                selected_target=context.selected_target,
                target_names=context.target_names,
            )
        except ValueError:
            if required:
                raise
            return None
    return target


def _json_value(value: Any) -> Any:
    if isinstance(value, SherpaDataset):
        return _json_value(value.X)
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("deployment output mappings must use string keys")
        return {key: _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        raise ValueError("deployment output contains a non-finite value")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"deployment output contains unsupported value {type(value).__name__}")


def _csv_body(value: Any) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    if isinstance(value, list):
        if value and all(isinstance(row, list) for row in value):
            writer.writerows(value)
        else:
            writer.writerow(value)
    elif isinstance(value, dict):
        writer.writerow(["key", "value"])
        for key in sorted(value):
            writer.writerow([key, json.dumps(value[key], sort_keys=True, separators=(",", ":"), allow_nan=False)])
    else:
        writer.writerow([value])
    return output.getvalue()


def format_deployment_output(
    payload: Any,
    *,
    output_format: str,
    key_value_separator: str = "=",
    end_of_message_tag: str = "\\n",
) -> dict[str, Any]:
    """Return the closed response envelope used by every deployment runtime."""

    reject_spectrochempy_transport(payload, boundary="deployment response formatting")
    if output_format not in _FORMATS:
        raise ValueError(f"unsupported deployment output format: {output_format!r}")
    if key_value_separator not in _SEPARATORS:
        raise ValueError("deployment key_value_separator must be one of '=', ':', or '\\t'")
    if end_of_message_tag not in _ENDINGS:
        raise ValueError("deployment end_of_message_tag must be '', '\\n', or '\\r\\n'")

    value = _json_value(payload)
    if output_format == "json":
        body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        content: Any = value
        media_type = "application/json"
    elif output_format == "csv":
        body = _csv_body(value)
        content = body
        media_type = "text/csv"
    else:
        ending = _ENDINGS[end_of_message_tag]
        if isinstance(value, dict):
            body = "; ".join(f"{key}{key_value_separator}{value[key]}" for key in sorted(value)) + ending
        else:
            body = f"Result{key_value_separator}{value}{ending}"
        content = body
        media_type = "text/plain"

    return {
        "schema_version": DEPLOYMENT_RESPONSE_SCHEMA,
        "format": output_format,
        "media_type": media_type,
        "content": content,
        "body": body,
        "content_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


__all__ = [
    "DEPLOYMENT_INPUT_SCHEMA",
    "DEPLOYMENT_RESPONSE_SCHEMA",
    "admit_deployment_input",
    "format_deployment_output",
    "validate_deployment_input_set",
]
