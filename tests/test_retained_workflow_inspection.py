"""Unavailable workspaces preserve inert evidence without invoking node code."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from spectra_sherpa.app.services.dag.pack_requirements import capture_pack_graph_binding
from spectra_sherpa.app.services.retained_workflow_inspection import inspect_saved_workflow
from tests.test_pack_manifest import pack
from tests.test_pack_requirements import FixtureRegistry, graph


def saved(node_type, binding=None):
    return SimpleNamespace(
        name="Historical graph",
        pack_binding=binding,
        nodes=[
            SimpleNamespace(
                node_id="0",
                node_type=node_type,
                label="<script>inert</script>",
                parameters={"count": 9007199254740993, "units": "mg/L", "role": "held_out"},
            )
        ],
        edges=[],
    )


@pytest.mark.parametrize("node_type", ["pro.absent.operation", "legacy.unknown_operation"])
def test_unknown_operations_are_read_only_even_without_pack_prefix(node_type):
    workflow = saved(node_type)
    result = inspect_saved_workflow(workflow, registry=FixtureRegistry())
    assert result.read_only
    assert result.model_dump()["read_only"] is True
    assert result.unavailable_node_ids == ("0",)
    assert result.graph.nodes[0].node_type == node_type
    assert result.graph.nodes[0].label == "<script>inert</script>"
    assert "9007199254740993" in result.graph.nodes[0].parameters_json
    assert result.graph.nodes[0].parameters == workflow.nodes[0].parameters


def test_matching_oss_identity_does_not_claim_parameter_or_entitlement_admission():
    result = inspect_saved_workflow(saved("preprocess.clip_floor"), registry=FixtureRegistry())
    # Even nonsensical parameters are read without parameter callbacks. This is
    # an availability projection, not a successful execution preflight.
    assert result is None


@pytest.mark.parametrize("changed", ["missing", "build", "contract"])
def test_unavailable_pack_preserves_original_binding(changed):
    original = pack()
    binding = capture_pack_graph_binding(graph(original.nodes[0]), registry=FixtureRegistry(original))
    workflow = saved(original.nodes[0], binding.model_dump(mode="json"))
    before = deepcopy(workflow.pack_binding)
    registry = {
        "missing": FixtureRegistry(),
        "build": FixtureRegistry(pack(build_sha256="b" * 64)),
        "contract": FixtureRegistry(original, contract="d" * 64),
    }[changed]
    result = inspect_saved_workflow(workflow, registry=registry)
    assert result.read_only and result.binding_unavailable
    assert result.graph.pack_binding == binding
    assert workflow.pack_binding == before


async def test_saved_workflow_route_returns_inert_inspection_after_pack_removal(test_session, test_user, monkeypatch):
    from spectra_sherpa.app.api.v1.routes.workflows import crud
    from spectra_sherpa.app.schemas.workflows import WorkflowCreate
    from spectra_sherpa.app.services.dag.pack_execution_access import use_pack_execution_authorizer
    from tests.pack_retention_fixtures import authorize_retained_fixture, make_retained_registry

    registry = make_retained_registry(monkeypatch)
    with use_pack_execution_authorizer(authorize_retained_fixture):
        detail = await crud.persist_workflow(
            WorkflowCreate(name="Removed pack", nodes=[{"node_id": "pack", "node_type": "pro.reference.record"}]),
            session=test_session,
            current_user=test_user,
        )
    denied = await crud.get_workflow(detail.id, session=test_session, current_user=test_user)
    assert denied.retained_inspection.read_only
    assert denied.retained_inspection.graph.pack_binding == detail.pack_binding
    registry._nodes.pop("pro.reference.record")
    registry._pack_manifests = ()
    result = await crud.get_workflow(detail.id, session=test_session, current_user=test_user)
    assert result.retained_inspection.read_only
    assert result.retained_inspection.graph.pack_binding == detail.pack_binding
    assert result.retained_inspection.unavailable_node_ids == ("pack",)
