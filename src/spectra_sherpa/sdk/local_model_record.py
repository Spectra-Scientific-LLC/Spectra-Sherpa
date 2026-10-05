"""Portable, self-asserted records for one locally owned model.

The record is deliberately an OSS format rather than a database row or a
managed-registry object.  It travels with an exported model, remains readable
without an account, and contains only identities, metadata, and scalar
evidence--never spectra, targets, predictions, fitted-state bytes, paths, or
credentials.  A future local index may cache records for convenience, but the
record itself is the authority and can always rebuild that index.

Version one has a deliberately small, closed vocabulary.  In particular it
records unknown feature-domain facts as ``null`` rather than guessing from a
model family.  A registry may not infer a positive compatibility claim from an
unknown fact.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability

from .canonical_application import CanonicalApplicationPlan
from .canonical_capsule import CanonicalWorkflowCapsule
from .canonical_fitted_artifact import CanonicalFittedArtifact

LOCAL_MODEL_RECORD_VERSION = "spectra-local-model-record/1"
FEATURE_DOMAIN_SIGNATURE_VERSION = "spectra-feature-domain-signature/1"
MODEL_PERFORMANCE_VERSION = "spectra-model-performance/1"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "model",
        "training_dataset",
        "feature_domain",
        "preprocessing",
        "performance",
        "derivation",
        "provenance",
        "record_digest",
    }
)
_MODEL_FIELDS = frozenset(
    {
        "model_identity",
        "family_id",
        "artifact_digest",
        "application_plan_digest",
        "graph_digest",
        "node_id",
        "operation_id",
        "contract_digest",
        "parameters",
    }
)
_DATASET_FIELDS = frozenset({"content_digest", "reference_digest", "n_samples", "n_features"})
_FEATURE_DOMAIN_FIELDS = frozenset(
    {
        "schema_version",
        "technique",
        "measurement_mode",
        "axis_kind",
        "axis_units",
        "feature_identity_digest",
        "coordinate_start",
        "coordinate_end",
        "n_features",
    }
)
_PREPROCESSING_FIELDS = frozenset({"node_id", "operation_id", "contract_digest", "lifecycle_kind", "parameters"})
_PERFORMANCE_FIELDS = frozenset(
    {
        "schema_version",
        "task_kind",
        "evaluation_kind",
        "metric_registry_version",
        "primary_metric",
        "validation_execution_digest",
        "scalars",
    }
)
_SCALAR_FIELDS = frozenset({"metric_id", "value", "objective", "unit"})
_DERIVATION_FIELDS = frozenset({"schema_version", "links", "campaign", "full_refit_evidence_digest"})
_LINK_FIELDS = frozenset({"relation", "record_digest"})
_CAMPAIGN_FIELDS = frozenset(
    {
        "campaign_id",
        "candidate_id",
        "candidate_ordinal",
        "candidate_count",
        "candidate_ids",
        "baseline_candidate_id",
        "search_space_digest",
        "selection_status",
        "decision_digest",
    }
)
_PROVENANCE_FIELDS = frozenset({"recorded_at", "actor"})
_ACTOR_FIELDS = frozenset({"kind", "ref"})
_RELATIONS = frozenset({"refit_from", "imported_from", "supersedes"})
_SELECTION_STATUSES = frozenset({"not_recorded", "selected", "not_selected", "no_defensible_improvement"})
_SCALAR_CONTRACTS = {
    "regression": {
        "rmse": "minimize",
        "mae": "minimize",
        "bias": "target_zero",
        "r2": "maximize",
        "sep": "minimize",
        "slope": "target_one",
        "intercept": "target_zero",
        "rer": "maximize",
    },
    "classification": {
        "accuracy": "maximize",
        "balanced_accuracy": "maximize",
        "macro_f1": "maximize",
        "mcc": "maximize",
    },
}


class LocalModelRecordError(ValueError):
    """A portable local-model record is malformed or unbound."""


@dataclass(frozen=True)
class LocalRecordActor:
    """Self-asserted local actor identity; this is not managed attestation."""

    kind: str
    ref: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "ref": self.ref}


@dataclass(frozen=True)
class LocalModelRecord:
    """One immutable, portable local model record.

    ``record_digest`` identifies this complete self-asserted record.  It is
    intentionally distinct from ``model_identity``: importing the same record
    onto another machine preserves both values, while a later refit can create
    a new record that explicitly links to this one.
    """

    payload: dict[str, Any]
    record_digest: str

    @classmethod
    def from_canonical(
        cls,
        *,
        capsule: CanonicalWorkflowCapsule,
        artifact: CanonicalFittedArtifact,
        application_plan: CanonicalApplicationPlan,
        capability: SpectralDatasetCapability,
        actor: LocalRecordActor,
        recorded_at: str,
        campaign_provenance: Mapping[str, Any],
        derivation_links: Sequence[Mapping[str, str]] = (),
    ) -> "LocalModelRecord":
        """Create a record from real admitted canonical values.

        ``capability`` is read only for its non-disclosing digest, dimensions,
        and domain/feature-axis signature.  Its arrays never enter the record.
        The caller supplies the local actor and timestamp because OSS has no
        server-side identity authority and must not pretend otherwise.
        """

        if not isinstance(capsule, CanonicalWorkflowCapsule):
            raise LocalModelRecordError("local model record requires a verified canonical capsule")
        if not isinstance(artifact, CanonicalFittedArtifact):
            raise LocalModelRecordError("local model record requires a verified fitted artifact")
        if not isinstance(application_plan, CanonicalApplicationPlan):
            raise LocalModelRecordError("local model record requires a verified application plan")
        if not isinstance(capability, SpectralDatasetCapability):
            raise LocalModelRecordError("local model record requires a local spectral capability")
        if not isinstance(actor, LocalRecordActor):
            raise LocalModelRecordError("local model record actor is invalid")
        try:
            application_plan.require_matches(capsule, artifact)
        except Exception as exc:  # The three canonical classes own their detailed diagnostic.
            raise LocalModelRecordError("local model record canonical identities do not agree") from exc

        request = capsule.payload["admitted_request"]
        if (
            capability.content_digest != request["dataset_content_digest"]
            or capability.envelope_digest != request["capability_digest"]
        ):
            raise LocalModelRecordError("local model record capability does not match the canonical execution")
        if capability.metadata["dataset_ref_digest"] != request["dataset_ref_digest"]:
            raise LocalModelRecordError("local model record dataset reference does not match the canonical execution")

        model_node = _model_node(application_plan)
        model = {
            "model_identity": _digest(
                {
                    "schema_version": "spectra-model-identity/1",
                    "family_id": model_node["source_operation_id"],
                    "artifact_digest": artifact.artifact_digest,
                }
            ),
            "family_id": model_node["source_operation_id"],
            "artifact_digest": artifact.artifact_digest,
            "application_plan_digest": application_plan.application_plan_digest,
            "graph_digest": application_plan.payload["graph_digest"],
            "node_id": model_node["node_id"],
            "operation_id": model_node["source_operation_id"],
            "contract_digest": model_node["source_contract_digest"],
            "parameters": deepcopy(dict(model_node["parameters"])),
        }
        data = _dataset_identity(request)
        feature_domain = _feature_domain(capability, expected_features=data["n_features"])
        preprocessing = _preprocessing(application_plan, model_node_id=model["node_id"])
        performance = _performance(capsule, capability)
        derivation = _derivation(
            capsule,
            artifact,
            derivation_links=derivation_links,
            campaign_provenance=campaign_provenance,
        )
        unsigned = {
            "schema_version": LOCAL_MODEL_RECORD_VERSION,
            "model": model,
            "training_dataset": data,
            "feature_domain": feature_domain,
            "preprocessing": preprocessing,
            "performance": performance,
            "derivation": derivation,
            "provenance": {"recorded_at": _canonical_timestamp(recorded_at), "actor": actor.as_dict()},
        }
        record = cls._validated({**unsigned, "record_digest": _digest(unsigned)})
        record.require_matches(capsule=capsule, artifact=artifact, application_plan=application_plan)
        return record

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LocalModelRecord":
        """Re-admit one detached record without requiring a local server."""

        return cls._validated(value)

    def as_dict(self) -> dict[str, Any]:
        """Return a detached JSON-safe record."""

        return deepcopy(self.payload)

    def canonical_bytes(self) -> bytes:
        """Return stable bytes suitable for package members and signatures."""

        return _canonical_json(self.payload)

    def require_matches(
        self,
        *,
        capsule: CanonicalWorkflowCapsule,
        artifact: CanonicalFittedArtifact,
        application_plan: CanonicalApplicationPlan,
    ) -> None:
        """Reject a record substituted across canonical package identities."""

        request = capsule.payload["admitted_request"]
        model = self.payload["model"]
        if (
            model["artifact_digest"] != artifact.artifact_digest
            or model["application_plan_digest"] != application_plan.application_plan_digest
            or model["graph_digest"] != application_plan.payload["graph_digest"]
            or self.payload["training_dataset"]["content_digest"]
            != capsule.payload["admitted_request"]["dataset_content_digest"]
            or self.payload["training_dataset"]["reference_digest"]
            != capsule.payload["admitted_request"]["dataset_ref_digest"]
            or self.payload["performance"]["validation_execution_digest"]
            != capsule.execution_evidence.validation_execution_digest
            or self.payload["derivation"]["full_refit_evidence_digest"]
            != application_plan.payload["full_refit_evidence_digest"]
        ):
            raise LocalModelRecordError("local model record differs from canonical package identities")
        _require_campaign_matches_request(self.payload["derivation"]["campaign"], request)

    def require_matches_campaign_evidence(self, campaign_evidence: Any) -> None:
        """Bind the portable derivation to the complete selected-campaign ledger."""

        evidence = getattr(campaign_evidence, "payload", None)
        if not isinstance(evidence, Mapping):
            raise LocalModelRecordError("local model record cannot bind campaign evidence")
        evidence_campaign = evidence.get("campaign")
        candidates = evidence.get("candidates")
        decision = evidence.get("decision")
        if (
            not isinstance(evidence_campaign, Mapping)
            or not isinstance(candidates, list)
            or not candidates
            or not isinstance(decision, Mapping)
        ):
            raise LocalModelRecordError("local model record cannot bind campaign evidence")
        winner_id = decision.get("winner_candidate_id")
        winner = next(
            (
                candidate
                for candidate in candidates
                if isinstance(candidate, Mapping) and candidate.get("candidate_id") == winner_id
            ),
            None,
        )
        if winner is None or not all(isinstance(candidate, Mapping) for candidate in candidates):
            raise LocalModelRecordError("local model record cannot bind campaign evidence")
        expected = {
            "campaign_id": evidence_campaign.get("campaign_id"),
            "candidate_id": winner_id,
            "candidate_ordinal": (
                winner.get("declared_ordinal")
                if decision.get("schema_version") == "spectra-scientist-reviewed-selection/1"
                else winner.get("ordinal")
            ),
            "candidate_count": len(candidates),
            "candidate_ids": [candidate.get("candidate_id") for candidate in candidates],
            "baseline_candidate_id": candidates[0].get("candidate_id"),
            "search_space_digest": evidence_campaign.get("search_space_digest"),
            "selection_status": "selected",
            # Structural refits retain the immutable development settlement;
            # the separate reviewed decision additionally binds the promotion.
            "decision_digest": (
                decision.get("settlement_digest")
                if decision.get("schema_version") == "spectra-scientist-reviewed-selection/1"
                else evidence_campaign.get("decision_digest")
            ),
        }
        if self.payload["derivation"]["campaign"] != expected:
            raise LocalModelRecordError("local model record differs from canonical campaign evidence")

    @classmethod
    def _validated(cls, value: Mapping[str, Any]) -> "LocalModelRecord":
        if not isinstance(value, Mapping) or set(value) != _RECORD_FIELDS:
            raise LocalModelRecordError("local model record fields are closed")
        if value["schema_version"] != LOCAL_MODEL_RECORD_VERSION:
            raise LocalModelRecordError("local model record schema is unsupported")
        model = _validate_model(value["model"])
        training_dataset = _validate_dataset(value["training_dataset"])
        feature_domain = _validate_feature_domain(
            value["feature_domain"], expected_features=training_dataset["n_features"]
        )
        preprocessing = _validate_preprocessing(value["preprocessing"], model_node_id=model["node_id"])
        performance = _validate_performance(value["performance"])
        derivation = _validate_derivation(value["derivation"])
        provenance = _validate_provenance(value["provenance"])
        unsigned = {
            "schema_version": LOCAL_MODEL_RECORD_VERSION,
            "model": model,
            "training_dataset": training_dataset,
            "feature_domain": feature_domain,
            "preprocessing": preprocessing,
            "performance": performance,
            "derivation": derivation,
            "provenance": provenance,
        }
        record_digest = _require_digest(value["record_digest"], "record_digest")
        if record_digest != _digest(unsigned):
            raise LocalModelRecordError("local model record content digest mismatch")
        return cls(payload={**unsigned, "record_digest": record_digest}, record_digest=record_digest)


def _model_node(application_plan: CanonicalApplicationPlan) -> Mapping[str, Any]:
    node_id = application_plan.payload["model_node_id"]
    nodes = [node for node in application_plan.payload["nodes"] if node["node_id"] == node_id]
    if len(nodes) != 1:
        raise LocalModelRecordError("canonical application plan has no unique model node")
    return nodes[0]


def _dataset_identity(request: Mapping[str, Any]) -> dict[str, Any]:
    shape = request["dataset_shape"]
    return {
        "content_digest": request["dataset_content_digest"],
        "reference_digest": request["dataset_ref_digest"],
        "n_samples": shape["n_samples"],
        "n_features": shape["n_features"],
    }


def _feature_domain(capability: SpectralDatasetCapability, *, expected_features: int) -> dict[str, Any]:
    metadata = capability.metadata
    axes = metadata["axes"]
    feature = axes.get("feature") if isinstance(axes, Mapping) else None
    values = capability.arrays.get("axis.feature.values")
    coordinate_start: float | None = None
    coordinate_end: float | None = None
    if values is not None:
        if len(values) != expected_features:
            raise LocalModelRecordError("feature-axis values do not match canonical feature count")
        coordinate_start, coordinate_end = float(values[0]), float(values[-1])
    domain = metadata["domain"]
    return {
        "schema_version": FEATURE_DOMAIN_SIGNATURE_VERSION,
        "technique": domain.get("technique"),
        "measurement_mode": domain.get("measurement_mode"),
        "axis_kind": feature.get("axis_type") if isinstance(feature, Mapping) else None,
        "axis_units": feature.get("units") if isinstance(feature, Mapping) else None,
        "feature_identity_digest": capability.evidence_summary()["feature_identity_digest"],
        "coordinate_start": coordinate_start,
        "coordinate_end": coordinate_end,
        "n_features": expected_features,
    }


def _preprocessing(application_plan: CanonicalApplicationPlan, *, model_node_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for node in application_plan.payload["nodes"]:
        if node["node_id"] == model_node_id:
            continue
        operation = node["source_operation_id"]
        if not operation.startswith(("preprocess.", "baseline.", "select.", "selection.")):
            raise LocalModelRecordError(
                f"canonical application plan has an unclassified preprocessing operation: {operation}"
            )
        records.append(
            {
                "node_id": node["node_id"],
                "operation_id": operation,
                "contract_digest": node["source_contract_digest"],
                "lifecycle_kind": "fitted" if "artifact_binding" in node else "stateless",
                "parameters": deepcopy(dict(node["parameters"])),
            }
        )
    return records


def _performance(capsule: CanonicalWorkflowCapsule, capability: SpectralDatasetCapability) -> dict[str, Any]:
    metrics = capsule.execution_evidence.payload["validation_execution"]["metrics"]
    task_kind = metrics.get("task_type", "regression")
    if task_kind == "regression":
        unit = capability.metadata["target_context"].get("target_units")
        scalar_units = {
            "rmse": unit,
            "mae": unit,
            "bias": unit,
            "r2": None,
            "sep": unit,
            "slope": None,
            "intercept": unit,
            "rer": None,
        }
        primary_metric = "rmse"
    elif task_kind == "classification":
        scalar_units = {metric_id: None for metric_id in _SCALAR_CONTRACTS[task_kind]}
        primary_metric = "balanced_accuracy"
    else:
        raise LocalModelRecordError("canonical execution has an unsupported supervised task")
    scalars = [
        {
            "metric_id": metric_id,
            "value": metrics[metric_id],
            "objective": objective,
            "unit": scalar_units[metric_id],
        }
        for metric_id, objective in _SCALAR_CONTRACTS[task_kind].items()
    ]
    return {
        "schema_version": MODEL_PERFORMANCE_VERSION,
        "task_kind": task_kind,
        "evaluation_kind": capsule.payload["admitted_request"]["evaluation_kind"],
        "metric_registry_version": metrics["registry_version"],
        "primary_metric": primary_metric,
        "validation_execution_digest": capsule.execution_evidence.validation_execution_digest,
        "scalars": scalars,
    }


def _derivation(
    capsule: CanonicalWorkflowCapsule,
    artifact: CanonicalFittedArtifact,
    *,
    derivation_links: Sequence[Mapping[str, str]],
    campaign_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    campaign = deepcopy(dict(campaign_provenance))
    return {
        "schema_version": "spectra-model-derivation/1",
        "links": [deepcopy(dict(link)) for link in derivation_links],
        "campaign": campaign,
        "full_refit_evidence_digest": artifact.payload["full_refit_evidence"]["content_digest"],
    }


def _validate_model(value: Any) -> dict[str, Any]:
    model = _closed(value, _MODEL_FIELDS, "local model")
    for field in ("model_identity", "artifact_digest", "application_plan_digest", "graph_digest", "contract_digest"):
        model[field] = _require_digest(model[field], f"model.{field}")
    for field in ("family_id", "node_id", "operation_id"):
        model[field] = _identifier(model[field], f"model.{field}")
    if (
        not model["operation_id"].startswith(("model.", "classification."))
        or model["family_id"] != model["operation_id"]
    ):
        raise LocalModelRecordError("local model family must be its supervised model operation")
    if not isinstance(model["parameters"], Mapping):
        raise LocalModelRecordError("local model parameters are invalid")
    expected_identity = _digest(
        {
            "schema_version": "spectra-model-identity/1",
            "family_id": model["family_id"],
            "artifact_digest": model["artifact_digest"],
        }
    )
    if model["model_identity"] != expected_identity:
        raise LocalModelRecordError("local model identity is not bound to its fitted artifact")
    model["parameters"] = deepcopy(dict(model["parameters"]))
    return model


def _validate_dataset(value: Any) -> dict[str, Any]:
    dataset = _closed(value, _DATASET_FIELDS, "local training dataset")
    for field in ("content_digest", "reference_digest"):
        dataset[field] = _require_digest(dataset[field], f"training_dataset.{field}")
    for field in ("n_samples", "n_features"):
        if isinstance(dataset[field], bool) or not isinstance(dataset[field], int) or dataset[field] < 1:
            raise LocalModelRecordError(f"training_dataset.{field} is invalid")
    return dataset


def _validate_feature_domain(value: Any, *, expected_features: int) -> dict[str, Any]:
    domain = _closed(value, _FEATURE_DOMAIN_FIELDS, "feature-domain signature")
    if domain["schema_version"] != FEATURE_DOMAIN_SIGNATURE_VERSION:
        raise LocalModelRecordError("feature-domain signature schema is unsupported")
    for field in ("technique", "measurement_mode", "axis_kind", "axis_units"):
        if domain[field] is not None and (not isinstance(domain[field], str) or not domain[field].strip()):
            raise LocalModelRecordError(f"feature_domain.{field} is invalid")
    if domain["feature_identity_digest"] is not None:
        domain["feature_identity_digest"] = _require_digest(
            domain["feature_identity_digest"], "feature_domain.feature_identity_digest"
        )
    for field in ("coordinate_start", "coordinate_end"):
        if domain[field] is not None and (
            isinstance(domain[field], bool)
            or not isinstance(domain[field], (int, float))
            or not math.isfinite(domain[field])
        ):
            raise LocalModelRecordError(f"feature_domain.{field} is invalid")
    if domain["n_features"] != expected_features:
        raise LocalModelRecordError("feature-domain feature count differs from training dataset")
    if (domain["coordinate_start"] is None) != (domain["coordinate_end"] is None):
        raise LocalModelRecordError("feature-domain coordinate bounds must be both known or both unknown")
    return dict(domain)


def _validate_preprocessing(value: Any, *, model_node_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise LocalModelRecordError("preprocessing lineage must be a list")
    result: list[dict[str, Any]] = []
    seen: set[str] = {model_node_id}
    for item in value:
        record = _closed(item, _PREPROCESSING_FIELDS, "preprocessing lineage entry")
        for field in ("node_id", "operation_id", "lifecycle_kind"):
            record[field] = _identifier(record[field], f"preprocessing.{field}")
        record["contract_digest"] = _require_digest(record["contract_digest"], "preprocessing.contract_digest")
        if record["node_id"] in seen:
            raise LocalModelRecordError("preprocessing lineage repeats a node")
        if not record["operation_id"].startswith(("preprocess.", "baseline.", "select.", "selection.")):
            raise LocalModelRecordError("preprocessing lineage operation is not admitted")
        if record["lifecycle_kind"] not in {"fitted", "stateless"} or not isinstance(record["parameters"], Mapping):
            raise LocalModelRecordError("preprocessing lineage entry is invalid")
        seen.add(record["node_id"])
        record["parameters"] = deepcopy(dict(record["parameters"]))
        result.append(record)
    return result


def _validate_performance(value: Any) -> dict[str, Any]:
    performance = _closed(value, _PERFORMANCE_FIELDS, "model performance")
    if performance["schema_version"] != MODEL_PERFORMANCE_VERSION:
        raise LocalModelRecordError("model performance schema is unsupported")
    task_kind = performance["task_kind"]
    if task_kind not in _SCALAR_CONTRACTS:
        raise LocalModelRecordError("model performance task kind is unsupported")
    performance["evaluation_kind"] = _identifier(performance["evaluation_kind"], "performance.evaluation_kind")
    if not isinstance(performance["metric_registry_version"], str) or not performance["metric_registry_version"]:
        raise LocalModelRecordError("model performance metric registry is invalid")
    performance["primary_metric"] = _identifier(performance["primary_metric"], "performance.primary_metric")
    performance["validation_execution_digest"] = _require_digest(
        performance["validation_execution_digest"], "performance.validation_execution_digest"
    )
    scalar_contracts = _SCALAR_CONTRACTS[task_kind]
    if performance["primary_metric"] not in scalar_contracts:
        raise LocalModelRecordError("model performance primary metric is not admitted for its task")
    if not isinstance(performance["scalars"], list) or not performance["scalars"]:
        raise LocalModelRecordError("model performance scalars are invalid")
    scalars: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in performance["scalars"]:
        scalar = _closed(item, _SCALAR_FIELDS, "model performance scalar")
        scalar["metric_id"] = _identifier(scalar["metric_id"], "performance.scalar.metric_id")
        if scalar["metric_id"] not in scalar_contracts or scalar["metric_id"] in seen:
            raise LocalModelRecordError("model performance scalar is unsupported or repeated")
        if scalar["objective"] != scalar_contracts[scalar["metric_id"]]:
            raise LocalModelRecordError("model performance scalar objective is invalid")
        if scalar["value"] is not None and (
            isinstance(scalar["value"], bool)
            or not isinstance(scalar["value"], (int, float))
            or not math.isfinite(scalar["value"])
        ):
            raise LocalModelRecordError("model performance scalar value is invalid")
        if scalar["unit"] is not None and (not isinstance(scalar["unit"], str) or not scalar["unit"].strip()):
            raise LocalModelRecordError("model performance scalar unit is invalid")
        seen.add(scalar["metric_id"])
        scalars.append(dict(scalar))
    if performance["primary_metric"] not in seen:
        raise LocalModelRecordError("model performance does not include its primary metric")
    if seen != set(scalar_contracts):
        raise LocalModelRecordError("model performance does not include the complete task metric vector")
    performance["scalars"] = scalars
    return performance


def _validate_derivation(value: Any) -> dict[str, Any]:
    derivation = _closed(value, _DERIVATION_FIELDS, "model derivation")
    if derivation["schema_version"] != "spectra-model-derivation/1":
        raise LocalModelRecordError("model derivation schema is unsupported")
    if not isinstance(derivation["links"], list):
        raise LocalModelRecordError("model derivation links are invalid")
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in derivation["links"]:
        link = _closed(item, _LINK_FIELDS, "model derivation link")
        if link["relation"] not in _RELATIONS:
            raise LocalModelRecordError("model derivation relation is unsupported")
        link["record_digest"] = _require_digest(link["record_digest"], "derivation.record_digest")
        identity = (link["relation"], link["record_digest"])
        if identity in seen:
            raise LocalModelRecordError("model derivation link is repeated")
        seen.add(identity)
        links.append(link)
    campaign = _closed(derivation["campaign"], _CAMPAIGN_FIELDS, "model campaign provenance")
    for field in ("campaign_id", "candidate_id", "baseline_candidate_id"):
        campaign[field] = _identifier(campaign[field], f"derivation.campaign.{field}")
    for field in ("candidate_ordinal", "candidate_count"):
        if isinstance(campaign[field], bool) or not isinstance(campaign[field], int) or campaign[field] < 1:
            raise LocalModelRecordError(f"derivation.campaign.{field} is invalid")
    if not isinstance(campaign["candidate_ids"], list) or not campaign["candidate_ids"]:
        raise LocalModelRecordError("model campaign candidate identities are invalid")
    campaign["candidate_ids"] = [
        _identifier(item, "derivation.campaign.candidate_id") for item in campaign["candidate_ids"]
    ]
    if campaign["candidate_ids"] != list(dict.fromkeys(campaign["candidate_ids"])):
        raise LocalModelRecordError("model campaign candidate identities repeat")
    if (
        campaign["candidate_count"] != len(campaign["candidate_ids"])
        or not 1 <= campaign["candidate_ordinal"] <= campaign["candidate_count"]
        or campaign["candidate_id"] != campaign["candidate_ids"][campaign["candidate_ordinal"] - 1]
        or campaign["baseline_candidate_id"] not in campaign["candidate_ids"]
    ):
        raise LocalModelRecordError("model campaign provenance is internally inconsistent")
    if campaign["search_space_digest"] is not None:
        campaign["search_space_digest"] = _require_digest(
            campaign["search_space_digest"], "derivation.campaign.search_space_digest"
        )
    if campaign["selection_status"] not in _SELECTION_STATUSES:
        raise LocalModelRecordError("model campaign selection status is unsupported")
    if campaign["decision_digest"] is not None:
        campaign["decision_digest"] = _require_digest(
            campaign["decision_digest"], "derivation.campaign.decision_digest"
        )
    if campaign["selection_status"] == "not_recorded":
        if campaign["decision_digest"] is not None:
            raise LocalModelRecordError("unrecorded campaign selection cannot have a decision digest")
    elif campaign["decision_digest"] is None:
        raise LocalModelRecordError("recorded campaign selection requires a decision digest")
    derivation["links"] = links
    derivation["campaign"] = campaign
    derivation["full_refit_evidence_digest"] = _require_digest(
        derivation["full_refit_evidence_digest"], "derivation.full_refit_evidence_digest"
    )
    return derivation


def _require_campaign_matches_request(campaign: Mapping[str, Any], request: Mapping[str, Any]) -> None:
    search = request.get("search")
    if not isinstance(search, Mapping) or search.get("schema_version") != "spectra-canonical-search-execution/2":
        raise LocalModelRecordError("local model record requires the current canonical search authority")
    expected = {
        "campaign_id": request.get("campaign_id"),
        "candidate_id": request.get("candidate_id"),
        "candidate_ordinal": search.get("candidate_ordinal"),
        "candidate_count": search.get("candidate_count"),
        "search_space_digest": search.get("search_space_digest"),
        "selection_status": "selected",
    }
    actual = {field: campaign.get(field) for field in expected}
    if actual != expected:
        raise LocalModelRecordError("local model record campaign differs from canonical execution")


def _validate_provenance(value: Any) -> dict[str, Any]:
    provenance = _closed(value, _PROVENANCE_FIELDS, "local record provenance")
    recorded_at = provenance["recorded_at"]
    if not isinstance(recorded_at, str):
        raise LocalModelRecordError("local record timestamp is invalid")
    provenance["recorded_at"] = _canonical_timestamp(recorded_at)
    actor = _closed(provenance["actor"], _ACTOR_FIELDS, "local record actor")
    actor["kind"] = _identifier(actor["kind"], "provenance.actor.kind")
    actor["ref"] = _identifier(actor["ref"], "provenance.actor.ref")
    provenance["actor"] = actor
    return provenance


def _canonical_timestamp(value: str) -> str:
    """Normalize a timezone-aware self-asserted timestamp before it is hashed."""

    if not isinstance(value, str):
        raise LocalModelRecordError("local record timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LocalModelRecordError("local record timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise LocalModelRecordError("local record timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _closed(value: Any, fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise LocalModelRecordError(f"{label} fields are closed")
    return dict(value)


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise LocalModelRecordError(f"{label} is invalid")
    return value


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise LocalModelRecordError(f"{label} is invalid")
    return value


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


__all__ = [
    "FEATURE_DOMAIN_SIGNATURE_VERSION",
    "LOCAL_MODEL_RECORD_VERSION",
    "MODEL_PERFORMANCE_VERSION",
    "LocalModelRecord",
    "LocalModelRecordError",
    "LocalRecordActor",
]
