"""Ordinary-workbench application tests for canonical fitted artifacts."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.canonical_artifact_store import (
    init_canonical_artifact_store,
)
from spectra_sherpa.app.services.dag.executor_pool import WorkerExecutionContext, _run_node_in_worker
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    execute_candidate_validation,
    execute_selected_candidate_full_refit,
)
from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import (
    FittedPLSV2Node,
    make_fitted_pls_state_envelope,
)
from spectra_sherpa.app.services.dag.nodes.preprocessing.emsc_node import EMSCNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.msc_node import MSCNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.osc_node import OSCNode
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.services.workflow_access import workflow_requires_canonical_artifact_grant
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.canonical_artifact import CanonicalArtifactStoreError, ReadOnlyCanonicalArtifactReader
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.sdk.canonical_application import CanonicalApplicationPlan
from spectra_sherpa.sdk.canonical_capsule import CanonicalWorkflowCapsule
from spectra_sherpa.sdk.canonical_execution_evidence import CanonicalExecutionEvidence
from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifact
from spectra_sherpa.sdk.canonical_full_refit_evidence import CanonicalFullRefitEvidence
from spectra_sherpa.sdk.validate import make_split_plan

MANAGED_OPTIMIZATION_PROFILE = managed_optimization_profile()
APPLICATION_AXIS = np.linspace(900.0, 1900.0, 16)


def test_canonical_artifact_grant_depends_on_binding_mode_not_apply_node_type() -> None:
    """Local fitted-state edges stay local; every imported application requests custody."""

    local_nodes = [
        SimpleNamespace(node_type="model.apply_fitted_pls", parameters={}),
        SimpleNamespace(node_type="classification.apply_plsda", parameters={}),
    ]
    assert workflow_requires_canonical_artifact_grant(local_nodes) is False

    binding = {
        "artifact_digest": "a" * 64,
        "state_node_id": "fit",
        "state_digest": "b" * 64,
        "state_content_digest": "c" * 64,
        "serializer": "canonical-state/1",
        "source_contract_digest": "d" * 64,
    }
    imported_types = {
        "classification.apply_plsda",
        "model.apply_fitted_pls",
        "preprocess.apply_fitted_emsc",
        "preprocess.apply_fitted_msc",
        "preprocess.apply_fitted_osc",
        "preprocess.apply_fitted_scale",
    }
    for node_type in imported_types:
        node = SimpleNamespace(node_type=node_type, parameters=dict(binding))
        assert workflow_requires_canonical_artifact_grant([node]) is True

    partial = SimpleNamespace(
        node_type="model.apply_fitted_pls",
        parameters={"state_digest": "b" * 64},
    )
    assert workflow_requires_canonical_artifact_grant([partial]) is True


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _materialized_application(
    tmp_path: Path,
    *,
    n_components: int = 2,
    fitted_preprocess: tuple[str, dict[str, object]] | None = None,
) -> tuple[CanonicalApplicationPlan, np.ndarray, CanonicalFittedArtifact]:
    rng = np.random.default_rng(20260813)
    axis = APPLICATION_AXIS
    target = np.linspace(-1.0, 1.0, 12)
    nuisance = rng.normal(size=(12, 3)) @ rng.normal(scale=0.08, size=(3, 16))
    X = (
        np.linspace(0.85, 1.15, 12)[:, None] * (1.2 + target[:, None] * np.sin(axis / 175.0) + nuisance)
        + np.linspace(-0.05, 0.05, 12)[:, None]
    )
    split = make_split_plan(X.shape[0], n_splits=3)
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=X, target=target, feature_axis=SpectralAxis(values=axis, units="cm-1")),
        custody_id="public-fixture",
        dataset_ref_digest="a" * 64,
        split_plan_digest=split.digest,
    )
    nodes = [
        *(
            [WorkflowNode("fitted-preprocess", fitted_preprocess[0], fitted_preprocess[1])]
            if fitted_preprocess is not None
            else []
        ),
        WorkflowNode("scale", "preprocess.scale", {"method": "autoscale", "center": True}),
        WorkflowNode("model", "model.fitted_pls", {"n_components": n_components, "scale": True}),
        WorkflowNode("score", "diagnostics.regression_evaluator", {}),
    ]
    graph = admit_validation_graph(
        nodes, [WorkflowEdge(left.node_id, right.node_id) for left, right in zip(nodes, nodes[1:])]
    )
    validation = asyncio.run(execute_candidate_validation(graph, capability, split))
    refit = asyncio.run(execute_selected_candidate_full_refit(graph, capability, validation))
    versions = {
        str(requirement["distribution"]): str(requirement["version"])
        for node in graph.nodes
        for requirement in MANAGED_OPTIMIZATION_PROFILE.operation(node.operation_id).payload["runtime_requirements"]
    }
    runtime = MANAGED_OPTIMIZATION_PROFILE.runtime_attestation(
        tuple(node.operation_id for node in graph.nodes), version_resolver=versions.__getitem__
    ).as_dict()
    evidence = CanonicalExecutionEvidence.from_validation_execution(validation, runtime_attestation=runtime)
    refit_evidence = CanonicalFullRefitEvidence.from_full_refit_execution(refit)
    request = _request(graph, capability, split.digest, runtime)
    capsule = CanonicalWorkflowCapsule.from_admitted_request(request, evidence, full_refit_evidence=refit_evidence)
    artifact = CanonicalFittedArtifact.from_full_refit_execution(refit)
    source = artifact.write_new((tmp_path / f"runner-output-{n_components}").resolve())
    store = init_canonical_artifact_store(tmp_path)
    installed = store.install_from_directory(source)
    # Re-importing verified bytes is safe and does not create a second mutable
    # copy.  e3 will add project/user admission around this installer.
    assert store.install_from_directory(source).artifact_digest == installed.artifact_digest
    return CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact), X, artifact


def _request(
    graph, capability: SpectralDatasetCapability, split_digest: str, runtime: dict[str, object]
) -> dict[str, object]:
    import hashlib
    import json

    unsigned: dict[str, object] = {
        "protocol": "spectra-canonical-runner/5",
        "execution_purpose": "candidate_validation",
        "winner_refit_authority_digest": None,
        "confirmation_authority": None,
        "request_id": "canonical-request-001",
        "campaign_id": "canonical-campaign-001",
        "candidate_id": "canonical-candidate-001",
        "profile": {
            "profile_id": MANAGED_OPTIMIZATION_PROFILE.profile_id,
            "profile_version": MANAGED_OPTIMIZATION_PROFILE.profile_version,
            "profile_digest": MANAGED_OPTIMIZATION_PROFILE.digest,
        },
        "graph": graph.as_dict(),
        "evaluation_kind": "public_reproducibility",
        "dataset_role": "public_reproducibility",
        "capability_digest": capability.envelope_digest,
        "dataset_content_digest": capability.content_digest,
        "dataset_ref_digest": "a" * 64,
        "dataset_shape": {"n_samples": 12, "n_features": 16, "grouped": False},
        "split_digest": split_digest,
        "validation": {
            "schema_version": "spectra-canonical-validation/3",
            "task_type": "regression",
            "selection": "group_kfold_when_groups_else_kfold",
            "outer_splits": 3,
            "shuffle": False,
            "metric_registry_version": "2",
            "primary_metric": "rmse",
        },
        "search": {
            "schema_version": "spectra-canonical-search-execution/2",
            "strategy": "finite_declared_parameter_grid",
            "search_space_digest": "9" * 64,
            "candidate_ordinal": 1,
            "candidate_count": 2,
            "candidate_id": "canonical-candidate-001",
            "candidate_graph_digest": graph.digest,
        },
        "resources": {
            "schema_version": "spectra-canonical-resources/1",
            "timeout_seconds": 30,
            "cpu_seconds": 30,
            "memory_bytes": 1024**3,
            "temp_bytes": 512 * 1024**2,
            "max_file_bytes": 128 * 1024**2,
            "stdout_bytes": 65536,
            "stderr_bytes": 16384,
        },
        "runtime_attestation": runtime,
    }
    return {
        **unsigned,
        "request_digest": hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(
                "utf-8"
            )
        ).hexdigest(),
    }


def _application_nodes(plan: CanonicalApplicationPlan) -> tuple[WorkflowNode, WorkflowNode]:
    scale, model = plan.payload["nodes"]
    return (
        WorkflowNode(scale["node_id"], scale["application_operation_id"], scale["artifact_binding"]),
        WorkflowNode(model["node_id"], model["application_operation_id"], model["artifact_binding"]),
    )


def _application_input(X: np.ndarray, rows: int) -> SherpaDataset:
    return SherpaDataset(
        X=X[:rows],
        feature_axis=SpectralAxis(values=APPLICATION_AXIS, units="cm-1"),
    )


def _canonical_runtime(tmp_path: Path, artifact_digest: str) -> ExecutionRuntime:
    return ExecutionRuntime(
        canonical_artifact_reader=ReadOnlyCanonicalArtifactReader(
            tmp_path,
            allowed_artifact_digests=(artifact_digest,),
        )
    )


async def _run_with_runtime(node, runtime: ExecutionRuntime, *args, **kwargs):
    node.bind_execution_runtime(runtime)
    return await node.run(*args, **kwargs)


def test_artifact_application_nodes_have_closed_local_only_contracts() -> None:
    """Imported-model execution is explicit, not a legacy-node exception."""

    for operation_id in (
        "preprocess.apply_fitted_emsc",
        "preprocess.apply_fitted_msc",
        "preprocess.apply_fitted_osc",
        "preprocess.apply_fitted_scale",
        "model.apply_fitted_pls",
    ):
        metadata = node_registry.get_metadata(operation_id)
        contract = metadata.resolved_execution_contract()

        assert contract is not None
        assert contract.payload["operation_id"] == operation_id
        assert contract.payload["lifecycle_kind"] == "artifact_application"
        assert list(contract.payload["managed_optimization_eligibility"]) == ["local"]
        assert list(contract.payload["required_worker_capabilities"]) == ["read_canonical_fitted_artifact"]


@pytest.mark.parametrize(
    ("source_operation", "parameters", "application_operation", "source_node_class"),
    [
        ("preprocess.msc", {"reference_method": "mean"}, "preprocess.apply_fitted_msc", MSCNode),
        (
            "preprocess.emsc",
            {"reference_method": "median", "poly_order": 1},
            "preprocess.apply_fitted_emsc",
            EMSCNode,
        ),
        ("preprocess.osc", {"n_components": 1}, "preprocess.apply_fitted_osc", OSCNode),
    ],
)
def test_fitted_preprocessing_application_uses_the_exact_imported_state(
    tmp_path: Path,
    source_operation: str,
    parameters: dict[str, object],
    application_operation: str,
    source_node_class,
) -> None:
    plan, X, artifact = _materialized_application(
        tmp_path,
        fitted_preprocess=(source_operation, parameters),
    )
    projected = plan.payload["nodes"][0]
    assert projected["application_operation_id"] == application_operation
    application_input = _application_input(X, 3)
    expected = source_node_class("expected", {}).apply_fitted_state(
        application_input,
        json_load(artifact.state_bytes["fitted-preprocess"]),
    )

    observed = asyncio.run(
        _run_with_runtime(
            node_registry.create_node(
                projected["application_operation_id"],
                projected["node_id"],
                projected["artifact_binding"],
            ),
            _canonical_runtime(tmp_path, artifact.artifact_digest),
            application_input,
        )
    )

    np.testing.assert_allclose(observed.outputs["default"].X, expected.X, rtol=1e-13, atol=1e-13)
    assert observed.diagnostics["canonical_artifact"]["artifact_digest"] == artifact.artifact_digest


def test_canonical_application_nodes_apply_the_artifact_without_refitting(tmp_path: Path) -> None:
    plan, X, artifact = _materialized_application(tmp_path)
    scale_node, model_node = _application_nodes(plan)
    from spectra_sherpa.app.services.dag.node_base import node_registry

    input_data = _application_input(X, 3)
    runtime = _canonical_runtime(tmp_path, artifact.artifact_digest)
    applied_scale = asyncio.run(
        _run_with_runtime(
            node_registry.create_node(scale_node.node_type, scale_node.node_id, scale_node.parameters),
            runtime,
            input_data,
        )
    )
    applied_model = asyncio.run(
        _run_with_runtime(
            node_registry.create_node(model_node.node_type, model_node.node_id, model_node.parameters),
            runtime,
            applied_scale.outputs["default"],
        )
    )
    scale_state = json_load(artifact.state_bytes["scale"])
    expected_scale = (input_data.X - np.asarray(scale_state["mean"], dtype=np.float64)) / np.asarray(
        scale_state["scale"], dtype=np.float64
    )
    model_state = json_load(artifact.state_bytes["model"])
    expected_predictions = (expected_scale - np.asarray(model_state["feature_offset"], dtype=np.float64)) @ np.asarray(
        model_state["coefficients"], dtype=np.float64
    ) + np.asarray(model_state["prediction_offset"], dtype=np.float64)
    np.testing.assert_allclose(applied_scale.outputs["default"].X, expected_scale)
    np.testing.assert_allclose(applied_model.outputs["default"], expected_predictions)
    assert applied_model.diagnostics["canonical_artifact"]["artifact_digest"] == artifact.artifact_digest
    assert applied_model.outputs["default"].shape == (3, 1)
    with pytest.raises(RuntimeError, match="node execution runtime is unavailable"):
        asyncio.run(
            node_registry.create_node(model_node.node_type, model_node.node_id, model_node.parameters).run(input_data)
        )


def test_local_and_imported_pls_state_converge_on_the_same_application_math(tmp_path: Path) -> None:
    plan, X, artifact = _materialized_application(tmp_path)
    scale_node, imported_node = _application_nodes(plan)
    scaled = asyncio.run(
        _run_application_node_in_parent(
            scale_node, _application_input(X, 3), _canonical_runtime(tmp_path, artifact.artifact_digest)
        )
    ).outputs["default"]
    local_node = node_registry.create_node("model.apply_fitted_pls", "local-apply", {})
    local_result = asyncio.run(
        local_node.run(
            default=scaled,
            fitted_state=make_fitted_pls_state_envelope(json_load(artifact.state_bytes["model"])),
        )
    )
    imported_result = asyncio.run(
        _run_with_runtime(
            node_registry.create_node(
                imported_node.node_type,
                imported_node.node_id,
                imported_node.parameters,
            ),
            _canonical_runtime(tmp_path, artifact.artifact_digest),
            scaled,
        )
    )

    np.testing.assert_allclose(local_result.outputs["default"], imported_result.outputs["default"])
    assert local_result.diagnostics["fitted_state_custody"]["mode"] == "local_fitted_state"
    assert imported_result.diagnostics["fitted_state_custody"]["mode"] == "canonical_artifact"


def test_imported_pls_refuses_suffix_era_state_without_response_authority(tmp_path: Path) -> None:
    plan, X, _artifact = _materialized_application(tmp_path)
    _scale_node, imported_node = _application_nodes(plan)
    parameters = dict(imported_node.parameters)
    parameters["source_contract_digest"] = "ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d"

    class LegacyReader:
        def load_bound_state(self, *args, **kwargs):
            pytest.fail("incompatible historical state must refuse before loading")

    with pytest.raises(ValueError, match="producer contract is not compatible"):
        asyncio.run(
            _run_with_runtime(
                node_registry.create_node("model.apply_fitted_pls", "model", parameters),
                ExecutionRuntime(canonical_artifact_reader=LegacyReader()),
                _application_input(X, 3),
            )
        )


def test_local_pls_application_does_not_open_artifact_custody_in_a_worker(tmp_path: Path) -> None:
    X = np.arange(48, dtype=float).reshape(6, 8)
    training = SherpaDataset(X=X, target=X[:, 0] * 0.2)
    fit_result = asyncio.run(FittedPLSV2Node("local-fit", {"n_components": 1}).run(training))
    context = WorkerExecutionContext(
        execution_id="local-state-application",
        runtime=ExecutionRuntime(),
        origin_pid=os.getpid(),
    )

    result = _run_node_in_worker(
        "model.apply_fitted_pls",
        "local-apply",
        {},
        (),
        {
            "default": SherpaDataset(X=X[:2]),
            "fitted_state": fit_result.outputs["fitted_state"],
        },
        context,
    )

    assert result.outputs["default"].shape == (2, 1)
    assert result.diagnostics["fitted_state_custody"]["mode"] == "local_fitted_state"


def test_application_node_rejects_an_extra_or_swapped_artifact_binding(tmp_path: Path) -> None:
    plan, X, _artifact = _materialized_application(tmp_path)
    _scale, model = _application_nodes(plan)
    parameters = dict(model.parameters)
    parameters["artifact_digest"] = "0" * 64
    from spectra_sherpa.app.services.dag.node_base import node_registry

    with pytest.raises(CanonicalArtifactStoreError, match="not authorized by this read grant"):
        asyncio.run(
            _run_with_runtime(
                node_registry.create_node(model.node_type, model.node_id, parameters),
                _canonical_runtime(tmp_path, _artifact.artifact_digest),
                SherpaDataset(X=X[:1]),
            )
        )
    parameters = dict(model.parameters)
    parameters["extra"] = "not admitted"
    with pytest.raises(ValueError, match="parameters contain undeclared fields"):
        asyncio.run(node_registry.create_node(model.node_type, model.node_id, parameters).run(SherpaDataset(X=X[:1])))


def test_canonical_application_model_runs_in_a_fresh_spawned_worker(tmp_path: Path) -> None:
    plan, X, artifact = _materialized_application(tmp_path)
    scale, model = _application_nodes(plan)
    runtime = _canonical_runtime(tmp_path, artifact.artifact_digest)
    context = WorkerExecutionContext(
        execution_id="canonical-application-test",
        runtime=runtime,
        capabilities=("read_canonical_fitted_artifact",),
        origin_pid=os.getpid(),
    )
    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    except (NotImplementedError, PermissionError, OSError) as exc:
        pytest.skip(f"spawn worker unavailable: {exc}")
    try:
        scaled = asyncio.run(_run_application_node_in_parent(scale, _application_input(X, 2), runtime))
        result = pool.submit(
            _run_node_in_worker,
            model.node_type,
            model.node_id,
            model.parameters,
            (),
            {"default": scaled.outputs["default"]},
            context,
        ).result(timeout=30)
    finally:
        pool.shutdown(wait=True)

    assert result.outputs["default"].shape == (2, 1)
    assert result.diagnostics["canonical_artifact"]["artifact_digest"] == artifact.artifact_digest
    provenance = result.diagnostics["worker_execution"]
    assert provenance["mode"] == "spawned_worker"
    assert provenance["worker_pid"] != os.getpid()


def test_application_node_fails_closed_without_a_trusted_read_grant(tmp_path: Path) -> None:
    plan, X, _artifact = _materialized_application(tmp_path)
    _scale, model = _application_nodes(plan)
    from spectra_sherpa.app.services.dag.node_base import node_registry

    with pytest.raises(RuntimeError, match="node execution runtime is unavailable"):
        asyncio.run(
            node_registry.create_node(model.node_type, model.node_id, model.parameters).run(SherpaDataset(X=X[:1]))
        )


def test_read_grant_cannot_apply_another_project_artifact_in_the_same_root(tmp_path: Path) -> None:
    _first_plan, _first_X, first_artifact = _materialized_application(tmp_path, n_components=1)
    second_plan, second_X, second_artifact = _materialized_application(tmp_path, n_components=2)
    _second_scale, second_model = _application_nodes(second_plan)
    from spectra_sherpa.app.services.dag.node_base import node_registry

    assert first_artifact.artifact_digest != second_artifact.artifact_digest
    # Both distinct artifacts reside in the same application-owned root before
    # e3b installs durable project custody. A grant for one must never become
    # root-wide authority.
    with pytest.raises(CanonicalArtifactStoreError, match="not authorized by this read grant"):
        asyncio.run(
            _run_with_runtime(
                node_registry.create_node(second_model.node_type, second_model.node_id, second_model.parameters),
                _canonical_runtime(tmp_path, first_artifact.artifact_digest),
                SherpaDataset(X=second_X[:1]),
            )
        )


def test_canonical_read_capabilities_do_not_bleed_between_async_executions(tmp_path: Path) -> None:
    _first_plan, _first_X, first_artifact = _materialized_application(tmp_path, n_components=1)
    _second_plan, _second_X, second_artifact = _materialized_application(tmp_path, n_components=2)

    async def _read_with_its_own_runtime(artifact: CanonicalFittedArtifact) -> str:
        runtime = _canonical_runtime(tmp_path, artifact.artifact_digest)
        await asyncio.sleep(0)
        return runtime.require_canonical_artifact_reader().load(artifact.artifact_digest).artifact_digest

    async def _read_both() -> list[str]:
        return await asyncio.gather(
            _read_with_its_own_runtime(first_artifact),
            _read_with_its_own_runtime(second_artifact),
        )

    assert asyncio.run(_read_both()) == [first_artifact.artifact_digest, second_artifact.artifact_digest]
    with pytest.raises(PermissionError, match="canonical fitted-artifact read capability is unavailable"):
        ExecutionRuntime().require_canonical_artifact_reader()


def test_spawned_application_node_rejects_missing_scoped_grant(tmp_path: Path) -> None:
    plan, X, _artifact = _materialized_application(tmp_path)
    scale, model = _application_nodes(plan)
    context = WorkerExecutionContext(
        execution_id="canonical-application-without-grant",
        runtime=ExecutionRuntime(),
        capabilities=("read_canonical_fitted_artifact",),
        origin_pid=os.getpid(),
    )
    scaled = asyncio.run(
        _run_application_node_in_parent(
            scale,
            _application_input(X, 1),
            _canonical_runtime(tmp_path, _artifact.artifact_digest),
        )
    )

    with pytest.raises(PermissionError, match="canonical fitted-artifact read capability is unavailable"):
        _run_node_in_worker(
            model.node_type,
            model.node_id,
            model.parameters,
            (),
            {"default": scaled.outputs["default"]},
            context,
        )


async def _run_application_node_in_parent(
    node: WorkflowNode,
    dataset: SherpaDataset,
    runtime: ExecutionRuntime,
):
    from spectra_sherpa.app.services.dag.node_base import node_registry

    instance = node_registry.create_node(node.node_type, node.node_id, node.parameters)
    instance.bind_execution_runtime(runtime)
    return await instance.run(dataset)


def json_load(value: bytes) -> dict[str, object]:
    loaded = json.loads(value)
    assert isinstance(loaded, dict)
    return loaded
