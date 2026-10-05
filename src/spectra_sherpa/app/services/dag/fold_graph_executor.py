"""Execute the admitted canonical validation graph once for one data fold.

The original one-role executor remains deliberately narrow, accepting an
unbranched default-port path made from reviewed stateless transforms.  The
paired executor below adds the first fitted-transform seam without introducing
a parallel candidate recipe: it accepts a :class:`ValidationGraph` and creates
every node through ``FoldLifecycleContext``.  Later M4.5 slices extend this
same path for fitted estimators rather than reintroducing a hidden pipeline.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, Mapping

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.classification_application import (
    CLASSIFICATION_REJECT_LABEL,
    ClassificationApplicationError,
    validate_classification_application,
)
from spectra_sherpa.app.services.dag.fold_lifecycle import (
    FittedStateRecord,
    FoldAttempt,
    FoldLifecycleContext,
    FoldPartition,
    FullDataFittedStateRecord,
    FullDataRefitContext,
)
from spectra_sherpa.app.services.dag.node_base import NodeResult
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import (
    ValidationGraph,
    ValidationGraphError,
    assert_admitted_validation_graph,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, TargetAccess
from spectra_sherpa.sdk.validate import (
    CLASSIFICATION_METRIC_SET_REGISTRY_VERSION,
    METRIC_PARITY_ABSOLUTE_TOLERANCE,
    METRIC_PARITY_RELATIVE_TOLERANCE,
    REGRESSION_METRIC_REGISTRY_VERSION,
    ClassificationMetricAccumulator,
    ClassificationMetricSet,
    RegressionMetricAccumulator,
    RegressionMetrics,
    SplitPlan,
    classification_metric_set,
    validate_classification_split_plan,
    validate_supervised_metric_record,
)

SupervisedMetrics = RegressionMetrics | ClassificationMetricSet
MetricAccumulator = RegressionMetricAccumulator | ClassificationMetricAccumulator

FoldRole = Literal["train", "test"]
logger = logging.getLogger(__name__)
_PRIVATE_CLASSIFICATION_TRACE_AUTHORITY = object()
_PRIVATE_CLASSIFICATION_STATE_BYTES_MAX = 128 * 1024 * 1024


class FoldGraphExecutionError(RuntimeError):
    """The admitted graph did not produce the typed local fold result promised."""


def _require_target(target: np.ndarray | None, *, node_id: str, role: str) -> np.ndarray:
    """Fail closed when a supervised consumer receives no target capability."""

    if target is None:
        raise FoldGraphExecutionError(f"{node_id} requires target data for {role}")
    return target


def _fit_fold_transform_state(
    node: Any,
    context: FoldLifecycleContext,
    input_data: SherpaDataset,
    *,
    node_id: str,
) -> dict[str, object]:
    """Fit one transform with exactly the target access its contract grants."""

    fit = getattr(node, "fit_fitted_state", None)
    if not callable(fit):
        raise TypeError("fitted node does not expose the required local fit method")
    access = TargetAccess(context.contract.payload["target_access"])
    if access is TargetAccess.NONE:
        state = fit(input_data)
    else:
        target = context.target("train")
        if access is not TargetAccess.OPTIONAL:
            target = _require_target(target, node_id=node_id, role="fitted-transform training")
        state = fit(input_data, target)
    if not isinstance(state, dict):
        raise TypeError("fitted node must return a JSON-object state")
    return state


def _fit_full_transform_state(
    node: Any,
    context: FullDataRefitContext,
    input_data: SherpaDataset,
    *,
    node_id: str,
) -> dict[str, object]:
    """Fit a full-data transform without granting undeclared target access."""

    fit = getattr(node, "fit_fitted_state", None)
    if not callable(fit):
        raise TypeError("fitted node does not expose the required local fit method")
    access = TargetAccess(context.contract.payload["target_access"])
    if access is TargetAccess.NONE:
        state = fit(input_data)
    else:
        target = context.target()
        if access is not TargetAccess.OPTIONAL:
            target = _require_target(target, node_id=node_id, role="full-data fitted-transform training")
        state = fit(input_data, target)
    if not isinstance(state, dict):
        raise TypeError("fitted node must return a JSON-object state")
    return state


@dataclass(frozen=True)
class NodeExecutionTrace:
    """One sample-free observation made at a real canonical node boundary.

    This deliberately records identity and typed-envelope facts, not numerical
    arrays, fitted-state bytes, predictions, or wall-clock measurements.  The
    latter are either scientifically sensitive or operationally variable; the
    durable M4.8 archive gives those concerns their own governed records.
    """

    node_id: str
    operation_id: str
    contract: Mapping[str, Any]
    contract_digest: str
    parameters: Mapping[str, Any]
    parameter_digest: str
    role_envelopes: tuple[tuple[FoldRole, tuple[int, ...], tuple[int, ...]], ...]
    partition_digest: str
    seed: int | None
    feature_identity_digest: str | None
    fitted_state_digest: str | None
    fitted_state_serializer: str | None

    def as_dict(self) -> dict[str, Any]:
        """Return the closed public trace projection for evidence consumers."""

        payload = {
            "node_id": self.node_id,
            "operation_id": self.operation_id,
            "contract": dict(self.contract),
            "contract_digest": self.contract_digest,
            "parameters": dict(self.parameters),
            "parameter_digest": self.parameter_digest,
            "role_envelopes": [
                {"role": role, "input_shape": list(input_shape), "output_shape": list(output_shape)}
                for role, input_shape, output_shape in self.role_envelopes
            ],
            "partition_digest": self.partition_digest,
            "seed": self.seed,
            "feature_identity_digest": self.feature_identity_digest,
            "fitted_state_digest": self.fitted_state_digest,
            "fitted_state_serializer": self.fitted_state_serializer,
        }
        # The calls below intentionally make a malformed internal trace fail at
        # its producer rather than handing a non-finite or non-canonical value
        # to an evidence serializer later.
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        return json.loads(encoded)


def _parameter_digest(parameters: Mapping[str, Any]) -> str:
    """Name the exact admitted parameter projection without a second format."""

    try:
        encoded = json.dumps(parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise FoldGraphExecutionError("canonical node parameters must be finite JSON") from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _shape(value: Any) -> tuple[int, ...]:
    """Return a bounded JSON-compatible shape from an executed local value."""

    shape = getattr(value, "shape", None)
    if not isinstance(shape, tuple) or len(shape) > 4 or any(not isinstance(item, (int, np.integer)) for item in shape):
        raise FoldGraphExecutionError("node execution has no bounded shape")
    return tuple(int(item) for item in shape)


def _node_trace(
    graph_node: Any,
    capability: SpectralDatasetCapability,
    partition: FoldPartition,
    *,
    parameters: Mapping[str, Any],
    role_envelopes: tuple[tuple[FoldRole, tuple[int, ...], tuple[int, ...]], ...],
    seed: int | None,
    fitted_state_digest: str | None = None,
) -> NodeExecutionTrace:
    """Capture an actual node boundary after its lifecycle call succeeded."""

    contract = graph_node.contract
    summary = capability.evidence_summary()
    feature_digest = summary["feature_identity_digest"]
    if feature_digest is not None and not isinstance(feature_digest, str):  # Defensive: capability owns this summary.
        raise FoldGraphExecutionError("capability feature identity is unavailable for execution evidence")
    serializer = contract.payload["fitted_state_serializer"] if fitted_state_digest is not None else None
    if serializer is not None and not isinstance(serializer, str):
        raise FoldGraphExecutionError("fitted execution has no declared state serializer")
    return NodeExecutionTrace(
        node_id=graph_node.node_id,
        operation_id=graph_node.operation_id,
        contract=contract.as_dict(),
        contract_digest=contract.digest,
        parameters=dict(parameters),
        parameter_digest=_parameter_digest(parameters),
        role_envelopes=role_envelopes,
        partition_digest=partition.digest,
        seed=seed,
        feature_identity_digest=feature_digest,
        fitted_state_digest=fitted_state_digest,
        fitted_state_serializer=serializer,
    )


@dataclass(frozen=True)
class FoldGraphExecution:
    """Local-only outcome for one exact graph, capability partition, and role."""

    graph_digest: str
    capability_content_digest: str
    capability_envelope_digest: str
    partition_digest: str
    role: FoldRole
    output: SherpaDataset
    node_ids: tuple[str, ...]


@dataclass(frozen=True)
class FoldPairGraphExecution:
    """Local-only train/test outcome from one shared, leakage-safe fold attempt.

    The paired API is required for fitted operations.  It keeps the train fit
    and held-out apply phases inside one private :class:`FoldAttempt` and does
    not expose fitted state or its private attempt identity in the result.
    """

    graph_digest: str
    capability_content_digest: str
    capability_envelope_digest: str
    partition_digest: str
    train_output: SherpaDataset
    test_output: SherpaDataset
    node_ids: tuple[str, ...]


@dataclass(frozen=True)
class SupervisedFoldGraphExecution:
    """Private fold predictions from an admitted terminal fitted model.

    This is intentionally *not* a metrics or evidence record.  Its only
    responsibility is to prove that the canonical typed graph supplies the
    training spectra and training targets to an explicit fitted model, then
    supplies held-out spectra only to that exact fitted state.  The following
    evaluator slice is the sole authority allowed to retrieve held-out targets
    and calculate validation metrics.
    """

    graph_digest: str
    capability_content_digest: str
    capability_envelope_digest: str
    partition_digest: str
    train_predictions: np.ndarray
    test_predictions: np.ndarray
    fitted_state_digest: str
    node_ids: tuple[str, ...]


@dataclass(frozen=True, init=False)
class PrivateClassificationFoldTrace:
    """Bounded local row trace from the exact application scored by a fold."""

    partition_digest: str
    fitted_state_digest: str
    fitted_state: FittedStateRecord
    application_digest: str
    test_indices: tuple[int, ...]
    truth: tuple[Any, ...]
    predictions: tuple[Any, ...]
    class_labels: tuple[Any, ...]
    class_responses: np.ndarray
    decision_margins: np.ndarray

    @classmethod
    def _bound(
        cls,
        *,
        partition_digest: str,
        fitted_state: FittedStateRecord,
        application_digest: str,
        test_indices: tuple[int, ...],
        truth: tuple[Any, ...],
        predictions: tuple[Any, ...],
        class_labels: tuple[Any, ...],
        class_responses: np.ndarray,
        decision_margins: np.ndarray,
    ) -> "PrivateClassificationFoldTrace":
        trace = object.__new__(cls)
        object.__setattr__(trace, "partition_digest", partition_digest)
        object.__setattr__(trace, "fitted_state_digest", fitted_state.digest)
        object.__setattr__(trace, "fitted_state", fitted_state)
        object.__setattr__(trace, "application_digest", application_digest)
        object.__setattr__(trace, "test_indices", test_indices)
        object.__setattr__(trace, "truth", truth)
        object.__setattr__(trace, "predictions", predictions)
        object.__setattr__(trace, "class_labels", class_labels)
        object.__setattr__(trace, "class_responses", class_responses)
        object.__setattr__(trace, "decision_margins", decision_margins)
        object.__setattr__(trace, "_trace_authority", _PRIVATE_CLASSIFICATION_TRACE_AUTHORITY)
        return trace


@dataclass(frozen=True, init=False)
class PrivateClassificationValidationTrace:
    """Local-only row authority paired to one public validation execution."""

    validation_execution_digest: str
    folds: tuple[PrivateClassificationFoldTrace, ...]

    @classmethod
    def _bound(
        cls,
        execution: "CandidateValidationExecution",
        folds: tuple[PrivateClassificationFoldTrace, ...],
    ) -> "PrivateClassificationValidationTrace":
        if getattr(execution, "_validation_authority", None) is not _CANDIDATE_VALIDATION_AUTHORITY:
            raise FoldGraphExecutionError("private classification custody requires executor-issued validation")
        if len(folds) != len(execution.folds):
            raise FoldGraphExecutionError("private classification custody does not cover every outer fold")
        retained_state_bytes = 0
        seen_indices: list[int] = []
        for split_fold, public_fold, trace in zip(
            execution.split_plan.folds,
            execution.folds,
            folds,
            strict=True,
        ):
            if (
                type(trace) is not PrivateClassificationFoldTrace
                or getattr(trace, "_trace_authority", None) is not _PRIVATE_CLASSIFICATION_TRACE_AUTHORITY
            ):
                raise FoldGraphExecutionError("private classification custody contains a forged fold trace")
            expected_partition = FoldPartition.create(
                split_fold.train,
                split_fold.test,
                sample_count=execution.split_plan.n_samples,
            )
            if (
                trace.partition_digest != expected_partition.digest
                or trace.partition_digest != public_fold.partition_digest
                or trace.test_indices != tuple(int(value) for value in split_fold.test)
                or trace.fitted_state_digest != trace.fitted_state.digest
                or trace.fitted_state_digest != public_fold.fitted_state_digest
                or trace.application_digest != public_fold.prediction_application_digest
            ):
                raise FoldGraphExecutionError("private classification custody disagrees with public validation")
            if trace.fitted_state.partition_digest != trace.partition_digest:
                raise FoldGraphExecutionError("private classification state has the wrong fold authority")
            retained_state_bytes += trace.fitted_state.state_size_bytes
            if retained_state_bytes > _PRIVATE_CLASSIFICATION_STATE_BYTES_MAX:
                raise FoldGraphExecutionError("private classification fitted-state custody exceeds its byte limit")
            responses = np.asarray(trace.class_responses, dtype=np.float64)
            classes = np.asarray(trace.class_labels, dtype=object)
            predicted = classes[np.argmax(responses, axis=1)]
            margins = np.sort(responses, axis=1)[:, -1] - np.sort(responses, axis=1)[:, -2]
            try:
                rebound_application = validate_classification_application(
                    fitted_state_digest=trace.fitted_state_digest,
                    predictions=trace.predictions,
                    responses=responses,
                    classes=trace.class_labels,
                )
            except ClassificationApplicationError as exc:
                raise FoldGraphExecutionError(
                    "private classification custody has inconsistent application data"
                ) from exc
            if (
                tuple(predicted.tolist()) != trace.predictions
                or not np.array_equal(margins, trace.decision_margins)
                or rebound_application.application_digest != trace.application_digest
            ):
                raise FoldGraphExecutionError("private classification custody has inconsistent application data")
            if (
                classification_metric_set(
                    trace.truth,
                    trace.predictions,
                    labels=public_fold.metrics.labels,
                )
                != public_fold.metrics
            ):
                raise FoldGraphExecutionError("private classification custody disagrees with public fold metrics")
            seen_indices.extend(trace.test_indices)
        if sorted(seen_indices) != list(range(execution.split_plan.n_samples)):
            raise FoldGraphExecutionError("private classification custody does not score every sample exactly once")
        result = object.__new__(cls)
        object.__setattr__(result, "validation_execution_digest", execution.digest)
        object.__setattr__(result, "folds", folds)
        object.__setattr__(result, "_trace_authority", _PRIVATE_CLASSIFICATION_TRACE_AUTHORITY)
        return result


@dataclass(frozen=True)
class ScoredSupervisedFoldGraphExecution:
    """Bounded held-out supervised result from one canonical graph execution.

    The result names the exact graph, data capability, partition, fitted model
    state, and evaluator, but deliberately does not retain row-level targets
    or predictions.  The evaluator is the sole code path that retrieves the
    held-out target from its fold lifecycle authority.
    """

    graph_digest: str
    capability_content_digest: str
    capability_envelope_digest: str
    partition_digest: str
    fitted_state_digest: str
    metrics: SupervisedMetrics
    model_node_id: str
    evaluator_node_id: str
    node_ids: tuple[str, ...]
    node_execution_traces: tuple[NodeExecutionTrace, ...]
    prediction_application_digest: str | None = None


_CANDIDATE_VALIDATION_AUTHORITY = object()
_FULL_DATA_REFIT_AUTHORITY = object()


@dataclass(frozen=True, init=False)
class CandidateValidationExecution:
    """Executor-issued pooled evaluation of one exact canonical candidate.

    The public constructor is deliberately disabled.  This record authorizes
    the later all-sample refit, so ordinary callers must not be able to invent
    favorable metrics or fold identities and present them as completed
    validation.  ``execute_candidate_validation`` is its only producer.
    """

    graph_digest: str
    capability_content_digest: str
    capability_envelope_digest: str
    split_plan: SplitPlan
    task_type: str
    model_operation_id: str
    metrics: SupervisedMetrics
    folds: tuple[ScoredSupervisedFoldGraphExecution, ...]

    @classmethod
    def _bound(
        cls,
        *,
        graph_digest: str,
        capability_content_digest: str,
        capability_envelope_digest: str,
        split_plan: SplitPlan,
        task_type: str,
        model_operation_id: str,
        metrics: SupervisedMetrics,
        folds: tuple[ScoredSupervisedFoldGraphExecution, ...],
    ) -> "CandidateValidationExecution":
        execution = object.__new__(cls)
        object.__setattr__(execution, "graph_digest", graph_digest)
        object.__setattr__(execution, "capability_content_digest", capability_content_digest)
        object.__setattr__(execution, "capability_envelope_digest", capability_envelope_digest)
        object.__setattr__(execution, "split_plan", split_plan)
        object.__setattr__(execution, "task_type", task_type)
        object.__setattr__(execution, "model_operation_id", model_operation_id)
        object.__setattr__(execution, "metrics", metrics)
        object.__setattr__(execution, "folds", folds)
        # This local-only authority is intentionally absent from dataclass
        # fields and every serialized digest/evidence representation.
        object.__setattr__(execution, "_validation_authority", _CANDIDATE_VALIDATION_AUTHORITY)
        return execution

    def as_dict(self) -> dict:
        """Return the bounded, sample-free validation identity payload.

        This is deliberately the only serialization used to name a canonical
        validation execution.  Later evidence contracts wrap this payload;
        they must not recreate the digest from a second projection of the
        scientific graph.
        """

        return {
            "schema_version": "spectra-candidate-validation/3",
            "graph_digest": self.graph_digest,
            "capability_content_digest": self.capability_content_digest,
            "capability_envelope_digest": self.capability_envelope_digest,
            "split_plan_digest": self.split_plan.digest,
            "task_type": self.task_type,
            "model_operation_id": self.model_operation_id,
            "metrics": self.metrics.as_dict(),
            "folds": [
                {
                    "partition_digest": fold.partition_digest,
                    "metrics": fold.metrics.as_dict(),
                    "model_node_id": fold.model_node_id,
                    "evaluator_node_id": fold.evaluator_node_id,
                    "node_ids": list(fold.node_ids),
                    "prediction_application_digest": fold.prediction_application_digest,
                }
                for fold in self.folds
            ],
        }

    @property
    def digest(self) -> str:
        """Identify bounded validation evidence without serializing fitted state."""
        return hashlib.sha256(
            json.dumps(
                self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
            ).encode("utf-8")
        ).hexdigest()


def _serialize_executor_issued_validation(
    execution: CandidateValidationExecution,
) -> tuple[dict[str, object], str]:
    """Expose evidence only for a validation issued by this executor.

    This stays private because it is an authority bridge, not a general
    serialization API. Detached evidence is verified through the OSS evidence
    contract after this one-time in-process issuance check.
    """

    if (
        type(execution) is not CandidateValidationExecution
        or getattr(execution, "_validation_authority", None) is not _CANDIDATE_VALIDATION_AUTHORITY
    ):
        raise FoldGraphExecutionError("canonical evidence requires an executor-issued validation execution")
    return execution.as_dict(), execution.digest


@dataclass(frozen=True, init=False)
class FullDataRefitExecution:
    """Local application fit bound to one selected validation result.

    The selected validation remains the only performance measurement linked to
    this record.  The included states exist solely for local application and
    later explicit artifact materialization; they are not validation evidence.
    """

    validation_execution_digest: str
    graph_digest: str
    capability_content_digest: str
    capability_envelope_digest: str
    model_node_id: str
    fitted_states: tuple[FullDataFittedStateRecord, ...]
    node_ids: tuple[str, ...]

    @classmethod
    def _bound(
        cls,
        *,
        validation_execution_digest: str,
        graph_digest: str,
        capability_content_digest: str,
        capability_envelope_digest: str,
        model_node_id: str,
        fitted_states: tuple[FullDataFittedStateRecord, ...],
        node_ids: tuple[str, ...],
    ) -> "FullDataRefitExecution":
        execution = object.__new__(cls)
        object.__setattr__(execution, "validation_execution_digest", validation_execution_digest)
        object.__setattr__(execution, "graph_digest", graph_digest)
        object.__setattr__(execution, "capability_content_digest", capability_content_digest)
        object.__setattr__(execution, "capability_envelope_digest", capability_envelope_digest)
        object.__setattr__(execution, "model_node_id", model_node_id)
        object.__setattr__(execution, "fitted_states", fitted_states)
        object.__setattr__(execution, "node_ids", node_ids)
        # Like validation authority, this marker is local-only and deliberately
        # absent from the sample-free serialization below.  A full-data refit
        # can produce an application artifact, so callers must not be able to
        # construct a detached object and present it as executor-issued.
        object.__setattr__(execution, "_full_refit_authority", _FULL_DATA_REFIT_AUTHORITY)
        return execution

    def as_dict(self) -> dict[str, object]:
        """Return the bounded identity of an application fit, never metrics.

        This projection includes only hashes and contract metadata.  In
        particular it omits fitted-state bytes, samples, targets, predictions,
        and any validation metric so an all-data refit cannot be misread as a
        second evaluation.
        """

        return {
            "schema_version": "spectra-full-data-refit/1",
            "validation_execution_digest": self.validation_execution_digest,
            "graph_digest": self.graph_digest,
            "capability_content_digest": self.capability_content_digest,
            "capability_envelope_digest": self.capability_envelope_digest,
            "model_node_id": self.model_node_id,
            "node_ids": list(self.node_ids),
            "fitted_state_references": [
                {
                    "node_id": record.node_id,
                    "state_digest": record.digest,
                    "serializer": record.serializer,
                    "contract_digest": record.contract_digest,
                    "candidate_node_digest": record.candidate_node_digest,
                    "seed": record.seed,
                }
                for record in self.fitted_states
            ],
        }

    @property
    def digest(self) -> str:
        """Identify the bounded full-data refit without exposing its state."""

        return hashlib.sha256(
            json.dumps(
                self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
            ).encode("utf-8")
        ).hexdigest()


def _serialize_executor_issued_full_refit(
    execution: FullDataRefitExecution,
) -> tuple[dict[str, object], str]:
    """Expose a full-refit projection only when the executor issued it."""

    if (
        type(execution) is not FullDataRefitExecution
        or getattr(execution, "_full_refit_authority", None) is not _FULL_DATA_REFIT_AUTHORITY
    ):
        raise FoldGraphExecutionError("canonical refit evidence requires an executor-issued full-data refit")
    return execution.as_dict(), execution.digest


async def execute_fold_graph(
    graph: ValidationGraph,
    capability: SpectralDatasetCapability,
    partition: FoldPartition,
    *,
    role: FoldRole,
) -> FoldGraphExecution:
    """Run an already-admitted graph with no alternate data or topology path."""

    if role not in {"train", "test"}:
        raise FoldGraphExecutionError("fold role must be train or test")
    try:
        assert_admitted_validation_graph(graph)
    except ValidationGraphError as exc:
        raise FoldGraphExecutionError("validation graph is not an admitted execution identity") from exc

    current: SherpaDataset | None = None
    executed_ids: list[str] = []
    for graph_node in graph.nodes:
        context = FoldLifecycleContext(graph_node.contract, capability, partition)
        lifecycle = LifecycleKind(graph_node.contract.payload["lifecycle_kind"])
        if lifecycle is not LifecycleKind.STATELESS_TRANSFORM:
            raise FoldGraphExecutionError("this executor slice supports reviewed stateless transforms only")
        try:
            node = context.fresh_node(graph_node.node_id, graph_node.parameters)
        except Exception:
            logger.exception("Fold graph node initialization failed for node_id=%s", graph_node.node_id)
            raise FoldGraphExecutionError(f"{graph_node.node_id} initialization failed") from None
        input_data = current if current is not None else context.dataset(role)
        try:
            raw_result = await node.execute(input_data=input_data)
        except Exception:
            logger.exception("Fold graph node execution failed for node_id=%s", graph_node.node_id)
            raise FoldGraphExecutionError(f"{graph_node.node_id} execution failed") from None
        try:
            result = NodeResult.wrap(raw_result)
        except Exception:
            logger.exception("Fold graph node returned a malformed result for node_id=%s", graph_node.node_id)
            raise FoldGraphExecutionError(f"{graph_node.node_id} returned a malformed result") from None
        if set(result.outputs) != {"default"}:
            raise FoldGraphExecutionError(f"{graph_node.node_id} did not produce the required default output")
        output = result.outputs["default"]
        if not isinstance(output, SherpaDataset):
            raise FoldGraphExecutionError(f"{graph_node.node_id} did not produce a local SherpaDataset")
        if output.X.shape[0] != input_data.X.shape[0]:
            raise FoldGraphExecutionError(f"{graph_node.node_id} violated its preserves-samples contract")
        current = output
        executed_ids.append(graph_node.node_id)

    assert current is not None  # graph.nodes is checked above; preserve narrowed type for callers.
    return FoldGraphExecution(
        graph.digest,
        capability.content_digest,
        capability.envelope_digest,
        partition.digest,
        role,
        current,
        tuple(executed_ids),
    )


def _validate_output(*, graph_node_id: str, output: object, input_data: SherpaDataset) -> SherpaDataset:
    """Bound one node's local output without exposing raw exception details."""

    try:
        result = NodeResult.wrap(output)
    except Exception:
        logger.exception("Fold graph node returned a malformed result for node_id=%s", graph_node_id)
        raise FoldGraphExecutionError(f"{graph_node_id} returned a malformed result") from None
    if set(result.outputs) != {"default"}:
        raise FoldGraphExecutionError(f"{graph_node_id} did not produce the required default output")
    dataset = result.outputs["default"]
    if not isinstance(dataset, SherpaDataset):
        raise FoldGraphExecutionError(f"{graph_node_id} did not produce a local SherpaDataset")
    if dataset.X.shape[0] != input_data.X.shape[0]:
        raise FoldGraphExecutionError(f"{graph_node_id} violated its preserves-samples contract")
    return dataset


def _validate_predictions(*, graph_node_id: str, output: object, input_data: SherpaDataset) -> np.ndarray:
    """Return a bounded numeric or categorical prediction matrix for one fold."""

    try:
        result = NodeResult.wrap(output)
    except Exception:
        logger.exception("Fold model returned a malformed result for node_id=%s", graph_node_id)
        raise FoldGraphExecutionError(f"{graph_node_id} returned a malformed result") from None
    if set(result.outputs) != {"default"}:
        raise FoldGraphExecutionError(f"{graph_node_id} did not produce the required default output")
    predictions = np.asarray(result.outputs["default"])
    if predictions.ndim == 1:
        predictions = predictions.reshape(-1, 1)
    if predictions.ndim != 2 or predictions.shape[0] != input_data.X.shape[0] or predictions.shape[1] < 1:
        raise FoldGraphExecutionError(f"{graph_node_id} did not produce a bounded prediction matrix")
    if np.issubdtype(predictions.dtype, np.number):
        if not np.isfinite(predictions.astype(np.float64, copy=False)).all():
            raise FoldGraphExecutionError(f"{graph_node_id} did not produce finite numeric predictions")
    elif any(
        value is None
        or isinstance(value, (list, tuple, dict, set, np.ndarray))
        or (isinstance(value, (float, np.floating)) and not np.isfinite(float(value)))
        for value in predictions.reshape(-1).tolist()
    ):
        raise FoldGraphExecutionError(f"{graph_node_id} did not produce bounded categorical predictions")
    result = np.array(predictions, copy=True)
    result.setflags(write=False)
    return result


def _classification_application(
    *,
    graph_node_id: str,
    output: object,
    input_data: SherpaDataset,
    fitted_state_digest: str,
) -> tuple[np.ndarray, np.ndarray, tuple[Any, ...], np.ndarray, str]:
    """Delegate one combined decision/response application without replay."""

    if not isinstance(output, tuple) or len(output) != 4:
        raise FoldGraphExecutionError(f"{graph_node_id} did not return combined classification output")
    raw_predictions, raw_responses, raw_classes, semantics = output
    try:
        record = validate_classification_application(
            predictions=raw_predictions,
            responses=raw_responses,
            classes=raw_classes,
            fitted_state_digest=fitted_state_digest,
            semantics=semantics,
        )
    except ClassificationApplicationError as exc:
        raise FoldGraphExecutionError(f"{graph_node_id} returned an invalid classification application") from exc
    if record.responses.shape[0] != input_data.X.shape[0]:
        raise FoldGraphExecutionError(f"{graph_node_id} returned the wrong classification sample count")
    return (
        record.predictions,
        record.responses,
        record.classes,
        record.margins,
        record.application_digest,
    )


async def _execute_stateless_node(
    context: FoldLifecycleContext, *, graph_node_id: str, parameters: dict[str, object], input_data: SherpaDataset
) -> SherpaDataset:
    """Run one fresh stateless node in a single role's private context."""

    try:
        node = context.fresh_node(graph_node_id, parameters)
        raw_output = await node.execute(input_data=input_data)
    except Exception:
        logger.exception("Fold graph node execution failed for node_id=%s", graph_node_id)
        raise FoldGraphExecutionError(f"{graph_node_id} execution failed") from None
    return _validate_output(graph_node_id=graph_node_id, output=raw_output, input_data=input_data)


async def execute_validation_fold(
    graph: ValidationGraph,
    capability: SpectralDatasetCapability,
    partition: FoldPartition,
) -> FoldPairGraphExecution:
    """Execute one admitted graph across train and held-out roles as one attempt.

    Stateless operations are rebuilt independently per role.  A fitted
    transform is fitted only with the current training data, records that
    local state under the exact graph/capability/partition authority, and
    applies precisely that record to current held-out data.  No method ever
    fits from held-out rows.
    """

    try:
        assert_admitted_validation_graph(graph)
    except ValidationGraphError as exc:
        raise FoldGraphExecutionError("validation graph is not an admitted execution identity") from exc

    attempt = FoldAttempt.create()
    train_current: SherpaDataset | None = None
    test_current: SherpaDataset | None = None
    executed_ids: list[str] = []
    for graph_node in graph.nodes:
        lifecycle = LifecycleKind(graph_node.contract.payload["lifecycle_kind"])
        train_context = FoldLifecycleContext(graph_node.contract, capability, partition, attempt=attempt)
        test_context = FoldLifecycleContext(graph_node.contract, capability, partition, attempt=attempt)
        train_input = train_current if train_current is not None else train_context.dataset("train")
        test_input = test_current if test_current is not None else test_context.dataset("test")
        parameters = dict(graph_node.parameters)
        if lifecycle is LifecycleKind.STATELESS_TRANSFORM:
            train_current = await _execute_stateless_node(
                train_context, graph_node_id=graph_node.node_id, parameters=parameters, input_data=train_input
            )
            test_current = await _execute_stateless_node(
                test_context, graph_node_id=graph_node.node_id, parameters=parameters, input_data=test_input
            )
        elif lifecycle is LifecycleKind.FITTED_TRANSFORM:
            try:
                train_node = train_context.fresh_node(graph_node.node_id, parameters)
                test_node = test_context.fresh_node(graph_node.node_id, parameters)
                fit = getattr(train_node, "fit_fitted_state", None)
                apply = getattr(test_node, "apply_fitted_state", None)
                if not callable(fit) or not callable(apply):
                    raise TypeError("fitted node does not expose the required local fit/apply methods")
                state = _fit_fold_transform_state(
                    train_node,
                    train_context,
                    train_input,
                    node_id=graph_node.node_id,
                )
                record = train_context.record_fitted_state(
                    state,
                    role="train",
                    graph=graph,
                    node_id=graph_node.node_id,
                    parameters=parameters,
                )
                record.assert_matches(test_context, graph=graph, node_id=graph_node.node_id, parameters=parameters)
                train_raw = train_node.apply_fitted_state(train_input, record.state)
                test_raw = test_node.apply_fitted_state(test_input, record.state)
            except Exception:
                logger.exception("Fold graph fitted node execution failed for node_id=%s", graph_node.node_id)
                raise FoldGraphExecutionError(f"{graph_node.node_id} fitted execution failed") from None
            train_current = _validate_output(graph_node_id=graph_node.node_id, output=train_raw, input_data=train_input)
            test_current = _validate_output(graph_node_id=graph_node.node_id, output=test_raw, input_data=test_input)
        else:
            raise FoldGraphExecutionError(f"{graph_node.node_id} has an unsupported lifecycle for this executor")
        executed_ids.append(graph_node.node_id)

    assert train_current is not None and test_current is not None
    return FoldPairGraphExecution(
        graph.digest,
        capability.content_digest,
        capability.envelope_digest,
        partition.digest,
        train_current,
        test_current,
        tuple(executed_ids),
    )


async def execute_supervised_validation_fold(
    graph: ValidationGraph,
    capability: SpectralDatasetCapability,
    partition: FoldPartition,
) -> SupervisedFoldGraphExecution:
    """Run one canonical transform-to-model graph without scoring it.

    The terminal fitted model is the first target-consuming lifecycle role.
    It obtains targets *only* through its training context.  The held-out
    context applies the bound state to held-out spectra, but this function
    never reads a held-out target.  Keeping prediction and scoring separate
    prevents a model node from silently becoming its own evaluator.
    """

    try:
        assert_admitted_validation_graph(graph)
    except ValidationGraphError as exc:
        raise FoldGraphExecutionError("validation graph is not an admitted execution identity") from exc

    attempt = FoldAttempt.create()
    train_current: SherpaDataset | None = None
    test_current: SherpaDataset | None = None
    executed_ids: list[str] = []
    model_result: SupervisedFoldGraphExecution | None = None
    for index, graph_node in enumerate(graph.nodes):
        lifecycle = LifecycleKind(graph_node.contract.payload["lifecycle_kind"])
        train_context = FoldLifecycleContext(graph_node.contract, capability, partition, attempt=attempt)
        test_context = FoldLifecycleContext(graph_node.contract, capability, partition, attempt=attempt)
        train_input = train_current if train_current is not None else train_context.dataset("train")
        test_input = test_current if test_current is not None else test_context.dataset("test")
        parameters = dict(graph_node.parameters)
        if lifecycle is LifecycleKind.STATELESS_TRANSFORM:
            if model_result is not None:
                raise FoldGraphExecutionError("a transform may not follow a supervised terminal model")
            train_current = await _execute_stateless_node(
                train_context, graph_node_id=graph_node.node_id, parameters=parameters, input_data=train_input
            )
            test_current = await _execute_stateless_node(
                test_context, graph_node_id=graph_node.node_id, parameters=parameters, input_data=test_input
            )
        elif lifecycle is LifecycleKind.FITTED_TRANSFORM:
            if model_result is not None:
                raise FoldGraphExecutionError("a transform may not follow a supervised terminal model")
            try:
                train_node = train_context.fresh_node(graph_node.node_id, parameters)
                test_node = test_context.fresh_node(graph_node.node_id, parameters)
                fit = getattr(train_node, "fit_fitted_state", None)
                apply = getattr(test_node, "apply_fitted_state", None)
                if not callable(fit) or not callable(apply):
                    raise TypeError("fitted node does not expose the required local fit/apply methods")
                state = _fit_fold_transform_state(
                    train_node,
                    train_context,
                    train_input,
                    node_id=graph_node.node_id,
                )
                record = train_context.record_fitted_state(
                    state,
                    role="train",
                    graph=graph,
                    node_id=graph_node.node_id,
                    parameters=parameters,
                )
                record.assert_matches(test_context, graph=graph, node_id=graph_node.node_id, parameters=parameters)
                train_raw = train_node.apply_fitted_state(train_input, record.state)
                test_raw = test_node.apply_fitted_state(test_input, record.state)
            except Exception:
                logger.exception("Fold graph fitted transform execution failed for node_id=%s", graph_node.node_id)
                raise FoldGraphExecutionError(f"{graph_node.node_id} fitted execution failed") from None
            train_current = _validate_output(graph_node_id=graph_node.node_id, output=train_raw, input_data=train_input)
            test_current = _validate_output(graph_node_id=graph_node.node_id, output=test_raw, input_data=test_input)
        elif lifecycle is LifecycleKind.FITTED_MODEL:
            if index != len(graph.nodes) - 1 or model_result is not None:
                raise FoldGraphExecutionError("a supervised fitted model must be the terminal graph node")
            try:
                train_node = train_context.fresh_node(graph_node.node_id, parameters)
                test_node = test_context.fresh_node(graph_node.node_id, parameters)
                fit = getattr(train_node, "fit_fitted_state", None)
                apply_name = (
                    "predict_fitted_labels"
                    if graph_node.contract.payload["supervised_task"] == "classification"
                    else "apply_fitted_state"
                )
                apply = getattr(test_node, apply_name, None)
                if not callable(fit) or not callable(apply):
                    raise TypeError("fitted model does not expose the required local fit/apply methods")
                # This is the only model target read.  ``test_context.target``
                # is deliberately never called in this prediction-only layer.
                state = fit(
                    train_input,
                    (
                        train_context.target_dataset("train")
                        if graph_node.operation_id == "model.fitted_pls"
                        else _require_target(
                            train_context.target("train"),
                            node_id=graph_node.node_id,
                            role="training",
                        )
                    ),
                )
                record = train_context.record_fitted_state(
                    state,
                    role="train",
                    graph=graph,
                    node_id=graph_node.node_id,
                    parameters=parameters,
                )
                record.assert_matches(test_context, graph=graph, node_id=graph_node.node_id, parameters=parameters)
                train_predictions = _validate_predictions(
                    graph_node_id=graph_node.node_id,
                    output=getattr(train_node, apply_name)(train_input, record.state),
                    input_data=train_input,
                )
                test_predictions = _validate_predictions(
                    graph_node_id=graph_node.node_id,
                    output=apply(test_input, record.state),
                    input_data=test_input,
                )
            except FoldGraphExecutionError:
                raise
            except Exception:
                logger.exception("Fold graph fitted model execution failed for node_id=%s", graph_node.node_id)
                raise FoldGraphExecutionError(f"{graph_node.node_id} fitted model execution failed") from None
            model_result = SupervisedFoldGraphExecution(
                graph.digest,
                capability.content_digest,
                capability.envelope_digest,
                partition.digest,
                train_predictions,
                test_predictions,
                record.digest,
                tuple([*executed_ids, graph_node.node_id]),
            )
        else:
            raise FoldGraphExecutionError(f"{graph_node.node_id} has an unsupported lifecycle for this executor")
        executed_ids.append(graph_node.node_id)

    if model_result is None:
        raise FoldGraphExecutionError("supervised validation graph requires one terminal fitted model")
    return model_result


async def execute_scored_supervised_validation_fold(
    graph: ValidationGraph,
    capability: SpectralDatasetCapability,
    partition: FoldPartition,
    *,
    _metric_accumulator: MetricAccumulator | None = None,
    _private_classification_trace: list[PrivateClassificationFoldTrace] | None = None,
) -> ScoredSupervisedFoldGraphExecution:
    """Execute one transform → fitted-model → evaluator validation graph.

    The model receives only training targets.  The terminal evaluator is the
    one and only component allowed to request held-out truth, score it through
    the versioned SDK registry, and emit the bounded metric record.  No raw
    predictions or targets cross this method's return boundary.
    """

    try:
        assert_admitted_validation_graph(graph)
    except ValidationGraphError as exc:
        raise FoldGraphExecutionError("validation graph is not an admitted execution identity") from exc

    attempt = FoldAttempt.create()
    train_current: SherpaDataset | None = None
    test_current: SherpaDataset | None = None
    executed_ids: list[str] = []
    model_node_id: str | None = None
    fitted_state_digest: str | None = None
    fitted_state_record: FittedStateRecord | None = None
    test_predictions: np.ndarray | None = None
    class_responses: np.ndarray | None = None
    class_labels: tuple[Any, ...] | None = None
    decision_margins: np.ndarray | None = None
    prediction_application_digest: str | None = None
    simca_membership: np.ndarray | None = None
    simca_labels: tuple[str, ...] | None = None
    execution_traces: list[NodeExecutionTrace] = []

    for index, graph_node in enumerate(graph.nodes):
        lifecycle = LifecycleKind(graph_node.contract.payload["lifecycle_kind"])
        train_context = FoldLifecycleContext(graph_node.contract, capability, partition, attempt=attempt)
        test_context = FoldLifecycleContext(graph_node.contract, capability, partition, attempt=attempt)
        parameters = dict(graph_node.parameters)
        if lifecycle is LifecycleKind.STATELESS_TRANSFORM:
            if model_node_id is not None:
                raise FoldGraphExecutionError("a transform may not follow a supervised fitted model")
            train_input = train_current if train_current is not None else train_context.dataset("train")
            test_input = test_current if test_current is not None else test_context.dataset("test")
            train_current = await _execute_stateless_node(
                train_context, graph_node_id=graph_node.node_id, parameters=parameters, input_data=train_input
            )
            test_current = await _execute_stateless_node(
                test_context, graph_node_id=graph_node.node_id, parameters=parameters, input_data=test_input
            )
            execution_traces.append(
                _node_trace(
                    graph_node,
                    capability,
                    partition,
                    parameters=parameters,
                    role_envelopes=(
                        ("train", _shape(train_input.X), _shape(train_current.X)),
                        ("test", _shape(test_input.X), _shape(test_current.X)),
                    ),
                    seed=train_context.seed,
                )
            )
        elif lifecycle is LifecycleKind.FITTED_TRANSFORM:
            if model_node_id is not None:
                raise FoldGraphExecutionError("a transform may not follow a supervised fitted model")
            train_input = train_current if train_current is not None else train_context.dataset("train")
            test_input = test_current if test_current is not None else test_context.dataset("test")
            try:
                train_node = train_context.fresh_node(graph_node.node_id, parameters)
                test_node = test_context.fresh_node(graph_node.node_id, parameters)
                fit = getattr(train_node, "fit_fitted_state", None)
                apply = getattr(test_node, "apply_fitted_state", None)
                if not callable(fit) or not callable(apply):
                    raise TypeError("fitted node does not expose the required local fit/apply methods")
                state = _fit_fold_transform_state(
                    train_node,
                    train_context,
                    train_input,
                    node_id=graph_node.node_id,
                )
                record = train_context.record_fitted_state(
                    state, role="train", graph=graph, node_id=graph_node.node_id, parameters=parameters
                )
                fitted_state_record = record
                record.assert_matches(test_context, graph=graph, node_id=graph_node.node_id, parameters=parameters)
                train_raw = train_node.apply_fitted_state(train_input, record.state)
                test_raw = test_node.apply_fitted_state(test_input, record.state)
            except Exception:
                logger.exception("Fold graph fitted transform execution failed for node_id=%s", graph_node.node_id)
                raise FoldGraphExecutionError(f"{graph_node.node_id} fitted execution failed") from None
            train_current = _validate_output(graph_node_id=graph_node.node_id, output=train_raw, input_data=train_input)
            test_current = _validate_output(graph_node_id=graph_node.node_id, output=test_raw, input_data=test_input)
            execution_traces.append(
                _node_trace(
                    graph_node,
                    capability,
                    partition,
                    parameters=parameters,
                    role_envelopes=(
                        ("train", _shape(train_input.X), _shape(train_current.X)),
                        ("test", _shape(test_input.X), _shape(test_current.X)),
                    ),
                    seed=train_context.seed,
                    fitted_state_digest=record.digest,
                )
            )
        elif lifecycle is LifecycleKind.FITTED_MODEL:
            if model_node_id is not None or index != len(graph.nodes) - 2:
                raise FoldGraphExecutionError(
                    "a supervised fitted model must immediately precede the terminal evaluator"
                )
            train_input = train_current if train_current is not None else train_context.dataset("train")
            test_input = test_current if test_current is not None else test_context.dataset("test")
            try:
                train_node = train_context.fresh_node(graph_node.node_id, parameters)
                test_node = test_context.fresh_node(graph_node.node_id, parameters)
                fit = getattr(train_node, "fit_fitted_state", None)
                classification_task = graph_node.contract.payload["supervised_task"] == "classification"
                combined_classification = classification_task and callable(
                    getattr(test_node, "predict_fitted_classification", None)
                )
                if classification_task and _private_classification_trace is not None and not combined_classification:
                    raise TypeError("private classification trace requires combined decision/response application")
                prediction_method = (
                    "predict_fitted_classification"
                    if combined_classification
                    else ("predict_fitted_labels" if classification_task else "apply_fitted_state")
                )
                apply = getattr(test_node, prediction_method, None)
                if not callable(fit) or not callable(apply):
                    raise TypeError("fitted model does not expose the required local fit/apply methods")
                state = fit(
                    train_input,
                    (
                        train_context.target_dataset("train")
                        if graph_node.operation_id == "model.fitted_pls"
                        else _require_target(
                            train_context.target("train"),
                            node_id=graph_node.node_id,
                            role="training",
                        )
                    ),
                )
                record = train_context.record_fitted_state(
                    state, role="train", graph=graph, node_id=graph_node.node_id, parameters=parameters
                )
                fitted_state_record = record
                record.assert_matches(test_context, graph=graph, node_id=graph_node.node_id, parameters=parameters)
                # Test targets are deliberately absent from the model branch.
                # Classification decisions and responses are obtained through
                # one combined application; neither public metrics nor the
                # private trace is allowed to replay the fitted model.
                applied = apply(test_input, record.state)
                if combined_classification:
                    (
                        test_predictions,
                        class_responses,
                        class_labels,
                        decision_margins,
                        prediction_application_digest,
                    ) = _classification_application(
                        graph_node_id=graph_node.node_id,
                        output=applied,
                        input_data=test_input,
                        fitted_state_digest=record.digest,
                    )
                else:
                    test_predictions = _validate_predictions(
                        graph_node_id=graph_node.node_id,
                        output=applied,
                        input_data=test_input,
                    )
                if graph_node.operation_id == "classification.simca":
                    from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import (
                        simca_acceptance_membership,
                    )

                    simca_labels, simca_membership = simca_acceptance_membership(test_input, record.state)
            except FoldGraphExecutionError:
                raise
            except Exception:
                logger.exception("Fold graph fitted model execution failed for node_id=%s", graph_node.node_id)
                raise FoldGraphExecutionError(f"{graph_node.node_id} fitted model execution failed") from None
            model_node_id = graph_node.node_id
            fitted_state_digest = record.digest
            execution_traces.append(
                _node_trace(
                    graph_node,
                    capability,
                    partition,
                    parameters=parameters,
                    role_envelopes=(("test", _shape(test_input.X), _shape(test_predictions)),),
                    seed=train_context.seed,
                    fitted_state_digest=record.digest,
                )
            )
        elif lifecycle is LifecycleKind.EVALUATOR:
            if index != len(graph.nodes) - 1 or model_node_id is None or test_predictions is None:
                raise FoldGraphExecutionError("a supervised evaluator must be the terminal node after one fitted model")
            try:
                evaluator = test_context.fresh_node(graph_node.node_id, parameters)
                score = getattr(evaluator, "score_held_out_predictions", None)
                if not callable(score):
                    raise TypeError("evaluator does not expose the required held-out scoring method")
                # This is the sole held-out target read in the scored graph.
                held_out_target = _require_target(
                    test_context.target("test"),
                    node_id=graph_node.node_id,
                    role="held-out evaluation",
                )
                score_kwargs: dict[str, object] = {"accumulator": _metric_accumulator}
                if graph_node.contract.payload["supervised_task"] == "classification":
                    score_kwargs.update(
                        simca_membership=simca_membership,
                        simca_labels=simca_labels,
                    )
                metric_record = score(test_predictions, held_out_target, **score_kwargs)
                expected_metric_type = (
                    ClassificationMetricSet
                    if graph_node.contract.payload["supervised_task"] == "classification"
                    else RegressionMetrics
                )
                if not isinstance(metric_record, expected_metric_type):
                    raise TypeError("evaluator did not return the versioned supervised metric record")
            except Exception:
                logger.exception("Fold graph evaluator execution failed for node_id=%s", graph_node.node_id)
                raise FoldGraphExecutionError(f"{graph_node.node_id} evaluator execution failed") from None
            executed_ids.append(graph_node.node_id)
            assert fitted_state_digest is not None
            if _private_classification_trace is not None:
                if not isinstance(metric_record, ClassificationMetricSet) or any(
                    value is None
                    for value in (
                        class_responses,
                        class_labels,
                        decision_margins,
                        prediction_application_digest,
                    )
                ):
                    raise FoldGraphExecutionError("private classification trace requires combined model responses")
                truth = np.asarray(held_out_target, dtype=object).reshape(-1)
                if truth.shape != test_predictions.reshape(-1).shape:
                    raise FoldGraphExecutionError("private classification trace target alignment failed")
                if fitted_state_record is None:
                    raise FoldGraphExecutionError("private classification trace has no fitted-state custody")
                _private_classification_trace.append(
                    PrivateClassificationFoldTrace._bound(
                        partition_digest=partition.digest,
                        fitted_state=fitted_state_record,
                        application_digest=str(prediction_application_digest),
                        test_indices=tuple(int(value) for value in partition.test_indices),
                        truth=tuple(truth.tolist()),
                        predictions=tuple(test_predictions.reshape(-1).tolist()),
                        class_labels=tuple(class_labels or ()),
                        class_responses=class_responses,
                        decision_margins=decision_margins,
                    )
                )
            execution_traces.append(
                _node_trace(
                    graph_node,
                    capability,
                    partition,
                    parameters=parameters,
                    role_envelopes=(("test", _shape(test_predictions), ()),),
                    seed=test_context.seed,
                )
            )
            return ScoredSupervisedFoldGraphExecution(
                graph.digest,
                capability.content_digest,
                capability.envelope_digest,
                partition.digest,
                fitted_state_digest,
                metric_record,
                model_node_id,
                graph_node.node_id,
                tuple(executed_ids),
                tuple(execution_traces),
                prediction_application_digest,
            )
        else:
            raise FoldGraphExecutionError(f"{graph_node.node_id} has an unsupported lifecycle for this executor")
        executed_ids.append(graph_node.node_id)

    raise FoldGraphExecutionError("supervised validation graph requires one terminal evaluator")


async def _execute_candidate_validation(
    graph: ValidationGraph,
    capability: SpectralDatasetCapability,
    split_plan: SplitPlan,
    *,
    private_classification_trace: list[PrivateClassificationFoldTrace] | None,
) -> CandidateValidationExecution:
    """Run one graph freshly across each locked outer fold and pool its score.

    The plan is validated against the admitted capability before any node is
    created.  Each fold gets a fresh attempt and fitted state through the
    one-fold authority.  Only its evaluator may read held-out targets; this
    function retains the mergeable metric accumulator inside its execution
    boundary and returns only bounded fold records plus pooled metrics.  Raw
    held-out targets and predictions never cross its public return boundary.
    """

    try:
        assert_admitted_validation_graph(graph)
    except ValidationGraphError as exc:
        raise FoldGraphExecutionError("validation graph is not an admitted execution identity") from exc
    sample_count = capability.arrays["X"].shape[0]
    if split_plan.n_samples != sample_count:
        raise FoldGraphExecutionError("split plan sample count does not match the admitted capability")
    groups = capability.arrays.get("groups")
    if split_plan.grouped and groups is None:
        raise FoldGraphExecutionError("grouped split plan requires groups in the admitted capability")
    try:
        split_plan.validate(groups if split_plan.grouped else None)
    except ValueError as exc:
        raise FoldGraphExecutionError("split plan is not a valid outer-fold execution identity") from exc

    fold_results: list[ScoredSupervisedFoldGraphExecution] = []
    evaluator_operation = graph.nodes[-1].operation_id
    if evaluator_operation == "diagnostics.classification_evaluator":
        target = capability.arrays.get("target")
        if target is None:
            raise FoldGraphExecutionError("classification validation requires an admitted target")
        simca_validation = any(node.operation_id == "classification.simca" for node in graph.nodes)
        if simca_validation and any(
            value == CLASSIFICATION_REJECT_LABEL for value in np.asarray(target).reshape(-1).tolist()
        ):
            raise FoldGraphExecutionError(
                f"SIMCA target class label {CLASSIFICATION_REJECT_LABEL!r} is reserved for rejected samples; "
                "rename the modeled class before execution"
            )
        try:
            validate_classification_split_plan(
                split_plan,
                np.asarray(target).reshape(-1),
                groups=groups if split_plan.grouped else None,
            )
        except ValueError as exc:
            raise FoldGraphExecutionError("classification validation requires a stratified outer-fold plan") from exc
        metric_labels = (
            np.unique(np.asarray(target).reshape(-1)).tolist()
            if simca_validation
            else np.asarray(target).reshape(-1).tolist()
        )
        if simca_validation:
            metric_labels.append(CLASSIFICATION_REJECT_LABEL)
        accumulator: MetricAccumulator = ClassificationMetricAccumulator(metric_labels)
    elif evaluator_operation == "diagnostics.regression_evaluator":
        accumulator = RegressionMetricAccumulator()
    else:
        raise FoldGraphExecutionError("validation graph has no admitted supervised evaluator")
    for fold in split_plan.folds:
        partition = FoldPartition.create(fold.train, fold.test, sample_count=sample_count)
        fold_results.append(
            await execute_scored_supervised_validation_fold(
                graph,
                capability,
                partition,
                _metric_accumulator=accumulator,
                _private_classification_trace=private_classification_trace,
            )
        )
    try:
        pooled_metrics = accumulator.metrics()
    except ValueError as exc:
        raise FoldGraphExecutionError("held-out fold metrics could not be pooled") from exc
    model_operations = [
        node.operation_id
        for node in graph.nodes
        if LifecycleKind(node.contract.payload["lifecycle_kind"]) is LifecycleKind.FITTED_MODEL
    ]
    if len(model_operations) != 1:
        raise FoldGraphExecutionError("candidate validation requires one exact fitted-model operation")
    task_type = "classification" if isinstance(pooled_metrics, ClassificationMetricSet) else "regression"
    return CandidateValidationExecution._bound(
        graph_digest=graph.digest,
        capability_content_digest=capability.content_digest,
        capability_envelope_digest=capability.envelope_digest,
        split_plan=split_plan,
        task_type=task_type,
        model_operation_id=model_operations[0],
        metrics=pooled_metrics,
        folds=tuple(fold_results),
    )


async def execute_candidate_validation(
    graph: ValidationGraph,
    capability: SpectralDatasetCapability,
    split_plan: SplitPlan,
) -> CandidateValidationExecution:
    """Return the ordinary bounded, row-free candidate validation result."""

    return await _execute_candidate_validation(
        graph,
        capability,
        split_plan,
        private_classification_trace=None,
    )


async def execute_candidate_validation_with_private_classification_trace(
    graph: ValidationGraph,
    capability: SpectralDatasetCapability,
    split_plan: SplitPlan,
) -> tuple[CandidateValidationExecution, PrivateClassificationValidationTrace]:
    """Collect a bounded local trace from the same classification applications.

    The public validation record stays row-free.  This explicit local entry
    point exists for governed evidence collectors and never refits or reapplies
    the model after the ordinary metric execution.
    """

    if graph.nodes[-1].operation_id != "diagnostics.classification_evaluator":
        raise FoldGraphExecutionError("private classification trace requires a classification evaluator")
    target = capability.arrays.get("target")
    if target is None:
        raise FoldGraphExecutionError("private classification trace requires an admitted target")
    target_values = np.asarray(target).reshape(-1).tolist()
    class_count = len({(type(value).__name__, str(value)) for value in target_values})
    if len(target_values) * class_count > 20_000_000:
        raise FoldGraphExecutionError("private classification trace exceeds its response-cell limit")
    traces: list[PrivateClassificationFoldTrace] = []
    execution = await _execute_candidate_validation(
        graph,
        capability,
        split_plan,
        private_classification_trace=traces,
    )
    return execution, PrivateClassificationValidationTrace._bound(execution, tuple(traces))


def _assert_regression_metrics(metrics: RegressionMetrics, *, expected_samples: int, label: str) -> None:
    """Reject malformed or scientifically impossible bounded metric records."""

    if not isinstance(metrics, RegressionMetrics):
        raise FoldGraphExecutionError(f"{label} metrics are malformed")
    if metrics.registry_version != REGRESSION_METRIC_REGISTRY_VERSION or type(metrics.n_samples) is not int:
        raise FoldGraphExecutionError(f"{label} metrics do not use the admitted registry")
    if metrics.n_samples != expected_samples:
        raise FoldGraphExecutionError(f"{label} metrics do not cover the admitted samples")
    try:
        finite_scalars = all(np.isfinite(value) for value in (metrics.rmse, metrics.mae, metrics.bias))
        finite_optional = all(
            value is None or np.isfinite(value)
            for value in (metrics.r2, metrics.sep, metrics.slope, metrics.intercept, metrics.rer)
        )
    except TypeError as exc:
        raise FoldGraphExecutionError(f"{label} metrics are malformed") from exc
    if (
        not finite_scalars
        or not finite_optional
        or metrics.rmse < 0
        or metrics.mae < 0
        or (metrics.sep is not None and metrics.sep < 0)
        or (metrics.rer is not None and metrics.rer < 0)
    ):
        raise FoldGraphExecutionError(f"{label} metrics contain impossible regression values")


def _assert_classification_metrics(
    metrics: ClassificationMetricSet,
    *,
    expected_samples: int,
    label: str,
) -> None:
    """Reject malformed or scientifically impossible classification records."""

    if not isinstance(metrics, ClassificationMetricSet):
        raise FoldGraphExecutionError(f"{label} metrics are malformed")
    if (
        metrics.registry_version != CLASSIFICATION_METRIC_SET_REGISTRY_VERSION
        or type(metrics.n_samples) is not int
        or metrics.n_samples != expected_samples
        or len(metrics.labels) < 2
    ):
        raise FoldGraphExecutionError(f"{label} metrics do not use the admitted classification registry")
    matrix = np.asarray(metrics.confusion_matrix)
    scalars = (metrics.accuracy, metrics.balanced_accuracy, metrics.macro_f1, metrics.mcc)
    rates = (*metrics.class_sensitivities, *metrics.class_specificities)
    if (
        matrix.shape != (len(metrics.labels), len(metrics.labels))
        or not np.issubdtype(matrix.dtype, np.integer)
        or np.any(matrix < 0)
        or int(matrix.sum()) != expected_samples
        or not all(np.isfinite(value) for value in scalars)
        or not all(0.0 <= value <= 1.0 for value in scalars[:3])
        or not -1.0 <= metrics.mcc <= 1.0
        or len(metrics.class_sensitivities) != len(metrics.labels)
        or len(metrics.class_specificities) != len(metrics.labels)
        or any(value is not None and (not np.isfinite(value) or not 0.0 <= value <= 1.0) for value in rates)
    ):
        raise FoldGraphExecutionError(f"{label} metrics contain impossible classification values")
    try:
        validate_supervised_metric_record(metrics.as_dict())
    except ValueError as exc:
        raise FoldGraphExecutionError(f"{label} metrics do not reproduce from their bounded evidence") from exc


def _assert_supervised_metrics(metrics: SupervisedMetrics, *, expected_samples: int, label: str) -> None:
    if isinstance(metrics, RegressionMetrics):
        _assert_regression_metrics(metrics, expected_samples=expected_samples, label=label)
        if metrics.r2 is not None and metrics.r2 > 1.0 + METRIC_PARITY_ABSOLUTE_TOLERANCE:
            raise FoldGraphExecutionError(f"{label} metrics contain impossible regression values")
    elif isinstance(metrics, ClassificationMetricSet):
        _assert_classification_metrics(metrics, expected_samples=expected_samples, label=label)
    else:
        raise FoldGraphExecutionError(f"{label} metrics are malformed")


def _assert_selected_validation_execution(
    execution: CandidateValidationExecution,
    graph: ValidationGraph,
    capability: SpectralDatasetCapability,
) -> None:
    """Reject a refit unless it names this exact candidate and capability."""

    if not isinstance(execution, CandidateValidationExecution):
        raise FoldGraphExecutionError("full-data refit requires a candidate validation execution")
    if getattr(execution, "_validation_authority", None) is not _CANDIDATE_VALIDATION_AUTHORITY:
        raise FoldGraphExecutionError("full-data refit requires an executor-issued validation execution")
    if (
        execution.graph_digest != graph.digest
        or execution.capability_content_digest != capability.content_digest
        or execution.capability_envelope_digest != capability.envelope_digest
    ):
        raise FoldGraphExecutionError("selected validation execution does not match the refit graph and capability")
    sample_count = capability.arrays["X"].shape[0]
    if execution.split_plan.n_samples != sample_count:
        raise FoldGraphExecutionError("selected validation execution has an incompatible split plan")
    try:
        execution.split_plan.validate(capability.arrays.get("groups") if execution.split_plan.grouped else None)
    except ValueError as exc:
        raise FoldGraphExecutionError("selected validation execution has an invalid split plan") from exc
    expected_partitions = tuple(
        FoldPartition.create(fold.train, fold.test, sample_count=sample_count).digest
        for fold in execution.split_plan.folds
    )
    if len(execution.folds) != len(execution.split_plan.folds):
        raise FoldGraphExecutionError("selected validation execution does not cover every locked outer fold")
    if tuple(fold.partition_digest for fold in execution.folds) != expected_partitions:
        raise FoldGraphExecutionError("selected validation execution does not cover its locked outer folds")

    expected_node_ids = tuple(node.node_id for node in graph.nodes)
    model_node_ids = tuple(
        node.node_id
        for node in graph.nodes
        if node.contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    )
    evaluator_node_ids = tuple(
        node.node_id for node in graph.nodes if node.contract.payload["lifecycle_kind"] == LifecycleKind.EVALUATOR.value
    )
    if len(model_node_ids) != 1 or len(evaluator_node_ids) != 1:
        raise FoldGraphExecutionError("selected validation execution has an invalid model/evaluator path")
    requires_application_digest = any(node.operation_id == "classification.plsda" for node in graph.nodes)

    for fold_number, (fold, split_fold) in enumerate(zip(execution.folds, execution.split_plan.folds, strict=True)):
        if not isinstance(fold, ScoredSupervisedFoldGraphExecution):
            raise FoldGraphExecutionError("selected validation execution contains a malformed fold record")
        if (
            fold.graph_digest != graph.digest
            or fold.capability_content_digest != capability.content_digest
            or fold.capability_envelope_digest != capability.envelope_digest
            or fold.node_ids != expected_node_ids
            or fold.model_node_id != model_node_ids[0]
            or fold.evaluator_node_id != evaluator_node_ids[0]
        ):
            raise FoldGraphExecutionError("selected validation execution contains a mismatched fold record")
        _assert_supervised_metrics(
            fold.metrics,
            expected_samples=len(split_fold.test),
            label=f"outer fold {fold_number}",
        )
        if (
            isinstance(fold.metrics, ClassificationMetricSet)
            and requires_application_digest
            and (
                not isinstance(fold.prediction_application_digest, str)
                or len(fold.prediction_application_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in fold.prediction_application_digest)
            )
        ):
            raise FoldGraphExecutionError("selected classification validation lacks its application identity")

    _assert_supervised_metrics(execution.metrics, expected_samples=sample_count, label="pooled validation")
    if isinstance(execution.metrics, ClassificationMetricSet):
        accumulator = ClassificationMetricAccumulator(execution.metrics.labels)
        for fold in execution.folds:
            if not isinstance(fold.metrics, ClassificationMetricSet):
                raise FoldGraphExecutionError("selected validation execution mixes metric task types")
            try:
                accumulator.merge(fold.metrics)
            except ValueError as exc:
                raise FoldGraphExecutionError("selected validation classification folds cannot be pooled") from exc
        if accumulator.metrics() != execution.metrics:
            raise FoldGraphExecutionError("selected validation pooled classification metrics do not match its folds")
        _ = execution.digest
        return
    fold_counts = np.asarray([fold.metrics.n_samples for fold in execution.folds], dtype=float)
    total_count = float(np.sum(fold_counts))
    pooled_rmse = float(
        np.sqrt(
            np.sum(fold_counts * np.asarray([fold.metrics.rmse**2 for fold in execution.folds], dtype=float))
            / total_count
        )
    )
    pooled_mae = float(
        np.sum(fold_counts * np.asarray([fold.metrics.mae for fold in execution.folds], dtype=float)) / total_count
    )
    pooled_bias = float(
        np.sum(fold_counts * np.asarray([fold.metrics.bias for fold in execution.folds], dtype=float)) / total_count
    )
    for observed, expected in (
        (execution.metrics.rmse, pooled_rmse),
        (execution.metrics.mae, pooled_mae),
        (execution.metrics.bias, pooled_bias),
    ):
        if not np.isclose(
            observed,
            expected,
            rtol=METRIC_PARITY_RELATIVE_TOLERANCE,
            atol=METRIC_PARITY_ABSOLUTE_TOLERANCE,
        ):
            raise FoldGraphExecutionError("selected validation execution pooled metrics do not match its folds")
    # Compute the bound identity before any node receives all samples.
    _ = execution.digest


async def execute_selected_candidate_full_refit(
    graph: ValidationGraph,
    capability: SpectralDatasetCapability,
    selected_validation: CandidateValidationExecution,
) -> FullDataRefitExecution:
    """Fit the selected graph once on all local data, separate from validation.

    The supplied graph is the scored development graph and therefore ends in
    an evaluator.  The evaluator is deliberately not run: its held-out-target
    semantics do not exist in a full-data refit.  Each preceding fitted node
    receives a fresh full-refit context, and the resulting local state is
    bound to both the graph and the selected validation execution.
    """

    try:
        assert_admitted_validation_graph(graph)
    except ValidationGraphError as exc:
        raise FoldGraphExecutionError(f"full-data refit requires an admitted validation graph: {exc}") from exc
    _assert_selected_validation_execution(selected_validation, graph, capability)
    return await execute_authorized_full_data_refit(
        graph,
        capability,
        validation_execution_digest=selected_validation.digest,
    )


async def execute_authorized_full_data_refit(
    graph: ValidationGraph,
    capability: SpectralDatasetCapability,
    *,
    validation_execution_digest: str,
) -> FullDataRefitExecution:
    """Fit one selected graph after an external authority verifies validation.

    Unlike :func:`execute_selected_candidate_full_refit`, this entry point
    does not accept an in-memory validation execution. It is for a durable
    managed authority that has already checked the selected terminal and now
    supplies only its immutable digest across a process boundary.  This
    operation deliberately fits all development data without calculating any
    folds, predictions, or validation metrics.
    """

    if not isinstance(validation_execution_digest, str) or len(validation_execution_digest) != 64:
        raise FoldGraphExecutionError("full-data refit requires a validation execution digest")
    if any(character not in "0123456789abcdef" for character in validation_execution_digest):
        raise FoldGraphExecutionError("full-data refit requires a validation execution digest")
    try:
        assert_admitted_validation_graph(graph)
    except ValidationGraphError as exc:
        raise FoldGraphExecutionError(f"full-data refit requires an admitted validation graph: {exc}") from exc
    if len(graph.nodes) < 2 or graph.nodes[-1].contract.payload["lifecycle_kind"] != LifecycleKind.EVALUATOR.value:
        raise FoldGraphExecutionError("full-data refit requires a graph with one terminal evaluator")

    current: SherpaDataset | None = None
    records: list[FullDataFittedStateRecord] = []
    executed_ids: list[str] = []
    model_node_id: str | None = None
    for graph_node in graph.nodes[:-1]:
        lifecycle = LifecycleKind(graph_node.contract.payload["lifecycle_kind"])
        context = FullDataRefitContext(
            graph_node.contract,
            capability,
            validation_execution_digest=validation_execution_digest,
        )
        parameters = dict(graph_node.parameters)
        input_data = current if current is not None else context.dataset()
        try:
            node = context.fresh_node(graph_node.node_id, parameters)
            if lifecycle is LifecycleKind.STATELESS_TRANSFORM:
                raw = await node.execute(input_data=input_data)
                current = _validate_output(graph_node_id=graph_node.node_id, output=raw, input_data=input_data)
            elif lifecycle is LifecycleKind.FITTED_TRANSFORM:
                fit = getattr(node, "fit_fitted_state", None)
                apply = getattr(node, "apply_fitted_state", None)
                if not callable(fit) or not callable(apply):
                    raise TypeError("fitted node does not expose local fit/apply methods")
                state = _fit_full_transform_state(
                    node,
                    context,
                    input_data,
                    node_id=graph_node.node_id,
                )
                record = context.record_fitted_state(
                    state, graph=graph, node_id=graph_node.node_id, parameters=parameters
                )
                current = _validate_output(
                    graph_node_id=graph_node.node_id, output=apply(input_data, record.state), input_data=input_data
                )
                records.append(record)
            elif lifecycle is LifecycleKind.FITTED_MODEL:
                if model_node_id is not None:
                    raise FoldGraphExecutionError("full-data refit permits one terminal fitted model")
                fit = getattr(node, "fit_fitted_state", None)
                if not callable(fit):
                    raise TypeError("fitted model does not expose a local fit method")
                state = fit(
                    input_data,
                    (
                        context.target_dataset()
                        if graph_node.operation_id == "model.fitted_pls"
                        else _require_target(
                            context.target(),
                            node_id=graph_node.node_id,
                            role="full-data refit",
                        )
                    ),
                )
                record = context.record_fitted_state(
                    state, graph=graph, node_id=graph_node.node_id, parameters=parameters
                )
                records.append(record)
                model_node_id = graph_node.node_id
            else:
                raise FoldGraphExecutionError(
                    "full-data refit does not execute evaluator or unsupported lifecycle nodes"
                )
        except FoldGraphExecutionError:
            raise
        except Exception:
            logger.exception("Full-data refit failed for node_id=%s", graph_node.node_id)
            raise FoldGraphExecutionError(f"{graph_node.node_id} full-data refit failed") from None
        executed_ids.append(graph_node.node_id)

    if model_node_id is None:
        raise FoldGraphExecutionError("full-data refit requires one fitted model before the evaluator")
    return FullDataRefitExecution._bound(
        validation_execution_digest=validation_execution_digest,
        graph_digest=graph.digest,
        capability_content_digest=capability.content_digest,
        capability_envelope_digest=capability.envelope_digest,
        model_node_id=model_node_id,
        fitted_states=tuple(records),
        node_ids=tuple(executed_ids),
    )


__all__ = [
    "FoldGraphExecution",
    "FoldGraphExecutionError",
    "FoldPairGraphExecution",
    "CandidateValidationExecution",
    "FullDataRefitExecution",
    "PrivateClassificationFoldTrace",
    "PrivateClassificationValidationTrace",
    "ScoredSupervisedFoldGraphExecution",
    "SupervisedFoldGraphExecution",
    "execute_fold_graph",
    "execute_candidate_validation",
    "execute_candidate_validation_with_private_classification_trace",
    "execute_authorized_full_data_refit",
    "execute_selected_candidate_full_refit",
    "execute_supervised_validation_fold",
    "execute_scored_supervised_validation_fold",
    "execute_validation_fold",
]
