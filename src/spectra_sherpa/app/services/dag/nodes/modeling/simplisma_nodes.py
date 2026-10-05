"""
SIMPLISMA self-modeling mixture analysis node.
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
    ensure_orientation as _ensure_orientation,
)
from .core_utils import (
    is_sequential_numeric as _is_sequential_numeric,
)
from .core_utils import (
    make_safe_coord as _make_safe_coord,
)

logger = logging.getLogger(__name__)


def _canonical_simplisma_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """Validate the closed SpectroChemPy SIMPLISMA parameter surface."""

    if set(parameters) != {"n_components", "noise", "tol"}:
        raise ValueError("SIMPLISMA parameters must use the exact three-field schema")
    n_components = parameters["n_components"]
    if isinstance(n_components, bool) or not isinstance(n_components, int) or not 2 <= n_components <= 500:
        raise ValueError("SIMPLISMA n_components must be an integer between 2 and 500")
    noise = parameters["noise"]
    tol = parameters["tol"]
    if isinstance(noise, bool) or not isinstance(noise, (int, float)) or not np.isfinite(noise):
        raise ValueError("SIMPLISMA noise must be finite")
    if not 0.0 <= float(noise) <= 15.0:
        raise ValueError("SIMPLISMA noise must be between 0 and 15 percent")
    if isinstance(tol, bool) or not isinstance(tol, (int, float)) or not np.isfinite(tol):
        raise ValueError("SIMPLISMA tolerance must be finite")
    if not 0.001 <= float(tol) <= 100.0:
        raise ValueError("SIMPLISMA tolerance must be between 0.001 and 100 percent")
    return {"n_components": n_components, "noise": float(noise), "tol": float(tol)}


def _simplisma_numeric_outputs(input_data: Any, *, parameters: Mapping[str, object]) -> dict[str, object]:
    """Run the one SpectroChemPy SIMPLISMA authority and return closed arrays."""

    canonical = _canonical_simplisma_parameters(parameters)
    input_ds = bind_X(
        input_data,
        missing_message="Missing required input: input_data (spectral mixtures)",
        dataset_error_message="input_data must be a dataset object",
        allow_array=False,
    )
    n_samples, n_features = input_ds.shape
    n_components = int(canonical["n_components"])
    if n_components > min(n_samples, n_features):
        raise ValueError("SIMPLISMA n_components may not exceed the smaller input dimension")
    scp = spectrochempy_adapter.require_spectrochempy("model.simplisma")
    model = scp.SIMPLISMA(
        n_components=n_components,
        noise=float(canonical["noise"]),
        tol=float(canonical["tol"]),
    )
    model.fit(
        spectrochempy_adapter.to_spectrochempy_dataset(
            input_ds,
            operation_id="model.simplisma",
        )
    )
    extracted = spectrochempy_adapter.extract_simplisma_state(model)
    concentrations = _ensure_orientation(
        extracted.C,
        expected_rows=n_samples,
        expected_cols=n_components,
        name="SIMPLISMA.C",
    )
    spectra = _ensure_orientation(
        extracted.St,
        expected_rows=n_components,
        expected_cols=n_features,
        name="SIMPLISMA.St",
    )
    purity = (
        np.asarray(extracted.purities, dtype=np.float64).reshape(-1) if extracted.purities is not None else np.array([])
    )
    if purity.shape != (n_components,):
        raise ValueError("SpectroChemPy SIMPLISMA did not expose one purity value per resolved component")
    if not np.isfinite(concentrations).all() or not np.isfinite(spectra).all() or not np.isfinite(purity).all():
        raise ValueError("SpectroChemPy SIMPLISMA returned non-finite results")
    return {
        "default": concentrations,
        "concentrations": concentrations,
        "spectra": spectra,
        "purity_values": purity,
    }


@register_node
class SIMPLISMANode(Node):
    """
    SIMPLISMA (SIMPLe-to-use Interactive Self-modeling Mixture Analysis) node.

    Performs SIMPLISMA decomposition to resolve pure component spectra
    from mixture data using a self-modeling approach based on purity maximization.

    Uses SpectroChemPy's SIMPLISMA implementation.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="none",
            offload_to_pool=True,
            required_worker_capabilities=["read_dataset"],
        ),
        node_type="model.simplisma",
        category="exploratory",
        label="Fit SIMPLISMA Pure Components",
        description="Fit self-modeling mixture components using purity maximization",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=2,
                max_value=500,
                max_value_reason="Bound local decomposition rank and memory use",
                step=1,
                description="Number of pure components to resolve",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="tol",
                label="Tolerance",
                param_type="number",
                default=0.1,
                min_value=0.001,
                max_value=100.0,
                max_value_reason="Closed percentage tolerance accepted by SpectroChemPy SIMPLISMA",
                step=0.01,
                description="Convergence tolerance",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="noise",
                label="Noise Level",
                param_type="number",
                default=3.0,
                min_value=0.0,
                max_value=15.0,
                max_value_reason="SpectroChemPy documents the SIMPLISMA noise range as 0-15 percent",
                step=0.1,
                description="Noise level for purity calculation",
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
                description="Primary resolved concentration profiles",
            ),
            PortMetadata(
                name="concentrations",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Concentrations",
                description="Resolved concentration profiles (C)",
            ),
            PortMetadata(
                name="spectra",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Pure Spectra",
                description="Resolved pure component spectra (St)",
            ),
            PortMetadata(
                name="purity_values",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Purity Values",
                description="Purity values for resolved components",
            ),
        ],
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.SIMPLISMA.html",
        canonical_parameter_validator=_canonical_simplisma_parameters,
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for SIMPLISMA decomposition."""
        if not use_scp:
            return [
                f"{indent}# --- SIMPLISMA ({self.node_id}) ---",
                f"{indent}# SIMPLISMA requires SpectroChemPy (pip install spectra-sherpa[scp])",
                f"{indent}raise ImportError('SIMPLISMA requires spectrochempy')",
            ]

        params = self._resolve_params()
        X_expr = inputs.get("default", inputs.get("X", "input_data"))
        return [
            f"{indent}# --- Canonical SIMPLISMA pure-variable estimates ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.simplisma_nodes "
            "import _simplisma_numeric_outputs",
            f"{indent}results[{self.node_id!r}] = _simplisma_numeric_outputs(",
            f"{indent}    {X_expr}, parameters={params!r},",
            f"{indent})",
        ]

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute SIMPLISMA decomposition on input dataset.

        Args:
            input_data: Dataset containing spectral mixture data
                       Shape should be (n_samples, n_wavenumbers)

        Returns:
            Dict containing:
            - C: Concentration profiles (n_samples, n_components)
            - St: Pure spectra (n_components, n_wavenumbers)
            - n_components: Number of resolved components
        """
        del kwargs
        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (spectral mixtures)",
            dataset_error_message="input_data must be an dataset object",
            allow_array=False,
        )
        params = self._resolve_params()
        n_components = int(params["n_components"])
        noise = float(params["noise"])
        n_samples, n_features = input_ds.shape
        numeric = _simplisma_numeric_outputs(input_ds, parameters=params)
        C_data = np.asarray(numeric["concentrations"], dtype=np.float64)
        St_data = np.asarray(numeric["spectra"], dtype=np.float64)
        purity_values = np.asarray(numeric["purity_values"], dtype=np.float64)

        # Get input coordinates for dataset creation
        _x_coord = input_ds.get_feature_axis()
        _y_coord = input_ds.get_observation_axis()

        logger.debug("[SIMPLISMA Node] Decomposition completed successfully")
        logger.debug("  - C shape: %s", C_data.shape)
        logger.debug("  - St shape: %s", St_data.shape)

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

        # Try to extract species names from input metadata (from BlendNode ground truth)
        species_names = None
        if hasattr(input_ds, "meta") and input_ds.meta:
            spectra_meta = input_ds.meta.get("spectra", {})
            if isinstance(spectra_meta, dict):
                species_list = spectra_meta.get("species", [])
                if species_list and len(species_list) >= n_components:
                    try:
                        names: list[str] = []
                        for spec in species_list[:n_components]:
                            if isinstance(spec, dict):
                                names.append(spec.get("name", f"Species {len(names) + 1}"))
                            elif hasattr(spec, "name"):
                                names.append(spec.name)
                            else:
                                names.append(f"Species {len(names) + 1}")
                        species_names = names
                    except Exception:
                        pass

        # Use species names if available, otherwise use generic labels
        component_labels = species_names or [f"Component {i + 1}" for i in range(n_components)]
        spectrum_labels = species_names or [f"Pure Spectrum {i + 1}" for i in range(n_components)]

        # =====================================================================
        # Create SherpaDataset objects for St and C with coordinate coupling
        # Same pattern as MCRNode (same C/St decomposition structure)
        # =====================================================================

        # St (Pure Spectra): shape (n_components, n_features)
        St_dataset = _create_spectral_dataset(
            data=St_data,
            x_coord=_x_coord,
            y_coord=_make_safe_coord(spectrum_labels, title="Component"),
            units=input_ds.units if hasattr(input_ds, "units") else None,
            title="SIMPLISMA Pure Component Spectra",
        )

        # C (Concentrations): shape (n_samples, n_components)
        C_dataset = _create_spectral_dataset(
            data=C_data,
            x_coord=_make_safe_coord(component_labels, title="Component"),
            y_coord=_y_coord,
            units="relative concentration",
            title="SIMPLISMA Concentration Profiles",
        )

        # Add processing history
        copy_processing_history(input_ds, C_dataset)
        add_processing_step(
            C_dataset,
            "model.simplisma.concentrations",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        copy_processing_history(input_ds, St_dataset)
        add_processing_step(
            St_dataset,
            "model.simplisma.spectra",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Propagate dataset-level flags. C (concentrations) is
        # sample-axis-preserved; St (pure spectra) rows are components.
        # Origin tags survive on every output.
        inherit_sample_flags(input_ds, C_dataset)
        inherit_origin_flags(input_ds, C_dataset)
        inherit_origin_flags(input_ds, St_dataset)

        # Store scientific metadata that coordinates can't carry
        C_dataset.meta.update(
            {
                "type": "SIMPLISMA",
                "n_components": n_components,
                "label_categories": label_categories,
                "species_names": species_names,
                "quality_summary": {
                    "n_components": int(n_components),
                },
            }
        )

        # Purity values extracted by SIMPLISMAExtract
        purity_list = purity_values.tolist()

        diagnostics: dict[str, Any] = {
            "n_components": int(n_components),
            "noise": float(noise),
        }
        if purity_list:
            try:
                diagnostics["purity_min"] = float(min(purity_list))
                diagnostics["purity_max"] = float(max(purity_list))
            except Exception:
                pass

        return NodeResult(
            outputs={
                "default": C_dataset,  # SherpaDataset: concentrations + sample labels (y) + component coords (x)
                "concentrations": C_dataset,  # Alias
                "spectra": St_dataset,  # SherpaDataset: pure spectra + wavenumbers (x) + component coords (y)
                "purity_values": purity_list,
            },
            diagnostics=diagnostics,
        )


bind_stable_execution_contract(
    SIMPLISMANode,
    runtime_family=RuntimeFamily.SPECTROCHEMPY,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.model.simplisma",
    implementation_version="1.0.1",
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
        "Windig & Guilment, Interactive self-modeling mixture analysis, Analytical Chemistry 63 (1991) 1425-1432",
        "SpectroChemPy SIMPLISMA documentation and purity-maximization implementation",
    ),
    deterministic=True,
    target_access=TargetAccess.NONE,
    group_access="none",
)
