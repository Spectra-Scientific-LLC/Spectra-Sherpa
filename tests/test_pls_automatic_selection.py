"""Automatic LV choice changes the fitted model, never only its report."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.modeling.pls_core import fit_simpls
from spectra_sherpa.sdk.validate import make_split_plan


def data():
    rng = np.random.default_rng(286)
    X = rng.normal(size=(60, 8))
    y = X[:, 0] * 2 + X[:, 1] * 0.4 + rng.normal(size=60)
    return SherpaDataset(X=X), y


def automatic(**extra):
    return FittedPLSV2Node(
        "automatic",
        {
            "n_components": 3,
            "scale": True,
            "component_fit_mode": "one_standard_error",
            "component_curve_max": 6,
            "component_cv_folds": 5,
            **extra,
        },
    )


def independent_choice(X, y, maximum=6):
    folds = make_split_plan(len(y), n_splits=5).folds
    means, errors = [], []
    for n in range(1, maximum + 1):
        rmses = []
        for fold in folds:
            model = PLSRegression(n_components=n, scale=True).fit(X[fold.train], y[fold.train])
            predicted = model.predict(X[fold.test]).reshape(-1)
            rmses.append(np.sqrt(np.mean((predicted - y[fold.test]) ** 2)))
        means.append(np.mean(rmses))
        errors.append(np.std(rmses, ddof=1) / np.sqrt(len(folds)))
    best = int(np.argmin(means))
    return next(n + 1 for n, mean in enumerate(means) if mean <= means[best] + errors[best])


def test_one_se_refits_exact_selected_count_and_reuses_its_curve():
    X, y = data()
    node = automatic()
    result = asyncio.run(node.execute(input_data=X, y=y))
    curve = result.outputs["component_curve"]
    state = result.outputs["fitted_state"]["state"]
    chosen = independent_choice(X.X, y)
    assert chosen != 3  # negative control for the old fixed starter
    assert state["n_components"] == curve["requested_components"] == chosen
    assert state["effective_n_components"] == curve["selected_components"]
    assert curve["component_fit_mode"] == "one_standard_error"
    assert curve["selection_rule_status"] == "matches_curve"
    expected = fit_simpls(X.X, y.reshape(-1, 1), n_components=chosen, scale=True)
    np.testing.assert_allclose(state["coefficients"], expected.coefficients, rtol=1e-12)
    np.testing.assert_allclose(result.outputs["default"], node.apply_fitted_state(X, state), rtol=1e-12)
    assert "refitted" in curve["selection_note"]


def test_outer_fold_fit_selects_inside_only_that_training_population():
    source, y = data()
    outer = make_split_plan(len(y), n_splits=3).folds[0]
    train = SherpaDataset(X=source.X[outer.train])
    train.provenance.append(op_id="data.train_test_split", parameters={"split": "train"})
    state = automatic().fit_fitted_state(train, y[outer.train])
    assert state["n_components"] == independent_choice(train.X, y[outer.train])
    # Locked outer samples can change arbitrarily without entering selection or fit.
    source.X[outer.test] += 1e5
    y[outer.test] -= 1e6
    same_train = SherpaDataset(X=source.X[outer.train])
    same_train.provenance.append(op_id="data.train_test_split", parameters={"split": "train"})
    assert automatic().fit_fitted_state(same_train, y[outer.train]) == state


@pytest.mark.parametrize("parameters", [{}, {"component_fit_mode": "manual"}])
def test_manual_fit_and_annotation_only_rule_keep_the_saved_count(parameters):
    X, y = data()
    node = FittedPLSV2Node(
        "manual", {"n_components": 3, "scale": True, "component_selection_rule": "one_standard_error", **parameters}
    )
    state = node.fit_fitted_state(X, y)
    expected = fit_simpls(X.X, y.reshape(-1, 1), n_components=3, scale=True)
    assert state["n_components"] == 3
    np.testing.assert_array_equal(state["coefficients"], expected.coefficients)


@pytest.mark.parametrize(
    "operation,parameters",
    [
        ("preprocess.scale", {}),
        ("data.train_test_split", {"split": "test"}),
    ],
)
def test_unsafe_or_held_out_source_refuses_instead_of_falling_back(operation, parameters):
    X, y = data()
    X.provenance.append(op_id=operation, parameters=parameters)
    with pytest.raises(ValueError, match="Automatic PLS selection unavailable"):
        automatic().fit_fitted_state(X, y)


def test_multitarget_and_unavailable_folds_do_not_silently_choose_fixed_model():
    X, y = data()
    with pytest.raises(ValueError, match="requires one response"):
        automatic().fit_fitted_state(X, np.column_stack([y, y * 2]))
    small = SherpaDataset(X=X.X[:3])
    with pytest.raises(ValueError, match="Automatic PLS selection unavailable"):
        automatic().fit_fitted_state(small, y[:3])


def repeated_data():
    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis

    source, y = data()
    groups = np.repeat(np.arange(20), 3)
    source.sample_axis = SampleAxis(
        labels=[f"row-{i}" for i in range(60)],
        sample_table={"specimen_id": [f"specimen-{g}" for g in groups]},
    )
    return source, y, groups


def test_repeated_specimens_require_explicit_groups_not_display_labels():
    source, y, groups = repeated_data()
    with pytest.raises(ValueError, match="Repeated specimen_id"):
        automatic().fit_fitted_state(source, y)
    state = automatic().fit_fitted_state(source, y, groups=groups)
    assert state["n_components"] >= 1
    with pytest.raises(ValueError, match="divides repeated"):
        automatic().fit_fitted_state(source, y, groups=np.arange(60))


def test_explicit_held_out_response_refuses_with_training_predictors():
    source, y = data()
    source.provenance.append(op_id="data.train_test_split", parameters={"split": "train"})
    response = SherpaDataset(X=y[:, None])
    response.provenance.append(op_id="data.train_test_split", parameters={"split": "test"})
    with pytest.raises(ValueError, match="response selection unavailable.*training partition"):
        automatic().fit_fitted_state(source, response)


@pytest.mark.asyncio
async def test_real_fold_executor_keeps_specimens_disjoint_inside_selection(monkeypatch):
    from pathlib import Path

    from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
    from spectra_sherpa.app.services.dag.fold_graph_executor import execute_supervised_validation_fold
    from spectra_sherpa.app.services.dag.fold_lifecycle import FoldPartition
    from spectra_sherpa.app.services.dag.nodes.modeling import pls_component_curve
    from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
    from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
    from spectra_sherpa.app.types import type_registry

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")
    source, y, groups = repeated_data()
    source.target = y
    # This capability carries explicit groups separately; no unbound sample table.
    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis

    source.sample_axis = SampleAxis(labels=[f"row-{i}" for i in range(60)])
    capability = SpectralDatasetCapability.from_dataset(source, groups=groups, custody_id="public-fixture")
    graph = admit_validation_graph(
        [
            WorkflowNode(
                "pls",
                "model.fitted_pls",
                {
                    "component_fit_mode": "one_standard_error",
                    "component_cv_folds": 5,
                    "component_curve_max": 6,
                    "scale": True,
                },
            )
        ],
        [],
    )
    partition = FoldPartition.create(np.arange(45), np.arange(45, 60), sample_count=60)
    plans = []
    original = pls_component_curve.make_split_plan

    def capture(rows, **kwargs):
        inner_groups = np.asarray(kwargs["groups"])
        np.testing.assert_array_equal(inner_groups, groups[:45])
        plan = original(rows, **kwargs)
        assert plan.method == "group_kfold"
        for fold in plan.folds:
            assert not set(inner_groups[fold.train]) & set(inner_groups[fold.test])
        plans.append(plan)
        return plan

    monkeypatch.setattr(pls_component_curve, "make_split_plan", capture)
    result = await execute_supervised_validation_fold(graph, capability, partition)
    assert result.test_predictions.shape == (15, 1)
    assert len(plans) == 1


def bound_repeated_data(grouping="specimen"):
    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis
    from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset

    source, y, specimen = repeated_data()
    if grouping == "divided":
        groups = np.random.default_rng(174).permutation(60)
    elif grouping == "batch":
        groups = specimen // 4
    else:
        groups = specimen
    table = {
        "sample_id": [f"row-{i}" for i in range(60)],
        "specimen_id": [f"specimen-{g}" for g in specimen],
        "group": [f"group-{g}" for g in groups],
        "response": y.tolist(),
    }
    source.sample_axis = SampleAxis(labels=table["sample_id"], sample_table=table)
    source.meta["source_collection"] = {
        "manifest_digest": "a" * 64,
        "collection_definition_sha256": "b" * 64,
        "scientific_collection_sha256": "c" * 64,
    }
    bound = attach_target_dataset(
        source,
        None,
        target_type="continuous",
        target_source="sample_table_column",
        target_column="response",
        group_column="group",
        node_id="target",
    )
    from spectra_sherpa.app.lib.sherpa_dataset import Provenance

    history = bound.provenance.to_list()
    for entry in history:
        entry["timestamp"] = "2026-10-29T00:00:00+00:00"
    bound.provenance = Provenance.from_list(history)
    return bound, np.asarray(table["group"])


def test_explicit_groups_cannot_override_coarser_bound_groups():
    source, groups = bound_repeated_data("batch")
    with pytest.raises(ValueError, match="groups differ from the bound dataset"):
        automatic().fit_fitted_state(source, None, groups=np.repeat(np.arange(20), 3))
    assert automatic().fit_fitted_state(source, None, groups=groups)["n_components"] >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["prediction", "scored", "refit"])
async def test_wire_capability_cannot_erase_divided_specimens_before_inner_cv(path, monkeypatch):
    from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
    from spectra_sherpa.app.services.dag.fold_graph_executor import (
        execute_authorized_full_data_refit,
        execute_scored_supervised_validation_fold,
        execute_supervised_validation_fold,
    )
    from spectra_sherpa.app.services.dag.fold_lifecycle import FoldPartition
    from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
    from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph

    source, groups = bound_repeated_data("divided")
    capability = SpectralDatasetCapability.from_dataset(
        source,
        groups=groups,
        custody_id="test",
        dataset_ref_digest=source.meta["supervision_binding"]["supervision_binding_sha256"],
        retain_sample_independence=True,
    )
    capability = SpectralDatasetCapability.from_wire(capability.to_wire())
    assert capability.to_dataset_and_groups()[0].sample_axis.sample_table is None
    nodes = [WorkflowNode("pls", "model.fitted_pls", {"component_fit_mode": "one_standard_error"})]
    edges = []
    if path != "prediction":
        nodes.append(WorkflowNode("eval", "diagnostics.regression_evaluator", {}))
        edges.append(WorkflowEdge("pls", "eval"))
    graph = admit_validation_graph(nodes, edges)
    partition = FoldPartition.create(np.arange(45), np.arange(45, 60), sample_count=60)
    with pytest.raises(ValueError, match="divides repeated"):
        capability.require_independent_validation_groups()
    fits = []

    def forbidden_fit(*args, **kwargs):
        fits.append(True)
        raise AssertionError("numerical fitting must not start")

    monkeypatch.setattr(FittedPLSV2Node, "fit_fitted_state", forbidden_fit)
    from spectra_sherpa.app.services.dag.fold_graph_executor import FoldGraphExecutionError

    with pytest.raises(FoldGraphExecutionError, match="execution failed|refit failed"):
        if path == "refit":
            await execute_authorized_full_data_refit(graph, capability, validation_execution_digest="a" * 64)
        elif path == "scored":
            await execute_scored_supervised_validation_fold(graph, capability, partition)
        else:
            await execute_supervised_validation_fold(graph, capability, partition)
    assert not fits


def test_independence_proof_survives_wire_and_cannot_omit_or_change_identities():
    from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability

    source, groups = bound_repeated_data()
    capability = SpectralDatasetCapability.from_dataset(
        source,
        groups=groups,
        custody_id="test",
        dataset_ref_digest=source.meta["supervision_binding"]["supervision_binding_sha256"],
        retain_sample_independence=True,
    )
    SpectralDatasetCapability.from_wire(capability.to_wire()).require_independent_validation_groups()
    import json

    assert "specimen-" not in json.dumps(dict(capability.evidence_summary()))
    for mutation in ("omit", "change", "order", "table", "legacy", "groups", "binding"):
        wire = capability.to_wire()
        proof = wire["metadata"]["sample_independence"]
        if mutation == "omit":
            proof["identities"] = {}
        elif mutation == "change":
            proof["identities"]["specimen_id"][1] = "other"
        elif mutation == "table":
            proof["table_projection"] = [x for x in proof["table_projection"] if x["name"] != "specimen_id"]
            proof["identities"] = {}
        elif mutation == "order":
            proof["identities"]["specimen_id"].reverse()
        elif mutation == "binding":
            proof["supervision_binding"]["group_column"] = "specimen_id"
        elif mutation == "legacy":
            del wire["metadata"]["sample_independence"]
        arrays = dict(capability.arrays)
        if mutation == "groups":
            arrays["groups"] = np.asarray([f"other-{i}" for i in range(60)])
        # Even if a caller recomputes the outer envelope, it cannot manufacture
        # a different grouping proof for the original source scientific digest.
        changed = SpectralDatasetCapability(arrays=arrays, metadata=wire["metadata"])
        with pytest.raises(ValueError, match="independence|specimen-independence"):
            changed.require_independent_validation_groups()


def test_manual_capability_keeps_exact_preautomatic_wire_and_digest():
    import hashlib
    import json

    from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability

    source, groups = bound_repeated_data()
    kwargs = dict(
        groups=groups,
        custody_id="test",
        dataset_ref_digest=source.meta["supervision_binding"]["supervision_binding_sha256"],
    )
    legacy = SpectralDatasetCapability.from_dataset(source, **kwargs)
    assert "sample_independence" not in legacy.metadata
    # Captured from the paired public pre-auto implementation (dd280907).
    assert legacy.content_digest == "94587a491ecf2a98c8ce3cb146eaecebb00930926828080c7209d066afe0f88f"
    assert legacy.envelope_digest == "d7c66245f0649a6b5936d5d5358da95eb57c79fe7e890409adf051a809ecd49b"
    wire = legacy.to_wire()
    assert (
        hashlib.sha256(json.dumps(wire, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        == "03c523dbc8e71ac571f7cc02bcedbc137a66cffec8569823130e4ccd36c31920"
    )
    assert SpectralDatasetCapability.from_wire(wire).to_wire() == wire
    with pytest.raises(ValueError, match="retained specimen-independence"):
        legacy.require_independent_validation_groups()
    automatic_capability = SpectralDatasetCapability.from_dataset(source, retain_sample_independence=True, **kwargs)
    automatic_capability.require_independent_validation_groups()
    assert automatic_capability.content_digest != legacy.content_digest
    assert automatic_capability.envelope_digest != legacy.envelope_digest
