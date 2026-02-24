"""
SIMPLISMA self-modeling mixture analysis node.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ...io_contracts import (
    bind_X,
    resolve_legacy_input,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    PortMetadata,
    register_node,
)
from .core_utils import (
    is_sequential_numeric as _is_sequential_numeric,
)

logger = logging.getLogger(__name__)

from spectra_sherpa.app.lib.adapters.scp_extractors import SIMPLISMAExtract, _unwrap_to_numpy
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
        category="modeling",
        label="SIMPLISMA",
        description="Self-modeling mixture analysis using purity maximization",
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
                name="tol",
                label="Tolerance",
                param_type="number",
                default=0.1,
                min_value=0.001,
                max_value=1.0,
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
                max_value=10.0,
                step=0.1,
                description="Noise level for purity calculation",
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
                label="SIMPLISMA Model",
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
        C_data = extracted.C
        St_data = extracted.St
        purities = extracted.purities

        # Get wavenumber axis from input if available
        wavenumbers = None
        _x_coord = input_ds.feature_axis
        if _x_coord is not None:
            try:
                wavenumbers = _unwrap_to_numpy(_x_coord, name="wavenumbers").astype(np.float64).tolist()
            except Exception:
                pass

        # Get time axis from input if available
        times = None
        _y_coord = input_ds.sample_axis
        if _y_coord is not None:
            try:
                times = _unwrap_to_numpy(_y_coord, name="times").astype(np.float64).tolist()
            except Exception:
                pass
        if times is None:
            # Use sample indices as time points
            times = list(range(n_samples))

        logger.debug("[SIMPLISMA Node] Decomposition completed successfully")
        logger.debug("  - C shape: %s", C_data.shape)
        logger.debug("  - St shape: %s", St_data.shape)

        # Extract sample labels from input data for categorical coloring
        sample_labels = None
        label_categories = None

        if _y_coord is not None:
            if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                try:
                    labels = _y_coord.labels
                    raw = labels.tolist() if hasattr(labels, "tolist") else list(labels)
                    # Convert ALL labels to native Python str — avoids numpy StrDType
                    # ufunc errors when sorting/comparing numpy string scalars
                    sample_labels = [str(l) for l in raw]
                    label_categories = sorted(set(sample_labels))
                    logger.debug(
                        "[SIMPLISMA Node] Extracted %s sample labels with %s unique categories",
                        len(sample_labels),
                        len(label_categories),
                    )
                except Exception as e:
                    logger.warning(
                        "[SIMPLISMA Node] Could not extract categorical labels from y.labels: %s", e, exc_info=True
                    )
                    sample_labels = None
                    label_categories = None

            if sample_labels is None and hasattr(_y_coord, "data") and _y_coord.data is not None:
                try:
                    # Fallback: use y-axis data as numeric labels
                    y_data = _y_coord.data
                    raw = y_data.tolist() if hasattr(y_data, "tolist") else list(y_data)
                    sample_labels = [str(l) for l in raw]

                    # For numeric data, only treat as categorical if:
                    # 1. Reasonable number of unique values (< 20)
                    # 2. NOT a sequential series (e.g., not time indices or temperature series)
                    unique_values = sorted(set(sample_labels))
                    if len(unique_values) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique_values
                        logger.debug(
                            "[SIMPLISMA Node] Using numeric y.data as categorical labels: %s categories",
                            len(label_categories),
                        )
                except Exception as e:
                    logger.warning(
                        "[SIMPLISMA Node] Could not extract categorical labels from y.data: %s", e, exc_info=True
                    )
                    sample_labels = None
                    label_categories = None

        # If no labels found, generate default sample labels
        if sample_labels is None:
            sample_labels = [f"Sample {i+1}" for i in range(n_samples)]

        # Purity values extracted by SIMPLISMAExtract
        purity_list = purities.tolist() if purities is not None else []

        return {
            "model": simplisma,
            "concentrations": C_data.tolist(),
            "spectra": St_data.tolist(),
            "purity_values": purity_list,
            "C": C_data.tolist(),  # Concentration profiles (n_samples, n_components)
            "St": St_data.tolist(),  # Pure spectra (n_components, n_features)
            "n_components": n_components,
            "n_samples": n_samples,
            "n_features": n_features,
            # Primary data for visualization - concentration profiles
            "data": C_data.tolist(),
            "metadata": {
                "type": "SIMPLISMA",
                "output_type": "decomposition",
                "n_components": n_components,
                "n_samples": n_samples,
                "n_features": n_features,
                # Labels for concentration columns
                "labels": [f"Component {i+1}" for i in range(n_components)],
                # X-axis for C plot (time/sample index)
                "x_axis": times,
                "x_label": "Time / Sample Index",
                "y_label": "Relative Concentration",
                # Wavenumbers for St plot
                "wavenumbers": wavenumbers,
                # Additional data for St visualization
                "St": St_data.tolist(),
                "St_labels": [f"Pure Spectrum {i+1}" for i in range(n_components)],
                # Sample labels for categorical coloring
                "sample_labels": sample_labels,  # List of labels (one per sample)
                "label_categories": label_categories,  # List of unique categories (None if no categorical labels)
            },
        }


