"""SyntheticCurveNode -- generate synthetic concentration timeseries.

Registered as ``data.synthetic_curve``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import (
    SherpaDataset,
    SpectralAxis,
)
from spectra_sherpa.app.models.spectra_meta import (
    ConcentrationProfile,
    ConcentrationUnit,
    DataProvenance,
    SourceType,
    SpectraMeta,
    set_spectra_meta,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ...node_base import Node, NodeMetadata, NodeParameter, register_node

logger = logging.getLogger(__name__)


@register_node
class SyntheticCurveNode(Node):
    """
    Synthetic Curve node for generating concentration timeseries.

    Generates synthetic concentration curves for blending operations.
    """

    metadata = NodeMetadata(
        node_type="data.synthetic_curve",
        category="synthesis",
        label="Synthetic Curve",
        description="Generate synthetic concentration curves",
        parameters=[
            NodeParameter(
                name="curve_type",
                label="Curve Type",
                param_type="select",
                default="sigmoid",
                options=["sigmoid", "gaussian", "linear", "exponential", "step"],
                description="Type of concentration curve",
                required=True,
            ),
            NodeParameter(
                name="n_points",
                label="Number of Points",
                param_type="number",
                default=100,
                min_value=10,
                description="Number of time points",
                required=True,
            ),
            NodeParameter(
                name="max_concentration",
                label="Max Concentration",
                param_type="number",
                default=1.0,
                min_value=0.0,
                description="Maximum concentration value",
                required=True,
            ),
            NodeParameter(
                name="center",
                label="Center Position",
                param_type="number",
                default=0.5,
                min_value=0.0,
                step=0.1,
                description="Center of sigmoid/gaussian (0-1)",
                required=False,
            ),
            NodeParameter(
                name="width",
                label="Width",
                param_type="number",
                default=0.1,
                min_value=0.01,
                step=0.01,
                description="Width of sigmoid/gaussian",
                required=False,
            ),
        ],
        input_types=[],
        input_ports=[],
        output_type="NDDataset",
    )

    async def execute(self, *args) -> Any:
        """Generate synthetic concentration curve."""
        curve_type = self.parameters.get("curve_type", "sigmoid")
        n_points = int(self.parameters.get("n_points", 100))
        max_conc = self.parameters.get("max_concentration", 1.0)
        center = self.parameters.get("center", 0.5)
        width = self.parameters.get("width", 0.1)

        t = np.linspace(0, 1, n_points)

        if curve_type == "sigmoid":
            curve = max_conc / (1 + np.exp(-(t - center) / width))
        elif curve_type == "gaussian":
            curve = max_conc * np.exp(-((t - center) ** 2) / (2 * width**2))
        elif curve_type == "linear":
            curve = max_conc * t
        elif curve_type == "exponential":
            curve = max_conc * (1 - np.exp(-t / width))
        elif curve_type == "step":
            curve = np.where(t >= center, max_conc, 0.0)
        else:
            curve = np.ones(n_points) * max_conc

        dataset = SherpaDataset(
            X=curve.reshape(1, -1),
            feature_axis=SpectralAxis(values=t * n_points, title="Time", units="s"),
            backend="numpy",
            title=f"Concentration ({curve_type})",
            units="mol/L",
        )

        # Attach metadata with concentration profile
        concentration_profile = ConcentrationProfile(
            species_index=0,
            species_name="Synthetic Species",
            curve_type=curve_type,
            values=curve.tolist(),
            max_concentration=max_conc,
            min_concentration=float(curve.min()),
            center=center,
            width=width,
            unit=ConcentrationUnit.MOL_L,
        )

        meta = SpectraMeta(
            concentrations=[concentration_profile],
            provenance=DataProvenance(
                source_type=SourceType.SYNTHETIC,
                created_datetime=datetime.utcnow().isoformat(),
            ),
            is_ground_truth=True,
            processing_steps=["synthetic_curve_generation"],
            custom={
                "curve_params": {
                    "curve_type": curve_type,
                    "n_points": n_points,
                    "max_concentration": max_conc,
                    "center": center,
                    "width": width,
                }
            },
        )
        set_spectra_meta(dataset, meta)

        # Record provenance in dataset.meta
        add_processing_step(
            dataset,
            "data.synthetic_curve",
            {
                "curve_type": curve_type,
                "n_points": n_points,
                "max_concentration": max_conc,
                "center": center,
                "width": width,
            },
            node_id=self.node_id,
        )
        return dataset
