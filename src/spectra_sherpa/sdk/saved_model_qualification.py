"""Frozen authority for E1655 assessment of one native saved PLS model.

This is deliberately separate from CanonicalApplicationPlan. A Workbench
ModelArtifact cannot acquire canonical full-refit lineage by being saved.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Mapping

import numpy as np
from pydantic import Field, model_validator

from .prediction_uncertainty import ClosedRecord, _digest


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def retain_pls_training_specimens(artifact: dict[str, Any], dataset: Any) -> None:
    """Bind fitted PLS row IDs without changing other model producers."""

    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

    if not isinstance(dataset, SherpaDataset) or dataset.sample_axis is None:
        return
    labels = dataset.sample_axis.labels
    if labels is None:
        return
    ids = list(labels)
    if (
        len(ids) != dataset.n_samples
        or len(ids) > 8192
        or any(not isinstance(value, str) or not value.strip() for value in ids)
        or len(set(ids)) != len(ids)
    ):
        return
    encoded = json.dumps(ids, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > 131072:
        return
    artifact["metadata"]["training_specimen_ids"] = ids
    artifact["arrays"]["native_training_specimen_ids"] = np.frombuffer(encoded, dtype=np.uint8).copy()


class SavedModelApplicationPlan(ClosedRecord):
    """Exact stored bytes and both operations used by native PLS replay."""

    schema_version: Literal["spectrasherpa.saved-model-application-plan/1"]
    artifact_uid: str = Field(min_length=1, max_length=36)
    artifact_digest: str = Field(pattern="^[a-f0-9]{64}$")
    manifest_digest: str = Field(pattern="^[a-f0-9]{64}$")
    training_scientific_digest: str = Field(pattern="^[a-f0-9]{64}$")
    training_specimen_identity_digest: str = Field(pattern="^[a-f0-9]{64}$")
    training_specimen_count: int = Field(ge=2)
    state_content_digest: str = Field(pattern="^[a-f0-9]{64}$")
    producer_contract_digest: str = Field(pattern="^[a-f0-9]{64}$")
    inner_application_contract_digest: str = Field(pattern="^[a-f0-9]{64}$")
    outer_application_contract_digest: str = Field(pattern="^[a-f0-9]{64}$")
    response_identity: dict[str, Any]
    effective_components: int = Field(ge=1)
    application_plan_digest: str = Field(pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def coherent(self):
        if self.application_plan_digest != _digest(self.model_dump(exclude={"application_plan_digest"})):
            raise ValueError("saved-model application plan integrity mismatch")
        return self

    @classmethod
    def from_verified_snapshot(cls, model: Any, manifest: dict[str, Any], arrays: dict[str, np.ndarray]):
        """Admit only a current native PLS artifact; caller verifies storage and owner."""

        from spectra_sherpa.app.services.dag.nodes.modeling.apply_fitted_pls_node import ApplyFittedPLSV2Node
        from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import (
            FittedPLSV2Node,
            make_fitted_pls_state_envelope,
        )
        from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import LoadApplyModelNode
        from spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model import SCHEMA, STATE_ARRAY

        if (
            model.model_type != "pls"
            or manifest.get("model_type") != "pls"
            or manifest.get("native_model_schema") != SCHEMA
            or manifest.get("native_node_type") != "model.fitted_pls"
            or manifest.get("artifact_uid") != model.artifact_uid
            or manifest.get("integrity_hash") != model.integrity_hash
            or manifest.get("training_scientific_digest") != model.training_scientific_digest
            or not isinstance(model.training_scientific_digest, str)
        ):
            raise ValueError("saved PLS model lacks exact native artifact authority")
        encoded = arrays.get(STATE_ARRAY)
        if encoded is None or encoded.dtype != np.uint8 or encoded.ndim != 1:
            raise ValueError("saved PLS fitted state is unavailable")
        payload = json.loads(encoded.tobytes().decode("utf-8"))
        if payload.get("schema_version") != SCHEMA or payload.get("node_type") != "model.fitted_pls":
            raise ValueError("saved PLS state contradicts its manifest")
        producer = FittedPLSV2Node.metadata.resolved_execution_contract()
        inner = ApplyFittedPLSV2Node.metadata.resolved_execution_contract()
        outer = LoadApplyModelNode.metadata.resolved_execution_contract()
        if producer is None or inner is None or outer is None:
            raise ValueError("saved PLS execution contracts are unavailable")
        if payload.get("source_contract_digest") != producer.digest:
            raise ValueError("saved PLS producer contract changed")
        state = FittedPLSV2Node("saved-qualification", {}).validate_fitted_state(payload.get("state"))
        envelope = make_fitted_pls_state_envelope(state)
        if state["response_identity"] != manifest.get("response_identity"):
            raise ValueError("saved PLS response authority changed")
        if state["effective_n_components"] != manifest.get("n_components"):
            raise ValueError("saved PLS fitted rank contradicts its manifest")
        training_ids = manifest.get("training_specimen_ids")
        if (
            not isinstance(training_ids, list)
            or len(training_ids) < 2
            or any(not isinstance(value, str) or not value.strip() for value in training_ids)
            or len(set(training_ids)) != len(training_ids)
            or len(training_ids) != state["reference_samples"]
        ):
            raise ValueError("saved PLS model lacks exact fitted specimen identities")
        bound_ids = arrays.get("native_training_specimen_ids")
        if bound_ids is None or bound_ids.dtype != np.uint8 or bound_ids.ndim != 1:
            raise ValueError("fitted specimen identities are not bound to stored model bytes")
        if bound_ids.tobytes() != json.dumps(training_ids, separators=(",", ":"), ensure_ascii=False).encode("utf-8"):
            raise ValueError("saved PLS fitted specimen identities contradict stored model bytes")
        data = {
            "schema_version": "spectrasherpa.saved-model-application-plan/1",
            "artifact_uid": model.artifact_uid,
            "artifact_digest": model.integrity_hash,
            "manifest_digest": _manifest_digest(manifest),
            "training_scientific_digest": model.training_scientific_digest,
            "training_specimen_identity_digest": _digest(training_ids),
            "training_specimen_count": len(training_ids),
            "state_content_digest": envelope["state_content_digest"],
            "producer_contract_digest": producer.digest,
            "inner_application_contract_digest": inner.digest,
            "outer_application_contract_digest": outer.digest,
            "response_identity": state["response_identity"],
            "effective_components": state["effective_n_components"],
        }
        return cls.model_validate({**data, "application_plan_digest": _digest(data)})

    def assert_snapshot(self, model: Any, manifest: dict[str, Any], arrays: dict[str, np.ndarray]) -> None:
        if self != self.from_verified_snapshot(model, manifest, arrays):
            raise ValueError("saved-model qualification is stale for the current artifact")
