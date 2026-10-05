"""Scientific definition and execution parity for ``data.train_test_split``."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - register built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.meta_helpers import get_processing_history
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset
from spectra_sherpa.app.services.dag.nodes.data.split_planner import (
    bind_split_groups,
    materialize_split_outputs,
    plan_train_test_split,
    space_filling_coverage,
)
from tests.performance_contract import PerformanceCeiling


def _dataset(n_samples: int = 20, n_features: int = 6) -> SherpaDataset:
    values = np.random.RandomState(912).normal(size=(n_samples, n_features))
    labels = np.asarray(["low", "high"] * (n_samples // 2))
    return SherpaDataset(
        X=values,
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1800.0, n_features), units="cm-1"),
        sample_axis=SampleAxis(labels=[f"sample-{index:02d}" for index in range(n_samples)]),
        target=labels,
        target_context=TargetContext(
            target_type="categorical",
            target_name="class",
            target_names=["class"],
            class_names=["low", "high"],
            n_classes=2,
        ),
        backend="numpy",
    )


def _grouped_dataset() -> SherpaDataset:
    n_samples = 12
    sample_ids = [f"sample-{index:02d}" for index in range(n_samples)]
    table = {
        "sample_id": sample_ids,
        "class": ["angustifolia", "intermedia", "angustifolia", "intermedia"] * 3,
        "block": [1] * 4 + [2] * 4 + [3] * 4,
    }
    source = SherpaDataset(
        X=np.random.RandomState(817).normal(size=(n_samples, 6)),
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1800.0, 6), units="cm-1"),
        sample_axis=SampleAxis(labels=sample_ids, sample_table=table),
        extra={
            "source_collection": {
                "manifest_digest": "1" * 64,
                "collection_definition_sha256": "2" * 64,
                "scientific_collection_sha256": "3" * 64,
            }
        },
        backend="numpy",
    )
    return attach_target_dataset(
        source,
        None,
        target_type="categorical",
        target_source="sample_table_column",
        target_column="class",
        group_column="block",
        node_id="attach",
    )


def _two_instrument_continuous_dataset() -> SherpaDataset:
    """The staging case: two instrument views and one continuous response.

    Forty spectra on each of two instruments, M5 and MP5, carrying a Moisture
    concentration rather than a class. This is what a scientist selects in My
    Dataset when grouping a corn calibration by Instrument, and it is the
    configuration every split method has to answer for.
    """

    n_per_instrument = 40
    n_samples = n_per_instrument * 2
    generator = np.random.RandomState(4114)
    sample_ids = [f"corn-{index:03d}" for index in range(n_samples)]
    instruments = ["M5"] * n_per_instrument + ["MP5"] * n_per_instrument
    moisture = generator.uniform(9.0, 11.5, n_samples)
    table = {
        # sample_id is the structural row identity every real sample table
        # carries; specimen_id is the corn set's own unique per-row label.
        "sample_id": sample_ids,
        "specimen_id": sample_ids,
        "instrument": instruments,
        "Moisture": [float(value) for value in moisture],
    }
    source = SherpaDataset(
        X=generator.normal(size=(n_samples, 16)),
        feature_axis=SpectralAxis(values=np.linspace(1100.0, 2498.0, 16), units="nm"),
        sample_axis=SampleAxis(labels=sample_ids, sample_table=table),
        extra={
            "source_collection": {
                "manifest_digest": "4" * 64,
                "collection_definition_sha256": "5" * 64,
                "scientific_collection_sha256": "6" * 64,
            }
        },
        backend="numpy",
    )
    return attach_target_dataset(
        source,
        None,
        target_type="continuous",
        target_source="sample_table_column",
        target_column="Moisture",
        group_column="instrument",
        node_id="attach",
    )


def _one_instrument_continuous_dataset() -> SherpaDataset:
    """The single-M5 Corn selection with Instrument still bound as a group."""

    n_samples = 40
    generator = np.random.RandomState(4115)
    sample_ids = [f"corn-m5-{index:03d}" for index in range(n_samples)]
    source = SherpaDataset(
        X=generator.normal(size=(n_samples, 16)),
        feature_axis=SpectralAxis(values=np.linspace(1100.0, 2498.0, 16), units="nm"),
        sample_axis=SampleAxis(
            labels=sample_ids,
            sample_table={
                "sample_id": sample_ids,
                "instrument": ["M5"] * n_samples,
                "Moisture": generator.uniform(9.0, 11.5, n_samples).tolist(),
            },
        ),
        extra={
            "source_collection": {
                "manifest_digest": "7" * 64,
                "collection_definition_sha256": "8" * 64,
                "scientific_collection_sha256": "9" * 64,
            }
        },
        backend="numpy",
    )
    return attach_target_dataset(
        source,
        None,
        target_type="continuous",
        target_source="sample_table_column",
        target_column="Moisture",
        group_column="instrument",
        node_id="attach",
    )


def test_kennard_stone_matches_reference_maximin_sequence() -> None:
    """Farthest pair, then lowest-index winner under maximin ties."""

    X = np.asarray([[0.0], [10.0], [4.0], [7.0], [2.0], [9.0], [5.0], [1.0]])
    plan = plan_train_test_split(X, method="kennard_stone", test_size=0.5)

    np.testing.assert_array_equal(plan.train_indices, [0, 1, 6, 3])
    np.testing.assert_array_equal(plan.test_indices, [2, 4, 5, 7])


def test_duplex_matches_snee_two_pair_then_alternating_sequence() -> None:
    """Calibration and validation each receive their own farthest seed pair."""

    X = np.asarray([[0.0], [10.0], [4.0], [7.0], [2.0], [9.0], [5.0], [1.0]])
    plan = plan_train_test_split(X, method="duplex", test_size=0.5)

    np.testing.assert_array_equal(plan.train_indices, [0, 1, 6, 3])
    np.testing.assert_array_equal(plan.test_indices, [5, 7, 2, 4])


def test_spxy_matches_published_joint_normalized_distance_sequence() -> None:
    """The independent maxima of X and y distances contribute equal scales."""

    X = np.asarray([[0.0], [10.0], [4.0], [7.0], [2.0]])
    y = np.asarray([0.0, 0.0, 10.0, 10.0, 5.0])
    plan = plan_train_test_split(X, y, method="spxy", test_size=0.4)

    np.testing.assert_array_equal(plan.train_indices, [0, 3, 1])
    np.testing.assert_array_equal(plan.test_indices, [2, 4])


@pytest.mark.parametrize(
    "method", ["random", "stratified", "sequential", "group_holdout", "kennard_stone", "duplex", "spxy"]
)
def test_every_admitted_method_produces_one_exact_disjoint_partition(method: str) -> None:
    dataset = _dataset()
    y = dataset.target
    if method == "spxy":
        y = np.linspace(0.0, 1.0, dataset.shape[0])
    seed = 37 if method in {"random", "stratified"} else 42
    groups = None
    held_out_groups = None
    if method == "group_holdout":
        groups = np.asarray(["even" if index % 2 == 0 else "odd" for index in range(dataset.shape[0])])
        held_out_groups = ["odd"]
    plan = plan_train_test_split(
        dataset.X,
        y,
        method=method,
        test_size=0.2,
        random_seed=seed,
        groups=groups,
        held_out_groups=held_out_groups,
    )

    combined = np.concatenate((plan.train_indices, plan.test_indices))
    np.testing.assert_array_equal(np.sort(combined), np.arange(dataset.shape[0]))
    assert np.intersect1d(plan.train_indices, plan.test_indices).size == 0
    assert len(plan.digest) == 64


def test_split_plan_digest_binds_settings_and_exact_membership() -> None:
    X = _dataset().X
    first = plan_train_test_split(X, method="random", test_size=0.2, random_seed=1)
    repeated = plan_train_test_split(X, method="random", test_size=0.2, random_seed=1)
    changed = plan_train_test_split(X, method="random", test_size=0.2, random_seed=2)

    assert first.digest == repeated.digest
    assert first.digest != changed.digest
    np.testing.assert_array_equal(first.train_indices, repeated.train_indices)

    changed_data = np.array(X, copy=True)
    changed_data[0, 0] += 1.0
    same_membership = plan_train_test_split(changed_data, method="random", test_size=0.2, random_seed=1)
    np.testing.assert_array_equal(first.train_indices, same_membership.train_indices)
    assert first.x_content_digest != same_membership.x_content_digest
    assert first.digest != same_membership.digest


def test_materialization_rejects_changed_inputs_and_forged_plan_membership() -> None:
    dataset = _dataset()
    X = np.asarray(dataset.X)
    y = np.asarray(dataset.target)
    plan = plan_train_test_split(X, y, method="stratified", test_size=0.2, random_seed=17)

    changed_X = np.array(X, copy=True)
    changed_X[0, 0] += 1.0
    with pytest.raises(ValueError, match="X content digest"):
        materialize_split_outputs(dataset, changed_X, y, plan, node_id="partition")

    changed_y = np.array(y, copy=True)
    changed_y[0] = "high" if changed_y[0] != "high" else "low"
    with pytest.raises(ValueError, match="y content digest"):
        materialize_split_outputs(dataset, X, changed_y, plan, node_id="partition")
    with pytest.raises(ValueError, match="y is missing"):
        materialize_split_outputs(dataset, X, None, plan, node_id="partition")

    forged_membership = replace(
        plan,
        train_indices=np.concatenate((plan.train_indices[:-1], plan.test_indices[:1])),
    )
    with pytest.raises(ValueError, match="exact, disjoint"):
        materialize_split_outputs(dataset, X, y, forged_membership, node_id="partition")

    forged_digest = replace(plan, digest="0" * 64)
    with pytest.raises(ValueError, match="digest does not match"):
        materialize_split_outputs(dataset, X, y, forged_digest, node_id="partition")

    no_target_plan = plan_train_test_split(X, method="sequential", test_size=0.2)
    with pytest.raises(ValueError, match="y content digest"):
        materialize_split_outputs(dataset, X, y, no_target_plan, node_id="partition")

    stale_X = np.array(X, copy=True)
    stale_X[0, 0] += 1.0
    ks_plan = plan_train_test_split(X, method="kennard_stone", test_size=0.2)
    with pytest.raises(ValueError, match="X content digest"):
        space_filling_coverage(stale_X, ks_plan)


def test_reference_methods_fail_closed_outside_their_scientific_definition() -> None:
    X = np.arange(24, dtype=np.float64).reshape(8, 3)
    with pytest.raises(ValueError, match="spxy requires explicit or embedded target"):
        plan_train_test_split(X, method="spxy")
    with pytest.raises(ValueError, match="raw-space Euclidean"):
        plan_train_test_split(X, np.arange(8), method="spxy", distance_metric="mahalanobis")
    with pytest.raises(ValueError, match="at least two test samples"):
        plan_train_test_split(X, method="duplex", test_size=0.125)
    with pytest.raises(ValueError, match="distinct samples"):
        plan_train_test_split(np.ones((8, 3)), method="kennard_stone")
    with pytest.raises(ValueError, match="does not admit a random_seed"):
        plan_train_test_split(X, method="kennard_stone", random_seed=7)
    with pytest.raises(ValueError, match="does not admit distance_metric"):
        plan_train_test_split(X, method="sequential", distance_metric="mahalanobis")


def test_spxy_coverage_uses_the_same_joint_xy_distance_authority() -> None:
    X = np.asarray([[0.0], [10.0], [4.0], [7.0], [2.0]])
    y = np.asarray([0.0, 0.0, 10.0, 10.0, 5.0])
    plan = plan_train_test_split(X, y, method="spxy", test_size=0.4)

    coverage = space_filling_coverage(X, plan, y)
    np.testing.assert_allclose(
        [coverage["mean_nn_distance"], coverage["max_nn_distance"], coverage["min_nn_distance"]],
        [1.1, 1.3, 1.0],
    )
    with pytest.raises(ValueError, match="requires the target values"):
        space_filling_coverage(X, plan)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "extra"),
    [
        ("random", {}),
        ("sequential", {}),
        ("group_holdout", {"held_out_groups": ["MP5"]}),
        ("kennard_stone", {}),
        ("duplex", {}),
        ("spxy", {}),
    ],
)
async def test_two_instrument_continuous_split_executes_through_the_node(method: str, extra: dict) -> None:
    """Every admitted method runs on two instrument groups and a continuous target.

    This is the staging configuration end to end: the node executes, the plan
    binding is re-validated on materialization, and the partition is exact. A
    planner that agrees with itself but not with its own binding validator fails
    here, which is what "split-plan group identity is malformed" was.
    """

    dataset = _two_instrument_continuous_dataset()
    node = node_registry.create_node(
        "data.train_test_split",
        "partition_1",
        {"split_method": method, "test_size": 0.25, **extra},
    )

    outputs = await node.execute(X=dataset)

    train_indices = np.asarray(outputs["train_indices"])
    test_indices = np.asarray(outputs["test_indices"])
    assert train_indices.size > 0 and test_indices.size > 0
    combined = np.concatenate((train_indices, test_indices))
    np.testing.assert_array_equal(np.sort(combined), np.arange(dataset.X.shape[0]))

    step = get_processing_history(outputs["X_train"])[-1]
    parameters = step["parameters"]
    assert step["op_id"] == "data.train_test_split"
    # The attached instrument authority is bound whichever method ran.
    assert parameters["n_groups"] == 2
    if method in ("kennard_stone", "duplex", "spxy"):
        # A space-filling method covers the extremes across both instruments and
        # claims no holdout, so both appear in the test partition.
        assert not parameters["held_out_groups"]
        instruments = np.asarray(dataset.sample_axis.sample_table["instrument"])
        assert set(instruments[test_indices].tolist()) == {"M5", "MP5"}
    else:
        # A group-partitioning method holds one whole instrument out.
        assert len(parameters["held_out_groups"]) == 1
        instruments = np.asarray(dataset.sample_axis.sample_table["instrument"])
        assert set(instruments[test_indices].tolist()) == set(parameters["held_out_groups"])
        assert not set(instruments[train_indices].tolist()) & set(parameters["held_out_groups"])


@pytest.mark.asyncio
async def test_stratified_names_the_continuous_target_it_cannot_stratify() -> None:
    """A continuous response has no classes whose proportions could be preserved.

    The underlying splitter used to report its own internal vocabulary
    ("Supported target types are: ('binary', 'multiclass'). Got 'continuous'")
    once a run was already under way, which named neither the parameter to change
    nor the alternative.
    """

    dataset = _two_instrument_continuous_dataset()
    node = node_registry.create_node(
        "data.train_test_split",
        "partition_1",
        {"split_method": "stratified", "test_size": 0.25},
    )

    with pytest.raises(ValueError, match="requires a categorical target; this target is continuous"):
        await node.execute(X=dataset)


def test_a_space_filling_plan_may_not_claim_a_group_it_did_not_hold_out() -> None:
    """The binding validator keeps the converse invariant it is responsible for."""

    dataset = _grouped_dataset()
    groups = bind_split_groups(dataset)
    target = np.arange(dataset.X.shape[0], dtype=np.float64).reshape(-1, 1)
    plan = plan_train_test_split(dataset.X, target, method="kennard_stone", test_size=0.25, groups=groups)

    forged = replace(plan, held_out_groups=(1,))
    with pytest.raises(ValueError, match="may not claim held-out groups"):
        materialize_split_outputs(dataset, dataset.X, target, forged, node_id="partition", groups=groups)


def test_node_contract_exposes_the_closed_method_and_exact_membership_vocabulary() -> None:
    metadata = node_registry.get_metadata("data.train_test_split")
    parameters = {parameter.name: parameter for parameter in metadata.parameters}
    assert [option["value"] for option in parameters["split_method"].options] == [
        "random",
        "stratified",
        "sequential",
        "group_holdout",
        "kennard_stone",
        "duplex",
        "spxy",
    ]
    assert parameters["held_out_groups"].visible_when == {"split_method": ["group_holdout"]}
    assert "group_holdout" not in parameters["test_size"].visible_when["split_method"]
    assert parameters["distance_metric"].options == ["euclidean", "mahalanobis"]
    assert "shuffle" not in parameters
    contract = metadata.resolved_execution_contract()
    assert contract is not None
    assert contract.payload["implementation_version"] == "4.2.0"
    assert contract.payload["help_reference"] == "docs/nodes/data.md"
    assert len(contract.payload["citations"]) == 4
    assert [port["name"] for port in contract.payload["semantic_outputs"]] == [
        "X_train",
        "X_test",
        "y_train",
        "y_test",
        "train_indices",
        "test_indices",
    ]


@pytest.mark.asyncio
async def test_live_and_generated_execution_share_planner_outputs_context_and_provenance() -> None:
    dataset = _dataset()
    node = node_registry.create_node(
        "data.train_test_split",
        "partition",
        {"split_method": "stratified", "test_size": 0.2, "random_seed": 73},
    )

    live = await node.execute(X=dataset)
    namespace = {"dataset": dataset, "np": np, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset"}, indent="", use_scp=False)), namespace)  # noqa: S102
    generated = namespace["results"]["partition"]

    for name in ("train_indices", "test_indices", "y_train", "y_test"):
        np.testing.assert_array_equal(generated[name], live[name])
    for name in ("X_train", "X_test"):
        np.testing.assert_array_equal(generated[name].X, live[name].X)
        np.testing.assert_array_equal(generated[name].target, live[name].target)
        assert generated[name].sample_axis.labels == live[name].sample_axis.labels
        generated_step = get_processing_history(generated[name])[-1]
        live_step = get_processing_history(live[name])[-1]
        assert generated_step["op_id"] == live_step["op_id"] == "data.train_test_split"
        assert generated_step["parameters"] == live_step["parameters"]
        assert len(generated_step["parameters"]["digest"]) == 64


@pytest.mark.asyncio
async def test_explicit_target_dataset_data_and_context_are_authoritative_in_both_paths() -> None:
    predictors = _dataset()
    response_values = np.column_stack((np.linspace(0.0, 1.0, 20), np.linspace(2.0, 5.0, 20) ** 2))
    response = SherpaDataset(
        X=response_values,
        sample_axis=predictors.sample_axis.copy(),
        target=np.asarray(["embedded-target-must-not-win"] * 20),
        target_context=TargetContext(
            target_type="continuous",
            target_names=["density", "viscosity"],
            target_units="mPa s",
            selected_target="viscosity",
        ),
        backend="numpy",
    )
    node = node_registry.create_node(
        "data.train_test_split",
        "partition",
        {"split_method": "spxy", "test_size": 0.2},
    )

    live = await node.execute(X=predictors, y=response)
    namespace = {"predictors": predictors, "response": response, "np": np, "results": {}}
    exec(
        "\n".join(node.generate_python({"X": "predictors", "y": "response"}, indent="", use_scp=False)),
        namespace,
    )  # noqa: S102
    generated = namespace["results"]["partition"]

    expected = response_values[:, 1]
    for result in (live, generated):
        np.testing.assert_array_equal(result["y_train"], expected[result["train_indices"]])
        np.testing.assert_array_equal(result["y_test"], expected[result["test_indices"]])
        for output_name in ("X_train", "X_test"):
            context = result[output_name].target_context
            assert context.target_type == "continuous"
            assert context.target_name == "viscosity"
            assert context.target_names == ["viscosity"]
            assert context.target_units == "mPa s"
            assert context.selected_target == "viscosity"
    np.testing.assert_array_equal(live["train_indices"], generated["train_indices"])


@pytest.mark.asyncio
async def test_inferred_multitarget_selection_is_preserved_in_both_paths() -> None:
    dataset = _dataset()
    target = np.column_stack((np.linspace(0.0, 1.0, 20), np.linspace(3.0, 7.0, 20) ** 2))
    dataset.target = target
    dataset.target_context = TargetContext(
        target_type="continuous",
        target_names=["moisture", "protein"],
        target_units="percent",
        selected_target="protein",
    )
    node = node_registry.create_node(
        "data.train_test_split",
        "partition",
        {"split_method": "spxy", "test_size": 0.2},
    )

    live = await node.execute(X=dataset)
    namespace = {"dataset": dataset, "np": np, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset"}, indent="", use_scp=False)), namespace)  # noqa: S102
    generated = namespace["results"]["partition"]

    for result in (live, generated):
        np.testing.assert_array_equal(result["y_train"], target[result["train_indices"], 1])
        assert result["X_train"].target_context.target_names == ["protein"]
        assert result["X_train"].target_context.target_units == "percent"
    np.testing.assert_array_equal(live["train_indices"], generated["train_indices"])


@pytest.mark.asyncio
async def test_exact_explicit_categorical_target_inherits_context_and_one_label_authority() -> None:
    dataset = _dataset()
    labels = np.repeat(np.asarray([0, 1], dtype=np.int64), 10)
    dataset.target = labels
    dataset.target_context = TargetContext(target_type="categorical", target_names=["material"])
    node = node_registry.create_node(
        "data.train_test_split",
        "partition",
        {"split_method": "stratified", "test_size": 0.2, "random_seed": 42},
    )

    result = await node.execute(X=dataset, y=np.array(labels, copy=True))

    assert set(result["y_train"].tolist()) == {"0", "1"}
    assert set(result["y_test"].tolist()) == {"0", "1"}
    assert result["X_train"].target_context.target_type == "categorical"
    assert result["X_test"].target_context.target_names == ["material"]


@pytest.mark.asyncio
async def test_unrelated_explicit_target_never_inherits_predictor_target_context() -> None:
    dataset = _dataset()
    embedded = np.repeat(np.asarray([0, 1], dtype=np.int64), 10)
    explicit = np.tile(np.asarray([0, 1], dtype=np.int64), 10)
    dataset.target = embedded
    dataset.target_context = TargetContext(target_type="categorical", target_names=["material"])
    node = node_registry.create_node(
        "data.train_test_split",
        "partition",
        {"split_method": "stratified", "test_size": 0.2, "random_seed": 42},
    )

    result = await node.execute(X=dataset, y=explicit)

    assert np.issubdtype(np.asarray(result["y_train"]).dtype, np.integer)
    assert result["X_train"].target_context.target_type is None
    assert result["X_test"].target_context.target_names is None


@pytest.mark.asyncio
async def test_sample_identity_is_never_inferred_as_a_supervised_target() -> None:
    dataset = _dataset()
    dataset.target = None
    dataset.target_context = TargetContext()

    ordinary = node_registry.create_node(
        "data.train_test_split",
        "partition",
        {"split_method": "sequential", "test_size": 0.2},
    )
    result = await ordinary.execute(X=dataset)

    assert "y_train" not in result
    assert "y_test" not in result
    assert result["X_train"].target is None
    assert result["X_test"].target is None
    assert result["X_train"].target_context.target_names is None
    assert result["X_test"].target_context.target_names is None
    assert result["X_train"].target_context.selected_target is None
    assert result["X_test"].target_context.selected_target is None

    for method in ("stratified", "spxy"):
        supervised = node_registry.create_node(
            "data.train_test_split",
            f"partition-{method}",
            {"split_method": method, "test_size": 0.2},
        )
        with pytest.raises(ValueError, match="requires explicit or embedded target"):
            await supervised.execute(X=dataset)


def test_superseded_sample_partition_identity_is_not_registered() -> None:
    with pytest.raises(KeyError, match="Unknown node type"):
        node_registry.create_node("selection.sample_partition", "prototype", {})


@pytest.mark.parametrize("method", ["random", "stratified", "sequential"])
def test_grouped_planner_holds_out_whole_bound_groups(method: str) -> None:
    dataset = _grouped_dataset()
    groups = bind_split_groups(dataset)
    assert groups is not None

    plan = plan_train_test_split(
        dataset.X,
        dataset.target,
        method=method,
        test_size=0.25,
        random_seed=19 if method in {"random", "stratified"} else 42,
        groups=groups,
    )

    assert plan.groups_content_digest is not None
    assert plan.n_groups == 3
    assert plan.held_out_groups is not None
    assert set(groups[plan.train_indices].tolist()).isdisjoint(groups[plan.test_indices].tolist())
    assert set(groups[plan.test_indices].tolist()) == set(plan.held_out_groups)
    assert set(np.asarray(dataset.target)[plan.train_indices].tolist()) == {"angustifolia", "intermedia"}
    assert set(np.asarray(dataset.target)[plan.test_indices].tolist()) == {"angustifolia", "intermedia"}


def test_group_holdout_records_the_exact_named_holdout() -> None:
    """The scientist names the test groups; the plan binds their canonical values."""

    dataset = _grouped_dataset()
    groups = bind_split_groups(dataset)
    assert groups is not None

    # The fixture's block column is integer; a text-entered "3" selects block 3
    # and the plan records the bound group's own representation.
    plan = plan_train_test_split(
        dataset.X, dataset.target, method="group_holdout", groups=groups, held_out_groups=["3"]
    )
    repeat = plan_train_test_split(
        dataset.X, dataset.target, method="group_holdout", groups=groups, held_out_groups=["3"]
    )
    other = plan_train_test_split(
        dataset.X, dataset.target, method="group_holdout", groups=groups, held_out_groups=["2"]
    )

    assert plan.held_out_groups == (3,)
    assert set(groups[plan.test_indices].tolist()) == {3}
    assert set(groups[plan.train_indices].tolist()) == {1, 2}
    assert plan.digest == repeat.digest
    assert plan.digest != other.digest
    np.testing.assert_array_equal(plan.train_indices, repeat.train_indices)


def test_group_holdout_refuses_an_unknown_total_or_unbounded_selection() -> None:
    dataset = _grouped_dataset()
    groups = bind_split_groups(dataset)
    assert groups is not None

    with pytest.raises(ValueError, match=r"held-out group 'MP5' is not one of the bound groups: 1, 2, 3"):
        plan_train_test_split(dataset.X, method="group_holdout", groups=groups, held_out_groups=["MP5"])
    with pytest.raises(ValueError, match="at least one group in the training partition"):
        plan_train_test_split(dataset.X, method="group_holdout", groups=groups, held_out_groups=["1", "2", "3"])
    with pytest.raises(ValueError, match="at least one named group"):
        plan_train_test_split(dataset.X, method="group_holdout", groups=groups, held_out_groups=[])
    with pytest.raises(ValueError, match="named twice"):
        plan_train_test_split(dataset.X, method="group_holdout", groups=groups, held_out_groups=[3, "3"])
    with pytest.raises(ValueError, match="requires an attached grouping column"):
        plan_train_test_split(dataset.X, method="group_holdout", held_out_groups=["3"])
    with pytest.raises(ValueError, match="does not admit a random_seed"):
        plan_train_test_split(dataset.X, method="group_holdout", groups=groups, held_out_groups=["3"], random_seed=7)


def test_group_holdout_parameters_are_scoped_to_the_method() -> None:
    metadata = node_registry.get_metadata("data.train_test_split")

    canonical = metadata.canonicalize_parameters(
        {
            "split_method": "group_holdout",
            "held_out_groups": ["MP5"],
            "test_size": 0.9,
            "random_seed": 5,
            "n_components": 4,
        }
    )
    assert canonical["held_out_groups"] == ["MP5"]
    assert canonical["test_size"] == 0.2
    assert canonical["random_seed"] == 42
    assert canonical["n_components"] == 0

    reset = metadata.canonicalize_parameters({"split_method": "random", "held_out_groups": ["MP5"]})
    assert reset["held_out_groups"] == []

    with pytest.raises(ValueError, match="at least one named group"):
        metadata.canonicalize_parameters({"split_method": "group_holdout"})


@pytest.mark.asyncio
async def test_group_holdout_live_and_generated_execution_agree() -> None:
    dataset = _grouped_dataset()
    node = node_registry.create_node(
        "data.train_test_split",
        "partition",
        {"split_method": "group_holdout", "held_out_groups": ["3"]},
    )

    live = await node.execute(X=dataset)
    namespace = {"dataset": dataset, "np": np, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset"}, indent="", use_scp=False)), namespace)  # noqa: S102
    generated = namespace["results"]["partition"]

    np.testing.assert_array_equal(live["train_indices"], generated["train_indices"])
    np.testing.assert_array_equal(live["test_indices"], generated["test_indices"])
    live_step = get_processing_history(live["X_train"])[-1]
    assert live_step["parameters"]["held_out_groups"] == [3]


@pytest.mark.parametrize("method", ["kennard_stone", "duplex", "spxy"])
def test_space_filling_ignores_an_attached_group_authority_without_claiming_it(method: str) -> None:
    """A space-filling method covers the spectral extremes, grouped or not.

    Selecting a grouping column names a validation authority; it is not by
    itself a request to partition by it. These methods select individual samples
    by distance and have no whole-group definition, so they cannot hold a group
    out and must not pretend to. The partition therefore matches the ungrouped
    one exactly, while the plan still records that an authority was attached:
    n_groups counts it and held_out_groups stays empty.
    """

    dataset = _grouped_dataset()
    groups = bind_split_groups(dataset)
    # spxy is defined on a numeric response, and this fixture's target is
    # categorical. That constraint is about target dtype, not grouping, so give
    # spxy a numeric response rather than dropping it from the comparison.
    target = np.arange(dataset.X.shape[0], dtype=np.float64).reshape(-1, 1) if method == "spxy" else dataset.target

    ungrouped = plan_train_test_split(dataset.X, target, method=method, test_size=0.25)
    grouped = plan_train_test_split(dataset.X, target, method=method, test_size=0.25, groups=groups)

    assert np.array_equal(np.sort(grouped.train_indices), np.sort(ungrouped.train_indices))
    assert np.array_equal(np.sort(grouped.test_indices), np.sort(ungrouped.test_indices))
    # No group was held out, and the plan says so rather than implying otherwise.
    assert grouped.held_out_groups is None
    # The attached authority is still recorded and bound, so the two plans are
    # distinguishable and each stays reproducible from its own inputs.
    assert grouped.n_groups == len(set(np.asarray(groups).tolist()))
    assert grouped.groups_content_digest is not None
    assert grouped.digest != ungrouped.digest


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["kennard_stone", "duplex", "spxy"])
async def test_single_instrument_space_filling_executes_with_bound_group(method: str) -> None:
    """A lone M5 group is valid metadata when the method does not hold groups out."""

    dataset = _one_instrument_continuous_dataset()
    groups = bind_split_groups(dataset)
    assert groups is not None and set(groups.tolist()) == {"M5"}
    node = node_registry.create_node("data.train_test_split", "partition", {"split_method": method, "test_size": 0.25})

    live = await node.execute(X=dataset)
    namespace = {"dataset": dataset, "np": np, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset"}, indent="", use_scp=False)), namespace)  # noqa: S102
    generated = namespace["results"]["partition"]

    np.testing.assert_array_equal(live["train_indices"], generated["train_indices"])
    np.testing.assert_array_equal(live["test_indices"], generated["test_indices"])
    plan = plan_train_test_split(dataset.X, dataset.target, method=method, test_size=0.25, groups=groups)
    assert plan.n_groups == 1
    assert plan.held_out_groups is None


def test_single_instrument_group_partition_still_refuses() -> None:
    dataset = _one_instrument_continuous_dataset()
    with pytest.raises(ValueError, match="at least two distinct groups"):
        plan_train_test_split(dataset.X, dataset.target, method="random", groups=bind_split_groups(dataset))


@pytest.mark.asyncio
async def test_node_rebinds_valid_group_supervision_on_both_outputs_and_in_generated_code() -> None:
    dataset = _grouped_dataset()
    node = node_registry.create_node(
        "data.train_test_split",
        "partition",
        {"split_method": "stratified", "test_size": 0.25, "random_seed": 11},
    )

    live = await node.execute(X=dataset)
    namespace = {"dataset": dataset, "np": np, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset"}, indent="", use_scp=False)), namespace)  # noqa: S102
    generated = namespace["results"]["partition"]

    for result in (live, generated):
        train_groups = bind_split_groups(result["X_train"])
        assert train_groups is not None
        assert result["X_test"].meta.get("supervision_binding") is None
        assert result["X_train"].meta["supervision_binding"]["sample_count"] == len(result["train_indices"])
        assert result["X_test"].sample_axis.sample_table["block"] == [
            int(value) for value in bind_split_groups(dataset)[result["test_indices"]]
        ]
    np.testing.assert_array_equal(live["train_indices"], generated["train_indices"])


def test_grouped_stratified_holdout_does_not_require_minority_support_for_every_cv_fold() -> None:
    # Eleven independent specimens, with three replicates each and 7/2/2
    # class support. A three-specimen holdout can represent all three classes.
    specimen_classes = np.asarray(["a", "c", "b", "a", "a", "a", "a", "a", "b", "a", "c"])
    groups = np.tile(np.asarray([1, 5, 4, 3, 6, 0, 2, 7, 8, 9, 10]), 3)
    y = np.tile(specimen_classes, 3)
    X = np.arange(66, dtype=float).reshape(33, 2)
    plan = plan_train_test_split(X, y, method="stratified", test_size=0.25, random_seed=42, groups=groups)
    repeat = plan_train_test_split(X, y, method="stratified", test_size=0.25, random_seed=42, groups=groups)
    assert len(plan.test_indices) == 9
    assert len(plan.train_indices) == 24
    assert set(y[plan.train_indices]) == set(y[plan.test_indices]) == {"a", "b", "c"}
    assert set(groups[plan.train_indices]).isdisjoint(groups[plan.test_indices])
    np.testing.assert_array_equal(plan.test_indices, repeat.test_indices)
    changed_X = plan_train_test_split(X * -17, y, method="stratified", test_size=0.25, random_seed=42, groups=groups)
    np.testing.assert_array_equal(plan.test_indices, changed_X.test_indices)


def test_grouped_stratified_holdout_refuses_a_class_with_one_independent_specimen() -> None:
    groups = np.repeat(np.arange(8), 3)
    y = np.repeat(["a"] * 7 + ["b"], 3)
    with pytest.raises(ValueError, match="independent group support"):
        plan_train_test_split(np.ones((24, 2)), y, method="stratified", test_size=0.25, groups=groups)


def test_group_digest_prevents_materializing_a_plan_against_changed_group_identity() -> None:
    dataset = _grouped_dataset()
    groups = bind_split_groups(dataset)
    assert groups is not None
    plan = plan_train_test_split(dataset.X, dataset.target, method="random", test_size=0.25, groups=groups)
    changed = np.array(groups, copy=True)
    changed[0] = 99

    with pytest.raises(ValueError, match="validation group content"):
        materialize_split_outputs(
            dataset,
            dataset.X,
            dataset.target,
            plan,
            node_id="partition",
            groups=changed,
        )


def test_space_filling_planner_has_a_generous_absolute_performance_ceiling() -> None:
    X = np.random.RandomState(85).normal(size=(300, 80))
    with PerformanceCeiling("data.train_test_split", "300x80-duplex", 5.0).measure():
        plan = plan_train_test_split(X, method="duplex", test_size=0.2, n_components=8)

    assert plan.train_indices.size == 240
