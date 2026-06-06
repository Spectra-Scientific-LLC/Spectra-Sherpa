"""
SIMPLISMA self-modeling mixture analysis node.
"""

from __future__ import annotations

import logging
from typing import Any

from spectra_sherpa.app.services.dag.meta_helpers import (
    add_processing_step,
    copy_processing_history,
    inherit_origin_flags,
    inherit_sample_flags,
)

from ...io_contracts import (
    bind_X,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
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

from spectra_sherpa.app.lib.adapters.scp_extractors import SIMPLISMAExtract
from spectra_sherpa.app.lib.scp_compat import scp, to_nddataset


@register_node
class SIMPLISMANode(Node):
    """
    SIMPLISMA (SIMPLe-to-use Interactive Self-modeling Mixture Analysis) node.

    Performs SIMPLISMA decomposition to resolve pure component spectra
    from mixture data using a self-modeling approach based on purity maximization.

    Uses SpectroChemPy's SIMPLISMA implementation.
    """

    metadata = NodeMetadata(
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
                step=0.1,
                description="Noise level for purity calculation",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset"],
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
                name="model",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="Fitted SIMPLISMA Pure Components",
                description="Fitted SIMPLISMA model object",
            ),
            PortMetadata(
                name="concentrations",
                type_ref="spectrasherpa://types/Array1D/1.0",
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
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.SIMPLISMA.html",
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
        n_components = params.get("n_components", 3)
        tol = params.get("tol", 0.1)
        noise = params.get("noise", 3.0)

        X_expr = inputs.get("default", inputs.get("X", "input_data"))

        lines: list[str] = []
        lines.append(f"{indent}# --- SIMPLISMA ({self.node_id}) ---")
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")
        lines.append(f"{indent}_X_ndd = scp.NDDataset(_X_data)")
        lines.append(f"{indent}_simplisma = scp.SIMPLISMA(n_components={n_components}, tol={tol}, noise={noise})")
        lines.append(f"{indent}_simplisma.fit(_X_ndd)")
        lines.append(f"{indent}_C = np.asarray(_simplisma.C.data, dtype=np.float64)")
        lines.append(f"{indent}_St = np.asarray(_simplisma.St.data, dtype=np.float64)")
        lines.append(
            f"{indent}_purity = ("
            f"np.asarray(_simplisma.Pur.data, dtype=np.float64).tolist()"
            f" if hasattr(_simplisma, 'Pur') and _simplisma.Pur is not None"
            f" else [])"
        )
        lines.append(f'{indent}print(f"  SIMPLISMA ({n_components} components): C={{_C.shape}}, St={{_St.shape}}")')
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'model': _simplisma,")
        lines.append(f"{indent}    'concentrations': _C,")
        lines.append(f"{indent}    'spectra': _St,")
        lines.append(f"{indent}    'purity_values': _purity,")
        lines.append(f"{indent}}}")

        return lines

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
        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (spectral mixtures)",
            dataset_error_message="input_data must be an dataset object",
            allow_array=False,
        )
        input_ndd = to_nddataset(input_ds)

        # Get parameters
        n_components = self.parameters.get("n_components", 3)
        tol = self.parameters.get("tol", 0.1)
        noise = self.parameters.get("noise", 3.0)

        # Validate input shape
        if len(input_ds.shape) != 2:
            raise ValueError(f"Expected 2D input, got shape {input_ds.shape}")

        n_samples, n_features = input_ds.shape
        if n_components > min(n_samples, n_features):
            raise ValueError(
                f"n_components ({n_components}) cannot exceed min(n_samples, n_features) = {min(n_samples, n_features)}"
            )

        logger.debug("[SIMPLISMA Node] Executing with:")
        logger.debug("  - n_components: %s", n_components)
        logger.debug("  - tol: %s", tol)
        logger.debug("  - noise: %s", noise)
        logger.debug("  - Data shape: %s samples x %s features", n_samples, n_features)

        # Perform SIMPLISMA using SpectroChemPy
        simplisma = scp.SIMPLISMA(n_components=n_components, tol=tol, noise=noise)
        simplisma.fit(input_ndd)

        # Extract results using typed extractor
        extracted = SIMPLISMAExtract.from_scp(simplisma)
        C_data = _ensure_orientation(
            extracted.C,
            expected_rows=n_samples,
            expected_cols=n_components,
            name="SIMPLISMA.C",
        )
        St_data = _ensure_orientation(
            extracted.St,
            expected_rows=n_components,
            expected_cols=n_features,
            name="SIMPLISMA.St",
        )
        purities = extracted.purities

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
                                names.append(spec.get("name", f"Species {len(names)+1}"))
                            elif hasattr(spec, "name"):
                                names.append(spec.name)
                            else:
                                names.append(f"Species {len(names)+1}")
                        species_names = names
                    except Exception:
                        pass

        # Use species names if available, otherwise use generic labels
        component_labels = species_names or [f"Component {i+1}" for i in range(n_components)]
        spectrum_labels = species_names or [f"Pure Spectrum {i+1}" for i in range(n_components)]

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
        purity_list = purities.tolist() if purities is not None else []

        # Build model artifact for persistence
        from ._artifact_builder import build_model_artifact

        artifact = build_model_artifact(
            extracted,
            input_ds,
            node_id=self.node_id,
        )

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
                "model": simplisma,  # Model port
                "purity_values": purity_list,  # Plain list (1D diagnostic)
                "_model_artifact": artifact,
            },
            diagnostics=diagnostics,
        )
