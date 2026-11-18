"""Synthetic canonical pack for retention tests; no supplied private pack code."""

from dataclasses import replace

from spectra_sherpa.app.services.dag import node_base, saved_graph_admission
from spectra_sherpa.app.services.dag.nodes.preprocessing.clip_floor_node import ClipFloorNode
from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract
from tests.test_pack_manifest import pack


def make_retained_registry(monkeypatch, *, base_node=ClipFloorNode):
    class RetainedFixtureNode(base_node):
        metadata = replace(base_node.metadata)
        metadata.node_type = "pro.reference.record"
        metadata.distribution = "pro"
        payload = metadata.execution_contract.as_dict()
        payload["operation_id"] = metadata.node_type
        payload["implementation_id"] = "qualification.retained_record"
        metadata.execution_contract = NodeExecutionContract.from_dict(payload)

    registry = node_base.NodeRegistry()
    registry._nodes.update(node_base.node_registry._nodes)
    registry.register(RetainedFixtureNode)
    registry._pack_manifests = (pack(),)
    registry.freeze_builtins()
    from spectra_sherpa.app.services.dag import executor

    monkeypatch.setattr(executor, "node_registry", registry)
    monkeypatch.setattr(node_base, "node_registry", registry)
    monkeypatch.setattr(saved_graph_admission, "node_registry", registry)
    return registry
