"""SyntheticCurveNode -- generate synthetic concentration timeseries.

Registered as ``data.synthetic_curve``.
"""

from __future__ import annotations

import logging
from typing import Any

from spectra_sherpa.app.lib import sherpa_dataset as sherpa_dataset_contract
from spectra_sherpa.app.lib.sherpa_dataset import (
    SherpaDataset,
    TimeAxis,
)
from spectra_sherpa.app.services.dag import meta_helpers as dag_meta_helpers
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.core import spectra_meta as spectra_meta_contract
from spectra_sherpa.core.spectra_meta import (
    ConcentrationProfile,
    ConcentrationUnit,
    DataProvenance,
    SourceType,
    SpectraMeta,
    set_spectra_meta,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily

from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, register_node
from . import source_contracts
from .source_contracts import canonical_synthetic_curve_parameters, generate_synthetic_curve

logger = logging.getLogger(__name__)


def build_synthetic_curve_dataset(parameters: dict[str, object], *, node_id: str) -> SherpaDataset:
    """Build one typed curve result for live and generated DAG execution."""

    parameters = canonical_synthetic_curve_parameters(parameters)
    curve_type = str(parameters["curve_type"])
    max_conc = float(parameters["max_concentration"])
    center = float(parameters["center"])
    width = float(parameters["width"])
    time_seconds, curve = generate_synthetic_curve(parameters)

    dataset = SherpaDataset(
        X=curve.reshape(1, -1),
        feature_axis=TimeAxis(values=time_seconds, title="Time", units="s"),
        backend="numpy",
        title=f"Concentration ({curve_type})",
        units="mol/L",
    )

    concentration_profile = ConcentrationProfile(
        species_index=0,
        species_name="Synthetic Species",
        curve_type=curve_type,
        values=curve.tolist(),
        max_concentration=max_conc,
        min_concentration=float(curve.min()),
        center=center,
        width=width,
        unit=ConcentrationUnit.MOL_L,
    )
    meta = SpectraMeta(
        concentrations=[concentration_profile],
        provenance=DataProvenance(source_type=SourceType.SYNTHETIC),
        is_ground_truth=True,
        processing_steps=["synthetic_curve_generation"],
        custom={"curve_params": dict(parameters)},
    )
    set_spectra_meta(dataset, meta)
    add_processing_step(dataset, "data.synthetic_curve", dict(parameters), node_id=node_id)
    return dataset


@register_node
class SyntheticCurveNode(Node):
    """
    Synthetic Curve node for generating concentration timeseries.

    Generates synthetic concentration curves for blending operations.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="none",
            offload_to_pool=False,
        ),
        node_type="data.synthetic_curve",
        category="synthesis",
        label="Synthetic Curve",
        description="Generate synthetic concentration curves",
        parameters=[
            NodeParameter(
                name="curve_type",
                label="Curve Type",
                param_type="select",
                default="sigmoid",
                options=["sigmoid", "gaussian", "linear", "exponential", "step"],
                description="Type of concentration curve",
                required=True,
            ),
            NodeParameter(
                name="n_points",
                label="Number of Points",
                param_type="number",
                default=100,
                min_value=10,
                description="Number of time points",
                required=True,
            ),
            NodeParameter(
                name="max_concentration",
                label="Max Concentration",
                param_type="number",
                default=1.0,
                min_value=0.0,
                description="Maximum concentration value",
                required=True,
            ),
            NodeParameter(
                name="center",
                label="Center Position",
                param_type="number",
                default=0.5,
                min_value=0.0,
                step=0.1,
                description="Center of sigmoid/gaussian (0-1)",
                required=False,
            ),
            NodeParameter(
                name="width",
                label="Width",
                param_type="number",
                default=0.1,
                min_value=0.01,
                step=0.01,
                description="Width of sigmoid/gaussian",
                required=False,
            ),
            NodeParameter(
                name="duration_seconds",
                label="Duration (seconds)",
                param_type="number",
                default=1.0,
                min_value=1e-12,
                description="Physical duration represented by the normalized curve domain",
                required=True,
            ),
        ],
        input_types=[],
        input_ports=[],
        output_type="TimeSeries",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/TimeSeries/1.0",
                required=True,
                label="Concentration Time Series",
                description="One deterministic concentration curve on a physical time axis",
            )
        ],
        canonical_parameter_validator=canonical_synthetic_curve_parameters,
    )

    async def execute(self, *args) -> Any:
        """Generate synthetic concentration curve."""
        parameters = self.metadata.canonicalize_parameters(self.parameters)
        return build_synthetic_curve_dataset(parameters, node_id=self.node_id)

    def generate_python(self, inputs, indent="    ", use_scp=True):
        """Generate code that invokes the same typed scientific operation."""

        del inputs, use_scp
        parameters = self.metadata.canonicalize_parameters(self.parameters)
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.data.synthetic import build_synthetic_curve_dataset",
            f"{indent}results[{self.node_id!r}] = build_synthetic_curve_dataset(",
            f"{indent}    {parameters!r}, node_id={self.node_id!r}",
            f"{indent})",
        ]


bind_stable_execution_contract(
    SyntheticCurveNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.DATA_SOURCE,
    implementation_id="spectrasherpa.data.synthetic_curve",
    implementation_version="1.0.0",
    required_worker_capabilities=(),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 5, "cpu_seconds": 5, "memory_bytes": 268_435_456},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(source_contracts, sherpa_dataset_contract, spectra_meta_contract, dag_meta_helpers),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
)
