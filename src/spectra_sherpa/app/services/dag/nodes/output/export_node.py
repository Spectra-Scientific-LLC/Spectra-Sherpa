"""Canonical output artifact preparation node."""

from __future__ import annotations

from typing import Any

from spectra_sherpa.app.lib import export_artifact as export_authority
from spectra_sherpa.app.lib import portable_csv as portable_csv_contract
from spectra_sherpa.app.lib.export_artifact import build_export_artifact, canonicalize_export_parameters
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    DatasetRankPolicy,
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, register_node


def _canonical_export_parameters(raw: dict[str, object]) -> dict[str, object]:
    return canonicalize_export_parameters(raw)


@register_node
class ExportNode(Node):
    """Prepare exact downloadable bytes without granting filesystem access."""

    metadata = NodeMetadata(
        node_type="output.export",
        category="output",
        label="Prepare Export",
        description=(
            "Prepare a digest-bound CSV, JSON, or single-spectrum JCAMP-DX artifact. "
            "CSV and JSON retain one exact target and row-aligned sample metadata when present. "
            "The workbench downloads the exact prepared bytes; generated scripts "
            "materialize the same verified artifact under their export directory."
        ),
        parameters=[
            NodeParameter(
                name="filename",
                label="Filename",
                param_type="text",
                default="output.csv",
                description="Safe basename including the extension required by the selected format",
                required=True,
            ),
            NodeParameter(
                name="format",
                label="Format",
                param_type="select",
                default="csv",
                options=["csv", "json", "jdx"],
                description="Closed serialization format",
                required=True,
            ),
        ],
        input_types=["Any"],
        output_type="ExportArtifact",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Dataset",
                description=(
                    "Canonical exportable result; n-dimensional datasets are retained by JSON, "
                    "while CSV and JCAMP-DX require an explicit two-dimensional projection"
                ),
            )
        ],
        output_ports=[
            PortMetadata(
                name="artifact",
                type_ref="spectrasherpa://types/ExportArtifact/1.0",
                required=True,
                label="Prepared Export",
                description="Closed content, format, filename, size, and SHA-256 evidence",
            )
        ],
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="full_data",
            offload_to_pool=False,
        ),
        canonical_parameter_validator=_canonical_export_parameters,
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate the same pure serialization call used by live execution."""

        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return [
            f"{indent}# --- Prepare export ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.lib.export_artifact import build_export_artifact",
            f"{indent}results[{self.node_id!r}] = {{'artifact': build_export_artifact(",
            f"{indent}    {input_expr}, filename={parameters['filename']!r}, format={parameters['format']!r},",
            f"{indent})}}",
        ]

    async def execute(self, input_data: Any) -> dict[str, object]:
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        dataset = coerce_to_sherpa(
            input_data,
            input_name="output.export dataset",
            dataset_error_message="output.export requires a canonical dataset",
        )
        return {
            "artifact": build_export_artifact(
                dataset,
                filename=str(parameters["filename"]),
                format=str(parameters["format"]),
            )
        }


bind_stable_execution_contract(
    ExportNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.output.export",
    implementation_version="2.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 5, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/output.md",
    implementation_modules=(export_authority, portable_csv_contract),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    input_rank_policy=DatasetRankPolicy.PRESERVES_ND,
)


__all__ = ["ExportNode"]
