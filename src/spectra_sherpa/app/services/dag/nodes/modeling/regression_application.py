"""Portable local regression state; reuse the canonical artifact predictors.

Application data are already at the trainer's input boundary. Preprocessing
history is provenance, not an instruction to preprocess these rows a second time.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

import numpy as np

from spectra_sherpa.app.lib.fitted_state import LinearRegressionExtract, PCRExtract, SVRExtract
from spectra_sherpa.app.services.dag.fitted_input_identity import fitted_input_identity, require_fitted_input_identity
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa
from spectra_sherpa.core.node_identity import node_contract_digest_is_compatible

SCHEMA = "spectrasherpa.local-regression-application/1"
EXTRACTS = {"model.pcr": PCRExtract, "model.svr": SVRExtract, "model.linear_regression": LinearRegressionExtract}


def _json(value):
    return json.dumps(
        value, sort_keys=True, allow_nan=False, separators=(",", ":"), default=lambda v: v.tolist()
    ).encode()


def make_application_state(artifact, dataset, response, *, operation, targets, selected_index=None):
    from spectra_sherpa.app.services.dag.node_base import node_registry

    from .fitted_pls_node import _response_identity

    contract = node_registry.get_metadata(operation).resolved_execution_contract()
    identity = _response_identity(
        dataset if response is None else response, targets=targets, bound_names=[], embedded=response is None
    )
    if selected_index is not None:
        identity = {
            "names": None if identity["names"] is None else [identity["names"][selected_index]],
            "units": [identity["units"][selected_index]],
        }
    # Only the fitted estimator state is applied; never replay preprocessing.
    extract = EXTRACTS[operation].from_artifact(artifact["metadata"], artifact["arrays"])
    metadata, arrays = extract.to_artifact()
    payload = json.loads(
        _json(
            {
                "schema_version": SCHEMA,
                "operation_id": operation,
                "source_contract_digest": contract.digest,
                "input_identity": fitted_input_identity(dataset, features=dataset.shape[1]),
                "response_identity": identity,
                "metadata": metadata,
                "arrays": arrays,
            }
        )
    )
    return {**payload, "state_content_digest": hashlib.sha256(_json(payload)).hexdigest()}


def apply_application_state(input_data, envelope):
    from spectra_sherpa.app.services.dag.node_base import node_registry

    fields = {
        "schema_version",
        "operation_id",
        "source_contract_digest",
        "input_identity",
        "response_identity",
        "metadata",
        "arrays",
        "state_content_digest",
    }
    if not isinstance(envelope, Mapping) or set(envelope) != fields or envelope["schema_version"] != SCHEMA:
        raise ValueError("Regression prediction requires a closed, trainer-owned fitted state")
    operation = envelope["operation_id"]
    if operation not in EXTRACTS:
        raise ValueError("Unsupported regression fitted-state producer")
    payload = {key: value for key, value in envelope.items() if key != "state_content_digest"}
    if hashlib.sha256(_json(payload)).hexdigest() != envelope["state_content_digest"]:
        raise ValueError("Regression fitted-state digest does not match")
    contract = node_registry.get_metadata(operation).resolved_execution_contract()
    if not node_contract_digest_is_compatible(operation, envelope["source_contract_digest"], contract.digest):
        raise ValueError("Regression fitted-state producer contract is incompatible")
    dataset = coerce_to_sherpa(input_data, input_name="Application data")
    matrix = np.asarray(dataset.X, dtype=float)
    if matrix.ndim != 2 or not np.isfinite(matrix).all():
        raise ValueError("Regression application requires finite two-dimensional predictors")
    require_fitted_input_identity(dataset, envelope["input_identity"], features=matrix.shape[1])
    extract = EXTRACTS[operation].from_artifact(
        envelope["metadata"], {name: np.asarray(value) for name, value in envelope["arrays"].items()}
    )
    predicted = np.asarray(extract.predict(matrix), dtype=float).reshape(len(matrix), -1)
    if not np.isfinite(predicted).all():
        raise ValueError("Regression application produced non-finite predictions")
    from .fitted_pls_node import _admit_response_identity

    identity = _admit_response_identity(envelope["response_identity"], targets=predicted.shape[1])
    return predicted, identity
