"""Read-only reconstruction under the exact pre-Batch contract authority.

No historical implementation is installed or registered here. Structural
admission is shared with the current graph authority only while the archived
scientific declarations are exactly unchanged. Execution re-admission remains
live-only and rejects the historical representation explicitly.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from typing import Iterable, Mapping

from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.managed_optimization_profile import ManagedOptimizationProfile
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.stable_execution_contract import _canonical_digest, _parameter_schema
from spectra_sherpa.app.services.dag.validation_graph import (
    ValidationGraph,
    ValidationGraphError,
    admit_validation_graph,
    validation_graph_from_dict,
    validation_graph_identity_digest,
)
from spectra_sherpa.core.contract_compatibility import inspection_predecessor_catalog
from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract


class HistoricalValidationGraph(ValidationGraph):
    """Verified historical identity for inspection, never executable authority."""


# Exact inspected consumers after the component-evidence implementation added
# shared module digests. The catalog pins the preceding consumer. A later code
# change must be reviewed again rather than inheriting historical authority.
_INSPECTION_CONSUMERS = {
    "preprocess.osc": (
        "02a4281542fe5fe2a349dbc5e61a42e82fa4a9f346ddb21fd5bf2d64b96c7b1b",
        "4a65ee10a4cdd63629b8c7960da20d1f595ecc756e10041247b33416923a0938",
    ),
    "selection.variable_select": (
        "3209ca10ae4dfa04fe81b944d866182bb88bf5f3f9677c2618c5c100542b4f52",
        "d59bb4d8dac5d77830c633a15d9da90aab42cd9f2377344269a4d80d14841f16",
    ),
    "classification.knn": (
        "b75296b1e07af53623dfaf5e859b759d089eb1b4145a415bc555ff59cf4fec8a",
        "df59b9d414abefb1c93de58ef405f3044ad4c6a02b23dd62cf8cd38c131b58a7",
    ),
    "classification.simca": (
        "58ae844cdcd14833a6da09a7f658e979ed08d812fc5bed7ef9d230be6e79d72e",
        "2a591ac8626fe115463326b7f6b30b1ad3721c6392e6e4a07af786de13777388",
    ),
    # PR119: display descriptions/input-coordinate bindings and canonical
    # sample helpers changed source identities, not archived declarations.
    "model.dbscan": (
        "451a9425e58ba219a12584c037edce136cd263ab9e161e3e8ecf72b03c063a97",
        "5fae2be3e60e35b85b13cb9b80eb09b171743f319bed7dd48b13a8265f31690a",
    ),
    "model.hca": (
        "83d5a8ef60c050f623911740cd60ae1f31ca9abe38fd93ac969e2608b3fe4ed3",
        "0adc84cec3ce752df725518210701d744af62e2cbfd6cd3396eab0d3bce8495b",
    ),
    "model.kmeans": (
        "466e832a2bdf8e856d875cfee2abfdbeff46bea55c77d6d5c005fcc2aeb01879",
        "c65f7f11e6d2089abdec190e2c7aee80088eed4f2545ce55c0b92db1b2ebef30",
    ),
    "model.parafac": (
        "869e7edb4ca328e560bc543bfa4e6ed676314f6a8be49e2364985c3fe47a640d",
        "caa04a3f25923cfc7d83fe38defd47db25fcb10be1375d51d516ebc82b544ac0",
    ),
    "classification.plsda": (
        "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
        "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
    ),
    "model.load_apply": (
        "31e7394e58fa5f78fb8f1bdb1d9b848a6af69d0fb9345cfff033378c22d510dd",
        # Reviewed typed public refusals preserve every legacy admission check.
        # This pair permits historical inspection only, never old execution.
        "d3fb0d37037ce5c51bd5e8343386d8dc9bce131f53c08d368b21da3af97b54d9",
    ),
    "model.apply_fitted_linear_regression": (
        "9c43658d5b6ac5f8848979832e2eed47f573bb5598ccbe2f882727f7720ed379",
        "dd74469839faad7d699e1426c9b1d52708789759bdbd9a34e547278c668ba007",
    ),
    "model.apply_fitted_pcr": (
        "1aecb57326c2c3a8f71823a035cbcb2f21be34d72a3049daedcc5e67a399f2e9",
        "a26782875d287ce1b28fc0db96485362667bd67039ebd25f546f69a75f98bdf0",
    ),
    "model.apply_fitted_svr": (
        "244fe3defede23aefb869e74d97034600b1a73c9abb63694fb6101ed2fea9c34",
        "7a4e54b71e344ce4a3b2fee943a92c947bfa3b3316f8e8a522984dc18cddf13f",
    ),
    "model.fitted_linear_regression": (
        "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
        "a0a31850e5ec62ce5d3d45050af62f715306d1da9d84442d76d70b1b738303f8",
    ),
    "model.fitted_pcr": (
        "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
        "e76876f01548800f4b3ee2bdf0382359e046793a1e02e61e424e17b552256bf3",
    ),
    "model.fitted_pls": (
        "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
        "473b586d631d966d9a76a32ec3788f95b7aea3771fb8981256475061d1b52871",
    ),
    "model.fitted_svr": (
        "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
        "a6be415b3b1ed88d25ef0a220d1059031ada900f4c470d2a7cb762c250edf8af",
    ),
}


def historical_port_topology(graph: HistoricalValidationGraph) -> dict[str, object]:
    """Reproduce the sealed pre-component-curve port identity for readers."""

    from spectra_sherpa.app.services.dag.managed_port_topology import managed_port_topology

    if type(graph) is not HistoricalValidationGraph:
        raise ValidationGraphError("historical port topology requires a historical graph")
    value = managed_port_topology(
        [WorkflowNode(node.node_id, node.operation_id, dict(node.parameters)) for node in graph.nodes],
        [WorkflowEdge(edge.from_node, edge.to_node, edge.from_output, edge.to_input) for edge in graph.edges],
    )
    identity = {key: item for key, item in value.items() if key != "topology_digest"}
    for node, declaration in zip(graph.nodes, identity["nodes"], strict=True):
        if node.operation_id not in {"model.fitted_pls", "classification.plsda"}:
            continue
        archived = node.contract.payload["semantic_outputs"]
        current = declaration["output_ports"]
        if node.operation_id == "classification.plsda" and len(current) == len(archived) + 2:
            if current[-3]["name"] != "component_curve" or current[-2]["name"] != "sample_diagnostics":
                raise ValidationGraphError("historical PLS-DA output additions changed")
            declaration["output_ports"] = current[:-3] + current[-1:]
        elif len(current) == len(archived) + 1:
            curve = len(current) - (1 if node.operation_id == "model.fitted_pls" else 2)
            if current[curve]["name"] == "component_curve":
                declaration["output_ports"] = current[:curve] + current[curve + 1 :]
        if len(declaration["output_ports"]) != len(archived):
            raise ValidationGraphError("historical component port topology changed")
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )
    return {**identity, "topology_digest": hashlib.sha256(encoded).hexdigest()}


class HistoricalReconstructionContext:
    """One packaged predecessor authority; callers cannot supply contracts."""

    def __init__(self, profile_digest: str | None = None):
        self._catalog = inspection_predecessor_catalog(profile_digest)

    def require_historical_graph(self, graph: ValidationGraph) -> None:
        """Do not let an unchanged live reference escape a historical reader.

        Even a graph whose individual contracts have not changed must have
        been reconstructed in this context before a reader can retain it.
        """
        if type(graph) is not HistoricalValidationGraph:
            raise ValidationGraphError("historical reconstruction requires an explicitly historical graph")
        self.graph(graph.as_dict())

    def reconstruct(self, nodes: Iterable[WorkflowNode], edges: Iterable[WorkflowEdge]) -> HistoricalValidationGraph:
        """Reconstruct historical declarations without issuing execution authority.

        Used by deterministic record readers to independently rebuild recipes.
        Their outer record comparison must still verify the original identities.
        """

        current = admit_validation_graph(nodes, edges, require_live_runtime=False)
        wire = current.as_dict()
        membership = self._catalog["profile"]["operations"]
        for node in wire["nodes"]:
            if node["operation_id"] not in membership:
                raise ValidationGraphError("historical recipe uses an unrecognized operation")
            if node["operation_id"] == "model.fitted_pls":
                metadata = node_registry.get_metadata(node["operation_id"])
                if membership[node["operation_id"]] != metadata.resolved_execution_contract().digest:
                    # Current admission fills these new defaults even when a
                    # historical recipe never mentioned them. Remove only
                    # exact defaults before rebuilding the archived identity;
                    # graph() re-admits them into a detached projection.
                    additions = {"component_selection_rule", "component_curve_max", "component_cv_folds"}
                    defaults = {p.name: p.default for p in metadata.parameters if p.name in additions}
                    parameters = node["parameters"]
                    if {key: parameters.get(key) for key in additions} != defaults:
                        raise ValidationGraphError("historical PLS recipe contains changed component controls")
                    for key in additions:
                        parameters.pop(key)
            if node["operation_id"] == "model.load_apply":
                parameters = node["parameters"]
                if parameters.pop("acknowledge_legacy_input_uncertainty", None) is not False:
                    raise ValidationGraphError("historical application cannot acknowledge a legacy model")
            node["contract_digest"] = membership[node["operation_id"]]
        wire["graph_digest"] = validation_graph_identity_digest({k: v for k, v in wire.items() if k != "graph_digest"})
        return self.graph(wire)

    def contract(self, operation: str, digest: str) -> NodeExecutionContract:
        catalog = self._catalog
        try:
            current = node_registry.get_metadata(operation).resolved_execution_contract()
        except KeyError as exc:
            raise ValidationGraphError("historical operation is not locally recognized") from exc
        if current is None:
            raise ValidationGraphError("historical operation lacks a current structural authority")
        archived = catalog["contracts"].get(operation) or catalog.get("profile_contracts", {}).get(operation)
        if archived is None:
            if catalog["profile"]["operations"].get(operation) != digest or current.digest != digest:
                raise ValidationGraphError("unknown historical operation/contract identity")
            return current
        contract = NodeExecutionContract.from_dict(archived["payload"])
        if contract.digest != archived["digest"] or contract.digest != digest:
            raise ValidationGraphError("unknown historical operation/contract identity")
        inspected = _INSPECTION_CONSUMERS.get(operation)
        inspected_consumer = inspected == (catalog["current_contracts"][operation], current.digest)
        component_curve_consumer = inspected_consumer and operation == "model.fitted_pls"
        classifier_curve_consumer = inspected_consumer and operation == "classification.plsda"
        legacy_application_consumer = inspected_consumer and operation == "model.load_apply"
        if current.digest != catalog["current_contracts"][operation] and not inspected_consumer:
            raise ValidationGraphError("current implementation is not qualified for historical reconstruction")
        # A parameter-schema digest alone is not a schema. Reusing the current
        # admission requires the exact reviewed consumer and unchanged complete
        # declarations, not just matching serializer names or operation IDs.
        non_semantic = {"implementation_components", "implementation_digest"}
        # Exact, integrity-pinned registrations preserve read-only old profiles
        # across classifier state-schema upgrades. They never admit old state
        # for application or permit re-executing a historical graph.
        read_only_changes = set(archived.get("read_only_declaration_changes", ()))
        if not read_only_changes <= {"implementation_version", "fitted_state_serializer", "runtime_requirements"}:
            raise ValidationGraphError("unsupported historical declaration registration")
        non_semantic.update(read_only_changes)
        if component_curve_consumer:
            # This exact consumer only adds optional tuning controls and one
            # retained output. Verify the old declarations still project to
            # the archived bytes before using current structural admission.
            if tuple(contract.payload["runtime_requirements"]) != (
                {"distribution": "numpy", "version": "1.26.4"},
            ) or tuple(current.payload["runtime_requirements"]) != (
                {"distribution": "numpy", "version": "1.26.4"},
                {"distribution": "scipy", "version": "1.17.1"},
            ):
                raise ValidationGraphError("historical PLS runtime requirements changed")
            metadata = node_registry.get_metadata(operation)
            additions = {"component_selection_rule", "component_curve_max", "component_cv_folds"}
            if {parameter.name for parameter in metadata.parameters if parameter.name in additions} != additions:
                raise ValidationGraphError("historical PLS component controls changed")
            old_metadata = replace(metadata, parameters=[p for p in metadata.parameters if p.name not in additions])
            if _canonical_digest(_parameter_schema(old_metadata)) != contract.payload["parameter_schema_digest"]:
                raise ValidationGraphError("historical PLS parameter schema changed")
            old_outputs = contract.payload["semantic_outputs"]
            new_outputs = current.payload["semantic_outputs"]
            if len(new_outputs) != len(old_outputs) + 1 or tuple(new_outputs[:-1]) != tuple(old_outputs):
                raise ValidationGraphError("historical PLS output ports changed")
            if (
                new_outputs[-1]["name"] != "component_curve"
                or new_outputs[-1]["type_ref"] != "spectrasherpa://types/ValidationResult/1.0"
            ):
                raise ValidationGraphError("historical PLS component output changed")
            non_semantic.update({"parameter_schema_digest", "semantic_outputs"})
        if classifier_curve_consumer:
            old_outputs = contract.payload["semantic_outputs"]
            new_outputs = current.payload["semantic_outputs"]
            if (
                len(new_outputs) != len(old_outputs) + 2
                or tuple(new_outputs[:-3]) != tuple(old_outputs[:-1])
                or new_outputs[-1] != old_outputs[-1]
                or new_outputs[-3]["name"] != "component_curve"
                or new_outputs[-3]["type_ref"] != "spectrasherpa://types/ValidationResult/1.0"
                or new_outputs[-2]["name"] != "sample_diagnostics"
                or new_outputs[-2]["type_ref"] != "spectrasherpa://types/PLSDASampleDiagnostics/1.0"
            ):
                raise ValidationGraphError("historical PLS-DA component output changed")
            non_semantic.add("semantic_outputs")
        if legacy_application_consumer:
            metadata = node_registry.get_metadata(operation)
            addition = "acknowledge_legacy_input_uncertainty"
            matching = [parameter for parameter in metadata.parameters if parameter.name == addition]
            if len(matching) != 1 or matching[0].default is not False or matching[0].param_type != "boolean":
                raise ValidationGraphError("historical application acknowledgement declaration changed")
            old_metadata = replace(metadata, parameters=[p for p in metadata.parameters if p.name != addition])
            if _canonical_digest(_parameter_schema(old_metadata)) != contract.payload["parameter_schema_digest"]:
                raise ValidationGraphError("historical application parameter schema changed")
            non_semantic.add("parameter_schema_digest")
        before = {k: v for k, v in contract.payload.items() if k not in non_semantic}
        after = {k: v for k, v in current.payload.items() if k not in non_semantic}
        if before != after:
            raise ValidationGraphError("historical scientific declarations differ from current admission")
        return contract

    def profile(self) -> ManagedOptimizationProfile:
        record = self._catalog["profile"]
        contracts = tuple(self.contract(op, digest) for op, digest in sorted(record["operations"].items()))
        profile = ManagedOptimizationProfile(record["profile_id"], record["profile_version"], contracts)
        if profile.digest != record["profile_digest"]:
            raise ValidationGraphError("historical managed profile identity mismatch")
        return profile

    def require_profile(self, identity: Mapping[str, object]) -> ManagedOptimizationProfile:
        profile = self.profile()
        if dict(identity) != {
            "profile_id": profile.profile_id,
            "profile_version": profile.profile_version,
            "profile_digest": profile.digest,
        }:
            raise ValidationGraphError("unknown historical managed profile")
        return profile

    def graph(self, payload: Mapping[str, object]) -> HistoricalValidationGraph:
        """Preserve historical bytes after shared, non-executing admission.

        A detached current projection proves topology and closed parameters.
        It is discarded; the returned graph retains the archived contracts and
        must reproduce the caller's original graph digest exactly.
        """

        if not isinstance(payload, Mapping) or set(payload) != {"schema_version", "nodes", "edges", "graph_digest"}:
            raise ValidationGraphError("historical validation graph fields are closed")
        raw_nodes = payload["nodes"]
        if not isinstance(raw_nodes, list):
            raise ValidationGraphError("historical validation graph nodes must be an array")
        projection = deepcopy(dict(payload))
        contracts = {}
        historical_parameters = {}
        membership = self._catalog["profile"]["operations"]
        for raw, projected in zip(raw_nodes, projection["nodes"], strict=True):
            if not isinstance(raw, Mapping) or set(raw) != {"node_id", "operation_id", "parameters", "contract_digest"}:
                raise ValidationGraphError("historical validation graph node fields are closed")
            operation, digest, node_id = raw["operation_id"], raw["contract_digest"], raw["node_id"]
            if not all(isinstance(value, str) for value in (operation, digest, node_id)):
                raise ValidationGraphError("historical validation graph node identities must be text")
            if membership.get(operation) != digest:
                raise ValidationGraphError("historical graph mixes unsupported profile identities")
            contracts[node_id] = self.contract(operation, digest)
            if (
                operation == "model.fitted_pls"
                and contracts[node_id].digest
                != node_registry.get_metadata(operation).resolved_execution_contract().digest
            ):
                additions = {"component_selection_rule", "component_curve_max", "component_cv_folds"}
                parameters = raw["parameters"]
                if not isinstance(parameters, Mapping) or additions.intersection(parameters):
                    raise ValidationGraphError("historical PLS graph contains post-profile controls")
                historical_parameters[node_id] = dict(parameters)
                defaults = {
                    parameter.name: parameter.default
                    for parameter in node_registry.get_metadata(operation).parameters
                    if parameter.name in additions
                }
                projected["parameters"] = {**parameters, **defaults}
            if (
                operation == "model.load_apply"
                and contracts[node_id].digest
                != node_registry.get_metadata(operation).resolved_execution_contract().digest
            ):
                parameters = raw["parameters"]
                addition = "acknowledge_legacy_input_uncertainty"
                if not isinstance(parameters, Mapping) or addition in parameters:
                    raise ValidationGraphError("historical application contains post-profile acknowledgement")
                historical_parameters[node_id] = dict(parameters)
                projected["parameters"] = {**parameters, addition: False}
            projected["contract_digest"] = node_registry.get_metadata(operation).resolved_execution_contract().digest
        # Use the graph's existing canonical identity function, not a second
        # digest algorithm. Normal wire admission then checks every field.
        unsigned = {k: v for k, v in projection.items() if k != "graph_digest"}
        projection["graph_digest"] = validation_graph_identity_digest(unsigned)
        admitted = validation_graph_from_dict(projection, require_live_runtime=False)
        restored_nodes = []
        for node in admitted.nodes:
            if node.node_id in historical_parameters:
                old = historical_parameters[node.node_id]
                current = dict(node.parameters)
                additions = (
                    {"acknowledge_legacy_input_uncertainty"}
                    if node.operation_id == "model.load_apply"
                    else {"component_selection_rule", "component_curve_max", "component_cv_folds"}
                )
                metadata = node_registry.get_metadata(node.operation_id)
                defaults = {
                    parameter.name: parameter.default
                    for parameter in metadata.parameters
                    if parameter.name in additions
                }
                if {key: current.pop(key, None) for key in additions} != defaults or current != old:
                    raise ValidationGraphError("historical PLS parameters changed during current admission")
                node = replace(
                    node,
                    parameters_json=json.dumps(
                        old, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
                    ),
                )
            restored_nodes.append(replace(node, contract=contracts[node.node_id]))
        historical = object.__new__(HistoricalValidationGraph)
        object.__setattr__(historical, "nodes", tuple(restored_nodes))
        object.__setattr__(historical, "edges", admitted.edges)
        if historical.as_dict() != dict(payload):
            raise ValidationGraphError("historical validation graph does not reproduce its recorded identity")
        return historical
