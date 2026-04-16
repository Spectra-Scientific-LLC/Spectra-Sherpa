"""
MCR-ALS decomposition node.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history

from ...io_contracts import (
    bind_X,
    to_numpy_2d,
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

from spectra_sherpa.app.lib.adapters.scp_extractors import MCRExtract
from spectra_sherpa.app.lib.scp_compat import scp, to_nddataset


@register_node
class MCRNode(Node):
    """
    Multivariate Curve Resolution - Alternating Least Squares (MCR-ALS) node.

    Performs MCR-ALS decomposition on spectral data to resolve mixtures
    into pure component spectra and concentration profiles.

    Uses SpectroChemPy's MCRALS implementation.
    """

    metadata = NodeMetadata(
        node_type="model.mcr_als",
        category="exploratory",
        label="MCR-ALS",
        description="Multivariate Curve Resolution for mixture analysis",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=2,
                max_value=20,
                step=1,
                description="Number of pure components to resolve",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="non_negative_C",
                label="Non-negative Concentrations",
                param_type="boolean",
                default=True,
                description="Enforce non-negative concentration profiles",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="non_negative_St",
                label="Non-negative Spectra",
                param_type="boolean",
                default=True,
                description="Enforce non-negative spectra",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="max_iter",
                label="Maximum Iterations",
                param_type="number",
                default=50,
                min_value=10,
                max_value=500,
                step=10,
                description="Maximum ALS iterations",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=0.1,
                min_value=0.001,
                max_value=1.0,
                step=0.01,
                description="Convergence tolerance for ALS",
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
                label="MCR Model",
                description="Fitted MCR-ALS model object",
            ),
            PortMetadata(
                name="C",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Concentrations",
                description="Resolved concentration profiles (C) with sample/component axes",
            ),
            PortMetadata(
                name="St",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Pure Spectra",
                description="Resolved pure component spectra (S^T)",
            ),
            PortMetadata(
                name="residuals",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=False,
                label="Residuals",
                description="Modeling residuals",
            ),
        ],
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.MCRALS.html",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for MCR-ALS decomposition."""
        if not use_scp:
            return [
                f"{indent}# --- MCR-ALS ({self.node_id}) ---",
                f"{indent}# MCR-ALS requires SpectroChemPy (pip install spectra-sherpa[scp])",
                f"{indent}raise ImportError('MCR-ALS requires spectrochempy')",
            ]

        params = self._resolve_params()
        n_components = params.get("n_components", 3)
        nn_C = "True" if params.get("non_negative_C", True) else "False"
        nn_St = "True" if params.get("non_negative_St", True) else "False"
        max_iter = params.get("max_iter", 50)
        tol = params.get("tol", 0.1)

        X_expr = inputs.get("default", inputs.get("X", "input_data"))

        lines: list[str] = []
        lines.append(f"{indent}# --- MCR-ALS ({self.node_id}) ---")
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")
        lines.append(f"{indent}_X_ndd = scp.NDDataset(_X_data)")
        lines.append(f"{indent}# Initialize C from SVD")
        lines.append(f"{indent}_U, _S, _Vt = np.linalg.svd(_X_data, full_matrices=False)")
        lines.append(f"{indent}_C0 = np.abs(_U[:, :{n_components}] * _S[:{n_components}])")
        lines.append(f"{indent}_C0_ndd = scp.NDDataset(_C0)")
        lines.append(f"{indent}_mcr = scp.MCRALS(")
        lines.append(f"{indent}    _X_ndd, _C0_ndd,")
        lines.append(f"{indent}    nonnegConc=[0, 1] if {nn_C} else [],")
        lines.append(f"{indent}    nonnegSpec=[0, 1] if {nn_St} else [],")
        lines.append(f"{indent}    maxdiv={max_iter}, tol={tol},")
        lines.append(f"{indent})")
        lines.append(f"{indent}_C = np.asarray(_mcr.C.data, dtype=np.float64)")
        lines.append(f"{indent}_St = np.asarray(_mcr.St.data, dtype=np.float64)")
        lines.append(f'{indent}print(f"  MCR-ALS ({n_components} components): C={{_C.shape}}, St={{_St.shape}}")')
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'model': _mcr,")
        lines.append(f"{indent}    'C': _C,")
        lines.append(f"{indent}    'St': _St,")
        lines.append(f"{indent}    'residuals': _C @ _St - _X_data,")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute MCR-ALS decomposition on input dataset.

        Args:
            input_data: Dataset containing spectral mixture data (D matrix)
                       Shape should be (n_samples, n_wavenumbers)

        Returns:
            Dict containing:
            - model: The MCRALS model object
            - C: Concentration profiles (n_samples, n_components) as SpectralResult
            - St: Pure spectra (n_components, n_wavenumbers) as SpectralResult
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
        max_iter = self.parameters.get("max_iter", 50)
        tol = self.parameters.get("tol", 0.1)
        non_negative_C = self.parameters.get("non_negative_C", True)
        non_negative_St = self.parameters.get("non_negative_St", True)

        # Validate input shape
        if len(input_ds.shape) != 2:
            raise ValueError(f"Expected 2D input, got shape {input_ds.shape}")

        n_samples, n_features = input_ds.shape
        if n_components > min(n_samples, n_features):
            raise ValueError(
                f"n_components ({n_components}) cannot exceed min(n_samples, n_features) = {min(n_samples, n_features)}"
            )

        # Create initial guess for C using SVD
        # This provides a good starting point for ALS
        from numpy.linalg import svd

        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        U, S, Vt = svd(data, full_matrices=False)

        # Initial C estimate from first n_components of U*S
        C0_data = U[:, :n_components] @ np.diag(S[:n_components])
        # If non-negative, shift/scale to avoid negative initial guesses
        if non_negative_C:
            C0_data = np.abs(C0_data)
        C0 = scp.NDDataset(C0_data)

        # Determine appropriate solvers based on constraints
        solver_c = "nnls" if non_negative_C else "lstsq"
        solver_s = "nnls" if non_negative_St else "lstsq"

        # Create and fit MCR-ALS model
        mcr = scp.MCRALS(max_iter=max_iter, tol=tol, solverConc=solver_c, solverSpec=solver_s)
        mcr.fit(input_ndd, C0)

        # Extract results using typed extractor
        extracted = MCRExtract.from_scp(mcr)
        C_data = _ensure_orientation(
            extracted.C,
            expected_rows=n_samples,
            expected_cols=n_components,
            name="MCR.C",
        )
        St_data = _ensure_orientation(
            extracted.St,
            expected_rows=n_components,
            expected_cols=n_features,
            name="MCR.St",
        )

        # Get input coordinates for SherpaDataset creation
        # Use generic accessors to support all axis types (TimeAxis, SampleAxis, etc.)
        _x_coord = input_ds.get_feature_axis()
        _y_coord = input_ds.get_observation_axis()

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
                        logger.debug("[MCR-ALS Node] Extracted species names from input metadata: %s", species_names)
                    except Exception as e:
                        logger.warning("[MCR-ALS Node] Could not extract species names: %s", e, exc_info=True)

        # Use species names if available, otherwise use generic labels
        component_labels = species_names or [f"Component {i+1}" for i in range(n_components)]
        spectrum_labels = species_names or [f"Pure Spectrum {i+1}" for i in range(n_components)]

        # =====================================================================
        # Create SherpaDataset objects for St and C with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        # St (Pure Spectra): shape (n_components, n_features)
        # X-axis = wavenumbers from input, Y-axis = component labels
        St_dataset = _create_spectral_dataset(
            data=St_data,
            x_coord=_x_coord,
            y_coord=_make_safe_coord(spectrum_labels, title="Component"),
            units=input_ds.units if hasattr(input_ds, "units") else None,
            title="MCR-ALS Pure Component Spectra",
        )

        # C (Concentrations): shape (n_samples, n_components)
        # X-axis = component labels, Y-axis = sample labels/time
        C_dataset = _create_spectral_dataset(
            data=C_data,
            x_coord=_make_safe_coord(component_labels, title="Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="relative concentration",
            title="MCR-ALS Concentration Profiles",
        )

        # Compute residuals as SherpaDataset
        reconstructed = C_data @ St_data
        residuals_data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64) - reconstructed
        residuals_dataset = _create_spectral_dataset(
            data=residuals_data,
            x_coord=_x_coord,
            y_coord=_y_coord,  # Preserve sample labels from input
            units=input_ds.units if hasattr(input_ds, "units") else None,
            title="MCR-ALS Residuals",
        )

        # Add processing history to SherpaDataset outputs
        copy_processing_history(input_ds, C_dataset)
        add_processing_step(
            C_dataset,
            "model.mcr_als.concentrations",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        copy_processing_history(input_ds, St_dataset)
        add_processing_step(
            St_dataset,
            "model.mcr_als.spectra",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        copy_processing_history(input_ds, residuals_dataset)
        add_processing_step(
            residuals_dataset,
            "model.mcr_als.residuals",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Store scientific metadata + embed St/wavenumber data for detailed view plots
        wavenumbers = None
        x_title = None
        x_units = None
        if _x_coord is not None:
            try:
                wavenumbers = np.array(_x_coord.data).tolist()
            except Exception:
                pass
            x_title = getattr(_x_coord, "title", None)
            x_units = str(_x_coord.units) if getattr(_x_coord, "units", None) else None

        # NOTE: Keys "wavenumbers", "x_title", "x_units" are OVERWRITTEN by
        # _serialize_sherpa_dataset() with C_dataset's own feature axis (component
        # indices).  Use "spectral_" prefix so the original input wavenumbers
        # survive serialization and are available for St plots.
        C_dataset.meta.update(
            {
                "type": "MCR_ALS",
                "n_components": n_components,
                "label_categories": label_categories,
                "species_names": species_names,
                "labels": component_labels,
                "St": St_data.tolist(),
                "St_labels": spectrum_labels,
                "spectral_wavenumbers": wavenumbers,
                "spectral_x_title": x_title,
                "spectral_x_units": x_units,
            }
        )

        # Build model artifact for persistence
        from ._artifact_builder import build_model_artifact

        artifact = build_model_artifact(
            extracted,
            input_ds,
            node_id=self.node_id,
        )

        # Compute diagnostics scalars for Sherpa advisor
        diagnostics: dict[str, Any] = {"n_components": int(n_components)}
        try:
            residual_rms = float(np.sqrt(np.mean(residuals_data**2)))
            diagnostics["residual_rms"] = residual_rms
            input_ss = float(np.sum(data**2))
            if input_ss > 0:
                lof_percent = float(100.0 * np.sum(residuals_data**2) / input_ss)
                diagnostics["lof_percent"] = lof_percent
        except Exception:
            logger.debug("[MCR-ALS Node] Failed to compute residual diagnostics", exc_info=True)
        for attr, key in (("n_iter", "n_iter"), ("n_iter_", "n_iter")):
            if hasattr(mcr, attr):
                try:
                    diagnostics[key] = int(getattr(mcr, attr))
                    break
                except Exception:
                    pass
        for attr in ("converged", "converged_"):
            if hasattr(mcr, attr):
                try:
                    diagnostics["converged"] = bool(getattr(mcr, attr))
                    break
                except Exception:
                    pass

        quality_summary: dict = {
            "n_components": int(n_components),
            "method": "MCR-ALS",
        }
        if "n_iter" in diagnostics:
            quality_summary["n_iter"] = int(diagnostics["n_iter"])
        if "lof_percent" in diagnostics:
            quality_summary["lof_percent"] = float(diagnostics["lof_percent"])
        if "residual_rms" in diagnostics:
            quality_summary["residual_rms"] = float(diagnostics["residual_rms"])
        C_dataset.meta.update({"quality_summary": quality_summary})

        return NodeResult(
            outputs={
                "default": C_dataset,  # SherpaDataset: concentration profiles (n_samples, n_components)
                "C": C_dataset,  # Alias for concentrations
                "St": St_dataset,  # SherpaDataset: pure spectra (n_components, n_features)
                "residuals": residuals_dataset,  # SherpaDataset: residuals (n_samples, n_features)
                "model": mcr,  # Model port
                "_model_artifact": artifact,
            },
            diagnostics=diagnostics,
        )
