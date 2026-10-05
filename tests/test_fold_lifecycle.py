"""M4.5 fold-local authority and leakage-boundary tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
from spectra_sherpa.app.services.dag.fold_lifecycle import (
    FittedStateRecord,
    FoldLifecycleContext,
    FoldLifecycleError,
    FoldPartition,
    FullDataRefitContext,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract


def _contract(**changes):
    payload = node_registry.get_metadata("preprocess.smooth").resolved_execution_contract().as_dict()
    payload.update(changes)
    return NodeExecutionContract.from_dict(payload)


@pytest.fixture(autouse=True)
def loaded_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _context(contract=None):
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=np.arange(24, dtype=float).reshape(4, 6), target=np.arange(4, dtype=float)),
        custody_id="public-fixture",
        groups=np.array(["a", "a", "b", "b"]),
    )
    return FoldLifecycleContext(
        contract or _contract(), capability, FoldPartition.create([0, 1], [2, 3], sample_count=4)
    )


def _fitted_context(monkeypatch):
    contract = _contract(lifecycle_kind="fitted_transform", fitted_state_serializer="spectra.json.v1")
    metadata = node_registry.get_metadata(contract.payload["operation_id"])
    monkeypatch.setattr(
        node_registry, "get_metadata", lambda _operation_id: replace(metadata, execution_contract=contract)
    )
    context = _context(contract)
    # The context has checked its locally registered fitted identity.  Restore
    # the real registry before graph admission/re-admission, whose smooth
    # upstream contract must remain the actual stateless contract.
    monkeypatch.undo()
    return context


def _related_fitted_context(monkeypatch, reference, capability, partition, *, attempt=None):
    """Construct another context for the test-only provisional fitted contract."""

    metadata = node_registry.get_metadata(reference.contract.payload["operation_id"])
    monkeypatch.setattr(
        node_registry, "get_metadata", lambda _operation_id: replace(metadata, execution_contract=reference.contract)
    )
    context = FoldLifecycleContext(reference.contract, capability, partition, attempt=attempt)
    monkeypatch.undo()
    return context


def _graph(*, sigma: float = 1.0):
    return admit_validation_graph(
        [WorkflowNode("upstream-smooth", "preprocess.smooth", {"method": "gaussian", "sigma": sigma})], []
    )


def test_fold_context_partitions_private_copies_without_mutating_capability() -> None:
    context = _context()
    train = context.X("train")
    train[0, 0] = -1
    assert context.capability.arrays["X"][0, 0] == 0
    assert context.partition.digest
    with pytest.raises(FoldLifecycleError, match="disjoint"):
        FoldPartition.create([0, 1], [1, 2], sample_count=4)
    with pytest.raises(TypeError):
        FoldPartition(4, np.array([0]), np.array([4]))
    assert (
        FoldPartition.create([0], [1, 2], sample_count=4).digest
        != FoldPartition.create([0, 1], [2], sample_count=4).digest
    )
    partition = FoldPartition.create([0, 1], [2, 3], sample_count=4)
    mutated_view = partition.train_indices
    mutated_view.setflags(write=True)
    mutated_view[0] = 3
    np.testing.assert_array_equal(partition.train_indices, np.array([0, 1]))
    fold_dataset = context.dataset("train")
    assert fold_dataset.shape == (2, 6)
    assert fold_dataset.target is None


def test_target_and_group_access_fail_closed_by_contract_and_fold_role(monkeypatch) -> None:
    contract = _contract(target_access="fit_only", group_access="fit_only")
    metadata = node_registry.get_metadata(contract.payload["operation_id"])
    monkeypatch.setattr(
        node_registry, "get_metadata", lambda _operation_id: replace(metadata, execution_contract=contract)
    )
    context = _context(contract)
    np.testing.assert_array_equal(context.target("train"), np.array([0.0, 1.0]))
    np.testing.assert_array_equal(context.groups("train"), np.array(["a", "a"]))
    with pytest.raises(FoldLifecycleError, match="held-out"):
        context.target("test")
    with pytest.raises(FoldLifecycleError, match="held-out"):
        context.groups("test")


def test_default_contract_denies_target_access() -> None:
    with pytest.raises(FoldLifecycleError, match="does not permit target"):
        _context().target("train")


def test_optional_target_access_is_present_or_none_without_weakening_custody(monkeypatch) -> None:
    contract = _contract(target_access="optional")
    metadata = node_registry.get_metadata(contract.payload["operation_id"])
    monkeypatch.setattr(
        node_registry, "get_metadata", lambda _operation_id: replace(metadata, execution_contract=contract)
    )
    context = _context(contract)
    np.testing.assert_array_equal(context.target("train"), np.array([0.0, 1.0]))

    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=np.arange(24, dtype=float).reshape(4, 6)),
        custody_id="public-fixture-without-target",
    )
    without_target = FoldLifecycleContext(
        contract,
        capability,
        FoldPartition.create([0, 1], [2, 3], sample_count=4),
    )
    assert without_target.target("train") is None
    full_refit = FullDataRefitContext(
        contract,
        capability,
        validation_execution_digest="a" * 64,
    )
    assert full_refit.target() is None


def test_fresh_fold_nodes_cannot_reuse_state_and_json_state_is_identity_bound() -> None:
    context = _context()
    first = context.fresh_node("fold-1", {"method": "gaussian", "sigma": 1.0})
    second = context.fresh_node("fold-2", {"method": "gaussian", "sigma": 1.0})
    assert first is not second
    assert context.fitted_state_digest({"mean": [1.0, 2.0]}) == context.fitted_state_digest({"mean": [1.0, 2.0]})
    other_partition = FoldPartition.create([0, 2], [1, 3], sample_count=4)
    other_context = FoldLifecycleContext(context.contract, context.capability, other_partition)
    assert context.fitted_state_digest({"mean": [1.0, 2.0]}) != other_context.fitted_state_digest({"mean": [1.0, 2.0]})
    with pytest.raises(FoldLifecycleError, match="JSON-only"):
        context.fitted_state_digest({"object": object()})


def test_context_rejects_contract_or_partition_not_bound_to_its_capability() -> None:
    forged = _contract(target_access="fit_only")
    with pytest.raises(FoldLifecycleError, match="locally registered"):
        _context(forged)

    capability = _context().capability
    with pytest.raises(FoldLifecycleError, match="sample count"):
        FoldLifecycleContext(_contract(), capability, FoldPartition.create([0, 1], [2, 4], sample_count=5))


def test_state_identity_binds_capability_envelope_and_seed() -> None:
    context = _context()
    state = {"mean": [1.0, 2.0]}
    changed_custody = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=np.arange(24, dtype=float).reshape(4, 6), target=np.arange(4, dtype=float)),
        custody_id="different-public-fixture",
        groups=np.array(["a", "a", "b", "b"]),
    )
    changed_context = FoldLifecycleContext(context.contract, changed_custody, context.partition)
    assert context.fitted_state_digest(state) != changed_context.fitted_state_digest(state)


def test_fitted_state_record_is_json_only_private_and_fold_bound(monkeypatch) -> None:
    graph = _graph()
    context = _fitted_context(monkeypatch)
    record = context.record_fitted_state(
        {"mean": [1.0, 2.0]},
        role="train",
        graph=graph,
        node_id="scale",
        parameters={"with_std": True},
    )

    assert record.serializer == "spectra.json.v1"
    assert record.contract_digest == context.contract.digest
    assert record.capability_content_digest == context.capability.content_digest
    assert record.capability_envelope_digest == context.capability.envelope_digest
    assert record.partition_digest == context.partition.digest
    assert record.digest
    state_copy = record.state
    state_copy["mean"][0] = -1.0
    assert record.state == {"mean": [1.0, 2.0]}
    record.assert_matches(context, graph=graph, node_id="scale", parameters={"with_std": True})
    with pytest.raises(TypeError):
        FittedStateRecord("spectra.json.v1", "a", "b", "c", "d", None, "e", "f", "g", "{}")
    with pytest.raises(FoldLifecycleError, match="JSON-only"):
        context.record_fitted_state({"state": object()}, role="train", graph=graph, node_id="scale", parameters={})
    with pytest.raises(FoldLifecycleError, match="keys.*strings"):
        context.record_fitted_state(
            {1: "would otherwise be silently coerced"},
            role="train",
            graph=graph,
            node_id="scale",
            parameters={},
        )
    with pytest.raises(FoldLifecycleError, match="string"):
        context.record_fitted_state(
            {"nested": {1: "must not be coerced"}},
            role="train",
            graph=graph,
            node_id="scale",
            parameters={},
        )


def test_fitted_state_record_rejects_cross_fold_or_cross_custody_reuse(monkeypatch) -> None:
    graph = _graph()
    context = _fitted_context(monkeypatch)
    record = context.record_fitted_state(
        {"mean": [1.0, 2.0]}, role="train", graph=graph, node_id="scale", parameters={}
    )
    other_partition = FoldPartition.create([0, 2], [1, 3], sample_count=4)
    other_fold = _related_fitted_context(monkeypatch, context, context.capability, other_partition)
    with pytest.raises(FoldLifecycleError, match="does not match"):
        record.assert_matches(other_fold, graph=graph, node_id="scale", parameters={})
    other_capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=np.arange(24, dtype=float).reshape(4, 6), target=np.arange(4, dtype=float)),
        custody_id="changed-custody",
        groups=np.array(["a", "a", "b", "b"]),
    )
    other_custody = _related_fitted_context(monkeypatch, context, other_capability, context.partition)
    with pytest.raises(FoldLifecycleError, match="does not match"):
        record.assert_matches(other_custody, graph=graph, node_id="scale", parameters={})


def test_fitted_state_requires_training_role_candidate_identity_and_same_attempt(monkeypatch) -> None:
    graph = _graph()
    context = _fitted_context(monkeypatch)
    with pytest.raises(FoldLifecycleError, match="training fold"):
        context.record_fitted_state({"mean": [1.0]}, role="test", graph=graph, node_id="scale", parameters={})
    record = context.record_fitted_state(
        {"mean": [1.0]},
        role="train",
        graph=graph,
        node_id="scale",
        parameters={"with_std": True},
    )
    held_out_apply = _related_fitted_context(
        monkeypatch, context, context.capability, context.partition, attempt=context.attempt
    )
    record.assert_matches(held_out_apply, graph=graph, node_id="scale", parameters={"with_std": True})
    with pytest.raises(FoldLifecycleError, match="does not match"):
        record.assert_matches(context, graph=graph, node_id="scale", parameters={"with_std": False})
    with pytest.raises(FoldLifecycleError, match="does not match"):
        record.assert_matches(context, graph=_graph(sigma=2.0), node_id="scale", parameters={"with_std": True})
    retry = _related_fitted_context(monkeypatch, context, context.capability, context.partition)
    with pytest.raises(FoldLifecycleError, match="does not match"):
        record.assert_matches(retry, graph=graph, node_id="scale", parameters={"with_std": True})
    retry_record = retry.record_fitted_state(
        {"mean": [1.0]}, role="train", graph=graph, node_id="scale", parameters={"with_std": True}
    )
    # A fresh retry may not apply the earlier state, but reproducible state
    # material must retain the same digest rather than exposing retry identity.
    assert retry_record.digest == record.digest


def test_stateless_contract_cannot_create_fitted_state_record() -> None:
    with pytest.raises(FoldLifecycleError, match="only fitted"):
        _context().record_fitted_state(
            {"mean": [1.0, 2.0]}, role="train", graph=_graph(), node_id="scale", parameters={}
        )
