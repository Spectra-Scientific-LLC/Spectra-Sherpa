"""Explicit trusted-host composition; never discover code from retained data.

Classes are already imported trusted host code. Source inventory validation
establishes installed source identity, not previously loaded bytecode identity.
The installation must remain immutable from import through process lifetime.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path

from spectra_sherpa import __version__
from spectra_sherpa.app.services.tools.catalog import project_tool_catalog
from spectra_sherpa.app.services.tools.registry import ToolRegistry, tool_registry
from spectra_sherpa.app.services.tools.schemas import ToolDefinition, ToolHandler
from spectra_sherpa.core.pack_build import PackFile, verify_installed_build
from spectra_sherpa.core.pack_manifest import PackManifest, validate_pack_set

from .dag.node_base import Node, NodeRegistry, node_registry


@dataclass(frozen=True)
class InstalledPackTool:
    qualified_name: str
    definition: ToolDefinition
    handler: ToolHandler


@dataclass(frozen=True)
class ComposedPackTool:
    """Detached installed interface; only a private adapter may admit dispatch."""

    qualified_name: str
    pack_id: str
    definition_json: str
    handler: ToolHandler

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition.model_validate_json(self.definition_json)


@dataclass(frozen=True)
class InstalledPack:
    manifest: PackManifest
    source_root: Path
    files: tuple[PackFile, ...]
    nodes: tuple[type[Node], ...]
    tools: tuple[InstalledPackTool, ...] = ()


def _require_inventoried_source(implementation, root: Path, inventory: set[str]) -> None:
    source = inspect.getsourcefile(implementation)
    if source is None:
        raise ValueError("Pack implementation must have an inventoried Python source file")
    try:
        relative = Path(source).resolve(strict=True).relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("Pack implementation source is outside its installed inventory") from exc
    if relative not in inventory:
        raise ValueError("Pack implementation source is absent from its installed inventory")


def bootstrap(*, extensions: tuple[InstalledPack, ...] = ()) -> tuple[PackManifest, ...]:
    """Seal one exact composition before serving requests or creating workers.

    Validation runs outside the registry lock, after reserving construction.
    Reentrant/concurrent readers fail closed instead of waiting while holding
    Python import locks. A failed initial composition poisons this process.
    """
    registry = node_registry
    with registry._lock:
        if registry._startup_state not in {"pending", "frozen"} or registry._builtin_active:
            raise ValueError("Node catalog is unavailable during or after failed startup")
        initial = registry._startup_state == "pending"
        if initial:
            registry._startup_state = "composing"
        builtin_nodes = dict(registry._nodes)
        previous = registry._composition
    try:
        # Initialize the fixed builtin set outside the catalog lock. Checking
        # only previously imported tools would make admission import-dependent.
        from spectra_sherpa.app.services.tools import builtin  # noqa: F401

        reserved_names = {
            name
            for definition in tool_registry.list_definitions()
            for name in (definition.name, definition.mcp_name)
            if name is not None
        }
        manifests = validate_pack_set(
            tuple(pack.manifest for pack in extensions),
            core_version=__version__,
            contract_versions=frozenset({"4.0"}),
        )
        by_id = {pack.manifest.pack_id: pack for pack in extensions}
        staged = NodeRegistry()
        staged_tools = ToolRegistry()
        composed_tools = []
        identity = []
        portable_identity = []
        for manifest in manifests:
            pack = by_id[manifest.pack_id]
            verify_installed_build(pack.source_root, pack.files, manifest)
            root = pack.source_root.resolve(strict=True)
            inventory = {item.path for item in pack.files}
            declared = set()
            node_identity = []
            node_classes = []
            for implementation in pack.nodes:
                if not isinstance(implementation, type) or not issubclass(implementation, Node):
                    raise ValueError("Pack node implementation must be a Node class")
            for implementation in sorted(pack.nodes, key=lambda item: item.get_metadata().node_type):
                _require_inventoried_source(implementation, root, inventory)
                staged.register(implementation)
                metadata = implementation.get_metadata()
                if metadata.distribution != "pro" or metadata.node_type not in manifest.nodes:
                    raise ValueError("Pack node distribution or declared ownership differs")
                contract = metadata.resolved_execution_contract()
                if (
                    contract is None
                    or contract.payload["operation_id"] != metadata.node_type
                    or contract.payload["contract_version"] not in manifest.contract_versions
                ):
                    raise ValueError("Pack node execution contract is missing or incompatible")
                if metadata.node_type in declared:
                    raise ValueError("Duplicate pack node implementation")
                declared.add(metadata.node_type)
                node_classes.append(implementation)
                node_identity.append(
                    (metadata.node_type, implementation.__module__, implementation.__qualname__, contract.digest)
                )
            if declared != set(manifest.nodes):
                raise ValueError("Pack node implementation inventory differs from its manifest")
            tool_names = set()
            tool_identity = []
            for tool in sorted(pack.tools, key=lambda item: item.qualified_name):
                if tool.qualified_name not in manifest.tools or tool.qualified_name in tool_names:
                    raise ValueError("Pack tool declared ownership differs or is duplicated")
                if not inspect.iscoroutinefunction(tool.handler):
                    raise ValueError("Pack tool handler must be an explicit async installed function")
                _require_inventoried_source(tool.handler, root, inventory)
                definition = ToolDefinition.model_validate(tool.definition.model_dump())
                if definition.distribution != "pro" or not definition.requires_user:
                    raise ValueError("Pack tool requires explicit pro distribution and user identity")
                if {definition.name, definition.mcp_name} & reserved_names:
                    raise ValueError("Pack tool name or alias collides with an installed tool")
                staged_tools.register(definition, tool.handler)
                entry = staged_tools.get(definition.name)
                assert entry is not None
                stored = entry[0]
                serialized = json.dumps(stored.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
                composed_tools.append(ComposedPackTool(tool.qualified_name, manifest.pack_id, serialized, tool.handler))
                tool_identity.append((tool.qualified_name, serialized, tool.handler))
                tool_names.add(tool.qualified_name)
            if tool_names != set(manifest.tools):
                raise ValueError("Pack tool implementation inventory differs from its manifest")
            identity.append(
                (manifest.model_dump_json(), tuple(node_classes), tuple(node_identity), tuple(tool_identity))
            )
            portable_identity.append(
                {
                    "manifest": manifest.model_dump(mode="json"),
                    "nodes": node_identity,
                    "tools": [
                        (name, definition, handler.__module__, handler.__qualname__)
                        for name, definition, handler in tool_identity
                    ],
                }
            )
        # Reuse the canonical interface classification/alias validation once
        # across the complete tool set, including cross-pack alias collisions.
        project_tool_catalog(staged_tools, tuple(item.name for item in staged_tools.list_definitions()))
        composition = tuple(identity)
        digest = hashlib.sha256(
            json.dumps(portable_identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with registry._lock:
            if not initial:
                if previous != composition:
                    raise ValueError("Node catalog is already sealed with a different composition")
                return registry._pack_manifests
            if set(staged._nodes) & set(builtin_nodes):
                raise ValueError("Pack node collides with an installed built-in")
            registry._nodes = {**builtin_nodes, **staged._nodes}
            registry._builtin_types = set(builtin_nodes)
            registry._composition = composition
            registry._pack_manifests = manifests
            registry._pack_tools = tuple(composed_tools)
            registry._composition_digest = digest
            registry._frozen = True
            registry._startup_state = "frozen"
        return manifests
    except BaseException:
        if initial:
            with registry._lock:
                registry._startup_state = "failed"
        raise


def installed_pack_manifests() -> tuple[PackManifest, ...]:
    return node_registry.pack_manifests


def installed_pack_tools() -> tuple[ComposedPackTool, ...]:
    """Trusted adapter input only; never register into WS/Advisor/OSS MCP."""
    node_registry._ensure_ready()
    return node_registry._pack_tools


def installed_composition_digest() -> str:
    """Cross-process binding of manifests, node contracts and tool interfaces."""
    return node_registry.composition_digest
