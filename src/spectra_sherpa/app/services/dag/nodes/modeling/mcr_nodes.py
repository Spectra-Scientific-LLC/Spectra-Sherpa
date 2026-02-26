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
    resolve_legacy_input,
    to_numpy_2d,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    PortMetadata,
    register_node,
)
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
                description="Resolved concentration profiles (C) as NDDataset with sample/component axes",
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
        input_data = resolve_legacy_input(input_data, kwargs, "default")
        input_ds = bind_X(
            input_data,
            kwargs,
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
        C_data = extracted.C
        St_data = extracted.St

        # Get input coordinates for NDDataset creation
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
                        names = []
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
        # Create proper NDDataset objects for St and C with coordinate coupling
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

        # Compute residuals as NDDataset
        reconstructed = C_data @ St_data
        residuals_data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64) - reconstructed
        residuals_dataset = _create_spectral_dataset(
            data=residuals_data,
            x_coord=_x_coord,
            y_coord=_y_coord,  # Preserve sample labels from input
            units=input_ds.units if hasattr(input_ds, "units") else None,
            title="MCR-ALS Residuals",
        )

        # Add processing history to NDDataset outputs
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

        # Store only scientific metadata that coordinates can't carry
        C_dataset.meta.update(
            {
                "n_components": n_components,
                "label_categories": label_categories,
                "species_names": species_names,
            }
        )

        return {
            "default": C_dataset,  # NDDataset: concentration profiles + sample labels (y) + component coords (x)
            "C": C_dataset,  # Alias for concentrations
            "St": St_dataset,  # NDDataset: pure spectra + wavenumbers (x) + component coords (y)
            "residuals": residuals_dataset,  # NDDataset: residuals
            "model": mcr,  # Model port
        }
