"""ModelStore custody for native fitted states; application stays node-owned.

The JSON payload is retained as a hash-protected uint8 array. No pickle, refit,
coefficient translation, or reconstruction from a mutable workflow is involved.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.fitted_input_identity import fitted_input_identity, require_fitted_input_identity
from spectra_sherpa.core.node_identity import node_contract_digest_is_compatible

STATE_ARRAY = "native_fitted_state"
SCHEMA = "spectrasherpa.saved-native-model/1"
# Closed storage/application dispositions, also checked against the registry by
# the canonical artifact lifecycle suite. Cohort replay is not prediction.
NATIVE_MODEL_TYPES = {
    "model.fitted_pls": "pls",
    "model.fitted_pcr": "pcr",
    "model.fitted_svr": "svr",
    "model.fitted_linear_regression": "linear_regression",
    "model.kmeans": "kmeans",
    "model.parafac": "parafac",
    "model.hca": "hca",
    "model.dbscan": "dbscan",
}
COHORT_ONLY_TYPES = frozenset({"hca", "dbscan"})


def _json_array(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Fitted state contains an unsupported value: {type(value).__name__}")


class SavedNativeModel:
    def __init__(self, node: Any, dataset: SherpaDataset, state: Any) -> None:
        contract = node.metadata.resolved_execution_contract()
        if contract is None or node.metadata.node_type not in NATIVE_MODEL_TYPES:
            raise ValueError("Native fitted model has no declared artifact lifecycle")
        self.payload = {
            "schema_version": SCHEMA,
            "node_type": node.metadata.node_type,
            "serializer": contract.payload["fitted_state_serializer"],
            "source_contract_digest": contract.digest,
            "input_identity": fitted_input_identity(dataset, features=dataset.shape[-1]),
            "parameters": node._resolve_params(),
            "state": state,
        }

    def to_artifact(self) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        payload = self.payload
        state = payload["state"]
        metadata = {
            "model_type": NATIVE_MODEL_TYPES[payload["node_type"]],
            "native_model_schema": SCHEMA,
            "native_node_type": payload["node_type"],
            "n_components": state.get("effective_n_components", payload["parameters"].get("n_components")),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            allow_nan=False,
            default=_json_array,
        ).encode("utf-8")
        return metadata, {STATE_ARRAY: np.frombuffer(encoded, dtype=np.uint8).copy()}


def build_native_model_artifact(
    node: Any, dataset: SherpaDataset, state: Any, *, response_identity: dict[str, object] | None = None
) -> dict[str, Any]:
    from ._artifact_builder import build_model_artifact

    artifact = build_model_artifact(SavedNativeModel(node, dataset, state), dataset, node_id=node.node_id)
    if node.metadata.node_type == "model.fitted_pls":
        response_identity = state["response_identity"]
    if response_identity is not None:
        identity = response_identity
        metadata = artifact["metadata"]
        metadata["response_identity"] = identity
        # Connected response authority supersedes unrelated embedded targets.
        metadata["target_names"] = identity["names"]
        for key in ("selected_target", "target_units", "available_target_names", "target_mode"):
            metadata.pop(key, None)
        units = identity["units"]
        metadata["target_mode"] = "single" if len(units) == 1 else "multi"
        if identity["names"] and len(units) == 1:
            metadata["selected_target"] = identity["names"][0]
        if units and len(set(units)) == 1 and units[0] is not None:
            metadata["target_units"] = units[0]
    return artifact


def has_native_model_state(manifest: dict[str, Any], arrays: dict[str, np.ndarray]) -> bool:
    # Either marker selects strict admission, preventing a damaged payload from
    # falling back to an unrelated legacy coefficient interpretation.
    return STATE_ARRAY in arrays or "native_model_schema" in manifest or "native_node_type" in manifest


def apply_saved_native_model(
    manifest: dict[str, Any], arrays: dict[str, np.ndarray], source: Any, prepared: np.ndarray
) -> dict[str, Any]:
    from spectra_sherpa.app.services.dag.node_base import node_registry

    encoded = arrays.get(STATE_ARRAY)
    if encoded is None or encoded.dtype != np.uint8 or encoded.ndim != 1:
        raise ValueError("Saved native fitted-state payload is unavailable or malformed")
    payload = json.loads(encoded.tobytes().decode("utf-8"))
    node_type = payload.get("node_type")
    if (
        payload.get("schema_version") != SCHEMA
        or manifest.get("native_model_schema") != SCHEMA
        or node_type not in NATIVE_MODEL_TYPES
        or manifest.get("native_node_type") != node_type
        or manifest.get("model_type") != NATIVE_MODEL_TYPES[node_type]
    ):
        raise ValueError("Saved native fitted-state identity is unavailable or unsupported")
    if manifest["model_type"] in COHORT_ONLY_TYPES:
        raise ValueError("This clustering artifact retains its fitted cohort; it does not predict new observations")
    node = node_registry.create_node(node_type, "saved-native-model", payload["parameters"])
    contract = node.metadata.resolved_execution_contract()
    if (
        contract is None
        or payload["serializer"] != contract.payload["fitted_state_serializer"]
        or not node_contract_digest_is_compatible(node_type, payload["source_contract_digest"], contract.digest)
    ):
        raise ValueError("Saved native fitted-state execution contract is incompatible")
    dataset = source if isinstance(source, SherpaDataset) else SherpaDataset(X=np.asarray(source, dtype=float))
    mask = manifest.get("feature_mask")
    if mask is not None and dataset.shape[1] != prepared.shape[1]:
        dataset = dataset[:, np.asarray(mask, dtype=bool)]
    # Keep incoming axis/signal authority; never invent it from the saved state.
    dataset = dataset.with_data(prepared)
    require_fitted_input_identity(dataset, payload["input_identity"], features=prepared.shape[-1])
    if node_type == "model.fitted_pls":
        from .apply_fitted_pls_node import ApplyFittedPLSV2Node
        from .fitted_pls_node import make_fitted_pls_state_envelope

        outputs = (
            ApplyFittedPLSV2Node("saved-pls", {})
            ._execute_sync(dataset, fitted_state=make_fitted_pls_state_envelope(payload["state"]))
            .outputs
        )
    else:
        outputs = {"default": node.apply_fitted_state(dataset, payload["state"])}
    result = np.asarray(outputs["default"])
    clustering = node_type == "model.kmeans"
    transform = node_type == "model.parafac"
    result = result.reshape(len(dataset.X), -1)
    return {
        **outputs,
        "model_id": manifest["artifact_uid"],
        "result": result,
        **(
            {"labels": result[:, 0].tolist()}
            if clustering
            else {"transformed": result} if transform else {"y_pred": result, "predictions": result}
        ),
        "metadata": {
            "type": manifest["model_type"].upper(),
            "output_type": "clustering" if clustering else "decomposition" if transform else "regression",
        },
    }
