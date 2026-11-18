"""Inert pack identity and dependency contracts; never code-loading authority.

These records can accompany retained workflows/results even where the matching
code is absent. Parsing or comparing them does not import a pack, establish its
license, verify installed bytes, or authorize an operation. Trusted composition
must separately verify the exact installed build and enforce admission.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PackId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,47}$")]
Version = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", max_length=32)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
OperationId = Annotated[str, Field(pattern=r"^pro\.[a-z][a-z0-9-]{0,47}\.[a-z][a-z0-9_.-]{0,79}$")]
ContractVersion = Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$", max_length=16)]
MAX_PACKS = 64
PackStatus = Literal["matching_identity", "missing", "different_version", "different_build"]


class PackManifestError(ValueError):
    """An inert pack inventory is incomplete, contradictory or incompatible."""


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PackReference(Frozen):
    pack_id: PackId
    version: Version
    build_sha256: Digest


class PackManifest(PackReference):
    schema_version: Literal["spectra-pack/1"] = "spectra-pack/1"
    core_min: Version
    core_max_exclusive: Version
    contract_versions: Annotated[tuple[ContractVersion, ...], Field(min_length=1, max_length=8)]
    entitlement_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,95}$")]
    license_id: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9.+_-]{0,95}$")]
    nodes: Annotated[tuple[OperationId, ...], Field(max_length=128)] = ()
    tools: Annotated[tuple[OperationId, ...], Field(max_length=128)] = ()
    dependencies: Annotated[tuple[PackReference, ...], Field(max_length=16)] = ()

    @model_validator(mode="after")
    def closed_identity(self):
        if _version(self.core_min) >= _version(self.core_max_exclusive):
            raise ValueError("Pack core compatibility interval is empty")
        for names in (self.nodes, self.tools, self.contract_versions, tuple(ref.pack_id for ref in self.dependencies)):
            if len(names) != len(set(names)):
                raise ValueError("Duplicate pack declaration")
        prefix = f"pro.{self.pack_id}."
        if any(not name.startswith(prefix) for name in (*self.nodes, *self.tools)):
            raise ValueError("Pack operation is outside its declared namespace")
        if any(ref.pack_id == self.pack_id for ref in self.dependencies):
            raise ValueError("A pack cannot depend on itself")
        return self

    @property
    def reference(self):
        return PackReference(pack_id=self.pack_id, version=self.version, build_sha256=self.build_sha256)


def _version(value):
    # Validate standalone caller input using the same authority as manifests.
    from pydantic import TypeAdapter

    return tuple(int(part) for part in TypeAdapter(Version).validate_python(value, strict=True).split("."))


def parse_pack_manifest(payload: bytes) -> PackManifest:
    if type(payload) is not bytes or len(payload) > 65536:
        raise PackManifestError("Pack manifest exceeds the bounded wire contract")

    def unique_object(pairs):
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise PackManifestError("Duplicate manifest field")
        return dict(pairs)

    try:
        json.loads(payload, object_pairs_hook=unique_object)
    except PackManifestError:
        raise
    except (ValueError, RecursionError) as exc:
        raise PackManifestError("Invalid pack manifest JSON") from exc
    return PackManifest.model_validate_json(payload)


def validate_pack_set(
    manifests: tuple[PackManifest, ...], *, core_version: str, contract_versions: frozenset[str]
) -> tuple[PackManifest, ...]:
    """Return deterministic dependency order; validate only declared identities."""
    if len(manifests) > MAX_PACKS:
        raise PackManifestError("Too many packs")
    installed = {manifest.pack_id: manifest for manifest in manifests}
    if len(installed) != len(manifests):
        raise PackManifestError("Duplicate pack identity")
    version = _version(core_version)
    for manifest in manifests:
        if not _version(manifest.core_min) <= version < _version(manifest.core_max_exclusive):
            raise PackManifestError(f"Incompatible core version for pack {manifest.pack_id}")
        if not set(manifest.contract_versions) <= contract_versions:
            raise PackManifestError(f"Incompatible execution contract for pack {manifest.pack_id}")
        for reference in manifest.dependencies:
            dependency = installed.get(reference.pack_id)
            if dependency is None or dependency.reference != reference:
                raise PackManifestError(
                    f"Missing or incompatible dependency {reference.pack_id} for pack {manifest.pack_id}"
                )
    ordered = []
    visited = set()

    def visit(name, active):
        if name in active:
            raise PackManifestError("Pack dependency cycle")
        if name in visited:
            return
        for reference in sorted(installed[name].dependencies, key=lambda ref: ref.pack_id):
            visit(reference.pack_id, active | {name})
        visited.add(name)
        ordered.append(installed[name])

    for name in sorted(installed):
        visit(name, set())
    return tuple(ordered)


def required_pack_references(
    node_types: tuple[str, ...], manifests: tuple[PackManifest, ...]
) -> tuple[PackReference, ...]:
    """Project used nodes and transitive dependencies; ignore unrelated packs.

    The caller supplies its previously validated composition. Built-in node
    validity remains the NodeRegistry's responsibility, not this projection.
    """
    if len(manifests) > MAX_PACKS or len(node_types) > 1024:
        raise PackManifestError("Pack dependency projection exceeds its bound")
    installed = {manifest.pack_id: manifest for manifest in manifests}
    owners = {node: manifest for manifest in manifests for node in manifest.nodes}
    if len(installed) != len(manifests) or len(owners) != sum(len(m.nodes) for m in manifests):
        raise PackManifestError("Duplicate pack or node identity")
    needed = {}

    def include(manifest, active):
        if manifest.pack_id in active:
            raise PackManifestError("Pack dependency cycle")
        if manifest.pack_id in needed:
            return
        for reference in manifest.dependencies:
            dependency = installed.get(reference.pack_id)
            if dependency is None or dependency.reference != reference:
                raise PackManifestError(f"Missing or incompatible dependency {reference.pack_id}")
            include(dependency, active | {manifest.pack_id})
        needed[manifest.pack_id] = manifest.reference

    for node in node_types:
        if type(node) is not str or len(node) > 160:
            raise PackManifestError("Invalid node identity")
        if node.startswith("pro."):
            if node not in owners:
                raise PackManifestError(f"Unavailable pack node {node}")
            include(owners[node], set())
    return tuple(needed[name] for name in sorted(needed))


@dataclass(frozen=True)
class PackAvailability:
    required: PackReference
    status: PackStatus
    installed: PackReference | None


def inspect_pack_availability(
    required: tuple[PackReference, ...], installed: tuple[PackReference, ...]
) -> tuple[PackAvailability, ...]:
    """Inert retained-evidence comparison; matching is not execution permission."""
    if len(required) > MAX_PACKS or len(installed) > MAX_PACKS:
        raise PackManifestError("Pack inspection exceeds its bound")
    current = {ref.pack_id: ref for ref in installed}
    if len(current) != len(installed) or len({ref.pack_id for ref in required}) != len(required):
        raise PackManifestError("Duplicate pack inspection identity")
    result = []
    for ref in sorted(required, key=lambda item: item.pack_id):
        actual = current.get(ref.pack_id)
        status: PackStatus = "missing"
        if actual is not None:
            status = (
                "different_version"
                if actual.version != ref.version
                else "different_build" if actual.build_sha256 != ref.build_sha256 else "matching_identity"
            )
        result.append(PackAvailability(ref, status, actual))
    return tuple(result)
