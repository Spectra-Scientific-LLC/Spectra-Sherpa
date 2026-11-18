"""Scientific graph pack identity admission against trusted frozen composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from spectra_sherpa.core.pack_manifest import PackManifestError, required_pack_references
from spectra_sherpa.core.pack_requirements import PackGraphBinding, PackNodeBinding


@dataclass(frozen=True)
class PackBindingProblem:
    node_id: str
    node_type: str
    reason: Literal["missing_binding", "changed_binding", "unexpected_binding", "unavailable_node"]
    retained: PackNodeBinding | None
    current: PackNodeBinding | None


class PackBindingAdmissionError(ValueError):
    def __init__(self, problems: tuple[PackBindingProblem, ...]):
        self.problems = problems
        super().__init__("Retained pack bindings do not match the current executable graph")


def capture_pack_graph_binding(nodes: Sequence[Mapping[str, Any]], *, registry=None) -> PackGraphBinding:
    """Capture only a new graph admitted by the caller, never rebind old evidence.

    Registry metadata is trusted installed code. Inert readers must use the core
    parser instead. This capture does not replace graph/parameter admission.
    """
    if registry is None:
        from spectra_sherpa.app.services.dag.node_base import node_registry

        registry = node_registry
    if len(nodes) > 1024:
        raise PackManifestError("Too many nodes for retained pack binding")
    manifests = registry.pack_manifests
    bindings = []
    seen = set()
    for node in nodes:
        node_id, node_type = node.get("node_id"), node.get("node_type")
        if not isinstance(node_id, str) or not node_id or len(node_id) > 256 or node_id in seen:
            raise PackManifestError("Invalid or duplicate retained node identity")
        if not isinstance(node_type, str) or not node_type or len(node_type) > 160:
            raise PackManifestError("Invalid retained node type")
        seen.add(node_id)
        try:
            metadata = registry.get_metadata(node_type)
        except KeyError as exc:
            raise PackBindingAdmissionError(
                (PackBindingProblem(node_id, node_type, "unavailable_node", None, None),)
            ) from exc
        if metadata.distribution == "oss":
            if node_type.startswith("pro."):
                raise PackManifestError("Pack node claims OSS ownership")
            continue
        if metadata.distribution != "pro" or metadata.execution_contract is None:
            raise PackManifestError("Pack node lacks a canonical execution contract")
        bindings.append(
            PackNodeBinding(
                node_id=node_id,
                node_type=node_type,
                execution_contract_sha256=metadata.execution_contract.digest,
                required=required_pack_references((node_type,), manifests),
            )
        )
    return PackGraphBinding(nodes=tuple(sorted(bindings, key=lambda item: item.node_id)))


def require_matching_pack_binding(
    nodes: Sequence[Mapping[str, Any]], retained: PackGraphBinding | None, *, registry=None
) -> PackGraphBinding:
    """Refuse missing/changed ownership, contract or complete dependency identity.

    An absent historical binding is compatible only with an OSS-only graph.
    Current commercial entitlement and ordinary graph admission remain separate.
    """
    if (retained is None or not retained.nodes) and not any(
        isinstance(node.get("node_type"), str) and node["node_type"].startswith("pro.") for node in nodes
    ):
        # Existing OSS graph admission owns ordinary node validity. Do not
        # relabel legacy graphs or replace their established refusal semantics.
        return PackGraphBinding()
    previous = {node.node_id: node for node in retained.nodes} if retained is not None else {}
    try:
        current = capture_pack_graph_binding(nodes, registry=registry)
    except PackBindingAdmissionError as exc:
        raise PackBindingAdmissionError(
            tuple(
                PackBindingProblem(
                    problem.node_id, problem.node_type, problem.reason, previous.get(problem.node_id), None
                )
                for problem in exc.problems
            )
        ) from exc
    actual = {node.node_id: node for node in current.nodes}
    problems = []
    for node_id in sorted(previous.keys() | actual.keys()):
        old, new = previous.get(node_id), actual.get(node_id)
        if old == new:
            continue
        reason: Literal["missing_binding", "unexpected_binding", "changed_binding"] = (
            "missing_binding" if old is None else "unexpected_binding" if new is None else "changed_binding"
        )
        node = new or old
        assert node is not None
        problems.append(PackBindingProblem(node_id, node.node_type, reason, old, new))
    if problems:
        raise PackBindingAdmissionError(tuple(problems))
    return current
