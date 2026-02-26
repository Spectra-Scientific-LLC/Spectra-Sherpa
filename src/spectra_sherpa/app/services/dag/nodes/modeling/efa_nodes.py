"""
Evolving Factor Analysis (EFA) node.
"""

from __future__ import annotations

import logging
from typing import Any

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history

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
    create_spectral_dataset as _create_spectral_dataset,
)
from .core_utils import (
    make_safe_coord as _make_safe_coord,
)

logger = logging.getLogger(__name__)

from spectra_sherpa.app.lib.adapters.scp_extractors import EFAExtract
from spectra_sherpa.app.lib.scp_compat import scp, to_nddataset


@register_node
class EFANode(Node):
    """
    Evolving Factor Analysis (EFA) node.

    Performs EFA to determine the number of significant factors
    and the chemical rank of evolving systems.

    Uses SpectroChemPy's EFA implementation.
    """

    metadata = NodeMetadata(
        node_type="model.efa",
        category="exploratory",
        label="EFA",
        description="Evolving Factor Analysis for rank determination",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=10,
                min_value=1,
                max_value=50,
                step=1,
                description="Number of components to compute",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                required=True,
                label="EFA Model",
                description="EFA model object",
            ),
            PortMetadata(
                name="forward_eigenvalues",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Forward Eigenvalues",
                description="Eigenvalues from forward EFA as NDDataset (samples × components)",
            ),
            PortMetadata(
                name="backward_eigenvalues",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Backward Eigenvalues",
                description="Eigenvalues from backward EFA as NDDataset (samples × components)",
            ),
        ],
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.EFA.html",
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute EFA on input dataset.

        Args:
            input_data: Dataset containing evolving spectral data

        Returns:
            Dict containing forward and backward eigenvalues
        """
        input_data = resolve_legacy_input(input_data, kwargs, "default")
        input_ds = bind_X(
            input_data,
            kwargs,
            missing_message="Missing required input: input_data (evolving spectra)",
            dataset_error_message="input_data must be an dataset object",
            allow_array=False,
        )
        input_ndd = to_nddataset(input_ds)

        n_components = self.parameters.get("n_components", 10)

        # Perform EFA using SpectroChemPy
        efa = scp.EFA(n_components=n_components)
        efa.fit(input_ndd)

        # Extract results using typed extractor
        extracted = EFAExtract.from_scp(efa)
        forward_ev = extracted.forward_ev
        backward_ev = extracted.backward_ev

        # Get input y_coord for sample labels
        _y_coord = input_ds.sample_axis

        # =====================================================================
        # Create proper NDDataset objects for eigenvalues with coordinate coupling
        # This enables "smart array" behavior - slicing data also slices axes
        # =====================================================================

        component_labels = [f"EV{i+1}" for i in range(n_components)]

        # Forward eigenvalues: shape (n_samples, n_components)
        forward_ev_dataset = None
        if forward_ev is not None:
            forward_ev_dataset = _create_spectral_dataset(
                data=forward_ev,
                x_coord=_make_safe_coord(component_labels, title="Component"),
                y_coord=_y_coord,  # Preserve sample labels from input
                units="eigenvalue",
                title="EFA Forward Eigenvalues",
            )

        # Backward eigenvalues: shape (n_samples, n_components)
        backward_ev_dataset = None
        if backward_ev is not None:
            backward_ev_dataset = _create_spectral_dataset(
                data=backward_ev,
                x_coord=_make_safe_coord(component_labels, title="Component"),
                y_coord=_y_coord,  # Preserve sample labels from input
                units="eigenvalue",
                title="EFA Backward Eigenvalues",
            )

        # Add processing history to NDDataset outputs
        if forward_ev_dataset is not None:
            copy_processing_history(input_ds, forward_ev_dataset)
            add_processing_step(
                forward_ev_dataset,
                "model.efa.forward_eigenvalues",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        if backward_ev_dataset is not None:
            copy_processing_history(input_ds, backward_ev_dataset)
            add_processing_step(
                backward_ev_dataset,
                "model.efa.backward_eigenvalues",
                {"n_components": n_components},
                node_id=self.node_id,
            )

        # Store only scientific metadata that coordinates can't carry
        # Use forward_ev_dataset as default output
        default_dataset = forward_ev_dataset or backward_ev_dataset
        if default_dataset is not None:
            default_dataset.meta.update(
                {
                    "n_components": n_components,
                }
            )

        return {
            "default": default_dataset,  # NDDataset: forward eigenvalues (primary output)
            "forward_eigenvalues": forward_ev_dataset,  # NDDataset: forward eigenvalues
            "backward_eigenvalues": backward_ev_dataset,  # NDDataset: backward eigenvalues
            "model": efa,  # Model port
        }
