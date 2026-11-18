"""Retained bindings cannot silently acquire current code identity on reopen."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from spectra_sherpa.app.services.pack_requirements import (
    PackBindingAdmissionError,
    capture_pack_graph_binding,
    require_matching_pack_binding,
)
from spectra_sherpa.core.pack_manifest import PackManifestError
from spectra_sherpa.core.pack_requirements import PackGraphBinding, PackNodeBinding, parse_pack_graph_binding
from tests.test_pack_manifest import pack


class FixtureRegistry:
    def __init__(self, *manifests, contract="c" * 64):
        self.pack_manifests = manifests
        self.contract = contract

    def get_metadata(self, name):
        if name == "preprocess.clip_floor":
            return SimpleNamespace(distribution="oss", execution_contract=None)
        if any(name in manifest.nodes for manifest in self.pack_manifests):
            return SimpleNamespace(distribution="pro", execution_contract=SimpleNamespace(digest=self.contract))
        raise KeyError(name)


def graph(*types):
    return [{"node_id": str(index), "node_type": name} for index, name in enumerate(types)]


def test_reopen_preserves_exact_build_and_contract_and_never_rebinds():
    original = pack()
    nodes = graph(original.nodes[0])
    binding = capture_pack_graph_binding(nodes, registry=FixtureRegistry(original))
    wire = binding.model_dump_json().encode()
    for changed in (pack(build_sha256="b" * 64), pack(version="1.0.1")):
        with pytest.raises(PackBindingAdmissionError) as error:
            require_matching_pack_binding(nodes, parse_pack_graph_binding(wire), registry=FixtureRegistry(changed))
        (problem,) = error.value.problems
        assert problem.reason == "changed_binding"
        assert problem.retained.required == (original.reference,)
        assert problem.current.required == (changed.reference,)
    with pytest.raises(PackBindingAdmissionError):
        require_matching_pack_binding(nodes, binding, registry=FixtureRegistry(original, contract="d" * 64))
    assert parse_pack_graph_binding(wire) == binding
    assert binding.required == (original.reference,)


def test_transitive_dependencies_and_projection_exclude_unrelated_packs():
    base = pack("base")
    parent = pack("parent", dependencies=(base.reference,))
    unrelated = pack("unrelated")
    nodes = graph(parent.nodes[0], unrelated.nodes[0], "preprocess.clip_floor")
    binding = capture_pack_graph_binding(nodes, registry=FixtureRegistry(unrelated, parent, base))
    projected = binding.for_nodes(frozenset({"0", "2"}))
    assert projected.required == (base.reference, parent.reference)
    assert projected.nodes[0].node_type == parent.nodes[0]
    assert (
        capture_pack_graph_binding(graph("preprocess.clip_floor"), registry=FixtureRegistry(parent, base)).nodes == ()
    )
    stripped = projected.model_dump(mode="json")
    stripped["nodes"][0]["required"] = [parent.reference.model_dump(mode="json")]
    with pytest.raises(PackBindingAdmissionError):
        require_matching_pack_binding(
            nodes[:1], parse_pack_graph_binding(json.dumps(stripped).encode()), registry=FixtureRegistry(parent, base)
        )


def test_absent_historical_binding_works_only_for_oss_graphs():
    assert require_matching_pack_binding(graph("preprocess.clip_floor"), None).nodes == ()
    manifest = pack()
    nodes = graph(manifest.nodes[0])
    for missing in (None, PackGraphBinding()):
        with pytest.raises(PackBindingAdmissionError) as error:
            require_matching_pack_binding(nodes, missing, registry=FixtureRegistry(manifest))
        assert error.value.problems[0].reason == "missing_binding"


def test_missing_node_reports_exact_retained_owner_without_loading_it():
    manifest = pack()
    nodes = graph("preprocess.clip_floor", manifest.nodes[0])
    retained = capture_pack_graph_binding(nodes, registry=FixtureRegistry(manifest))
    with pytest.raises(PackBindingAdmissionError) as error:
        require_matching_pack_binding(nodes, retained, registry=FixtureRegistry())
    (problem,) = error.value.problems
    assert (problem.node_id, problem.node_type, problem.reason) == ("1", manifest.nodes[0], "unavailable_node")
    assert problem.retained == retained.nodes[0]
    assert problem.current is None


def test_forged_ownership_and_removed_node_are_refused():
    first, second = pack("first"), pack("second")
    nodes = graph(first.nodes[0])
    retained = capture_pack_graph_binding(nodes, registry=FixtureRegistry(first))
    with pytest.raises(PackBindingAdmissionError):
        require_matching_pack_binding(graph(second.nodes[0]), retained, registry=FixtureRegistry(second))
    with pytest.raises(PackBindingAdmissionError) as error:
        require_matching_pack_binding(graph("preprocess.clip_floor"), retained, registry=FixtureRegistry())
    assert error.value.problems[0].reason == "unexpected_binding"
    with pytest.raises(ValidationError, match="owning pack"):
        PackNodeBinding(
            node_id="x", node_type=first.nodes[0], execution_contract_sha256="c" * 64, required=(second.reference,)
        )


def test_inert_wire_is_closed_bounded_immutable_and_rejects_ambiguous_json():
    manifest = pack()
    binding = capture_pack_graph_binding(graph(manifest.nodes[0]), registry=FixtureRegistry(manifest))
    for key in ("module", "renderer_code", "skill", "loader"):
        payload = binding.model_dump(mode="json")
        payload[key] = "arbitrary"
        with pytest.raises(PackManifestError):
            parse_pack_graph_binding(json.dumps(payload).encode())
    with pytest.raises(PackManifestError):
        parse_pack_graph_binding(b'{"nodes":[],"nodes":[]}')
    with pytest.raises(PackManifestError):
        parse_pack_graph_binding(b" " * (1024 * 1024 + 1))
    with pytest.raises(PackManifestError):
        parse_pack_graph_binding(b"[" * 2000 + b"]" * 2000)
    with pytest.raises(ValidationError):
        binding.nodes[0].required[0].version = "9.0.0"
    detached = binding.model_dump(mode="json")
    detached["nodes"][0]["required"][0]["version"] = "9.0.0"
    assert binding.required == (manifest.reference,)
    assert parse_pack_graph_binding(binding.model_dump_json().encode()).digest == binding.digest


def test_duplicate_nodes_and_conflicting_builds_are_not_collapsed():
    manifest = pack()
    binding = capture_pack_graph_binding(graph(manifest.nodes[0]), registry=FixtureRegistry(manifest))
    with pytest.raises(ValidationError, match="unique"):
        PackGraphBinding(nodes=binding.nodes * 2)
    other = PackNodeBinding(
        node_id="1",
        node_type=manifest.nodes[0],
        execution_contract_sha256="c" * 64,
        required=(pack(build_sha256="b" * 64).reference,),
    )
    with pytest.raises(ValidationError, match="Conflicting"):
        PackGraphBinding(nodes=(*binding.nodes, other))


def test_shared_dependency_closure_cannot_produce_an_unreadable_saved_binding():
    dependencies = []
    for index in range(64):
        manifest = pack(f"pack-{index}", dependencies=((dependencies[-1].reference,) if dependencies else ()))
        dependencies.append(manifest)
    nodes = [{"node_id": str(index), "node_type": dependencies[-1].nodes[0]} for index in range(1024)]
    with pytest.raises(ValidationError, match="bounded wire contract"):
        capture_pack_graph_binding(nodes, registry=FixtureRegistry(*dependencies))
    small = capture_pack_graph_binding(nodes[:2], registry=FixtureRegistry(*dependencies))
    assert parse_pack_graph_binding(small.model_dump_json().encode()) == small
