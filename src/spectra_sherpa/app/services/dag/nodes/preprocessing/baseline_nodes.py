"""
Baseline correction nodes: BaselinePenalizedLSNode, BaselineRubberbandNode.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np

from ._shared import (
    _BASELINE_LAMBDA_DEFAULT,
    _LAMBDA_BY_TECHNIQUE,
    EFFECT_BASELINE_CORRECTED,
    Node,
    NodeMetadata,
    NodeParameter,
    PortMetadata,
    SherpaDataset,
    TransformSpec,
    TransformSpecNode,
    add_processing_step,
    baseline_penalized_ls,
    build_dataset_like,
    coerce_to_sherpa,
    register_node,
    scp_roundtrip,
    to_numpy_2d,
)
from ._transforms import _baseline_pls_export

logger = logging.getLogger(__name__)


@register_node
class BaselinePenalizedLSNode(TransformSpecNode):
    """
    Penalized Least Squares baseline correction node.

    Supports three algorithms via method selector:
    - ALS:    Asymmetric Least Squares (Eilers 2005)
    - ArPLS:  Asymmetrically Reweighted PLS (Baek et al. 2015)
    - AirPLS: Adaptive Iteratively Reweighted PLS (Zhang et al. 2010)
    """

    metadata = NodeMetadata(
        node_type="baseline.penalized_ls",
        category="preprocessing",
        label="Baseline (Penalized LS)",
        description=(
            "Estimates and subtracts a smooth baseline using Asymmetric Least Squares (ALS), "
            "Asymmetrically Reweighted PLS (ArPLS), or Adaptive Iteratively Reweighted PLS (AirPLS). "
            "Lambda is auto-selected by spectroscopic technique when left at default: "
            "NIR \u2192 1\u00d710\u2076, FTIR/IR \u2192 1\u00d710\u2077,"
            "Raman \u2192 1\u00d710\u2075, OES \u2192 1\u00d710\u2074. "
            "ArPLS and AirPLS are more robust than ALS for spectra with many or broad peaks."
        ),
        parameters=[
            NodeParameter(
                name="method",
                label="Algorithm",
                param_type="select",
                default="als",
                options=["als", "arpls", "airpls"],
                description="ALS: classic asymmetric; ArPLS: adaptive reweighted; AirPLS: iterative reweighted",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="lam",
                label="Lambda (Smoothness)",
                param_type="number",
                default=1e5,
                min_value=1e2,
                max_value=1e9,
                description=(
                    "Smoothness penalty \u2014 larger values produce a smoother (flatter) baseline. "
                    "When left at the default (1\u00d710\u2075), the value is auto-selected by technique "
                    "(NIR: 1\u00d710\u2076, FTIR/IR: 1\u00d710\u2077, Raman: 1\u00d710\u2075, OES: 1\u00d710\u2074). "
                    "Set explicitly to override the auto-selected value."
                ),
                required=False,
                category="basic",
                hint=(
                    "If the corrected baseline still curves under peaks, increase \u03bb. "
                    "If signal peaks are suppressed or flattened, decrease \u03bb. "
                    "A factor of 10\u00d7 change is a good starting step."
                ),
            ),
            NodeParameter(
                name="p",
                label="Asymmetry (p)",
                param_type="number",
                default=0.001,
                min_value=0.0001,
                max_value=0.1,
                step=0.0001,
                description="Asymmetry parameter (smaller = more asymmetric)",
                required=False,
                category="basic",
                visible_when={"method": ["als"]},
            ),
            NodeParameter(
                name="max_iter",
                label="Max Iterations",
                param_type="number",
                default=50,
                min_value=5,
                max_value=500,
                step=5,
                description="Maximum number of iterations",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=1e-6,
                min_value=1e-10,
                max_value=1e-2,
                description="Convergence tolerance on weight change",
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
        output_type="NDDataset",
    )

    spec = TransformSpec(
        transform_fn=baseline_penalized_ls,
        export_lines_fn=_baseline_pls_export,
        extra_imports=["import numpy as np", "from scipy import sparse"],
        state_effects=[EFFECT_BASELINE_CORRECTED],
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """Override TransformSpecNode to apply technology-aware lambda defaults.

        When the user has not explicitly overridden the lambda parameter (i.e.
        it still equals the node's built-in default of 1e5), we substitute a
        technique-specific starting value read from ``_LAMBDA_BY_TECHNIQUE``.
        An explicit user value \u2014 even if it happens to equal a table entry \u2014
        always takes precedence over the auto-selected value.
        """
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)

        params = self._resolve_params()
        user_lam = params.get("lam", _BASELINE_LAMBDA_DEFAULT)

        # Auto-select lambda when the user hasn't changed it from the node default
        effective_lam = user_lam
        technique_used: str | None = None
        if user_lam == _BASELINE_LAMBDA_DEFAULT:
            technique = None
            if isinstance(input_ds, SherpaDataset) and input_ds.domain is not None:
                technique = input_ds.domain.technique
            if technique:
                lookup = _LAMBDA_BY_TECHNIQUE.get(technique.upper().replace(" ", "_"))
                if lookup is not None:
                    effective_lam = lookup
                    technique_used = technique
                    logger.info(
                        "[Baseline] Auto-selected \u03bb=%g for technique '%s'. "
                        "Set the Lambda parameter explicitly to override.",
                        effective_lam,
                        technique,
                    )

        result_data = baseline_penalized_ls(
            data,
            method=params.get("method", "als"),
            lam=effective_lam,
            p=params.get("p", 0.001),
            max_iter=params.get("max_iter", 50),
            tol=params.get("tol", 1e-6),
        )

        # Compute baseline as the difference between original and corrected
        baseline = data - result_data
        baseline_diagnostics = {
            "baseline_mean": float(np.mean(baseline)),
            "baseline_std": float(np.std(baseline)),
            "baseline_max": float(np.max(np.abs(baseline))),
            "residual_rms": float(np.sqrt(np.mean(result_data**2))),
            "correction_magnitude_pct": float(100 * np.mean(np.abs(baseline)) / (np.mean(np.abs(data)) + 1e-12)),
        }

        result = build_dataset_like(result_data, input_ds, units=None)
        recorded_params = dict(params)
        recorded_params["lam"] = effective_lam
        if technique_used:
            recorded_params["_lam_auto_technique"] = technique_used
        add_processing_step(
            result,
            self.metadata.node_type,
            recorded_params,
            node_id=self.node_id,
            state_effects=[EFFECT_BASELINE_CORRECTED],
        )
        result.meta["baseline_diagnostics"] = baseline_diagnostics
        return result


@register_node
class BaselineRubberbandNode(Node):
    """
    Rubberband baseline correction node.

    Removes baseline by fitting a convex hull baseline.
    """

    scp_method = "basc"
    scp_extra_kwargs = {"method": "rubberband"}

    metadata = NodeMetadata(
        node_type="baseline.rubberband",
        category="preprocessing",
        label="Baseline (Rubberband)",
        description="Rubberband (convex hull) baseline correction",
        parameters=[
            NodeParameter(
                name="ranges",
                label="Spectral Ranges",
                param_type="text",
                default="",
                description="Optional: spectral ranges for baseline points (e.g., '4000:3800, 1800:1700')",
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
        output_type="NDDataset",
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.basc.html",
    )

    async def execute(self, input_data) -> SherpaDataset:
        """Execute rubberband baseline correction."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        ranges_str = self.parameters.get("ranges", "").strip()

        basc_kwargs: Dict[str, Any] = {"method": "rubberband"}
        if ranges_str:
            parsed = []
            for part in ranges_str.split(","):
                part = part.strip()
                if ":" in part:
                    lo, hi = part.split(":", 1)
                    parsed.append((float(lo.strip()), float(hi.strip())))
            if parsed:
                basc_kwargs["ranges"] = parsed

        return scp_roundtrip(
            input_ds,
            lambda ndd: ndd.basc(**basc_kwargs),
            op_id="baseline.rubberband",
            parameters={"method": "rubberband", "ranges": ranges_str or None},
            state_effects=[EFFECT_BASELINE_CORRECTED],
            node_id=self.node_id,
        )
