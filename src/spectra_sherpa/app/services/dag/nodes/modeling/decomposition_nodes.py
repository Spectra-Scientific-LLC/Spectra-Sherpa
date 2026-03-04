"""
Decomposition nodes: NMF, FastICA.
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


@register_node
class NMFNode(Node):
    """
    Non-negative Matrix Factorization (NMF) node.

    Performs NMF decomposition with non-negativity constraints on both
    the concentration (W) and spectral (H) matrices. Provides physically
    interpretable results for mixture analysis.

    Uses SpectroChemPy's NMF implementation.
    """

    metadata = NodeMetadata(
        node_type="model.nmf",
        category="exploratory",
        label="NMF",
        description="Non-negative Matrix Factorization for mixture analysis",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=2,
                max_value=20,
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
                min_value=50,
                max_value=1000,
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
                min_value=0.00001,
                max_value=0.01,
                step=0.0001,
                description="Convergence tolerance",
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
                label="NMF Model",
                description="Fitted NMF model object",
            ),
            PortMetadata(
                name="concentrations",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Concentrations",
                description="Concentration profiles (W matrix) as NDDataset with sample/component axes",
            ),
            PortMetadata(
                name="spectra",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Pure Spectra",
                description="Pure component spectra (H matrix) as NDDataset with wavenumber axis",
            ),
            PortMetadata(
                name="reconstruction_error",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
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
        """Generate Python export code for NMF decomposition."""
        params = self._resolve_params()
        n_components = params.get("n_components", 3)
        solver = params.get("solver", "mu")
        max_iter = params.get("max_iter", 200)
        tol = params.get("tol", 0.0001)

        X_expr = inputs.get("default", inputs.get("X", "input_data"))

        lines: list[str] = []
        lines.append(f"{indent}# --- NMF ({self.node_id}) ---")

        # Extract X
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")
        lines.append(f"{indent}if np.any(_X_data < 0):")
        lines.append(f"{indent}    _X_data = _X_data - _X_data.min()")

        # NMF uses sklearn regardless of use_scp
        lines.append(f"{indent}from sklearn.decomposition import NMF as _NMF")
        lines.append(f"{indent}_nmf = _NMF(n_components={n_components}, solver='{solver}', max_iter={max_iter}, tol={tol})")
        lines.append(f"{indent}_W = _nmf.fit_transform(_X_data)")
        lines.append(f"{indent}_H = _nmf.components_")
        lines.append(f"{indent}_err = _nmf.reconstruction_err_ if hasattr(_nmf, 'reconstruction_err_') else None")
        lines.append(f'{indent}print(f"  NMF ({n_components} components): W={{_W.shape}}, H={{_H.shape}}")')
        lines.append(f'{indent}if _err is not None:')
        lines.append(f'{indent}    print(f"    Reconstruction error: {{_err:.6f}}")')

        # Store result
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'default': _W,")
        lines.append(f"{indent}    'concentrations': _W,")
        lines.append(f"{indent}    'spectra': _H,")
        lines.append(f"{indent}    'reconstruction_error': _err,")
        lines.append(f"{indent}    'W': _W,")
        lines.append(f"{indent}    'H': _H,")
        lines.append(f"{indent}    'model': _nmf,")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute NMF decomposition on input dataset.

        Args:
            input_data: Dataset containing non-negative spectral data
                       Shape should be (n_samples, n_wavenumbers)

        Returns:
            Dict containing:
            - W: Basis matrix / concentration profiles (n_samples, n_components) as SpectralResult
            - H: Coefficient matrix / pure spectra (n_components, n_wavenumbers) as SpectralResult
            - n_components: Number of components
        """
        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (non-negative spectra)",
            dataset_error_message="input_data must be an dataset object",
            allow_array=False,
        )

        # Get parameters
        n_components = self.parameters.get("n_components", 3)
        solver = self.parameters.get("solver", "mu")
        max_iter = self.parameters.get("max_iter", 200)
        tol = self.parameters.get("tol", 0.0001)

        # Validate input shape
        if len(input_ds.shape) != 2:
            raise ValueError(f"Expected 2D input, got shape {input_ds.shape}")

        n_samples, n_features = input_ds.shape
        if n_components > min(n_samples, n_features):
            raise ValueError(
                f"n_components ({n_components}) cannot exceed min(n_samples, n_features) = {min(n_samples, n_features)}"
            )

        # Check for negative values (NMF requires non-negative data)
        data_array = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        if np.any(data_array < 0):
            logger.warning("[NMF Node] Input contains negative values, shifting to non-negative range")
            data_array = data_array - data_array.min()

        logger.debug("[NMF Node] Executing with:")
        logger.debug("  - n_components: %s", n_components)
        logger.debug("  - solver: %s", solver)
        logger.debug("  - max_iter: %s", max_iter)
        logger.debug("  - tol: %s", tol)
        logger.debug("  - Data shape: %s samples x %s features", n_samples, n_features)

        # Perform NMF using sklearn
        from sklearn.decomposition import NMF

        nmf = NMF(n_components=n_components, solver=solver, max_iter=max_iter, tol=tol)
        W_data = nmf.fit_transform(data_array)
        H_data = nmf.components_

        # Get input coordinates for NDDataset creation
        # Use generic accessors to support all axis types (TimeAxis, SampleAxis, etc.)
        _x_coord = input_ds.get_feature_axis()
        _y_coord = input_ds.get_observation_axis()

        # Get reconstruction error if available
        reconstruction_err = None
        if hasattr(nmf, "reconstruction_err_"):
            reconstruction_err = float(nmf.reconstruction_err_)

        logger.debug("[NMF Node] Decomposition completed successfully")
        logger.debug("  - W shape: %s", W_data.shape)
        logger.debug("  - H shape: %s", H_data.shape)
        if reconstruction_err is not None:
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
        # Create proper NDDataset objects for W and H with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        component_labels = [f"Component {i+1}" for i in range(n_components)]
        spectrum_labels = [f"Basis Spectrum {i+1}" for i in range(n_components)]

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
        )

        # Add processing history to NDDataset outputs
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

        # Store only scientific metadata that coordinates can't carry
        W_dataset.meta.update(
            {
                "type": "NMF",
                "n_components": n_components,
                "label_categories": label_categories,
                "reconstruction_error": reconstruction_err,
            }
        )

        return {
            "default": W_dataset,  # NDDataset: concentration profiles + sample labels (y) + component coords (x)
            "concentrations": W_dataset,  # Alias for default
            "spectra": H_dataset,  # NDDataset: basis spectra + wavenumbers (x) + component coords (y)
            "W": W_dataset,  # Alias for concentrations
            "H": H_dataset,  # Alias for spectra
            "model": nmf,  # Model port
        }


@register_node
class FastICANode(Node):
    """
    Fast Independent Component Analysis (FastICA) node.

    Performs ICA to separate multivariate signals into independent
    non-Gaussian signals. Useful for blind source separation in
    spectroscopic mixture analysis.

    Uses SpectroChemPy's FastICA implementation.
    """

    metadata = NodeMetadata(
        node_type="model.ica",
        category="exploratory",
        label="FastICA",
        description="Independent Component Analysis for blind source separation",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=2,
                max_value=20,
                step=1,
                description="Number of independent components to extract",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="algorithm",
                label="Algorithm",
                param_type="select",
                default="parallel",
                options=["parallel", "deflation"],
                description="ICA algorithm: 'parallel' (all components at once) or 'deflation' (one at a time)",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="fun",
                label="Contrast Function",
                param_type="select",
                default="logcosh",
                options=["logcosh", "exp", "cube"],
                description="Contrast function for ICA: 'logcosh', 'exp', or 'cube'",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="max_iter",
                label="Maximum Iterations",
                param_type="number",
                default=200,
                min_value=50,
                max_value=1000,
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
                min_value=0.00001,
                max_value=0.01,
                step=0.0001,
                description="Convergence tolerance",
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
                label="ICA Model",
                description="Fitted FastICA model object",
            ),
            PortMetadata(
                name="sources",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Source Signals",
                description="Independent source signals (S)",
            ),
            PortMetadata(
                name="mixing_matrix",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Mixing Matrix",
                description="Mixing matrix (A)",
            ),
            PortMetadata(
                name="components",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Components",
                description="Independent components (St)",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for FastICA decomposition."""
        params = self._resolve_params()
        n_components = params.get("n_components", 3)
        algorithm = params.get("algorithm", "parallel")
        fun = params.get("fun", "logcosh")
        max_iter = params.get("max_iter", 200)
        tol = params.get("tol", 0.0001)

        X_expr = inputs.get("default", inputs.get("X", "input_data"))

        lines: list[str] = []
        lines.append(f"{indent}# --- FastICA ({self.node_id}) ---")

        # Extract X
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")

        # FastICA uses sklearn regardless of use_scp
        lines.append(f"{indent}from sklearn.decomposition import FastICA as _FastICA")
        lines.append(f"{indent}_ica = _FastICA(n_components={n_components}, algorithm='{algorithm}', fun='{fun}', max_iter={max_iter}, tol={tol})")
        lines.append(f"{indent}_S = _ica.fit_transform(_X_data)")
        lines.append(f"{indent}_St = _ica.components_ if hasattr(_ica, 'components_') else None")
        lines.append(f"{indent}_A = _ica.mixing_ if hasattr(_ica, 'mixing_') else None")
        lines.append(f'{indent}print(f"  FastICA ({n_components} components): sources={{_S.shape}}")')
        lines.append(f'{indent}if _St is not None:')
        lines.append(f'{indent}    print(f"    Spectral profiles: {{_St.shape}}")')

        # Store result
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'default': _S,")
        lines.append(f"{indent}    'sources': _S,")
        lines.append(f"{indent}    'components': _St,")
        lines.append(f"{indent}    'mixing_matrix': _A,")
        lines.append(f"{indent}    'model': _ica,")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute FastICA decomposition on input dataset.

        Args:
            input_data: Dataset containing spectral mixture data
                       Shape should be (n_samples, n_wavenumbers)

        Returns:
            Dict containing:
            - S: Independent source signals (n_samples, n_components)
            - A: Mixing matrix (n_components, n_wavenumbers)
            - n_components: Number of components
        """
        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (spectral mixtures)",
            dataset_error_message="input_data must be an dataset object",
            allow_array=False,
        )

        # Get parameters
        n_components = self.parameters.get("n_components", 3)
        algorithm = self.parameters.get("algorithm", "parallel")
        fun = self.parameters.get("fun", "logcosh")
        max_iter = self.parameters.get("max_iter", 200)
        tol = self.parameters.get("tol", 0.0001)

        # Validate input shape
        if len(input_ds.shape) != 2:
            raise ValueError(f"Expected 2D input, got shape {input_ds.shape}")

        n_samples, n_features = input_ds.shape
        if n_components > min(n_samples, n_features):
            raise ValueError(
                f"n_components ({n_components}) cannot exceed min(n_samples, n_features) = {min(n_samples, n_features)}"
            )

        logger.debug("[FastICA Node] Executing with:")
        logger.debug("  - n_components: %s", n_components)
        logger.debug("  - algorithm: %s", algorithm)
        logger.debug("  - fun: %s", fun)
        logger.debug("  - max_iter: %s", max_iter)
        logger.debug("  - tol: %s", tol)
        logger.debug("  - Data shape: %s samples x %s features", n_samples, n_features)

        # Perform FastICA using sklearn
        from sklearn.decomposition import FastICA

        data_array = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        ica = FastICA(
            n_components=n_components,
            algorithm=algorithm,
            fun=fun,
            max_iter=max_iter,
            tol=tol,
        )
        S_data = ica.fit_transform(data_array)
        St_data = ica.components_ if hasattr(ica, "components_") else None
        A_data = ica.mixing_ if hasattr(ica, "mixing_") else None

        # Get input coordinates for NDDataset creation
        # Use generic accessors to support all axis types (TimeAxis, SampleAxis, etc.)
        _x_coord = input_ds.get_feature_axis()
        _y_coord = input_ds.get_observation_axis()

        logger.debug("[FastICA Node] Decomposition completed successfully")
        logger.debug("  - S (sources) shape: %s", S_data.shape)
        if St_data is not None:
            logger.debug("  - St (spectral profiles) shape: %s", St_data.shape)
        if A_data is not None:
            logger.debug("  - A (mixing) shape: %s", A_data.shape)

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
                                names.append(spec.get("name", f"IC {len(names)+1}"))
                            elif hasattr(spec, "name"):
                                names.append(spec.name)
                            else:
                                names.append(f"IC {len(names)+1}")
                        species_names = names
                        logger.debug("[FastICA Node] Extracted species names from input metadata: %s", species_names)
                    except Exception as e:
                        logger.warning("[FastICA Node] Could not extract species names: %s", e, exc_info=True)

        # Use species names if available, otherwise use generic labels
        component_labels = species_names or [f"IC {i+1}" for i in range(n_components)]
        spectrum_labels = species_names or [f"IC Spectrum {i+1}" for i in range(n_components)]

        # =====================================================================
        # Create proper NDDataset objects with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        # S (Sources): shape (n_samples, n_components)
        # X-axis = component labels, Y-axis = sample labels/time
        S_dataset = _create_spectral_dataset(
            data=S_data,
            x_coord=_make_safe_coord(component_labels, title="Independent Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="source signal",
            title="FastICA Source Signals",
        )

        # St (Spectral Profiles): shape (n_components, n_features)
        # X-axis = wavenumbers from input, Y-axis = component labels
        St_dataset = None
        if St_data is not None:
            St_dataset = _create_spectral_dataset(
                data=St_data,
                x_coord=_x_coord,
                y_coord=_make_safe_coord(spectrum_labels, title="Independent Component"),
                units=input_ds.units if hasattr(input_ds, "units") else None,
                title="FastICA Spectral Profiles",
            )

        # A (Mixing Matrix): shape (n_samples, n_components) or similar
        A_dataset = None
        if A_data is not None:
            A_dataset = _create_spectral_dataset(
                data=A_data,
                x_coord=_make_safe_coord(component_labels, title="Independent Component"),
                y_coord=_y_coord,  # Preserve sample labels from input
                units="mixing coefficient",
                title="FastICA Mixing Matrix",
            )

        # Add processing history to NDDataset outputs
        copy_processing_history(input_ds, S_dataset)
        add_processing_step(
            S_dataset,
            "model.ica.sources",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        if St_dataset is not None:
            copy_processing_history(input_ds, St_dataset)
            add_processing_step(
                St_dataset,
                "model.ica.components",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        if A_dataset is not None:
            copy_processing_history(input_ds, A_dataset)
            add_processing_step(
                A_dataset,
                "model.ica.mixing_matrix",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        # Store only scientific metadata that coordinates can't carry
        S_dataset.meta.update(
            {
                "type": "FastICA",
                "n_components": n_components,
                "label_categories": label_categories,
                "species_names": species_names,
            }
        )

        return {
            "default": S_dataset,  # NDDataset: source signals + sample labels (y) + IC coords (x)
            "sources": S_dataset,  # Alias for default
            "components": St_dataset,  # NDDataset: spectral profiles + wavenumbers (x) + IC coords (y)
            "mixing_matrix": A_dataset,  # NDDataset: mixing matrix
            "model": ica,  # Model port
        }


# =============================================================================
# Apply Model Nodes (Inference)
# =============================================================================
