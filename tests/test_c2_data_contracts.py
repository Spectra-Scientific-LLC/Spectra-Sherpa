"""C2a contract and admission proofs for retained data transformation nodes."""

from __future__ import annotations

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.execution_contract_vocabulary import ManagedOptimizationEligibility, TargetAccess


@pytest.mark.parametrize(
    ("node_type", "input_names", "output_names"),
    [
        ("data.filter_samples", ["X"], ["default"]),
        (
            "data.train_test_split",
            ["X", "y"],
            ["X_train", "X_test", "y_train", "y_test", "train_indices", "test_indices"],
        ),
        ("data.attach_target", ["X", "y", "sample_table"], ["default"]),
    ],
)
def test_retained_data_transform_has_one_complete_local_contract(
    node_type: str,
    input_names: list[str],
    output_names: list[str],
) -> None:
    metadata = node_registry.get_metadata(node_type)
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["contract_version"] == "4.0"
    assert contract.payload["operation_id"] == node_type
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert [port["name"] for port in contract.payload["semantic_inputs"]] == input_names
    assert [port["name"] for port in contract.payload["semantic_outputs"]] == output_names
    assert all(port["type_ref"].startswith("spectrasherpa://types/") for port in contract.payload["semantic_inputs"])
    assert all(port["type_ref"].startswith("spectrasherpa://types/") for port in contract.payload["semantic_outputs"])


def test_split_contract_preserves_named_same_type_outputs_and_seed_identity() -> None:
    contract = node_registry.get_metadata("data.train_test_split").resolved_execution_contract()
    assert contract is not None

    outputs = {port["name"]: port for port in contract.payload["semantic_outputs"]}
    assert outputs["X_train"]["type_ref"] == outputs["X_test"]["type_ref"]
    assert outputs["y_train"]["type_ref"] == outputs["y_test"]["type_ref"]
    assert outputs["y_train"]["required"] is False
    assert outputs["y_test"]["required"] is False
    assert contract.payload["deterministic"] is False
    assert contract.payload["seed_parameter"] == "random_seed"
    assert contract.payload["target_access"] == TargetAccess.OPTIONAL.value


def test_filter_admission_rejects_response_based_and_undeclared_rules() -> None:
    with pytest.raises(ValueError, match="not an admitted option"):
        node_registry.create_node("data.filter_samples", "filter", {"field": "target"})
    with pytest.raises(ValueError, match="undeclared fields"):
        node_registry.create_node("data.filter_samples", "filter", {"where": "response > 1"})


def test_filter_exact_values_are_explicitly_canonicalized() -> None:
    node = node_registry.create_node(
        "data.filter_samples",
        "filter",
        {
            "field": "sample_class",
            "filter_values": ["calibration", "validation"],
        },
    )

    assert node.parameters["match_mode"] == "in_list"
    assert node.parameters["case_sensitive"] is True
    assert node.parameters["filter_values"] == ["calibration", "validation"]


@pytest.mark.parametrize("seed", [True, 1.5, "42"])
def test_split_admission_rejects_noninteger_seeds(seed: object) -> None:
    with pytest.raises(ValueError, match="random_seed"):
        node_registry.create_node("data.train_test_split", "split", {"random_seed": seed})


def test_split_admission_rejects_removed_shuffle_switch() -> None:
    with pytest.raises(ValueError, match="undeclared fields: 'shuffle'"):
        node_registry.create_node(
            "data.train_test_split",
            "split",
            {"split_method": "stratified", "shuffle": False},
        )


def test_split_admission_resets_settings_the_chosen_method_does_not_govern() -> None:
    """A leftover from another method is normalized, not turned into a hard stop.

    The shipped PLS calibration sheet carries ``n_components: 5`` for its
    Kennard-Stone split. Switching that node to stratified sampling used to make
    the saved graph inadmissible over a field the contract already declares
    inapplicable and the Workbench does not show, leaving no way to run the sheet.
    """

    node = node_registry.create_node(
        "data.train_test_split",
        "split",
        {"split_method": "stratified", "n_components": 5, "distance_metric": "mahalanobis"},
    )

    assert node.parameters["n_components"] == 0
    assert node.parameters["distance_metric"] == "euclidean"
    # The seed still governs stratified sampling, so an explicit one survives.
    seeded = node_registry.create_node(
        "data.train_test_split",
        "split",
        {"split_method": "stratified", "random_seed": 7},
    )
    assert seeded.parameters["random_seed"] == 7

    # A deterministic method has no seed to honour, so it goes back to default.
    deterministic = node_registry.create_node(
        "data.train_test_split",
        "split",
        {"split_method": "kennard_stone", "random_seed": 7},
    )
    assert deterministic.parameters["random_seed"] == 42
    # Kennard-Stone does govern a distance space, so its settings are kept.
    assert deterministic.parameters["distance_metric"] == "euclidean"

    # spxy admits only its published raw-space Euclidean definition.
    spxy = node_registry.create_node(
        "data.train_test_split",
        "split",
        {"split_method": "spxy", "n_components": 4, "distance_metric": "mahalanobis"},
    )
    assert spxy.parameters["n_components"] == 0
    assert spxy.parameters["distance_metric"] == "euclidean"


def test_split_method_scoped_parameters_match_their_declarations() -> None:
    """The normalization table is the node's own declarations, not a second one."""

    from spectra_sherpa.app.services.dag.nodes.data.transforms import (
        _SPLIT_METHOD_SCOPED_PARAMETERS,
    )

    declarations = {
        parameter.name: parameter for parameter in node_registry.get_metadata("data.train_test_split").parameters
    }
    scoped = {name: (methods, default) for name, methods, default in _SPLIT_METHOD_SCOPED_PARAMETERS}

    # Every method-scoped setting is exactly a parameter the node declares
    # conditionally visible on split_method, and nothing else is.
    conditional = {
        name
        for name, parameter in declarations.items()
        if parameter.visible_when and "split_method" in parameter.visible_when
    }
    assert set(scoped) == conditional

    for name, (methods, default) in scoped.items():
        parameter = declarations[name]
        assert set(parameter.visible_when["split_method"]) == set(methods)
        assert parameter.default == default


@pytest.mark.asyncio
async def test_stratified_split_fails_closed_without_a_target() -> None:
    node = node_registry.create_node("data.train_test_split", "split", {"split_method": "stratified"})
    dataset = SherpaDataset(X=np.arange(24, dtype=np.float64).reshape(8, 3), backend="numpy")

    with pytest.raises(ValueError, match="requires explicit or embedded target"):
        await node.execute(X=dataset)


def test_attach_target_declares_required_target_access() -> None:
    contract = node_registry.get_metadata("data.attach_target").resolved_execution_contract()
    assert contract is not None
    assert contract.payload["target_access"] == TargetAccess.REQUIRED.value
    assert {port["name"]: port["required"] for port in contract.payload["semantic_inputs"]} == {
        "X": True,
        "y": False,
        "sample_table": False,
    }
