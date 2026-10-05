"""Canonical spectral smoothing node."""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.node_base import NodePolicy
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import _shared
from ._shared import (
    EFFECT_SMOOTHED,
    Node,
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    add_processing_step,
    build_dataset_like,
    coerce_to_sherpa,
    estimate_snr,
    header_line,
    register_node,
    to_numpy_2d,
)

_DEFAULT_SIZE = 11
_DEFAULT_ORDER = 2
_DEFAULT_LAMBDA = 100.0
_DEFAULT_DIFFERENCE_ORDER = "2"
_DEFAULT_SIGMA = 2.0


def _canonical_smooth_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the one admitted representation of a smoothing operation."""

    method = parameters["method"]
    if not isinstance(method, str) or method not in {"savitzky_golay", "whittaker", "gaussian"}:
        raise ValueError("smoothing method is not admitted")

    size = parameters["size"]
    order = parameters["order"]
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (size, order)):
        raise ValueError("smoothing size and order must be exact integers")
    if size < 3 or order < 1:
        raise ValueError("smoothing size and order must be positive within their admitted ranges")

    lam = parameters["lam"]
    sigma = parameters["sigma"]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (lam, sigma)):
        raise ValueError("smoothing lambda and sigma must be finite numbers")
    lam = float(lam)
    sigma = float(sigma)
    if not np.isfinite(lam) or lam < 1.0:
        raise ValueError("Whittaker lambda must be a finite number greater than or equal to 1")
    if not np.isfinite(sigma) or sigma < 0.1:
        raise ValueError("Gaussian sigma must be a finite number greater than or equal to 0.1")

    difference_order = parameters["d"]
    if not isinstance(difference_order, str) or difference_order not in {"1", "2", "3"}:
        raise ValueError("Whittaker difference order must be exactly '1', '2', or '3'")

    projected = {
        "method": method,
        "size": size,
        "order": order,
        "lam": lam,
        "d": difference_order,
        "sigma": sigma,
    }
    if method == "savitzky_golay":
        if size % 2 == 0 or order >= size:
            raise ValueError("Savitzky-Golay smoothing parameters are not scientifically admissible")
        if (lam, difference_order, sigma) != (
            _DEFAULT_LAMBDA,
            _DEFAULT_DIFFERENCE_ORDER,
            _DEFAULT_SIGMA,
        ):
            raise ValueError("Savitzky-Golay smoothing may not carry Whittaker or Gaussian settings")
    elif method == "whittaker":
        if (size, order, sigma) != (_DEFAULT_SIZE, _DEFAULT_ORDER, _DEFAULT_SIGMA):
            raise ValueError("Whittaker smoothing may not carry Savitzky-Golay or Gaussian settings")
    elif method == "gaussian":
        if (size, order, lam, difference_order) != (
            _DEFAULT_SIZE,
            _DEFAULT_ORDER,
            _DEFAULT_LAMBDA,
            _DEFAULT_DIFFERENCE_ORDER,
        ):
            raise ValueError("Gaussian smoothing may not carry Savitzky-Golay or Whittaker settings")
    return projected


def _smooth_dispatch(
    data: np.ndarray,
    method: str = "savitzky_golay",
    size: int = _DEFAULT_SIZE,
    order: int = _DEFAULT_ORDER,
    lam: float = _DEFAULT_LAMBDA,
    d: str = _DEFAULT_DIFFERENCE_ORDER,
    sigma: float = _DEFAULT_SIGMA,
) -> np.ndarray:
    """Execute only a fully admitted smoothing parameter projection."""

    projected = _canonical_smooth_parameters(
        {
            "method": method,
            "size": size,
            "order": order,
            "lam": lam,
            "d": d,
            "sigma": sigma,
        }
    )
    matrix = np.asarray(data, dtype=np.float64)
    if matrix.ndim != 2:
        raise ValueError("canonical smoothing requires a two-dimensional sample-by-feature matrix")
    if matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise ValueError("canonical smoothing requires at least one sample and one feature")
    if not np.isfinite(matrix).all():
        raise ValueError(
            "preprocess.smooth requires finite input values; remove an explicitly blanked region "
            "with preprocess.clip_range before smoothing"
        )

    if projected["method"] == "savitzky_golay":
        window = int(projected["size"])
        if window > matrix.shape[-1]:
            raise ValueError("Savitzky-Golay window size may not exceed the feature count")
        from scipy.signal import savgol_filter

        return np.apply_along_axis(
            savgol_filter,
            -1,
            matrix,
            window_length=window,
            polyorder=int(projected["order"]),
        )
    if projected["method"] == "whittaker":
        difference_order = int(str(projected["d"]))
        if matrix.shape[-1] <= difference_order:
            raise ValueError("Whittaker difference order must be smaller than the feature count")
        from scipy import sparse

        difference = sparse.eye(matrix.shape[1], format="csc")
        for _ in range(difference_order):
            difference = difference[1:] - difference[:-1]
        system = sparse.eye(matrix.shape[1], format="csc") + float(projected["lam"]) * (difference.T @ difference)
        return np.vstack([sparse.linalg.spsolve(system, row) for row in matrix])
    if projected["method"] == "gaussian":
        from scipy.ndimage import gaussian_filter1d

        return gaussian_filter1d(matrix, sigma=float(projected["sigma"]), axis=-1)
    raise AssertionError("closed smoothing grammar returned an unknown method")


@register_node
class SmoothNode(Node):
    """Apply one closed smoothing operation while preserving the spectral axis."""

    metadata = NodeMetadata(
        node_type="preprocess.smooth",
        category="preprocessing",
        label="Smooth",
        description="Smooth spectra with Savitzky-Golay, Whittaker, or Gaussian filtering.",
        parameters=[
            NodeParameter(
                name="method",
                label="Method",
                param_type="select",
                default="savitzky_golay",
                options=[
                    {"label": "Savitzky-Golay", "value": "savitzky_golay"},
                    {"label": "Whittaker", "value": "whittaker"},
                    {"label": "Gaussian", "value": "gaussian"},
                ],
                description="Smoothing algorithm",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="size",
                label="Window Size",
                param_type="number",
                default=_DEFAULT_SIZE,
                min_value=3,
                step=2,
                description="Odd Savitzky-Golay window size",
                category="basic",
                visible_when={"method": ["savitzky_golay"]},
            ),
            NodeParameter(
                name="order",
                label="Polynomial Order",
                param_type="number",
                default=_DEFAULT_ORDER,
                min_value=1,
                step=1,
                description="Savitzky-Golay polynomial order",
                category="basic",
                visible_when={"method": ["savitzky_golay"]},
            ),
            NodeParameter(
                name="lam",
                label="Lambda",
                param_type="number",
                default=_DEFAULT_LAMBDA,
                min_value=1,
                description="Whittaker smoothness penalty",
                category="basic",
                visible_when={"method": ["whittaker"]},
            ),
            NodeParameter(
                name="d",
                label="Difference Order",
                param_type="select",
                default=_DEFAULT_DIFFERENCE_ORDER,
                options=["1", "2", "3"],
                description="Whittaker difference order",
                category="advanced",
                visible_when={"method": ["whittaker"]},
            ),
            NodeParameter(
                name="sigma",
                label="Sigma",
                param_type="number",
                default=_DEFAULT_SIGMA,
                min_value=0.1,
                step=0.1,
                description="Gaussian kernel width",
                category="basic",
                visible_when={"method": ["gaussian"]},
            ),
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral rows to smooth while preserving their feature axis.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Smoothed Spectra",
                description="Spectra transformed by the selected admitted smoothing method.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SherpaDataset",
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_smooth_parameters,
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        return self.transform_dataset(input_data)

    def transform_dataset(self, input_data: Any) -> NodeResult:
        """One finalization path for live execution and Python export."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        params = self._resolve_params()
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        snr_before = estimate_snr(data)
        smoothed = _smooth_dispatch(data, **params)
        snr_after = estimate_snr(smoothed)
        result = build_dataset_like(smoothed, input_ds)
        add_processing_step(
            result,
            "preprocess.smooth",
            params,
            node_id=self.node_id,
            state_effects=[EFFECT_SMOOTHED],
        )
        result.meta["snr_before_db"] = snr_before
        result.meta["snr_after_db"] = snr_after
        result.meta["snr_improvement_db"] = snr_after - snr_before
        supervision_binding.rebind_sample_preserving_supervision(input_ds, result)
        return NodeResult(
            outputs={"default": result},
            diagnostics={
                "method": params["method"],
                "snr_before": float(snr_before),
                "snr_after": float(snr_after),
                "snr_improvement_db": float(snr_after - snr_before),
            },
        )

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        return [
            header_line("Canonical Smoothing", self.node_id, indent),
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_node import SmoothNode",
            f"{indent}_transform = SmoothNode({self.node_id!r}, {params!r})",
            f"{indent}results[{self.node_id!r}] = _transform.transform_dataset({inp}).outputs['default']",
        ]


bind_stable_execution_contract(
    SmoothNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.smooth",
    implementation_version="1.0.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(
        ManagedOptimizationEligibility.LOCAL,
        ManagedOptimizationEligibility.DEVELOPMENT,
        ManagedOptimizationEligibility.FULL_REFIT,
    ),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(_shared, supervision_binding),
    implementation_distributions=("numpy", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1")),
    managed_optimization_profiles=("first_party_pls",),
    citations=(
        "Savitzky and Golay, Analytical Chemistry 36 (1964) 1627-1639, DOI 10.1021/ac60214a047",
        "Eilers, Analytical Chemistry 75 (2003) 3631-3636, DOI 10.1021/ac034173t",
        "Lindeberg, Journal of Applied Statistics 21 (1994) 225-270, Gaussian scale-space smoothing",
    ),
)


__all__ = ["SmoothNode"]
