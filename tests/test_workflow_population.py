"""The source, not a model or plot, owns workflow observation curation."""

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.workflow_population import OBSERVATION_REF, source_population_outputs


def source():
    return SherpaDataset(
        np.arange(600, dtype=float).reshape(150, 4),
        sample_axis=SampleAxis(count=150, labels=["editable"] * 150),
        target=np.arange(150, dtype=float),
    )


def test_135_142_exclusion_subset_restore_and_restore_all():
    data = source()
    first = source_population_outputs(data, node_id="load")
    rows = first["exclusions"]["rows"]
    decision = {
        "source_digest": first["exclusions"]["source_digest"],
        "excluded_refs": [rows[134]["observation_ref"], rows[141]["observation_ref"]],
    }
    excluded = source_population_outputs(data, node_id="load", exclusions=decision)
    assert excluded["default"].shape == (148, 4)
    assert excluded["target"].shape[0] == 148
    assert excluded["__source_population"].shape == (150, 4)
    assert excluded["exclusions"]["identity_basis"] == "source_bound_row"
    assert excluded["exclusions"]["rows"][134]["result_row"] is None
    assert excluded["exclusions"]["rows"][135]["result_row"] == 135
    assert getattr(excluded["default"].sample_axis, OBSERVATION_REF)[134] == rows[135]["observation_ref"]
    decision["excluded_refs"] = decision["excluded_refs"][1:]
    restored = source_population_outputs(data, node_id="load", exclusions=decision)
    assert restored["default"].shape == (149, 4)
    assert restored["exclusions"]["rows"][134]["included"] is True
    assert restored["exclusions"]["rows"][141]["included"] is False
    assert source_population_outputs(data, node_id="load")["default"].shape == (150, 4)
    assert data.sample_axis.include_mask is None  # no mutation of My Dataset
    assert data.sample_axis.sample_table is None


def test_restore_does_not_override_source_curation():
    data = source()
    axis = data.sample_axis
    axis.include_mask = [False] + [True] * 149
    data.sample_axis = axis
    result = source_population_outputs(data, node_id="load")
    assert result["default"].n_samples == 149
    assert result["exclusions"]["workflow_excluded_count"] == 0
    assert result["exclusions"]["rows"][0]["source_included"] is False


def test_navigation_fallback_preserves_time_axis_and_materializes_large_source_inclusion():
    from spectra_sherpa.app.lib.axes import TimeAxis

    data = SherpaDataset(np.ones((3, 4)))
    data._axes[0] = TimeAxis(values=np.array([0.0, 2.0, 4.0]), units="s")  # generic dim-0 fixture
    before = data.scientific_digest
    loaded = source_population_outputs(data, node_id="time")
    assert isinstance(loaded["default"].get_observation_axis(), TimeAxis)
    assert loaded["default"].scientific_digest == before
    large = SherpaDataset(
        np.ones((100001, 2)), sample_axis=SampleAxis(count=100001, include_mask=[False] + [True] * 100000)
    )
    loaded = source_population_outputs(large, node_id="large")
    assert loaded["default"].n_samples == 100000
    assert loaded["exclusions"]["availability"] == "unavailable"
    assert large.n_samples == 100001


def test_nd_source_preserves_shape_and_masks_until_explicit_projection():
    data = SherpaDataset(np.arange(24.0).reshape(2, 3, 4), sample_axis=SampleAxis(count=2, include_mask=[True, False]))
    before = data.scientific_digest
    result = source_population_outputs(data, node_id="nd")
    assert result["default"].shape == (2, 3, 4)
    assert result["default"].scientific_digest == before
    np.testing.assert_array_equal(result["default"].sample_axis.include_mask, [True, False])
    assert result["exclusions"]["availability"] == "unavailable"
    assert "__source_population" not in result
    with pytest.raises(ValueError, match="two-dimensional"):
        source_population_outputs(data, node_id="nd", exclusions={"source_digest": "a" * 64, "excluded_refs": []})


def test_private_display_edges_refuse_at_insertion_and_runtime():
    from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode

    executor = DAGExecutor(process_pool=False)
    executor.add_node(WorkflowNode("load", "data.file_load", {"experiment_id": 1, "file_id": 1}))
    executor.add_node(WorkflowNode("stats", "stats.summary", {}))
    edge = WorkflowEdge("load", "stats", "__workflow_population")
    with pytest.raises(ValueError, match="not a connectable"):
        executor.add_edge(edge)
    executor.edges.append(edge)  # bypassing insertion cannot bypass runtime admission
    with pytest.raises(ValueError, match="not a connectable"):
        executor._get_node_inputs("stats")


def test_executable_export_never_silently_drops_source_curation():
    from types import SimpleNamespace

    from spectra_sherpa.app.services.python_export import build_canonical_executable_export

    state = source_population_outputs(source(), node_id="load")["exclusions"]
    node = SimpleNamespace(
        node_id="load",
        node_type="data.collection_load",
        parameters={
            "workflow_exclusions": {
                "source_digest": state["source_digest"],
                "excluded_refs": [state["rows"][134]["observation_ref"]],
            }
        },
    )
    with pytest.raises(ValueError, match="cannot yet replay"):
        build_canonical_executable_export(SimpleNamespace(nodes=[node], edges=[]), export_context=None)


def test_source_binding_refuses_wrong_values_order_and_node():
    data = source()
    first = source_population_outputs(data, node_id="load")["exclusions"]
    decision = {"source_digest": first["source_digest"], "excluded_refs": [first["rows"][134]["observation_ref"]]}
    with pytest.raises(ValueError, match="different source"):
        source_population_outputs(data[::-1], node_id="load", exclusions=decision)
    with pytest.raises(ValueError, match="unknown source"):
        source_population_outputs(data, node_id="other", exclusions=decision)


def test_typed_ids_are_separate_from_editable_labels():
    data = source()
    axis = data.sample_axis
    axis.sample_table = {"sample_id": [f"id-{i}" for i in range(150)]}
    data.sample_axis = axis
    result = source_population_outputs(data, node_id="load")
    assert result["exclusions"]["identity_basis"] == "typed_sample_id"
    assert result["exclusions"]["rows"][134]["sample_id"] == "id-134"
    assert result["exclusions"]["rows"][134]["sample_label"] == "editable"


def test_unknown_duplicate_and_empty_population_refused():
    data = source()
    state = source_population_outputs(data, node_id="load")["exclusions"]
    with pytest.raises(ValueError, match="unknown source"):
        source_population_outputs(
            data, node_id="load", exclusions={"source_digest": state["source_digest"], "excluded_refs": ["unknown"]}
        )
    with pytest.raises(ValueError, match="unique"):
        source_population_outputs(
            data, node_id="load", exclusions={"source_digest": state["source_digest"], "excluded_refs": ["x", "x"]}
        )
    with pytest.raises(ValueError, match="at least one"):
        source_population_outputs(
            data,
            node_id="load",
            exclusions={
                "source_digest": state["source_digest"],
                "excluded_refs": [row["observation_ref"] for row in state["rows"]],
            },
        )


def test_source_custody_changes_refs_even_when_science_is_identical():
    first = source()
    first.meta["source_collection"] = {"manifest_digest": "a" * 64}
    second = first.copy()
    second.meta["source_collection"] = {"manifest_digest": "b" * 64}
    old = source_population_outputs(first, node_id="load")["exclusions"]
    with pytest.raises(ValueError, match="different source"):
        source_population_outputs(
            second,
            node_id="load",
            exclusions={"source_digest": old["source_digest"], "excluded_refs": [old["rows"][0]["observation_ref"]]},
        )


def test_navigation_columns_do_not_grant_sample_table_authority_or_break_portable_inputs():
    from spectra_sherpa.app.services.dag.spectral_capability import SpectralCapabilityError, SpectralDatasetCapability

    data = source_population_outputs(source(), node_id="load")["default"]
    SpectralDatasetCapability.from_dataset(data, custody_id="workflow-navigation")
    axis = data.sample_axis
    axis.sample_table = {"unadmitted_target": list(range(data.n_samples))}
    data.sample_axis = axis
    with pytest.raises(SpectralCapabilityError, match="sample_table is not admitted"):
        SpectralDatasetCapability.from_dataset(data, custody_id="workflow-navigation")


def test_navigation_does_not_change_scientific_identity_without_curation():
    data = source()
    loaded = source_population_outputs(data, node_id="load")["default"]
    assert loaded.scientific_digest == data.scientific_digest
    assert loaded.sample_axis.sample_table is None
    assert loaded.sample_axis.workflow_observation_refs is not None
    restored = SherpaDataset.from_dict(loaded.to_dict())
    assert restored.sample_axis.workflow_observation_refs == loaded.sample_axis.workflow_observation_refs
    assert restored.scientific_digest == loaded.scientific_digest


def test_navigation_limit_does_not_block_large_dataset_loading():
    data = SherpaDataset(np.ones((100001, 1)))
    loaded = source_population_outputs(data, node_id="load")
    assert loaded["default"] is data
    assert loaded["exclusions"]["availability"] == "unavailable"
    assert loaded["default"].n_samples == 100001


def test_full_population_is_not_a_connectable_numerical_port():
    from spectra_sherpa.app.services.dag.nodes.data.file_load_node import FileLoadNode
    from spectra_sherpa.app.services.dag.nodes.data.loaders import CollectionLoadNode, LoadGroupNode

    for cls in (CollectionLoadNode, LoadGroupNode, FileLoadNode):
        assert "source_population" not in {port.name for port in cls.metadata.output_ports}
        assert any(
            port.name == "exclusions" and port.type_ref.endswith("WorkflowPopulation/1.0")
            for port in cls.metadata.output_ports
        )


def test_axis_free_projection_preserves_lineage_without_copying_fit_receipts():
    from spectra_sherpa.app.services.dag.population_display import applied_dataset

    data = source_population_outputs(source(), node_id="load")["__source_population"]
    template = SherpaDataset(np.ones((148, 4)))
    template.provenance.append(op_id="preprocess.scale", parameters={"method": "autoscale"})
    template.meta["supervision_binding"] = {"active_only": True}
    projected = applied_dataset(np.ones((150, 4)), data, template)
    assert projected.feature_axis is None
    assert "supervision_binding" not in projected.meta
    assert [step["op_id"] for step in projected.provenance.to_list()] == [
        "preprocess.scale",
        "spectrasherpa.population_display/1",
    ]


def test_prepared_navigation_is_rescoped_on_a_new_source():
    original = source_population_outputs(source(), node_id="old")["default"]
    reloaded = source_population_outputs(original, node_id="new")["default"]
    assert all(ref.startswith("new:") for ref in getattr(reloaded.sample_axis, OBSERVATION_REF))


@pytest.mark.asyncio
async def test_pca_companion_applies_retained_fit_without_changing_limits_or_n():
    from types import SimpleNamespace

    from sklearn.datasets import load_iris

    from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge
    from spectra_sherpa.app.services.dag.nodes.diagnostics import OutlierDetectionNode
    from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode, apply_pca_fitted_state
    from spectra_sherpa.app.services.dag.population_display import (
        DISPLAY_KEY,
        application_input,
        retain_population_display,
    )

    data = SherpaDataset(
        load_iris().data, sample_axis=SampleAxis(count=150, labels=[f"Original {i+1}" for i in range(150)])
    )
    state = source_population_outputs(data, node_id="load")["exclusions"]
    loaded = source_population_outputs(
        data,
        node_id="load",
        exclusions={
            "source_digest": state["source_digest"],
            "excluded_refs": [state["rows"][i]["observation_ref"] for i in (134, 141)],
        },
    )
    pca = PCANode("pca", {"n_components": "3", "standardized": True, "scaled": False})
    fitted = await pca.execute(loaded["default"])
    evaluator = OutlierDetectionNode("screen", {"confidence_level": 0.95})
    evaluated = await evaluator.execute(fitted.outputs["diagnostic_state"])

    async def project(node, outputs, inputs):
        return await node.project_population(outputs, inputs)

    executor = SimpleNamespace(
        nodes={"load": object(), "pca": pca, "screen": evaluator},
        _run_population_projection=project,
        results={"load": loaded, "pca": fitted.outputs, "screen": evaluated.outputs},
        edges=[WorkflowEdge("load", "pca"), WorkflowEdge("pca", "screen", "diagnostic_state")],
    )
    for node in ("load", "pca", "screen"):
        await retain_population_display(executor, node)
    display = executor.results["pca"][DISPLAY_KEY]["outputs"]["scores"]
    assert fitted.outputs["scores"].shape == (148, 3)
    assert display.shape == (150, 3)
    assert not bool(display.sample_axis.include_mask[134])
    retained_source = executor.results["load"][DISPLAY_KEY]["outputs"]["default"]
    np.testing.assert_allclose(
        display.X, apply_pca_fitted_state(application_input(retained_source), fitted.outputs["fitted_state"])
    )
    assert len(evaluated.outputs["T2"]) == 148
    overlay = executor.results["screen"][DISPLAY_KEY]["outputs"]
    assert len(overlay["T2"]) == 150
    assert "T2_limit" not in overlay and "Q_limit" not in overlay
    assert overlay["observation_axis"]["labels"][134] == "Original 135"
    assert fitted.outputs["diagnostic_state"]["n_observations"] == 148


@pytest.mark.asyncio
async def test_real_worker_projects_without_refitting_and_keeps_the_lease_after_display_refusal():
    from sklearn.datasets import load_iris

    from spectra_sherpa.app.services.dag.executor import DAGExecutor
    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool
    from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode

    original = SherpaDataset(load_iris().data, sample_axis=SampleAxis(count=150))
    state = source_population_outputs(original, node_id="load")["exclusions"]
    source_outputs = source_population_outputs(
        original,
        node_id="load",
        exclusions={"source_digest": state["source_digest"], "excluded_refs": [state["rows"][134]["observation_ref"]]},
    )
    node = PCANode("pca", {"n_components": "3", "standardized": True, "scaled": False})
    outputs = (await node.execute(source_outputs["default"])).outputs
    pool = IsolatedWorkerPool(max_workers=1)
    executor = DAGExecutor(process_pool=pool)
    async with pool.workflow():
        projected = await executor._run_population_projection(
            node, outputs, {"input_data": source_outputs["__source_population"]}
        )
        assert projected["scores"].shape == (150, 3)
        assert outputs["scores"].shape == (149, 3)
        with pytest.raises(ValueError):
            await executor._run_population_projection(node, {}, {"input_data": source_outputs["__source_population"]})
        again = await executor._run_population_projection(
            node, outputs, {"input_data": source_outputs["__source_population"]}
        )
        np.testing.assert_allclose(again["scores"].X, projected["scores"].X)
    pool.shutdown()


@pytest.mark.asyncio
async def test_optional_worker_timeout_does_not_poison_later_computation():
    import time

    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(max_workers=1)
    async with pool.workflow():
        with pytest.raises(TimeoutError):
            await pool.run(time.sleep, 1, timeout=0.01)
        pool.recover_optional_projection_failure()
        assert await pool.run(abs, -7, timeout=10) == 7
    assert not pool._active
    pool.shutdown()


def test_nested_projection_and_retained_state_count_towards_dispatch_budget():
    from spectra_sherpa.app.services.dag.population_display import projection_within_budget

    matrix = np.zeros((128, 128))
    assert not projection_within_budget({}, {"diagnostic_state": {"scores": matrix}}, limit=1024)
    assert not projection_within_budget({"fitted_state": {"loadings": matrix}}, {}, limit=1024)
    assert projection_within_budget({"scores": matrix}, {"same": matrix}, limit=matrix.nbytes + 1000)
    data = SherpaDataset(np.zeros((1, 2)), sample_axis=SampleAxis(count=1, sample_table={"annotation": ["x" * 8192]}))
    assert not projection_within_budget({}, {"X": data}, limit=1024)
    data = SherpaDataset(np.zeros((1, 2)))
    data.provenance.append(op_id="test", parameters={"annotation": "x" * 8192})
    assert not projection_within_budget({}, {"X": data}, limit=1024)


def test_display_application_rebinds_only_a_valid_supervision_receipt():
    from spectra_sherpa.app.services.dag.population_display import application_input
    from spectra_sherpa.app.services.dag.supervision_binding import (
        admit_attached_sample_table_supervision,
        attach_sample_table_supervision,
    )

    dataset = SherpaDataset(
        np.arange(12.0).reshape(3, 4),
        sample_axis=SampleAxis(
            count=3,
            labels=["a", "b", "c"],
            include_mask=[True, False, True],
            sample_table={"sample_id": ["a", "b", "c"], "Y": [1.0, 2.0, 3.0]},
        ),
    )
    dataset.meta["source_collection"] = {
        key: "a" * 64 for key in ("manifest_digest", "collection_definition_sha256", "scientific_collection_sha256")
    }
    bound = attach_sample_table_supervision(dataset, target_column="Y", target_type="continuous", node_id="attach")
    admitted = application_input(bound)
    assert admit_attached_sample_table_supervision(admitted) is not None
    np.testing.assert_array_equal(admitted.sample_axis.include_mask, [True, True, True])
    np.testing.assert_array_equal(bound.sample_axis.include_mask, [True, False, True])
