"""Inert, retained per-node pack bindings, separate from execution permission.

A binding records the exact producing code and contract, not today's installed
catalog. No registry or application import is needed to inspect or project it.
Historical production dependencies do not restrict reading retained values.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from spectra_sherpa.core.pack_manifest import (
    MAX_PACKS,
    Digest,
    Frozen,
    OperationId,
    PackManifestError,
    PackReference,
)

MAX_BINDING_BYTES = 1024 * 1024

NodeId = Annotated[str, Field(min_length=1, max_length=256)]


class PackNodeBinding(Frozen):
    node_id: NodeId
    node_type: OperationId
    execution_contract_sha256: Digest
    required: Annotated[tuple[PackReference, ...], Field(min_length=1, max_length=MAX_PACKS)]

    @model_validator(mode="after")
    def closed_requirements(self):
        names = tuple(ref.pack_id for ref in self.required)
        if names != tuple(sorted(set(names))):
            raise ValueError("Node pack requirements must be unique and sorted")
        if self.node_type.split(".", 2)[1] not in names:
            raise ValueError("Node pack binding omits its owning pack")
        return self


class PackGraphBinding(Frozen):
    schema_version: Literal["spectra-pack-graph/1"] = "spectra-pack-graph/1"
    nodes: Annotated[tuple[PackNodeBinding, ...], Field(max_length=1024)] = ()

    @model_validator(mode="after")
    def consistent_bindings(self):
        ids = tuple(node.node_id for node in self.nodes)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("Pack node bindings must be unique and sorted")
        _union_references(self.nodes)
        if len(self.model_dump_json().encode("utf-8")) > MAX_BINDING_BYTES:
            raise ValueError("Retained pack binding exceeds the bounded wire contract")
        return self

    @property
    def required(self) -> tuple[PackReference, ...]:
        return _union_references(self.nodes)

    @property
    def digest(self) -> str:
        """Versioned identity separate from historical workflow integrity hashes."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def for_nodes(self, node_ids: frozenset[str]) -> PackGraphBinding:
        """Project a caller's graph ancestry, never the entire installed catalog."""
        return PackGraphBinding(nodes=tuple(node for node in self.nodes if node.node_id in node_ids))


def _union_references(nodes: tuple[PackNodeBinding, ...]) -> tuple[PackReference, ...]:
    references: dict[str, PackReference] = {}
    for node in nodes:
        for ref in node.required:
            previous = references.get(ref.pack_id)
            if previous is not None and previous != ref:
                raise ValueError(f"Conflicting retained builds for pack {ref.pack_id}")
            references[ref.pack_id] = ref
    if len(references) > MAX_PACKS:
        raise ValueError("Too many retained packs")
    return tuple(references[name] for name in sorted(references))


def parse_pack_graph_binding(payload: bytes) -> PackGraphBinding:
    """Parse bounded JSON facts without loading any declared operation."""
    if type(payload) is not bytes or len(payload) > MAX_BINDING_BYTES:
        raise PackManifestError("Retained pack binding exceeds the bounded wire contract")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PackManifestError("Duplicate retained pack binding field")
            result[key] = value
        return result

    try:
        json.loads(payload, object_pairs_hook=unique_object)
        return PackGraphBinding.model_validate_json(payload)
    except (ValueError, RecursionError) as exc:
        raise PackManifestError("Invalid retained pack binding") from exc


class PackPreprocessingStep(Frozen):
    step_index: Annotated[int, Field(ge=0, lt=1024)]
    producer: PackNodeBinding


class PackPreprocessingBinding(Frozen):
    """Pack production identities projected onto an existing scientific chain."""

    schema_version: Literal["spectra-pack-preprocessing/1"] = "spectra-pack-preprocessing/1"
    chain_sha256: Digest
    steps: Annotated[tuple[PackPreprocessingStep, ...], Field(min_length=1, max_length=1024)]

    @model_validator(mode="after")
    def ordered_steps(self):
        indices = tuple(step.step_index for step in self.steps)
        if indices != tuple(sorted(set(indices))):
            raise ValueError("Pack preprocessing indices must be unique and sorted")
        if len(self.model_dump_json().encode("utf-8")) > MAX_BINDING_BYTES:
            raise ValueError("Pack preprocessing binding exceeds the bounded wire contract")
        return self


def preprocessing_chain_digest(chain: list) -> str:
    if len(chain) > 1024:
        raise PackManifestError("Too many preprocessing steps")
    return hashlib.sha256(
        json.dumps(chain, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def read_pack_preprocessing_binding(manifest: dict) -> PackPreprocessingBinding | None:
    """Inspect retained model facts without requiring their code or entitlement."""
    value = manifest.get("pack_preprocessing_binding")
    if value is None:
        return None
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(payload) > MAX_BINDING_BYTES:
        raise PackManifestError("Pack preprocessing binding exceeds the bounded wire contract")
    binding = PackPreprocessingBinding.model_validate_json(payload)
    chain = manifest.get("preprocessing_chain")
    if not isinstance(chain, list) or preprocessing_chain_digest(chain) != binding.chain_sha256:
        raise PackManifestError("Pack provenance does not match its preprocessing chain")
    if any(step.step_index >= len(chain) for step in binding.steps):
        raise PackManifestError("Pack provenance references a missing preprocessing step")
    return binding
