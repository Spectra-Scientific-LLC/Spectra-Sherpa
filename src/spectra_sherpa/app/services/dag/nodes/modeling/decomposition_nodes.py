"""
Decomposition nodes: NMF, FastICA.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.lib import nmf_core
from spectra_sherpa.app.lib.fitted_state import NMFExtract
from spectra_sherpa.app.services.dag.meta_helpers import (
    add_processing_step,
    copy_processing_history,
    inherit_origin_flags,
    inherit_sample_flags,
)
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    TargetAccess,
    WorkerCapability,
)

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
from ...stable_execution_contract import bind_stable_execution_contract
from .core_utils import (
    create_spectral_dataset as _create_spectral_dataset,
)
from .core_utils import (
    is_sequential_numeric as _is_sequential_numeric,
)
from .core_utils import (
    make_safe_coord as _make_safe_coord,
)

logger = logging.getLogger(__name__)


@register_node
class NMFNode(Node):
    """
    Non-negative Matrix Factorization (NMF) node.

    Performs NMF decomposition with non-negativity constraints on both
    the concentration (W) and spectral (H) matrices. Provides physically
    interpretable results for mixture analysis.

    Uses the one Sherpa-native numerical authority in ``nmf_core`` for live,
    generated, and fitted-state application paths.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="model.nmf",
        category="exploratory",
        label="Fit NMF Decomposition",
        description=(
            "Decomposes a spectral dataset into W (concentration profiles) × H (pure spectra) "
            "with non-negativity constraints, making components physically interpretable as "
            "mixture fractions. "
            "Input data must be strictly non-negative — add a Clip Floor node (floor=0) or apply "
            "baseline correction before NMF if your spectra contain negative values. "
            "Choose n_components based on the expected number of chemical species; "
            "'mu' solver is more robust, 'cd' converges faster on large datasets."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=2,
                max_value=500,
                max_value_reason="Bounds factor-state size and iterative decomposition cost.",
                step=1,
                description="Number of components to extract",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="solver",
                label="Solver",
                param_type="select",
                default="mu",
                options=["mu", "cd"],
                description="NMF solver: 'mu' (Multiplicative Update) or 'cd' (Coordinate Descent)",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="max_iter",
                label="Maximum Iterations",
                param_type="number",
                default=200,
                min_value=1,
                max_value=10000,
                max_value_reason="Bounds the declared convergence budget.",
                step=50,
                description="Maximum number of iterations",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=0.0001,
                min_value=0.000000000001,
                max_value=0.1,
                max_value_reason="Prevents a tolerance so loose that factorization stops without useful refinement.",
                step=0.0001,
                description="Convergence tolerance",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="random_state",
                label="Random Seed",
                param_type="number",
                default=42,
                min_value=0,
                max_value=4294967295,
                max_value_reason="Matches the closed unsigned 32-bit seed domain.",
                step=1,
                description="Seed for deterministic initialization and fixed-basis application",
                required=False,
                category="advanced",
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
                label="Concentration Profiles",
                description="Primary W matrix with observation and canonical-component axes",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                required=True,
                label="Fitted NMF Decomposition",
                description="Closed non-negative factor state for deterministic application",
            ),
            PortMetadata(
                name="concentrations",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Concentrations",
                description="Concentration profiles (W matrix) as SherpaDataset with sample/component axes",
            ),
            PortMetadata(
                name="spectra",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Pure Spectra",
                description="Pure component spectra (H matrix) as SherpaDataset with wavenumber axis",
            ),
            PortMetadata(
                name="reconstruction_error",
                type_ref="spectrasherpa://types/Scalar/1.0",
                required=True,
                label="Reconstruction Error",
                description="Final reconstruction error value",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python that calls the same NMF authority as live execution."""
        del use_scp
        input_expression = inputs.get("default", inputs.get("X", "input_data"))
        return [
            f"{indent}from spectra_sherpa.app.lib.nmf_core import nmf_numeric_outputs",
            f"{indent}results[{self.node_id!r}] = nmf_numeric_outputs(",
            f"{indent}    {input_expression}, parameters={self._resolve_params()!r},",
            f"{indent})",
        ]

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute NMF decomposition on input dataset.

        Args:
            input_data: Dataset containing non-negative spectral data
                       Shape should be (n_samples, n_wavenumbers)

        Returns:
            Dict containing:
            NodeResult with declared concentration, basis-spectrum, fitted-state,
            reconstruction-error, and model-artifact outputs.
        """
        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (non-negative spectra)",
            dataset_error_message="input_data must be an dataset object",
            allow_array=False,
        )

        del kwargs
        parameters = self._resolve_params()
        state = nmf_core.fit_nmf(input_ds, parameters=parameters)
        n_components = int(state["parameters"]["n_components"])
        W_data = np.asarray(state["concentrations"], dtype=np.float64)
        H_data = np.asarray(state["components"], dtype=np.float64)

        # Get input coordinates for SherpaDataset creation
        # Use generic accessors to support all axis types (TimeAxis, SampleAxis, etc.)
        _x_coord = input_ds.get_feature_axis()
        _y_coord = input_ds.get_observation_axis()

        reconstruction_err = float(state["reconstruction_error"])

        logger.debug("[NMF Node] Decomposition completed successfully")
        logger.debug("  - W shape: %s", W_data.shape)
        logger.debug("  - H shape: %s", H_data.shape)
        logger.debug("  - Reconstruction error: %.6f", reconstruction_err)

        # Extract label_categories for categorical coloring
        label_categories = None
        if _y_coord is not None:
            try:
                if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, "tolist") else list(_y_coord.labels)
                    label_categories = sorted(set(str(l) for l in raw))
                elif hasattr(_y_coord, "data") and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, "tolist") else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # =====================================================================
        # Create proper SherpaDataset objects for W and H with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        component_labels = [f"Component {i + 1}" for i in range(n_components)]
        spectrum_labels = [f"Basis Spectrum {i + 1}" for i in range(n_components)]

        # H (Pure Spectra): shape (n_components, n_features)
        # X-axis = wavenumbers from input, Y-axis = component labels
        H_dataset = _create_spectral_dataset(
            data=H_data,
            x_coord=_x_coord,
            y_coord=_make_safe_coord(spectrum_labels, title="Component"),
            units=input_ds.units if hasattr(input_ds, "units") else None,
            title="NMF Basis Spectra (H)",
        )

        # W (Concentrations): shape (n_samples, n_components)
        # X-axis = component labels, Y-axis = sample labels/time
        W_dataset = _create_spectral_dataset(
            data=W_data,
            x_coord=_make_safe_coord(component_labels, title="Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="relative concentration",
            title="NMF Concentration Profiles (W)",
            data_role="X_features",
        )

        # Add processing history to SherpaDataset outputs
        copy_processing_history(input_ds, W_dataset)
        add_processing_step(
            W_dataset,
            "model.nmf.concentrations",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        copy_processing_history(input_ds, H_dataset)
        add_processing_step(
            H_dataset,
            "model.nmf.spectra",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Propagate dataset-level flags. W (concentrations) is
        # sample-axis-preserved; H (basis spectra) rows are components.
        # Origin tags survive on every output.
        inherit_sample_flags(input_ds, W_dataset)
        inherit_origin_flags(input_ds, W_dataset)
        inherit_origin_flags(input_ds, H_dataset)

        # Store only scientific metadata that coordinates can't carry
        nmf_quality_summary: dict = {
            "n_components": int(n_components),
            "reconstruction_err": reconstruction_err,
        }
        W_dataset.meta.update(
            {
                "type": "NMF",
                "scientific_matrix_role": "component_concentrations",
                "n_components": n_components,
                "label_categories": label_categories,
                "reconstruction_error": reconstruction_err,
                "quality_summary": nmf_quality_summary,
            }
        )
        H_dataset.meta["scientific_matrix_role"] = "component_spectra"

        nmf_diagnostics: dict[str, Any] = {
            "n_components": int(n_components),
            "reconstruction_error": reconstruction_err,
            "n_iter": int(state["n_iter"]),
            "convergence_status": state["convergence_status"],
            "solver": str(state["parameters"]["solver"]),
            "application_rule": state["application_rule"],
        }

        from ._artifact_builder import build_model_artifact

        artifact = build_model_artifact(
            NMFExtract(
                H=H_data.astype(np.float64),
                n_components=int(n_components),
                solver=str(state["parameters"]["solver"]),
                max_iter=int(state["parameters"]["max_iter"]),
                tol=float(state["parameters"]["tol"]),
                random_state=int(state["parameters"]["random_state"]),
            ),
            input_ds,
            node_id=self.node_id,
            metrics=nmf_diagnostics,
        )

        return NodeResult(
            outputs={
                "default": W_dataset,
                "concentrations": W_dataset,
                "spectra": H_dataset,
                "model": state,
                "reconstruction_error": reconstruction_err,
                "_model_artifact": artifact,
            },
            diagnostics=nmf_diagnostics,
        )

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, Any]:
        """Fit the closed non-negative basis used by graph and artifact application."""
        del target
        return nmf_core.fit_nmf(input_data, parameters=self._resolve_params())

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        """Estimate concentrations against the frozen non-negative basis."""
        return nmf_core.apply_nmf(input_data, state)


bind_stable_execution_contract(
    NMFNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_MODEL,
    implementation_id="spectrasherpa.model.nmf",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 120, "cpu_seconds": 120, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/exploratory.md",
    implementation_modules=(nmf_core,),
    implementation_distributions=("numpy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0")),
    citations=(
        "Lee and Seung, Algorithms for Non-negative Matrix Factorization, Advances in Neural "
        "Information Processing Systems 13 (2001) 556-562",
        "Gaujoux and Seoighe, A flexible R package for nonnegative matrix factorization, "
        "BMC Bioinformatics 11 (2010) 367; R package NMF",
    ),
    fitted_state_serializer=nmf_core.NMF_STATE_SERIALIZER,
    deterministic=True,
    target_access=TargetAccess.NONE,
    group_access="none",
)


# =============================================================================
# Apply Model Nodes (Inference)
# =============================================================================
