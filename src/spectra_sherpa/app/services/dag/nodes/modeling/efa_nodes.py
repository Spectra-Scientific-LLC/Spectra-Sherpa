"""
Evolving Factor Analysis (EFA) node.
"""

from __future__ import annotations

import logging
from typing import Any

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history

from ...io_contracts import (
    bind_X,
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
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.EFA.html",
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
        n_components = params.get("n_components", 10)

        X_expr = inputs.get("default", inputs.get("X", "input_data"))

        lines: list[str] = []
        lines.append(f"{indent}# --- EFA ({self.node_id}) ---")
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")
        lines.append(f"{indent}_X_ndd = scp.NDDataset(_X_data)")
        lines.append(f"{indent}_efa = scp.EFA(n_components={n_components})")
        lines.append(f"{indent}_efa.fit(_X_ndd)")
        lines.append(f"{indent}_fwd = np.asarray(_efa.f_ev.data, dtype=np.float64)")
        lines.append(f"{indent}_bwd = np.asarray(_efa.b_ev.data, dtype=np.float64)")
        lines.append(
            f'{indent}print(f"  EFA ({n_components} components): forward={{_fwd.shape}}, backward={{_bwd.shape}}")'
        )
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'model': _efa,")
        lines.append(f"{indent}    'forward_eigenvalues': _fwd,")
        lines.append(f"{indent}    'backward_eigenvalues': _bwd,")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute EFA on input dataset.

        Args:
            input_data: Dataset containing evolving spectral data

        Returns:
            Dict containing forward and backward eigenvalues
        """
        input_ds = bind_X(
            input_data,
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

        # SCP EFA returns all eigenvalues per window position — shape is
        # (n_samples, min(n_samples, n_features)).  Truncate to the first
        # n_components columns which correspond to the dominant factors.
        if forward_ev is not None and forward_ev.shape[1] > n_components:
            forward_ev = forward_ev[:, :n_components]
        if backward_ev is not None and backward_ev.shape[1] > n_components:
            backward_ev = backward_ev[:, :n_components]

        # Get input y_coord for sample labels
        _y_coord = input_ds.sample_axis

        # =====================================================================
        # Create SherpaDataset objects for eigenvalues with coordinate coupling
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

        # Add processing history to SherpaDataset outputs
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
                    "type": "EFA",
                    "n_components": n_components,
                }
            )

        return {
            "default": default_dataset,  # SherpaDataset: forward eigenvalues (primary output)
            "forward_eigenvalues": forward_ev_dataset,  # SherpaDataset: forward eigenvalues (n_samples, n_components)
            "backward_eigenvalues": backward_ev_dataset,  # SherpaDataset: backward eigenvalues
            "model": efa,  # Model port
        }
