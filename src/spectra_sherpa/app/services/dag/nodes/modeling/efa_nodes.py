"""
Evolving Factor Analysis (EFA) node.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import numpy as np

from spectra_sherpa.app.lib import fitted_state
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers
from spectra_sherpa.app.services.dag.meta_helpers import (
    add_processing_step,
    copy_processing_history,
    inherit_origin_flags,
    inherit_sample_flags,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    TargetAccess,
    WorkerCapability,
)
from spectra_sherpa.interoperability import spectrochempy_adapter

from ...io_contracts import (
    bind_X,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from .core_utils import (
    create_spectral_dataset as _create_spectral_dataset,
)
from .core_utils import (
    make_safe_coord as _make_safe_coord,
)

logger = logging.getLogger(__name__)


def _canonical_efa_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """Validate the sole scientist-controlled EFA rank ceiling."""

    if set(parameters) != {"n_components"}:
        raise ValueError("EFA parameters must use the exact one-field schema")
    n_components = parameters["n_components"]
    if isinstance(n_components, bool) or not isinstance(n_components, int) or not 1 <= n_components <= 500:
        raise ValueError("EFA n_components must be an integer between 1 and 500")
    return {"n_components": n_components}


def _efa_numeric_outputs(input_data: Any, *, parameters: Mapping[str, object]) -> dict[str, np.ndarray]:
    """Run the one SpectroChemPy EFA authority and return closed diagnostics."""

    canonical = _canonical_efa_parameters(parameters)
    input_ds = bind_X(
        input_data,
        missing_message="Missing required input: input_data (evolving spectra)",
        dataset_error_message="input_data must be a dataset object",
        allow_array=False,
    )
    if input_ds.is_time_series is not True:
        raise ValueError(
            "EFA requires an explicitly ordered evolution coordinate. Mark the admitted sample axis as ordered "
            "only when acquisition time, elution order, concentration progression, or another scientific "
            "evolution order is known. Arbitrary sample order is not an EFA sequence."
        )
    n_samples, n_features = input_ds.shape
    n_components = int(canonical["n_components"])
    if n_components > min(n_samples, n_features):
        raise ValueError("EFA n_components may not exceed the smaller input dimension")
    scp = spectrochempy_adapter.require_spectrochempy("model.efa")
    model = scp.EFA(n_components=n_components)
    model.fit(
        spectrochempy_adapter.to_spectrochempy_dataset(
            input_ds,
            operation_id="model.efa",
        )
    )
    extracted = spectrochempy_adapter.extract_efa_state(model)
    if extracted.forward_ev is None or extracted.backward_ev is None:
        raise ValueError("SpectroChemPy EFA did not return both forward and backward eigenvalues")
    forward = np.asarray(extracted.forward_ev[:, :n_components], dtype=np.float64)
    backward = np.asarray(extracted.backward_ev[:, :n_components], dtype=np.float64)
    expected = (n_samples, n_components)
    if forward.shape != expected or backward.shape != expected:
        raise ValueError("SpectroChemPy EFA returned an unexpected diagnostic shape")
    if not np.isfinite(forward).all() or not np.isfinite(backward).all():
        raise ValueError("SpectroChemPy EFA returned non-finite diagnostics")
    return {
        "default": forward,
        "forward_eigenvalues": forward,
        "backward_eigenvalues": backward,
    }


@register_node
class EFANode(Node):
    """
    Evolving Factor Analysis (EFA) node.

    Performs EFA to determine the number of significant factors
    and the chemical rank of evolving systems.

    Uses SpectroChemPy's EFA implementation.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="none",
            offload_to_pool=True,
            required_worker_capabilities=["read_dataset"],
        ),
        node_type="model.efa",
        category="exploratory",
        label="Fit EFA Decomposition",
        description="Fit Evolving Factor Analysis for rank determination",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=10,
                min_value=1,
                max_value=500,
                max_value_reason="Bound exploratory rank and memory use on local workbench data",
                step=1,
                description="Number of components to compute",
                required=False,
            ),
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Forward Eigenvalues",
                description="Primary forward rank-evolution diagnostic",
            ),
            PortMetadata(
                name="forward_eigenvalues",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Forward Eigenvalues",
                description="Eigenvalues from forward EFA (samples × components)",
            ),
            PortMetadata(
                name="backward_eigenvalues",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Backward Eigenvalues",
                description="Eigenvalues from backward EFA (samples × components)",
            ),
        ],
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.EFA.html",
        canonical_parameter_validator=_canonical_efa_parameters,
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for EFA."""
        if not use_scp:
            return [
                f"{indent}# --- EFA ({self.node_id}) ---",
                f"{indent}# EFA requires SpectroChemPy (pip install spectra-sherpa[scp])",
                f"{indent}raise ImportError('EFA requires spectrochempy')",
            ]

        params = self._resolve_params()
        X_expr = inputs.get("default", inputs.get("X", "input_data"))
        return [
            f"{indent}# --- Canonical EFA rank diagnostics ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.efa_nodes import _efa_numeric_outputs",
            f"{indent}results[{self.node_id!r}] = _efa_numeric_outputs(",
            f"{indent}    {X_expr}, parameters={params!r},",
            f"{indent})",
        ]

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute EFA on input dataset.

        Args:
            input_data: Dataset containing evolving spectral data

        Returns:
            Dict containing forward and backward eigenvalues
        """
        del kwargs
        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (evolving spectra)",
            dataset_error_message="input_data must be an dataset object",
            allow_array=False,
        )
        params = self._resolve_params()
        numeric = _efa_numeric_outputs(input_ds, parameters=params)
        n_components = int(params["n_components"])
        forward_ev = numeric["forward_eigenvalues"]
        backward_ev = numeric["backward_eigenvalues"]

        # Get input y_coord for sample labels
        _y_coord = input_ds.sample_axis

        # =====================================================================
        # Create SherpaDataset objects for eigenvalues with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        component_labels = [f"EV{i + 1}" for i in range(n_components)]

        # Forward eigenvalues: shape (n_samples, n_components)
        forward_ev_dataset = _create_spectral_dataset(
            data=forward_ev,
            x_coord=_make_safe_coord(component_labels, title="Component"),
            y_coord=_y_coord,
            units="eigenvalue",
            title="EFA Forward Eigenvalues",
        )

        # Backward eigenvalues: shape (n_samples, n_components)
        backward_ev_dataset = _create_spectral_dataset(
            data=backward_ev,
            x_coord=_make_safe_coord(component_labels, title="Component"),
            y_coord=_y_coord,
            units="eigenvalue",
            title="EFA Backward Eigenvalues",
        )

        # Add processing history to SherpaDataset outputs
        copy_processing_history(input_ds, forward_ev_dataset)
        add_processing_step(
            forward_ev_dataset,
            "model.efa.forward_eigenvalues",
            params,
            node_id=self.node_id,
        )
        copy_processing_history(input_ds, backward_ev_dataset)
        add_processing_step(
            backward_ev_dataset,
            "model.efa.backward_eigenvalues",
            params,
            node_id=self.node_id,
        )

        # Propagate dataset-level flags. EFA forward/backward eigenvalues
        # have one row per sample (window position), so sample-axis flags
        # carry through. Origin tags survive on every output.
        inherit_sample_flags(input_ds, forward_ev_dataset)
        inherit_origin_flags(input_ds, forward_ev_dataset)
        inherit_sample_flags(input_ds, backward_ev_dataset)
        inherit_origin_flags(input_ds, backward_ev_dataset)

        # Store only scientific metadata that coordinates can't carry
        # Use forward_ev_dataset as default output
        default_dataset = forward_ev_dataset
        default_dataset.meta.update(
            {
                "type": "EFA",
                "n_components": n_components,
                "interpretation": "ordered_evolution_rank_diagnostic",
                "quality_summary": {"n_components": n_components},
            }
        )
        for efa_dataset in (forward_ev_dataset, backward_ev_dataset):
            if efa_dataset is not None:
                efa_dataset.meta.update(
                    {
                        "type": "EFA",
                        "n_components": n_components,
                        "interpretation": "ordered_evolution_rank_diagnostic",
                    }
                )

        efa_diagnostics: dict[str, Any] = {
            "n_components": n_components,
            "n_eigenvalues_forward": int(forward_ev.shape[1]),
            "n_eigenvalues_backward": int(backward_ev.shape[1]),
            "evolution_order": "declared_sample_order",
        }

        return NodeResult(
            outputs={
                "default": default_dataset,
                "forward_eigenvalues": forward_ev_dataset,
                "backward_eigenvalues": backward_ev_dataset,
            },
            diagnostics=efa_diagnostics,
        )


bind_stable_execution_contract(
    EFANode,
    runtime_family=RuntimeFamily.SPECTROCHEMPY,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.model.efa",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/exploratory.md",
    implementation_modules=(
        fitted_state,
        spectrochempy_adapter,
        dag_io_contracts,
        meta_helpers,
    ),
    implementation_distributions=("numpy", "scipy", "spectrochempy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("spectrochempy", "0.8.1")),
    citations=(
        "Maeder, Evolving factor analysis for the resolution of overlapping chromatographic peaks, "
        "Analytical Chemistry 59 (1987) 527-530",
        "SpectroChemPy EFA documentation and forward/reverse evolving-factor implementation",
    ),
    deterministic=True,
    target_access=TargetAccess.NONE,
    group_access="none",
)
