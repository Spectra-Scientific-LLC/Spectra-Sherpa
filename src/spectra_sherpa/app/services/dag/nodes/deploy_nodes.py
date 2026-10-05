"""Canonical entry and exit nodes for deployed DAGs."""

from __future__ import annotations

from typing import Any

from spectra_sherpa.app.services.dag import supervision_binding as supervision_contract
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    DatasetRankPolicy,
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from spectra_sherpa.sdk import deployment as deployment_contract

_DEPLOYMENT_IMPORT = (
    "from spectra_sherpa.sdk.deployment import "
    "admit_deployment_input, deployment_target_output, format_deployment_output, validate_deployment_input_set"
)
_SUPERVISION_IMPORT = (
    "from spectra_sherpa.app.services.dag.supervision_binding import " "admit_attached_sample_table_supervision"
)


@register_node
class DeployInputNode(Node):
    """Admit one explicitly supplied external scientific dataset.

    The execution engine must inject the payload matching ``stream_name``.
    Ordinary execution fails closed; a workflow can never appear successful
    by running against fabricated spectral data.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(offload_to_pool=False),
        node_type="deploy.input",
        category="deploy",
        label="Deploy Input",
        description="Admits a named external scientific dataset into a deployed DAG",
        parameters=[
            NodeParameter(
                name="stream_name",
                label="Stream Name",
                param_type="text",
                default="sample",
                description="Unique portable identifier for this external data stream",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="schema_version",
                label="Input Schema",
                param_type="select",
                default=deployment_contract.DEPLOYMENT_INPUT_SCHEMA,
                options=[deployment_contract.DEPLOYMENT_INPUT_SCHEMA],
                description="Closed external scientific-dataset request schema",
                required=True,
                category="advanced",
            ),
        ],
        input_types=[],
        input_ports=[],
        output_type="spectrasherpa://types/SpectralDataset/1.0",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Dataset",
                description="Exact admitted external dataset",
            ),
            PortMetadata(
                name="target",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Target Values",
                description="Reference values, or canonical text class labels for a declared categorical target",
            ),
        ],
    )
    python_extra_imports = [_DEPLOYMENT_IMPORT, _SUPERVISION_IMPORT]

    async def execute(self, *args: Any) -> Any:
        raise RuntimeError(
            f"deploy.input {self.node_id!r} requires an explicitly admitted external payload; "
            "ordinary DAG execution cannot fabricate deployment data"
        )

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, input_map: dict[str, str], indent: str = "    ", use_scp: bool = False) -> list[str]:
        stream_name = self.parameters.get("stream_name", "sample")
        schema_version = self.parameters.get("schema_version", deployment_contract.DEPLOYMENT_INPUT_SCHEMA)
        return [
            f"{indent}# --- {self.node_id} (Deploy Input) ---",
            f"{indent}# Admit the caller-supplied {stream_name!r} scientific dataset.",
            f"{indent}results[{self.node_id!r}] = {{'default': admit_deployment_input(",
            f"{indent}    deployment_inputs[{stream_name!r}],",
            f"{indent}    stream_name={stream_name!r},",
            f"{indent}    schema_version={schema_version!r},",
            f"{indent})}}",
            f"{indent}target = deployment_target_output(results[{self.node_id!r}]['default'], required=False)",
            f"{indent}if target is not None:",
            f"{indent}    results[{self.node_id!r}]['target'] = target",
        ]


@register_node
class DeployOutputNode(Node):
    """Serialize a DAG result into one deterministic response envelope."""

    metadata = NodeMetadata(
        policy=NodePolicy(data_egress_risk="full_data", offload_to_pool=False),
        node_type="deploy.output",
        category="deploy",
        label="Deploy Output",
        description="Formats one deployed DAG result through the canonical response contract",
        parameters=[
            NodeParameter(
                name="output_format",
                label="Output Format",
                param_type="select",
                default="json",
                options=["json", "csv", "plain_text"],
                description="Exact response representation",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="key_value_separator",
                label="Key-Value Separator",
                param_type="select",
                default="=",
                options=["=", ":", "\t"],
                description="Closed separator for plain-text mappings",
                required=True,
                category="advanced",
            ),
            NodeParameter(
                name="end_of_message_tag",
                label="End of Message Tag",
                param_type="select",
                default="\\n",
                options=["", "\\n", "\\r\\n"],
                description="Closed line ending for plain-text responses",
                required=True,
                category="advanced",
            ),
        ],
        input_types=["any"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Payload",
                description="Pipeline result to return",
            ),
        ],
        output_type="spectrasherpa://types/DeploymentResponse/1.0",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/DeploymentResponse/1.0",
                required=True,
                label="Response",
                description="Formatted response with exact byte digest",
            ),
        ],
    )
    python_extra_imports = [_DEPLOYMENT_IMPORT]

    async def execute(self, payload: Any) -> dict[str, Any]:
        return deployment_contract.format_deployment_output(
            payload,
            output_format=self.parameters.get("output_format", "json"),
            key_value_separator=self.parameters.get("key_value_separator", "="),
            end_of_message_tag=self.parameters.get("end_of_message_tag", "\\n"),
        )

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, input_map: dict[str, str], indent: str = "    ", use_scp: bool = False) -> list[str]:
        in_var = input_map.get("default", "None")
        output_format = self.parameters.get("output_format", "json")
        separator = self.parameters.get("key_value_separator", "=")
        ending = self.parameters.get("end_of_message_tag", "\\n")
        return [
            f"{indent}# --- {self.node_id} (Deploy Output) ---",
            f"{indent}results['{self.node_id}'] = format_deployment_output(",
            f"{indent}    {in_var},",
            f"{indent}    output_format={output_format!r},",
            f"{indent}    key_value_separator={separator!r},",
            f"{indent}    end_of_message_tag={ending!r},",
            f"{indent})",
        ]


bind_stable_execution_contract(
    DeployInputNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.DATA_SOURCE,
    implementation_id="spectrasherpa.deploy.input",
    implementation_version="3.1.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    target_access="optional",
    input_rank_policy=DatasetRankPolicy.PRESERVES_ND,
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 5, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(deployment_contract, supervision_contract),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
)

bind_stable_execution_contract(
    DeployOutputNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.deploy.output",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 5, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(deployment_contract,),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
)
