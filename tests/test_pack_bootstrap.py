"""Trusted composition is atomic; ordinary consumers only see a sealed catalog."""

import hashlib
import importlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from spectra_sherpa.app.services.dag.node_base import Node, NodeRegistry
from spectra_sherpa.app.services.tools.schemas import ToolDefinition
from spectra_sherpa.core.pack_build import PackFile, build_sha256
from tests.test_pack_manifest import pack

startup = importlib.import_module("spectra_sherpa.app.services.dag.bootstrap")


NODE_SOURCE = """
from dataclasses import replace
from spectra_sherpa.app.services.dag.nodes.preprocessing.clip_floor_node import ClipFloorNode
from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract

class Record(ClipFloorNode):
    metadata = replace(ClipFloorNode.metadata)
    metadata.node_type = "pro.reference.record"
    metadata.distribution = "pro"
    payload = metadata.execution_contract.as_dict()
    payload["operation_id"] = metadata.node_type
    payload["implementation_id"] = "qualification.record"
    metadata.execution_contract = NodeExecutionContract.from_dict(payload)

async def inspect_record(**kwargs):
    return {"available": True}
"""


@pytest.fixture
def registry(monkeypatch):
    registry = NodeRegistry(managed_startup=True)
    registry._finish_builtin_imports()
    monkeypatch.setattr(startup, "node_registry", registry)
    return registry


@pytest.fixture
def extension(tmp_path, monkeypatch):
    source = tmp_path / "qualification_pack.py"
    source.write_text(NODE_SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("qualification_pack", None)
    module = importlib.import_module("qualification_pack")
    files = (PackFile(path=source.name, sha256=hashlib.sha256(source.read_bytes()).hexdigest()),)
    yield startup.InstalledPack(
        manifest=pack(build_sha256=build_sha256(files), tools=()),
        source_root=tmp_path,
        files=files,
        nodes=(module.Record,),
    )
    sys.modules.pop("qualification_pack", None)


def test_exact_composition_is_repeatable_and_runtime_mutations_are_refused(registry, extension):
    assert startup.bootstrap(extensions=(extension,)) == (extension.manifest,)
    assert registry.get_node_class("pro.reference.record") is extension.nodes[0]
    assert startup.bootstrap(extensions=(extension,)) == (extension.manifest,)
    with pytest.raises(ValueError, match="different composition"):
        startup.bootstrap()
    with pytest.raises(ValueError, match="frozen"):
        registry.unregister("pro.reference.record")
    assert startup.installed_pack_manifests() == (extension.manifest,)


def test_first_read_seals_default_and_blocks_later_extension(registry, extension):
    assert registry.list_nodes() == []
    with pytest.raises(ValueError, match="different composition"):
        startup.bootstrap(extensions=(extension,))
    assert registry.list_nodes() == []


def test_failed_initial_composition_poisons_all_read_paths(registry, extension):
    (extension.source_root / "qualification_pack.py").write_text("# changed after import\n")
    with pytest.raises(ValueError, match="bytes differ"):
        startup.bootstrap(extensions=(extension,))
    for read in (
        registry.list_nodes,
        lambda: registry.get_metadata("missing"),
        lambda: registry.get_node_class("missing"),
        lambda: registry.create_node("missing", "test"),
        lambda: "missing" in registry,
        startup.installed_pack_manifests,
        startup.bootstrap,
    ):
        with pytest.raises(ValueError, match="unavailable"):
            read()


def test_concurrent_read_and_reentrant_bootstrap_never_observe_partial_composition(registry, extension, monkeypatch):
    entered, resume = Event(), Event()
    original = startup.verify_installed_build

    def held_verification(*args):
        entered.set()
        assert resume.wait(10)
        return original(*args)

    monkeypatch.setattr(startup, "verify_installed_build", held_verification)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(startup.bootstrap, extensions=(extension,))
        try:
            assert entered.wait(10)
            with pytest.raises(ValueError, match="unavailable"):
                registry.list_nodes()
            with pytest.raises(ValueError, match="unavailable"):
                startup.bootstrap()
        finally:
            resume.set()
        assert future.result(timeout=10) == (extension.manifest,)
    assert registry.get_node_class("pro.reference.record") is extension.nodes[0]


def test_direct_registration_does_not_inspect_candidate(registry):
    class Hostile(Node):
        @classmethod
        def get_metadata(cls):
            pytest.fail("inspected a runtime registration candidate")

    with pytest.raises(ValueError, match="runtime node registration is disabled"):
        registry.register(Hostile)
    assert registry.is_frozen


def test_classes_must_belong_to_inventory_and_declare_pro_ownership(registry, extension):
    extension.nodes[0].metadata.distribution = "oss"
    with pytest.raises(ValueError, match="ownership"):
        startup.bootstrap(extensions=(extension,))


def test_lean_builtin_registration_cannot_be_discarded_by_concurrent_bootstrap(monkeypatch):
    from spectra_sherpa.app.services.dag.nodes.preprocessing.clip_floor_node import ClipFloorNode

    entered, resume = Event(), Event()
    shared = []

    class HeldBuiltin(ClipFloorNode):
        __module__ = ClipFloorNode.__module__

        @classmethod
        def get_metadata(cls):
            entered.set()
            assert resume.wait(10)
            return ClipFloorNode.get_metadata()

    def register():
        registry = NodeRegistry(managed_startup=True)
        registry._finish_builtin_imports(lean=True)
        shared.append(registry)
        registry._register_builtin(HeldBuiltin)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(register)
        try:
            assert entered.wait(10)
            registry = shared[0]
            monkeypatch.setattr(startup, "node_registry", registry)
            with pytest.raises(ValueError, match="unavailable"):
                startup.bootstrap()
            with pytest.raises(ValueError, match="unavailable"):
                registry.list_nodes()
        finally:
            resume.set()
        future.result(timeout=10)
    assert startup.bootstrap() == ()
    assert registry.get_node_class(ClipFloorNode.metadata.node_type) is HeldBuiltin


def with_tool(extension, **definition_changes):
    definition = dict(
        name="reference_inspect",
        mcp_name="reference_inspect",
        version="1.0",
        description="Qualification interface",
        output_schema={"type": "object"},
        mutation="read",
        disclosure=["metadata"],
        distribution="pro",
        requires_user=True,
    )
    definition.update(definition_changes)
    tool = startup.InstalledPackTool(
        "pro.reference.inspect",
        ToolDefinition(**definition),
        sys.modules["qualification_pack"].inspect_record,
    )
    manifest = extension.manifest.model_copy(update={"tools": (tool.qualified_name,)})
    return replace(extension, manifest=manifest, tools=(tool,))


def test_pack_tools_remain_detached_and_absent_from_existing_providers(registry, extension):
    from spectra_sherpa.app.services.tools.registry import tool_registry

    extension = with_tool(extension)
    assert tool_registry.get("reference_inspect") is None
    startup.bootstrap(extensions=(extension,))
    composed = startup.installed_pack_tools()
    assert len(composed) == 1 and composed[0].qualified_name == "pro.reference.inspect"
    assert composed[0].handler is extension.tools[0].handler
    assert tool_registry.get("reference_inspect") is None
    assert "reference_inspect" not in {item.name for item in tool_registry.list_definitions()}
    projected = composed[0].definition
    projected.parameters["injected"] = True
    assert "injected" not in composed[0].definition.parameters
    assert startup.bootstrap(extensions=(extension,)) == (extension.manifest,)
    extension.tools[0].definition.description = "Changed installed interface"
    with pytest.raises(ValueError, match="different composition"):
        startup.bootstrap(extensions=(extension,))
    assert composed[0].definition.description == "Qualification interface"


@pytest.mark.parametrize("change", [{"version": None}, {"distribution": "oss"}, {"requires_user": False}])
def test_unclassified_or_unowned_pack_tool_is_refused(registry, extension, change):
    with pytest.raises(ValueError):
        startup.bootstrap(extensions=(with_tool(extension, **change),))
    with pytest.raises(ValueError, match="unavailable"):
        startup.installed_pack_tools()


def test_duplicate_tool_aliases_and_missing_handlers_are_refused(registry, extension):
    extension = with_tool(extension)
    extra = replace(
        extension.tools[0],
        qualified_name="pro.reference.second",
        definition=extension.tools[0].definition.model_copy(update={"name": "second_inspect"}),
    )
    manifest = extension.manifest.model_copy(
        update={"tools": (extension.tools[0].qualified_name, extra.qualified_name)}
    )
    with pytest.raises(ValueError, match="Duplicate projected tool name"):
        startup.bootstrap(extensions=(replace(extension, manifest=manifest, tools=(*extension.tools, extra)),))


def test_worker_digest_guard_refuses_equal_manifests_with_changed_node_contract(registry, extension, monkeypatch):
    from spectra_sherpa.app.services.dag.executor_pool import _initialize_worker
    from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract

    manifests = startup.bootstrap(extensions=(extension,))
    expected_digest = startup.installed_composition_digest()
    replacement = NodeRegistry(managed_startup=True)
    replacement._finish_builtin_imports()
    monkeypatch.setattr(startup, "node_registry", replacement)
    payload = extension.nodes[0].metadata.execution_contract.as_dict()
    payload["implementation_version"] = "999.0"
    extension.nodes[0].metadata.execution_contract = NodeExecutionContract.from_dict(payload)
    assert startup.bootstrap(extensions=(extension,)) == manifests
    with pytest.raises(RuntimeError, match="node/tool bindings differ"):
        _initialize_worker(None, manifests, expected_digest)


@pytest.mark.parametrize(
    "module",
    [
        "spectra_sherpa.app.services.dag.node_base",
        "spectra_sherpa.app.services.dag.presentation_contract",
        "spectra_sherpa.app.services.dag.nodes.preprocessing",
    ],
)
def test_fresh_contract_import_does_not_seal_but_first_read_does(module):
    script = f"""
import importlib
importlib.import_module({module!r})
from spectra_sherpa.app.services.dag.node_base import node_registry
assert not node_registry.is_frozen
assert node_registry.list_nodes()
assert node_registry.is_frozen
from spectra_sherpa.app.services.dag.bootstrap import bootstrap
assert bootstrap() == ()
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
