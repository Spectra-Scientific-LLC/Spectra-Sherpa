"""Leakage-safe authority for one canonical-DAG validation fold.

This module is intentionally independent of a particular estimator or
cross-validation library.  A future DAG-aware validation executor supplies a
partition and obtains data only through this object; node contracts decide
whether targets and groups are visible and whether a deterministic seed is
required.  The context never hands a node a mutable view into a spectral
capability and always constructs a fresh node instance for a fold attempt.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
from dataclasses import dataclass
from typing import Any, Literal, Mapping

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.node_base import Node, node_registry
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.execution_contract_vocabulary import (
    GroupAccess,
    ManagedOptimizationEligibility,
    NodeExecutionContract,
    TargetAccess,
)

FoldRole = Literal["train", "test"]
_FITTED_STATE_SCHEMA_VERSION = "spectra-fitted-state/1"


class FoldLifecycleError(PermissionError):
    """A candidate attempted an undeclared or scientifically unsafe action."""


def _sample_identity_axis(capability: SpectralDatasetCapability, indices: np.ndarray) -> SampleAxis | None:
    """Copy row identity only; never disclose class/group or sample-table targets."""
    metadata = capability.metadata.get("axes", {}).get("sample", {})
    labels = metadata.get("labels")
    if labels is not None:
        return SampleAxis(labels=[labels[int(i)] for i in indices])
    values = capability.arrays.get("axis.sample.values")
    return SampleAxis(values=np.array(values[indices], copy=True)) if values is not None else None


def _response_dataset(
    capability: SpectralDatasetCapability, target: np.ndarray | None, indices: np.ndarray
) -> SherpaDataset | None:
    if target is None:
        return None
    values = np.asarray(target)
    if values.ndim == 1:
        values = values[:, None]
    context = TargetContext.model_validate(dict(capability.metadata["target_context"]))
    if context.selected_target and context.target_names:
        if values.shape[1] != 1 or context.selected_target not in context.target_names:
            raise FoldLifecycleError("materialize the selected response before fitting a canonical model")
        context = context.model_copy(update={"target_names": [context.selected_target]})
    if context.target_names and len(context.target_names) != values.shape[1]:
        raise FoldLifecycleError("response names do not match authorized target columns")
    return SherpaDataset(
        X=np.array(values, copy=True),
        sample_axis=_sample_identity_axis(capability, indices),
        target_context=context,
    )


@dataclass(frozen=True, init=False)
class FoldAttempt:
    """One private execution attempt shared by train/apply phases of a fold.

    The identifier is never evidence material.  It prevents an equivalent
    retry from silently reusing state fitted during an earlier attempt, while
    allowing the train and held-out apply contexts in one attempt to share the
    deliberately created state record.
    """

    _identifier: str

    @classmethod
    def create(cls) -> "FoldAttempt":
        attempt = object.__new__(cls)
        object.__setattr__(attempt, "_identifier", secrets.token_hex(16))
        return attempt


def _canonical_json_value(value: Any) -> Any:
    """Normalize only finite JSON values without coercing Python mapping keys."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FoldLifecycleError("fitted state must be JSON-only and finite")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise FoldLifecycleError("fitted state must use JSON object keys that are strings")
        return {key: _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    raise FoldLifecycleError("fitted state must be JSON-only and finite")


def _canonical_state_json(state: Mapping[str, Any]) -> str:
    """Return closed JSON-object state; never coerce arbitrary Python keys."""

    if not isinstance(state, Mapping):
        raise FoldLifecycleError("fitted state must use a JSON object with string keys")
    try:
        encoded = json.dumps(
            _canonical_json_value(state), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise FoldLifecycleError("fitted state must be JSON-only and finite") from exc
    if not isinstance(decoded, Mapping):  # Defensive: json object state is the only admitted form.
        raise FoldLifecycleError("fitted state must use a JSON object")
    return encoded


def _admitted_graph_digest(graph: Any) -> str:
    """Derive graph identity from the graph authority, never caller text."""

    # Delayed import avoids making the graph-admission module depend on this
    # lifecycle module at import time.
    from spectra_sherpa.app.services.dag.validation_graph import ValidationGraphError, assert_admitted_validation_graph

    try:
        assert_admitted_validation_graph(graph)
        return graph.digest
    except ValidationGraphError as exc:
        raise FoldLifecycleError(f"fitted state requires an admitted validation graph: {exc}") from exc


@dataclass(frozen=True, init=False)
class FittedStateRecord:
    """Local-only, JSON-only fitted state bound to one training authority.

    This record is intentionally not an evidence or export payload.  Fitted
    parameters such as a training mean can themselves disclose information,
    so later evidence layers refer to its digest rather than serializing the
    state outside the execution boundary.  The record exists to make a future
    fitted node apply only the state trained by the exact admitted contract,
    capability, partition, and seed.
    """

    serializer: str
    contract_digest: str
    capability_content_digest: str
    capability_envelope_digest: str
    partition_digest: str
    seed: int | None
    graph_digest: str
    candidate_node_digest: str
    _attempt_identifier: str
    _state_json: str

    @classmethod
    def _bound(
        cls,
        *,
        serializer: str,
        contract_digest: str,
        capability_content_digest: str,
        capability_envelope_digest: str,
        partition_digest: str,
        seed: int | None,
        graph_digest: str,
        candidate_node_digest: str,
        attempt_identifier: str,
        state_json: str,
    ) -> "FittedStateRecord":
        record = object.__new__(cls)
        object.__setattr__(record, "serializer", serializer)
        object.__setattr__(record, "contract_digest", contract_digest)
        object.__setattr__(record, "capability_content_digest", capability_content_digest)
        object.__setattr__(record, "capability_envelope_digest", capability_envelope_digest)
        object.__setattr__(record, "partition_digest", partition_digest)
        object.__setattr__(record, "seed", seed)
        object.__setattr__(record, "graph_digest", graph_digest)
        object.__setattr__(record, "candidate_node_digest", candidate_node_digest)
        object.__setattr__(record, "_attempt_identifier", attempt_identifier)
        object.__setattr__(record, "_state_json", state_json)
        return record

    @property
    def state(self) -> Mapping[str, Any]:
        """Return a disposable decoded state object for a local apply step."""

        decoded = json.loads(self._state_json)
        if not isinstance(decoded, Mapping):
            raise FoldLifecycleError("fitted state record is malformed")
        return decoded

    @property
    def state_size_bytes(self) -> int:
        """Return the exact retained canonical-state byte count."""

        return len(self._state_json.encode("utf-8"))

    def canonical_state_bytes(self) -> bytes:
        """Return exact local custody bytes for a bounded private authority."""

        return self._state_json.encode("utf-8")

    @property
    def digest(self) -> str:
        """Return the identity of state and the authority that created it."""

        return hashlib.sha256(
            json.dumps(
                {
                    "schema_version": _FITTED_STATE_SCHEMA_VERSION,
                    "serializer": self.serializer,
                    "contract_digest": self.contract_digest,
                    "capability_content_digest": self.capability_content_digest,
                    "capability_envelope_digest": self.capability_envelope_digest,
                    "partition_digest": self.partition_digest,
                    "seed": self.seed,
                    "graph_digest": self.graph_digest,
                    "candidate_node_digest": self.candidate_node_digest,
                    "state": self.state,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def assert_matches(
        self,
        context: "FoldLifecycleContext",
        *,
        graph: Any,
        node_id: str,
        parameters: Mapping[str, Any],
    ) -> None:
        """Reject state reuse outside the authority that produced it."""

        expected = (
            context.contract.payload["fitted_state_serializer"],
            context.contract.digest,
            context.capability.content_digest,
            context.capability.envelope_digest,
            context.partition.digest,
            context.seed,
            _admitted_graph_digest(graph),
            context.candidate_node_digest(node_id, parameters),
            context.attempt._identifier,
        )
        observed = (
            self.serializer,
            self.contract_digest,
            self.capability_content_digest,
            self.capability_envelope_digest,
            self.partition_digest,
            self.seed,
            self.graph_digest,
            self.candidate_node_digest,
            self._attempt_identifier,
        )
        if expected != observed:
            raise FoldLifecycleError("fitted state does not match this local fold authority")


def _indices(value: Any, *, name: str, sample_count: int) -> np.ndarray:
    indices = np.asarray(value)
    if indices.ndim != 1 or indices.size == 0 or indices.dtype.kind not in "iu":
        raise FoldLifecycleError(f"{name} must be a non-empty one-dimensional integer vector")
    indices = np.array(indices, dtype=np.int64, copy=True)
    if (indices < 0).any() or (indices >= sample_count).any() or len(set(indices.tolist())) != len(indices):
        raise FoldLifecycleError(f"{name} is not a valid unique sample partition")
    indices.setflags(write=False)
    return indices


@dataclass(frozen=True, init=False)
class FoldPartition:
    """One immutable, disjoint train/test partition of an admitted capability."""

    sample_count: int
    _train_indices: tuple[int, ...]
    _test_indices: tuple[int, ...]

    @staticmethod
    def _copy_indices(indices: tuple[int, ...]) -> np.ndarray:
        """Return a read-only disposable view, never the identity backing store."""

        result = np.asarray(indices, dtype=np.int64)
        result.setflags(write=False)
        return result

    @property
    def train_indices(self) -> np.ndarray:
        return self._copy_indices(self._train_indices)

    @property
    def test_indices(self) -> np.ndarray:
        return self._copy_indices(self._test_indices)

    @classmethod
    def _validated(cls, sample_count: int, train_indices: Any, test_indices: Any) -> "FoldPartition":
        if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 2:
            raise FoldLifecycleError("sample_count must be an integer of at least two")
        train = _indices(train_indices, name="train_indices", sample_count=sample_count)
        test = _indices(test_indices, name="test_indices", sample_count=sample_count)
        if set(train.tolist()) & set(test.tolist()):
            raise FoldLifecycleError("train_indices and test_indices must be disjoint")
        partition = object.__new__(cls)
        object.__setattr__(partition, "sample_count", sample_count)
        object.__setattr__(partition, "_train_indices", tuple(int(index) for index in train))
        object.__setattr__(partition, "_test_indices", tuple(int(index) for index in test))
        return partition

    @classmethod
    def create(cls, train_indices: Any, test_indices: Any, *, sample_count: int) -> "FoldPartition":
        return cls._validated(sample_count, train_indices, test_indices)

    @property
    def digest(self) -> str:
        """Return an unambiguous identity for this ordered train/test split."""

        payload = {
            "schema_version": "spectra-fold-partition/1",
            "sample_count": self.sample_count,
            "train_indices": self.train_indices.tolist(),
            "test_indices": self.test_indices.tolist(),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()


class FoldLifecycleContext:
    """The only supported scientific-data authority for one node/fold attempt."""

    def __init__(
        self,
        contract: NodeExecutionContract,
        capability: SpectralDatasetCapability,
        partition: FoldPartition,
        *,
        seed: int | None = None,
        attempt: FoldAttempt | None = None,
    ) -> None:
        try:
            metadata = node_registry.get_metadata(contract.payload["operation_id"])
        except KeyError as exc:
            raise FoldLifecycleError("contract operation is unavailable in the local node registry") from exc
        registered_contract = metadata.resolved_execution_contract()
        if registered_contract is None or registered_contract.digest != contract.digest:
            raise FoldLifecycleError("contract does not match the locally registered operation identity")
        sample_count = capability.arrays["X"].shape[0]
        if partition.sample_count != sample_count:
            raise FoldLifecycleError("fold partition sample count does not match the admitted capability")
        self.contract = contract
        self.capability = capability
        self.partition = partition
        self.seed = seed
        if attempt is not None and not isinstance(attempt, FoldAttempt):
            raise FoldLifecycleError("fold attempt must be created by the lifecycle authority")
        self.attempt = attempt or FoldAttempt.create()
        if contract.payload["deterministic"]:
            if seed is not None:
                raise FoldLifecycleError("deterministic node must not receive a lifecycle seed")
        elif isinstance(seed, bool) or not isinstance(seed, int):
            raise FoldLifecycleError("non-deterministic node requires one explicit integer seed")

    def _indices(self, role: FoldRole) -> np.ndarray:
        if role == "train":
            return self.partition.train_indices
        if role == "test":
            return self.partition.test_indices
        raise FoldLifecycleError("fold role must be train or test")

    def X(self, role: FoldRole) -> np.ndarray:
        """Return a private writable copy; capability content remains immutable."""

        return np.array(self.capability.arrays["X"][self._indices(role)], copy=True)

    def dataset(self, role: FoldRole) -> SherpaDataset:
        """Return a private fold-local scientific dataset for a DAG root.

        The capability remains the only authority that rehydrates scientific
        context.  Replacing its matrix with the selected private rows retains
        feature/domain/provenance context while deliberately dropping the
        full-data target and sample context.  A node that needs targets or
        groups must request those explicitly through this context, where its
        immutable contract and fold role are enforced.
        """

        dataset, _groups = self.capability.to_dataset_and_groups()
        result = dataset.with_data(self.X(role))
        identity = _sample_identity_axis(self.capability, self._indices(role))
        if identity is not None:
            result.sample_axis = identity
        return result

    def target(self, role: FoldRole) -> np.ndarray | None:
        access = TargetAccess(self.contract.payload["target_access"])
        if access is TargetAccess.NONE:
            raise FoldLifecycleError("node contract does not permit target access")
        if access is TargetAccess.FIT_ONLY and role != "train":
            raise FoldLifecycleError("fit-only target access is unavailable on held-out samples")
        if "target" not in self.capability.arrays:
            if access is TargetAccess.OPTIONAL:
                return None
            raise FoldLifecycleError("node requires target access but the capability has no target")
        return np.array(self.capability.arrays["target"][self._indices(role)], copy=True)

    def target_dataset(self, role: FoldRole) -> SherpaDataset | None:
        """Read authorized targets first, then attach their own response authority."""
        target = self.target(role)
        return _response_dataset(self.capability, target, self._indices(role))

    def groups(self, role: FoldRole) -> np.ndarray | None:
        access = GroupAccess(self.contract.payload["group_access"])
        if access is GroupAccess.NONE:
            raise FoldLifecycleError("node contract does not permit group access")
        if access is GroupAccess.FIT_ONLY and role != "train":
            raise FoldLifecycleError("fit-only group access is unavailable on held-out samples")
        if "groups" not in self.capability.arrays:
            if access is GroupAccess.REQUIRED:
                raise FoldLifecycleError("node requires group access but the capability has no groups")
            return None
        return np.array(self.capability.arrays["groups"][self._indices(role)], copy=True)

    def fresh_node(self, node_id: str, parameters: Mapping[str, Any] | None = None) -> Node:
        """Build a fresh, contract-bound node for this fold; never clone state."""

        values = dict(parameters or {})
        seed_parameter = self.contract.payload["seed_parameter"]
        if seed_parameter is not None:
            if seed_parameter in values and values[seed_parameter] != self.seed:
                raise FoldLifecycleError("candidate seed differs from the admitted lifecycle seed")
            values[seed_parameter] = self.seed
        return node_registry.create_node(self.contract.payload["operation_id"], node_id, values)

    def candidate_node_digest(self, node_id: str, parameters: Mapping[str, Any]) -> str:
        """Identify one contract-bound candidate node without exposing its state."""

        if not isinstance(node_id, str) or not node_id:
            raise FoldLifecycleError("candidate node ID must be a non-empty string")
        parameters_json = _canonical_state_json(parameters)
        return hashlib.sha256(
            json.dumps(
                {
                    "schema_version": "spectra-fold-candidate-node/1",
                    "node_id": node_id,
                    "operation_id": self.contract.payload["operation_id"],
                    "contract_digest": self.contract.digest,
                    "parameters": json.loads(parameters_json),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def fitted_state_digest(self, state: Mapping[str, Any]) -> str:
        """Identify JSON-only state in the exact contract and training partition."""

        if not isinstance(state, Mapping):
            raise FoldLifecycleError("fitted state must use a JSON object")
        try:
            payload = json.dumps(
                {
                    "contract_digest": self.contract.digest,
                    "capability_envelope_digest": self.capability.envelope_digest,
                    "partition_digest": self.partition.digest,
                    "seed": self.seed,
                    "state": state,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise FoldLifecycleError("fitted state must be JSON-only and finite") from exc
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record_fitted_state(
        self,
        state: Mapping[str, Any],
        *,
        role: FoldRole,
        graph: Any,
        node_id: str,
        parameters: Mapping[str, Any],
    ) -> FittedStateRecord:
        """Bind JSON-only fitted state to this exact local training authority.

        Only a fitted transform or fitted model may create such a record.  A
        later apply path must use :meth:`FittedStateRecord.assert_matches` so
        state from another candidate, fold, custody envelope, or seed cannot
        be reused accidentally.
        """

        lifecycle = self.contract.payload["lifecycle_kind"]
        if lifecycle not in {"fitted_transform", "fitted_model"}:
            raise FoldLifecycleError("only fitted node contracts may record fitted state")
        if role != "train":
            raise FoldLifecycleError("fitted state may be recorded only from the training fold")
        graph_digest = _admitted_graph_digest(graph)
        serializer = self.contract.payload["fitted_state_serializer"]
        if not isinstance(serializer, str):  # Contract validation makes this defensive only.
            raise FoldLifecycleError("fitted node contract has no JSON state serializer")
        state_json = _canonical_state_json(state)
        return FittedStateRecord._bound(
            serializer=serializer,
            contract_digest=self.contract.digest,
            capability_content_digest=self.capability.content_digest,
            capability_envelope_digest=self.capability.envelope_digest,
            partition_digest=self.partition.digest,
            seed=self.seed,
            graph_digest=graph_digest,
            candidate_node_digest=self.candidate_node_digest(node_id, parameters),
            attempt_identifier=self.attempt._identifier,
            state_json=state_json,
        )


@dataclass(frozen=True, init=False)
class FullDataFittedStateRecord:
    """Local-only JSON state from a declared full-data refit.

    This is intentionally a distinct type from :class:`FittedStateRecord`.
    A full-data fit is suitable for applying a selected model, but it is never
    validation evidence and cannot be used as a fold-trained state record.
    The serialized state remains local until a later artifact/export boundary
    explicitly admits it.
    """

    serializer: str
    contract_digest: str
    capability_content_digest: str
    capability_envelope_digest: str
    graph_digest: str
    validation_execution_digest: str
    node_id: str
    candidate_node_digest: str
    seed: int | None
    _attempt_identifier: str
    _state_json: str

    @classmethod
    def _bound(
        cls,
        *,
        serializer: str,
        contract_digest: str,
        capability_content_digest: str,
        capability_envelope_digest: str,
        graph_digest: str,
        validation_execution_digest: str,
        node_id: str,
        candidate_node_digest: str,
        seed: int | None,
        attempt_identifier: str,
        state_json: str,
    ) -> "FullDataFittedStateRecord":
        record = object.__new__(cls)
        object.__setattr__(record, "serializer", serializer)
        object.__setattr__(record, "contract_digest", contract_digest)
        object.__setattr__(record, "capability_content_digest", capability_content_digest)
        object.__setattr__(record, "capability_envelope_digest", capability_envelope_digest)
        object.__setattr__(record, "graph_digest", graph_digest)
        object.__setattr__(record, "validation_execution_digest", validation_execution_digest)
        object.__setattr__(record, "node_id", node_id)
        object.__setattr__(record, "candidate_node_digest", candidate_node_digest)
        object.__setattr__(record, "seed", seed)
        object.__setattr__(record, "_attempt_identifier", attempt_identifier)
        object.__setattr__(record, "_state_json", state_json)
        return record

    @property
    def state(self) -> Mapping[str, Any]:
        """Return a disposable local copy for the immediate apply path."""

        decoded = json.loads(self._state_json)
        if not isinstance(decoded, Mapping):
            raise FoldLifecycleError("full-data fitted state record is malformed")
        return decoded

    @property
    def digest(self) -> str:
        """Return the identity of the state and its full-refit authority."""

        return hashlib.sha256(
            json.dumps(
                {
                    "schema_version": "spectra-full-data-fitted-state/1",
                    "serializer": self.serializer,
                    "contract_digest": self.contract_digest,
                    "capability_content_digest": self.capability_content_digest,
                    "capability_envelope_digest": self.capability_envelope_digest,
                    "graph_digest": self.graph_digest,
                    "validation_execution_digest": self.validation_execution_digest,
                    "node_id": self.node_id,
                    "candidate_node_digest": self.candidate_node_digest,
                    "seed": self.seed,
                    "state": self.state,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()


class FullDataRefitContext:
    """Authority for the post-selection full-data fit, never validation.

    This deliberately does not accept a fold partition or role.  Its methods
    are available only to a node whose immutable contract is explicitly
    eligible for ``full_refit``.  That makes a full-data application fit
    impossible to mistake for a held-out validation operation.
    """

    def __init__(
        self,
        contract: NodeExecutionContract,
        capability: SpectralDatasetCapability,
        *,
        validation_execution_digest: str,
        attempt: FoldAttempt | None = None,
        seed: int | None = None,
    ) -> None:
        try:
            metadata = node_registry.get_metadata(contract.payload["operation_id"])
        except KeyError as exc:
            raise FoldLifecycleError("contract operation is unavailable in the local node registry") from exc
        registered_contract = metadata.resolved_execution_contract()
        if registered_contract is None or registered_contract.digest != contract.digest:
            raise FoldLifecycleError("contract does not match the locally registered operation identity")
        if ManagedOptimizationEligibility.FULL_REFIT.value not in contract.payload["managed_optimization_eligibility"]:
            raise FoldLifecycleError("node contract is not eligible for a full-data refit")
        if not isinstance(validation_execution_digest, str) or len(validation_execution_digest) != 64:
            raise FoldLifecycleError("full-data refit requires a validation execution digest")
        if attempt is not None and not isinstance(attempt, FoldAttempt):
            raise FoldLifecycleError("full-data refit attempt must be created by the lifecycle authority")
        if contract.payload["deterministic"]:
            if seed is not None:
                raise FoldLifecycleError("deterministic node must not receive a lifecycle seed")
        elif isinstance(seed, bool) or not isinstance(seed, int):
            raise FoldLifecycleError("non-deterministic node requires one explicit integer seed")
        self.contract = contract
        self.capability = capability
        self.validation_execution_digest = validation_execution_digest
        self.attempt = attempt or FoldAttempt.create()
        self.seed = seed

    def dataset(self) -> SherpaDataset:
        """Return one private full-data dataset copy with its target withheld."""

        dataset, _groups = self.capability.to_dataset_and_groups()
        # ``SherpaDataset.with_data`` deliberately preserves a target when the
        # sample count is unchanged.  A full-data refit has exactly that shape,
        # so using it here would silently grant every upstream node the full
        # reference vector.  Rehydration already gave this context an isolated
        # data copy; explicitly clear its target before returning it.  Only a
        # fitted model with declared target access may obtain a separate copy
        # through :meth:`target` below.
        dataset.target = None
        return dataset

    def target(self) -> np.ndarray | None:
        """Return the full target only to a contract that declares access."""

        access = TargetAccess(self.contract.payload["target_access"])
        if access is TargetAccess.NONE:
            raise FoldLifecycleError("node contract does not permit target access")
        if "target" not in self.capability.arrays:
            if access is TargetAccess.OPTIONAL:
                return None
            raise FoldLifecycleError("node requires target access but the capability has no target")
        return np.array(self.capability.arrays["target"], copy=True)

    def target_dataset(self) -> SherpaDataset | None:
        """Response metadata never grants access to a withheld target array."""
        target = self.target()
        return _response_dataset(self.capability, target, np.arange(len(self.capability.arrays["X"])))

    def groups(self) -> np.ndarray | None:
        """Return full groups only to a contract that declares group access."""

        access = GroupAccess(self.contract.payload["group_access"])
        if access is GroupAccess.NONE:
            raise FoldLifecycleError("node contract does not permit group access")
        if "groups" not in self.capability.arrays:
            if access is GroupAccess.REQUIRED:
                raise FoldLifecycleError("node requires group access but the capability has no groups")
            return None
        return np.array(self.capability.arrays["groups"], copy=True)

    def fresh_node(self, node_id: str, parameters: Mapping[str, Any] | None = None) -> Node:
        """Create one new contract-bound node for this full-data fit."""

        values = dict(parameters or {})
        seed_parameter = self.contract.payload["seed_parameter"]
        if seed_parameter is not None:
            if seed_parameter in values and values[seed_parameter] != self.seed:
                raise FoldLifecycleError("candidate seed differs from the admitted lifecycle seed")
            values[seed_parameter] = self.seed
        return node_registry.create_node(self.contract.payload["operation_id"], node_id, values)

    def candidate_node_digest(self, node_id: str, parameters: Mapping[str, Any]) -> str:
        """Identify the exact contract-bound node without exposing its state."""

        if not isinstance(node_id, str) or not node_id:
            raise FoldLifecycleError("candidate node ID must be a non-empty string")
        return hashlib.sha256(
            json.dumps(
                {
                    "schema_version": "spectra-full-refit-candidate-node/1",
                    "node_id": node_id,
                    "operation_id": self.contract.payload["operation_id"],
                    "contract_digest": self.contract.digest,
                    "parameters": json.loads(_canonical_state_json(parameters)),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def record_fitted_state(
        self,
        state: Mapping[str, Any],
        *,
        graph: Any,
        node_id: str,
        parameters: Mapping[str, Any],
    ) -> FullDataFittedStateRecord:
        """Bind JSON-only state to this exact selected full-data graph."""

        if self.contract.payload["lifecycle_kind"] not in {"fitted_transform", "fitted_model"}:
            raise FoldLifecycleError("only fitted node contracts may record fitted state")
        serializer = self.contract.payload["fitted_state_serializer"]
        if not isinstance(serializer, str):
            raise FoldLifecycleError("fitted node contract has no JSON state serializer")
        return FullDataFittedStateRecord._bound(
            serializer=serializer,
            contract_digest=self.contract.digest,
            capability_content_digest=self.capability.content_digest,
            capability_envelope_digest=self.capability.envelope_digest,
            graph_digest=_admitted_graph_digest(graph),
            validation_execution_digest=self.validation_execution_digest,
            node_id=node_id,
            candidate_node_digest=self.candidate_node_digest(node_id, parameters),
            seed=self.seed,
            attempt_identifier=self.attempt._identifier,
            state_json=_canonical_state_json(state),
        )


__all__ = [
    "FittedStateRecord",
    "FoldLifecycleContext",
    "FoldLifecycleError",
    "FoldPartition",
    "FullDataFittedStateRecord",
    "FullDataRefitContext",
]
