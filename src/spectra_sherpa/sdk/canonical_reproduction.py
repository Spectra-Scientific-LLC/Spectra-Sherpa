"""Independent, OSS-only reproduction of a canonical project package.

Canonical package admission proves that the package bytes and the declared
evidence are internally consistent.  It does *not* prove that the reported
validation numbers were obtained by running the named scientific graph.  This
module deliberately supplies that next, separate proof rung:

* it re-admits a supplied local fixture against the capsule's exact dataset
  and split identities;
* it executes the admitted typed DAG fold by fold and compares fresh scalar
  metrics with the recorded evidence; and
* it applies the imported fitted artifact both through the visible,
  contract-bound application DAG and through the source fitted-state ABI, then
  compares the two local prediction vectors.

The returned report contains no spectra, targets, fitted-state bytes, or
prediction values.  It is useful when an optional publisher attestation is
missing or invalid: integrity, publisher authentication, validation
reproduction, and application reproduction remain four distinct results.
Nothing in this module imports :mod:`spectrasherpa_server`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.canonical_artifact_store import init_canonical_artifact_store
from spectra_sherpa.app.services.dag.fold_graph_executor import execute_candidate_validation
from spectra_sherpa.app.services.dag.node_base import NodeResult, node_registry
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.canonical_artifact import ReadOnlyCanonicalArtifactReader
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind

from .canonical_application_execution import execute_canonical_application
from .canonical_project import CanonicalProjectPackage, CanonicalProjectPackageError
from .canonical_publisher_attestation import (
    CanonicalPublisherAttestationError,
    CanonicalPublisherTrustAnchors,
    LocalCanonicalPublisherTrustStore,
    SignedCanonicalProjectAttestation,
)
from .validate import (
    METRIC_PARITY_ABSOLUTE_TOLERANCE,
    METRIC_PARITY_RELATIVE_TOLERANCE,
    SplitPlan,
    supervised_metric_task,
    validate_supervised_metric_record,
)

CANONICAL_REPRODUCTION_REPORT_VERSION = "spectra-canonical-reproduction-report/1"
_DIGEST_LENGTH = 64
_STATUS = frozenset({"passed", "failed", "not_provided", "not_run"})
logger = logging.getLogger(__name__)
_OUTCOME_FIELDS = frozenset({"status", "reason"})
_FIXTURE_FIELDS = frozenset(
    {
        "content_digest",
        "envelope_digest",
        "dataset_ref_digest",
        "split_plan_digest",
        "sample_identity_digest",
        "feature_identity_digest",
        "target_identity_digest",
        "group_identity_digest",
    }
)
_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "package_sha256",
        "capsule_digest",
        "artifact_digest",
        "application_plan_digest",
        "fixture_identity",
        "integrity_verified",
        "publisher_authenticated",
        "validation_reproduced",
        "application_reproduced",
    }
)


class CanonicalReproductionError(ValueError):
    """The local package, fixture, or reproduction projection is invalid."""


@dataclass(frozen=True)
class CanonicalReproductionReport:
    """A closed, data-free report of independent canonical reproduction."""

    payload: dict[str, Any]
    report_digest: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalReproductionReport":
        if not isinstance(value, Mapping):
            raise CanonicalReproductionError("canonical reproduction report must be an object")
        expected = value.get("report_digest")
        _require_digest(expected, "report_digest")
        payload = {key: deepcopy(item) for key, item in value.items() if key != "report_digest"}
        report = cls._validated(payload)
        if report.report_digest != expected:
            raise CanonicalReproductionError("canonical reproduction report content digest mismatch")
        return report

    @classmethod
    def _validated(cls, value: Mapping[str, Any]) -> "CanonicalReproductionReport":
        if set(value) != _REPORT_FIELDS:
            raise CanonicalReproductionError("canonical reproduction report fields are closed")
        if value["schema_version"] != CANONICAL_REPRODUCTION_REPORT_VERSION:
            raise CanonicalReproductionError("canonical reproduction report schema is unsupported")
        for field in ("package_sha256", "capsule_digest", "artifact_digest", "application_plan_digest"):
            _require_digest(value[field], field)
        _validate_fixture_identity(value["fixture_identity"])
        _validate_outcome(value["integrity_verified"], "integrity_verified", allowed={"passed"})
        _validate_outcome(value["publisher_authenticated"], "publisher_authenticated", allowed=_STATUS)
        _validate_validation_outcome(value["validation_reproduced"])
        _validate_application_outcome(value["application_reproduced"])
        payload = deepcopy(dict(value))
        return cls(payload=payload, report_digest=_digest(payload))

    def as_dict(self) -> dict[str, Any]:
        """Return the canonical, data-free report named by ``report_digest``."""

        return {**deepcopy(self.payload), "report_digest": self.report_digest}

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.as_dict())


def reproduce_canonical_project(
    package: CanonicalProjectPackage | bytes,
    *,
    fixture: SpectralDatasetCapability,
    split_plan: SplitPlan,
    publisher_attestation: Mapping[str, Any] | None = None,
    publisher_trust_anchors: Mapping[str, Any] | None = None,
) -> CanonicalReproductionReport:
    """Compute independent OSS validation and application reproduction.

    ``fixture`` is supplied by the local analyst.  It is never resolved from a
    package path or a managed service. It must be the exact fixture named by
    the capsule and is used for both the fold-by-fold validation and the
    application comparison. A later user-facing application workflow may bind
    its own data source; this scientific verifier intentionally keeps one
    exact public fixture so every comparison is independently attributable.

    A malformed package cannot yield a report because its identity is not
    trustworthy.  A valid package paired with an unavailable/incorrect local
    fixture *does* yield a signed-content report with ``not_run`` science
    outcomes, preserving the distinction between byte integrity and science.
    """

    _ensure_oss_execution_runtime()
    loaded = _load_package(package)
    if not isinstance(fixture, SpectralDatasetCapability):
        raise CanonicalReproductionError("canonical reproduction requires a local spectral capability fixture")
    if not isinstance(split_plan, SplitPlan):
        raise CanonicalReproductionError("canonical reproduction requires an admitted split plan")
    fixture_identity = _fixture_identity(fixture)
    publisher = _publisher_outcome(loaded, publisher_attestation, publisher_trust_anchors)
    identity_failure = _fixture_identity_failure(loaded, fixture, split_plan)
    if identity_failure is not None:
        validation = _science_not_run(identity_failure)
        application = _science_not_run(identity_failure)
    else:
        validation = _validation_outcome(loaded, fixture, split_plan)
        application = _application_outcome(loaded, fixture)

    return CanonicalReproductionReport._validated(
        {
            "schema_version": CANONICAL_REPRODUCTION_REPORT_VERSION,
            "package_sha256": loaded.archive_sha256,
            "capsule_digest": loaded.capsule.capsule_digest,
            "artifact_digest": loaded.artifact.artifact_digest,
            "application_plan_digest": loaded.application_plan.application_plan_digest,
            "fixture_identity": fixture_identity,
            "integrity_verified": {"status": "passed", "reason": None},
            "publisher_authenticated": publisher,
            "validation_reproduced": validation,
            "application_reproduced": application,
        }
    )


def _ensure_oss_execution_runtime() -> None:
    """Register the certified first-party profile without a server bootstrap.

    The verifier is deliberately usable from the free SDK in a fresh Python
    process. Importing the OSS node modules is the explicit registration
    boundary; importing a web application or managed server would make local
    verification depend on the paid deployment.
    """

    # Imports are deliberately local so offline package inspection remains
    # lightweight until the caller explicitly asks to execute science.
    import spectra_sherpa.app.services.dag.nodes.classification  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.classification_evaluator_node  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "app" / "types")


def _load_package(value: CanonicalProjectPackage | bytes) -> CanonicalProjectPackage:
    if isinstance(value, CanonicalProjectPackage):
        # Re-admit the archive rather than trusting a mutable Python object.
        archive = value.archive
    elif isinstance(value, bytes):
        archive = value
    else:
        raise CanonicalReproductionError("canonical reproduction requires package bytes or a canonical package")
    try:
        return CanonicalProjectPackage.from_archive(archive)
    except CanonicalProjectPackageError as exc:
        raise CanonicalReproductionError("canonical project package integrity verification failed") from exc


def _publisher_outcome(
    package: CanonicalProjectPackage,
    attestation_value: Mapping[str, Any] | None,
    anchors_value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if attestation_value is None and anchors_value is None:
        return {"status": "not_provided", "reason": "publisher_attestation_not_provided"}
    if attestation_value is None or anchors_value is None:
        return {"status": "failed", "reason": "publisher_attestation_or_trust_anchors_missing"}
    try:
        attestation = SignedCanonicalProjectAttestation.from_dict(attestation_value)
        anchors = CanonicalPublisherTrustAnchors.from_dict(anchors_value)
        LocalCanonicalPublisherTrustStore.from_document(anchors).verify(package=package, attestation=attestation)
    except CanonicalPublisherAttestationError:
        return {"status": "failed", "reason": "publisher_attestation_not_authenticated"}
    return {"status": "passed", "reason": None}


def _fixture_identity(capability: SpectralDatasetCapability) -> dict[str, str | None]:
    summary = capability.evidence_summary()
    return {
        "content_digest": _require_digest(summary["content_digest"], "fixture content digest"),
        "envelope_digest": _require_digest(summary["envelope_digest"], "fixture envelope digest"),
        "dataset_ref_digest": _optional_digest(summary["dataset_ref_digest"], "fixture dataset reference"),
        "split_plan_digest": _optional_digest(summary["split_plan_digest"], "fixture split digest"),
        "sample_identity_digest": _optional_digest(summary["sample_identity_digest"], "fixture sample identity"),
        "feature_identity_digest": _optional_digest(summary["feature_identity_digest"], "fixture feature identity"),
        "target_identity_digest": _optional_array_digest(capability.arrays.get("target"), "target"),
        "group_identity_digest": _optional_array_digest(capability.arrays.get("groups"), "groups"),
    }


def _fixture_identity_failure(
    package: CanonicalProjectPackage,
    fixture: SpectralDatasetCapability,
    split_plan: SplitPlan,
) -> str | None:
    request = package.capsule.payload["admitted_request"]
    summary = fixture.evidence_summary()
    expected = {
        "dataset_content_digest": request["dataset_content_digest"],
        "capability_digest": request["capability_digest"],
        "dataset_ref_digest": request["dataset_ref_digest"],
        "split_digest": request["split_digest"],
    }
    actual = {
        "dataset_content_digest": summary["content_digest"],
        "capability_digest": summary["envelope_digest"],
        "dataset_ref_digest": summary["dataset_ref_digest"],
        "split_digest": split_plan.digest,
    }
    if expected != actual:
        return "fixture_or_split_identity_mismatch"
    shape = request["dataset_shape"]
    x = fixture.arrays["X"]
    if x.shape != (shape["n_samples"], shape["n_features"]):
        return "fixture_shape_mismatch"
    grouped = "groups" in fixture.arrays
    if grouped != shape["grouped"]:
        return "fixture_grouping_mismatch"
    if summary["split_plan_digest"] != split_plan.digest:
        return "fixture_capability_split_binding_mismatch"
    return None


def _validation_outcome(
    package: CanonicalProjectPackage,
    fixture: SpectralDatasetCapability,
    split_plan: SplitPlan,
) -> dict[str, Any]:
    try:
        execution = asyncio.run(execute_candidate_validation(package.capsule.graph, fixture, split_plan))
    except Exception:
        return _science_failed("canonical_validation_execution_failed")
    expected = package.capsule.execution_evidence.payload["validation_execution"]
    actual = execution.as_dict()
    comparison = _validation_comparison(expected, actual)
    status: Literal["passed", "failed"] = "passed" if comparison["matches"] else "failed"
    return {
        "status": status,
        "reason": None if status == "passed" else "canonical_validation_metrics_differ",
        "expected_metrics": deepcopy(expected["metrics"]),
        "actual_metrics": deepcopy(actual["metrics"]),
        "fold_metric_matches": comparison["fold_metric_matches"],
        "pooled_metric_match": comparison["pooled_metric_match"],
    }


def _application_outcome(
    package: CanonicalProjectPackage,
    fixture: SpectralDatasetCapability,
) -> dict[str, Any]:
    task = _application_task(package)
    try:
        source_prediction = _apply_source_artifact(package, fixture, task=task)
        application_prediction = _apply_visible_application_dag(package, fixture, task=task)
    except Exception:
        logger.exception("Canonical fitted-artifact application reproduction failed")
        return _science_failed("canonical_artifact_application_failed")
    matches = _predictions_match(source_prediction, application_prediction, task=task)
    status: Literal["passed", "failed"] = "passed" if matches else "failed"
    return {
        "status": status,
        "reason": None if status == "passed" else "canonical_artifact_predictions_differ",
        "source_prediction_digest": _array_digest(source_prediction, "source_predictions"),
        "application_prediction_digest": _array_digest(application_prediction, "application_predictions"),
        "prediction_match": matches,
        "n_predictions": int(application_prediction.size),
    }


def _apply_source_artifact(
    package: CanonicalProjectPackage,
    fixture: SpectralDatasetCapability,
    *,
    task: str,
) -> np.ndarray:
    """Apply the artifact through source-node ABIs, outside the app DAG.

    This intentionally makes a second local path for comparison.  It is not
    a candidate materializer: every fitted state comes from the imported,
    immutable artifact and every source operation is re-admitted from the
    capsule graph.
    """

    current = _fixture_dataset(fixture)
    states = {node_id: json.loads(raw) for node_id, raw in package.artifact.state_bytes.items()}
    for graph_node in package.capsule.graph.nodes[:-1]:
        lifecycle = LifecycleKind(graph_node.contract.payload["lifecycle_kind"])
        node = node_registry.create_node(graph_node.operation_id, graph_node.node_id, graph_node.parameters)
        if lifecycle is LifecycleKind.STATELESS_TRANSFORM:
            # Canonical validation executes transforms through the managed
            # ``input_data`` port.  Reproduction must use that same contract;
            # calling a Workbench-facing positional port can legitimately
            # expose additional diagnostics such as selection masks and is a
            # different output surface.
            current = _dataset_output(
                asyncio.run(node.execute(input_data=current)),
                graph_node.node_id,
            )
        elif lifecycle in {LifecycleKind.FITTED_TRANSFORM, LifecycleKind.FITTED_MODEL}:
            state = states.get(graph_node.node_id)
            apply = getattr(node, "apply_fitted_state", None)
            if not isinstance(state, Mapping) or not callable(apply):
                raise CanonicalReproductionError("source fitted artifact operation is unavailable")
            raw = apply(current, state)
            if lifecycle is LifecycleKind.FITTED_TRANSFORM:
                current = _dataset_output(raw, graph_node.node_id)
            else:
                if task == "classification":
                    predict_labels = getattr(node, "predict_fitted_labels", None)
                    if not callable(predict_labels):
                        raise CanonicalReproductionError("source classifier label application is unavailable")
                    raw = predict_labels(current, state)
                return _prediction_output(raw, graph_node.node_id, task=task)
        else:
            raise CanonicalReproductionError("source application graph has an unsupported lifecycle")
    raise CanonicalReproductionError("source application graph has no fitted model")


def _apply_visible_application_dag(
    package: CanonicalProjectPackage,
    fixture: SpectralDatasetCapability,
    *,
    task: str,
) -> np.ndarray:
    """Run the imported visible application DAG under its scoped read grant."""

    current: SherpaDataset | np.ndarray = _fixture_dataset(fixture)
    with tempfile.TemporaryDirectory(prefix="spectra-canonical-reproduction-") as directory:
        base = Path(directory).resolve()
        source = package.artifact.write_new(base / "source-artifact")
        store = init_canonical_artifact_store(base)
        installed = store.install_from_directory(source)
        if installed.artifact_digest != package.artifact.artifact_digest:
            raise CanonicalReproductionError("installed canonical artifact differs from package")
        runtime = ExecutionRuntime(
            canonical_artifact_reader=ReadOnlyCanonicalArtifactReader(
                base,
                allowed_artifact_digests=(installed.artifact_digest,),
            )
        )
        execution = asyncio.run(
            execute_canonical_application(
                package.application_plan,
                current,
                runtime=runtime,
            )
        )
        model_node_id = package.application_plan.payload["model_node_id"]
        return _prediction_output(execution.results[model_node_id], model_node_id, task=task)


def _fixture_dataset(capability: SpectralDatasetCapability) -> SherpaDataset:
    dataset, _groups = capability.to_dataset_and_groups()
    return dataset


def _dataset_output(raw: object, node_id: str) -> SherpaDataset:
    result = NodeResult.wrap(raw)
    if set(result.outputs) != {"default"} or not isinstance(result.outputs["default"], SherpaDataset):
        raise CanonicalReproductionError(f"{node_id} did not produce a spectral dataset")
    return result.outputs["default"]


def _prediction_output(raw: object, node_id: str, *, task: str) -> np.ndarray:
    result = NodeResult.wrap(raw)
    if task == "classification":
        if isinstance(raw, np.ndarray):
            predictions = np.asarray(raw, dtype=str)
        else:
            if set(result.outputs) not in (
                {"class_scores", "y_pred"},
                {"y_pred", "y_prob"},
                {"class_affinity", "y_pred"},
            ):
                raise CanonicalReproductionError(f"{node_id} did not produce class predictions")
            predictions = np.asarray(result.outputs["y_pred"], dtype=str)
        if predictions.ndim != 1 or not predictions.size or any(not label for label in predictions.tolist()):
            raise CanonicalReproductionError(f"{node_id} class predictions are invalid")
        return np.array(predictions, copy=True)
    # The current PLS application declares bounded identity, applicability and
    # interval outputs alongside predictions. Confirmation/reproduction uses
    # only predictions; metadata never becomes a metric or leaves the worker.
    if set(result.outputs) not in (
        {"default"},
        {"default", "prediction_identity", "applicability", "prediction_intervals"},
    ):
        raise CanonicalReproductionError(f"{node_id} did not produce predictions")
    try:
        predictions = np.asarray(result.outputs["default"], dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise CanonicalReproductionError(f"{node_id} predictions are invalid") from exc
    if predictions.ndim == 1:
        predictions = predictions.reshape(-1, 1)
    if predictions.ndim != 2 or not predictions.size or not np.isfinite(predictions).all():
        raise CanonicalReproductionError(f"{node_id} predictions are invalid")
    return np.array(predictions, copy=True)


def _application_task(package: CanonicalProjectPackage) -> str:
    model_node_id = package.application_plan.payload["model_node_id"]
    model = next(
        (node for node in package.capsule.graph.nodes if node.node_id == model_node_id),
        None,
    )
    if model is None:
        raise CanonicalReproductionError("canonical application model node is unavailable")
    task = model.contract.payload.get("supervised_task")
    if task not in {"classification", "regression"}:
        raise CanonicalReproductionError("canonical application supervised task is unavailable")
    return str(task)


def _predictions_match(left: np.ndarray, right: np.ndarray, *, task: str) -> bool:
    if left.shape != right.shape:
        return False
    if task == "classification":
        return bool(np.array_equal(left, right))
    return bool(
        np.allclose(
            left,
            right,
            rtol=METRIC_PARITY_RELATIVE_TOLERANCE,
            atol=METRIC_PARITY_ABSOLUTE_TOLERANCE,
            equal_nan=False,
        )
    )


def _validation_comparison(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> dict[str, Any]:
    identity_fields = (
        "schema_version",
        "graph_digest",
        "capability_content_digest",
        "capability_envelope_digest",
        "split_plan_digest",
    )
    identities_match = all(expected.get(field) == actual.get(field) for field in identity_fields)
    expected_folds, actual_folds = expected.get("folds"), actual.get("folds")
    if (
        not isinstance(expected_folds, list)
        or not isinstance(actual_folds, list)
        or len(expected_folds) != len(actual_folds)
    ):
        return {"matches": False, "fold_metric_matches": [], "pooled_metric_match": False}
    fold_matches = [
        _fold_matches(expected_fold, actual_fold)
        for expected_fold, actual_fold in zip(expected_folds, actual_folds, strict=True)
    ]
    pooled = _metrics_match(expected.get("metrics"), actual.get("metrics"))
    return {
        "matches": identities_match and all(fold_matches) and pooled,
        "fold_metric_matches": fold_matches,
        "pooled_metric_match": pooled,
    }


def _fold_matches(expected: Any, actual: Any) -> bool:
    if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
        return False
    return (
        expected.get("partition_digest") == actual.get("partition_digest")
        and expected.get("model_node_id") == actual.get("model_node_id")
        and expected.get("evaluator_node_id") == actual.get("evaluator_node_id")
        and expected.get("node_ids") == actual.get("node_ids")
        and _metrics_match(expected.get("metrics"), actual.get("metrics"))
    )


def _metrics_match(expected: Any, actual: Any) -> bool:
    try:
        expected_record = validate_supervised_metric_record(expected)
        actual_record = validate_supervised_metric_record(actual)
    except (TypeError, ValueError):
        return False
    if supervised_metric_task(expected_record) != supervised_metric_task(actual_record):
        return False
    if supervised_metric_task(expected_record) == "classification":
        # Classification is a deterministic integer confusion-matrix
        # projection; there is no floating-point scientific ambiguity.
        return expected_record == actual_record
    if set(expected_record) != set(actual_record):
        return False
    if (
        expected_record["registry_version"] != actual_record["registry_version"]
        or expected_record["n_samples"] != actual_record["n_samples"]
    ):
        return False
    for field in ("rmse", "mae", "bias", "r2", "sep", "slope", "intercept", "rer"):
        left, right = expected_record[field], actual_record[field]
        if left is None or right is None:
            if left is not right:
                return False
        elif (
            not isinstance(left, (int, float))
            or not isinstance(right, (int, float))
            or not math.isclose(
                float(left),
                float(right),
                rel_tol=METRIC_PARITY_RELATIVE_TOLERANCE,
                abs_tol=METRIC_PARITY_ABSOLUTE_TOLERANCE,
            )
        ):
            return False
    return True


def _science_not_run(reason: str) -> dict[str, Any]:
    return {"status": "not_run", "reason": reason}


def _science_failed(reason: str) -> dict[str, Any]:
    return {"status": "failed", "reason": reason}


def _validate_fixture_identity(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != _FIXTURE_FIELDS:
        raise CanonicalReproductionError("canonical reproduction fixture identity is closed")
    for field, item in value.items():
        _optional_digest(item, f"fixture_identity.{field}")


def _validate_outcome(value: Any, label: str, *, allowed: set[str] | frozenset[str]) -> None:
    if not isinstance(value, Mapping) or set(value) != _OUTCOME_FIELDS or value.get("status") not in allowed:
        raise CanonicalReproductionError(f"canonical reproduction {label} outcome is invalid")
    reason = value.get("reason")
    if reason is not None and (not isinstance(reason, str) or not reason or len(reason) > 128):
        raise CanonicalReproductionError(f"canonical reproduction {label} reason is invalid")
    if (value["status"] == "passed") != (reason is None):
        raise CanonicalReproductionError(f"canonical reproduction {label} status/reason differs")


def _validate_validation_outcome(value: Any) -> None:
    if not isinstance(value, Mapping) or "status" not in value or value["status"] not in _STATUS:
        raise CanonicalReproductionError("canonical reproduction validation outcome is invalid")
    if set(value) == _OUTCOME_FIELDS:
        _validate_outcome(value, "validation_reproduced", allowed={"not_run", "failed"})
        return
    required = {
        "status",
        "reason",
        "expected_metrics",
        "actual_metrics",
        "fold_metric_matches",
        "pooled_metric_match",
    }
    if set(value) != required:
        raise CanonicalReproductionError("canonical reproduction validation fields are closed")
    if value["status"] not in {"passed", "failed"}:
        raise CanonicalReproductionError("canonical reproduction validation status is invalid")
    if (
        not isinstance(value["fold_metric_matches"], list)
        or not value["fold_metric_matches"]
        or not all(isinstance(item, bool) for item in value["fold_metric_matches"])
        or not isinstance(value["pooled_metric_match"], bool)
    ):
        raise CanonicalReproductionError("canonical reproduction validation comparisons are invalid")
    _validate_metrics_projection(value["expected_metrics"])
    _validate_metrics_projection(value["actual_metrics"])
    _validate_outcome(
        {"status": value["status"], "reason": value["reason"]},
        "validation_reproduced",
        allowed={"passed", "failed"},
    )


def _validate_application_outcome(value: Any) -> None:
    if not isinstance(value, Mapping) or "status" not in value or value["status"] not in _STATUS:
        raise CanonicalReproductionError("canonical reproduction application outcome is invalid")
    if set(value) == _OUTCOME_FIELDS:
        _validate_outcome(value, "application_reproduced", allowed={"not_run", "failed"})
        return
    required = {
        "status",
        "reason",
        "source_prediction_digest",
        "application_prediction_digest",
        "prediction_match",
        "n_predictions",
    }
    if set(value) != required or value["status"] not in {"passed", "failed"}:
        raise CanonicalReproductionError("canonical reproduction application fields are closed")
    _require_digest(value["source_prediction_digest"], "source_prediction_digest")
    _require_digest(value["application_prediction_digest"], "application_prediction_digest")
    if (
        not isinstance(value["prediction_match"], bool)
        or isinstance(value["n_predictions"], bool)
        or value["n_predictions"] < 1
    ):
        raise CanonicalReproductionError("canonical reproduction application comparison is invalid")
    _validate_outcome(
        {"status": value["status"], "reason": value["reason"]},
        "application_reproduced",
        allowed={"passed", "failed"},
    )


def _validate_metrics_projection(value: Any) -> None:
    try:
        validate_supervised_metric_record(value)
    except (TypeError, ValueError) as exc:
        raise CanonicalReproductionError("canonical reproduction metric projection is invalid") from exc


def _array_digest(value: np.ndarray, name: str) -> str:
    array = np.ascontiguousarray(np.asarray(value))
    if array.dtype.kind in {"O", "U", "S"}:
        labels = np.asarray(array, dtype=str)
        return hashlib.sha256(
            _canonical_json({"dtype": "unicode", "shape": list(labels.shape), "values": labels.tolist()})
        ).hexdigest()
    return hashlib.sha256(
        # ``name`` is an error-context label only.  A prediction vector from
        # the source ABI and one from the visible application DAG must produce
        # the same digest when their numeric representation is byte-identical.
        _canonical_json({"dtype": array.dtype.str, "shape": list(array.shape)})
        + array.tobytes()
    ).hexdigest()


def _optional_array_digest(value: Any, name: str) -> str | None:
    return None if value is None else _array_digest(np.asarray(value), name)


def _optional_digest(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_digest(value, label)


def _require_digest(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_LENGTH
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise CanonicalReproductionError(f"{label} must be a SHA-256 digest")
    return value


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CanonicalReproductionError("canonical reproduction report must contain finite JSON") from exc


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


__all__ = [
    "CANONICAL_REPRODUCTION_REPORT_VERSION",
    "CanonicalReproductionError",
    "CanonicalReproductionReport",
    "reproduce_canonical_project",
]
