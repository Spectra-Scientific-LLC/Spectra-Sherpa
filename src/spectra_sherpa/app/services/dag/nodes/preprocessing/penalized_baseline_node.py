"""Canonical penalized least-squares baseline correction.

The canvas, SDK, generated Python, model replay, and managed execution import
the dispatcher in this module.  There is no technique-dependent parameter
substitution: the five persisted parameters are the five executed parameters.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import sparse

from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.node_base import NodePolicy
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from ._shared import (
    EFFECT_BASELINE_CORRECTED,
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    TransformSpec,
    TransformSpecNode,
    add_processing_step,
    build_dataset_like,
    coerce_to_sherpa,
    register_node,
    to_numpy_2d,
)

_METHODS = frozenset({"als", "arpls", "airpls"})
_DEFAULT_ASYMMETRY = 0.001


def _canonical_penalized_ls_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return one explicit, fail-closed penalized-LS parameter payload."""

    method = parameters["method"]
    lam = parameters["lam"]
    asymmetry = parameters["p"]
    max_iter = parameters["max_iter"]
    tolerance = parameters["tol"]
    if not isinstance(method, str) or method not in _METHODS:
        raise ValueError("penalized-LS method must be als, arpls, or airpls")
    if isinstance(lam, bool) or not isinstance(lam, (int, float)) or not math.isfinite(lam) or lam < 1e2:
        raise ValueError("penalized-LS lambda must be a finite number greater than or equal to 100")
    if (
        isinstance(asymmetry, bool)
        or not isinstance(asymmetry, (int, float))
        or not math.isfinite(asymmetry)
        or not 0.0 < asymmetry < 1.0
    ):
        raise ValueError("penalized-LS asymmetry must be strictly between zero and one")
    if method != "als" and float(asymmetry) != _DEFAULT_ASYMMETRY:
        raise ValueError("penalized-LS asymmetry is only configurable for the als method")
    if isinstance(max_iter, bool) or not isinstance(max_iter, int) or not 5 <= max_iter <= 1000:
        raise ValueError("penalized-LS max_iter must be an integer from 5 through 1000")
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not math.isfinite(tolerance)
        or not 0.0 < tolerance < 1.0
    ):
        raise ValueError("penalized-LS tolerance must be finite and strictly between zero and one")
    return {
        "method": method,
        "lam": float(lam),
        "p": float(asymmetry),
        "max_iter": max_iter,
        "tol": float(tolerance),
    }


def _managed_penalized_ls_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Restrict hosted baseline work to a bounded numerical envelope."""

    projected = _canonical_penalized_ls_parameters(parameters)
    if float(projected["lam"]) > 1e9:
        raise ValueError("managed penalized-LS lambda may not exceed 1e9")
    if float(projected["p"]) > 0.1:
        raise ValueError("managed penalized-LS asymmetry may not exceed 0.1")
    if int(projected["max_iter"]) > 100:
        raise ValueError("managed penalized-LS max_iter may not exceed 100")
    if float(projected["tol"]) > 1e-2:
        raise ValueError("managed penalized-LS tolerance may not exceed 1e-2")
    return projected


def _difference_penalty(n_features: int, lam: float) -> sparse.csc_matrix:
    identity = sparse.eye(n_features, format="csc")
    first = sparse.diags(
        [-np.ones(n_features - 1), np.ones(n_features - 1)],
        [0, 1],
        shape=(n_features - 1, n_features),
        format="csc",
    )
    second = sparse.diags(
        [-np.ones(n_features - 2), np.ones(n_features - 2)],
        [0, 1],
        shape=(n_features - 2, n_features - 1),
        format="csc",
    )
    difference = second @ first @ identity
    return lam * difference.T @ difference


def _fit_als(
    spectrum: np.ndarray,
    *,
    penalty: sparse.csc_matrix,
    p: float,
    max_iter: int,
    tol: float,
) -> tuple[np.ndarray, int, bool]:
    weights = np.ones(spectrum.size, dtype=np.float64)
    baseline = np.zeros_like(spectrum)
    for iteration in range(1, max_iter + 1):
        matrix = sparse.diags(weights, format="csc") + penalty
        candidate = sparse.linalg.spsolve(matrix, weights * spectrum)
        updated = np.where(spectrum > candidate, p, 1.0 - p)
        delta = np.linalg.norm(updated - weights) / (np.linalg.norm(weights) + 1e-12)
        baseline = np.asarray(candidate, dtype=np.float64)
        if delta < tol:
            return baseline, iteration, True
        weights = updated
    return baseline, max_iter, False


def _fit_arpls(
    spectrum: np.ndarray,
    *,
    penalty: sparse.csc_matrix,
    max_iter: int,
    tol: float,
) -> tuple[np.ndarray, int, bool]:
    weights = np.ones(spectrum.size, dtype=np.float64)
    baseline = np.zeros_like(spectrum)
    for iteration in range(1, max_iter + 1):
        matrix = sparse.diags(weights, format="csc") + penalty
        baseline = np.asarray(sparse.linalg.spsolve(matrix, weights * spectrum), dtype=np.float64)
        residual = spectrum - baseline
        negative = residual[residual < 0.0]
        if negative.size == 0:
            return baseline, iteration, True
        mean = float(negative.mean())
        deviation = float(negative.std(ddof=1)) if negative.size > 1 else 0.0
        if deviation < 1e-12:
            return baseline, iteration, True
        exponent = np.clip(2.0 * (residual - (2.0 * deviation - mean)) / deviation, -709.0, 709.0)
        updated = 1.0 / (1.0 + np.exp(exponent))
        delta = np.linalg.norm(updated - weights) / (np.linalg.norm(weights) + 1e-12)
        if delta < tol:
            return baseline, iteration, True
        weights = updated
    return baseline, max_iter, False


def _fit_airpls(
    spectrum: np.ndarray,
    *,
    penalty: sparse.csc_matrix,
    max_iter: int,
    tol: float,
) -> tuple[np.ndarray, int, bool]:
    magnitude = float(np.abs(spectrum).sum())
    if magnitude < 1e-12:
        return np.zeros_like(spectrum), 0, True
    weights = np.ones(spectrum.size, dtype=np.float64)
    baseline = np.zeros_like(spectrum)
    for iteration in range(1, max_iter + 1):
        matrix = sparse.diags(weights, format="csc") + penalty
        baseline = np.asarray(sparse.linalg.spsolve(matrix, weights * spectrum), dtype=np.float64)
        residual = spectrum - baseline
        negative = residual < 0.0
        negative_sum = float(np.abs(residual[negative]).sum())
        if negative_sum < tol * magnitude:
            return baseline, iteration, True
        weights = np.zeros(spectrum.size, dtype=np.float64)
        if negative.any() and negative_sum > 1e-12:
            exponent = np.clip(
                iteration * np.abs(residual[negative]) / negative_sum,
                0.0,
                709.0,
            )
            weights[negative] = np.exp(exponent)
            edge_exponent = min(
                iteration * float(np.abs(residual[negative]).max()) / negative_sum,
                709.0,
            )
            edge_weight = float(np.exp(edge_exponent))
            weights[0] = edge_weight
            weights[-1] = edge_weight
    return baseline, max_iter, False


def _penalized_baseline_dispatch(
    data: np.ndarray,
    *,
    method: str,
    lam: float,
    p: float,
    max_iter: int,
    tol: float,
) -> tuple[np.ndarray, dict[str, object]]:
    """Execute the canonical algorithm and return corrected data plus diagnostics."""

    params = _canonical_penalized_ls_parameters(
        {"method": method, "lam": lam, "p": p, "max_iter": max_iter, "tol": tol}
    )
    matrix = np.asarray(data, dtype=np.float64)
    was_vector = matrix.ndim == 1
    if was_vector:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 3:
        raise ValueError("penalized-LS input must contain at least one spectrum and three features")
    if not np.isfinite(matrix).all():
        raise ValueError("penalized-LS input must contain only finite values")

    penalty = _difference_penalty(matrix.shape[1], float(params["lam"]))
    baselines = np.empty_like(matrix)
    iterations: list[int] = []
    unconverged: list[int] = []
    for index, spectrum in enumerate(matrix):
        if params["method"] == "als":
            baseline, used, converged = _fit_als(
                spectrum,
                penalty=penalty,
                p=float(params["p"]),
                max_iter=int(params["max_iter"]),
                tol=float(params["tol"]),
            )
        elif params["method"] == "arpls":
            baseline, used, converged = _fit_arpls(
                spectrum,
                penalty=penalty,
                max_iter=int(params["max_iter"]),
                tol=float(params["tol"]),
            )
        else:
            baseline, used, converged = _fit_airpls(
                spectrum,
                penalty=penalty,
                max_iter=int(params["max_iter"]),
                tol=float(params["tol"]),
            )
        if not np.isfinite(baseline).all():
            raise ValueError(f"penalized-LS produced a non-finite baseline for spectrum {index}")
        baselines[index] = baseline
        iterations.append(used)
        if not converged:
            unconverged.append(index)
    if unconverged:
        raise ValueError(
            "penalized-LS did not converge within max_iter for spectrum indexes "
            + ", ".join(str(index) for index in unconverged[:10])
        )

    corrected = matrix - baselines
    diagnostics: dict[str, object] = {
        "algorithm": params["method"],
        "converged_spectra": int(matrix.shape[0]),
        "nonconverged_spectra": 0,
        "maximum_iterations_used": max(iterations),
        "input_feature_count": int(matrix.shape[1]),
        "baseline_mean": float(np.mean(baselines)),
        "baseline_standard_deviation": float(np.std(baselines)),
        "maximum_absolute_correction": float(np.max(np.abs(baselines))),
        "corrected_root_mean_square": float(np.sqrt(np.mean(corrected**2))),
        "correction_magnitude_percent": float(100.0 * np.mean(np.abs(baselines)) / (np.mean(np.abs(matrix)) + 1e-12)),
    }
    return (corrected[0] if was_vector else corrected), diagnostics


def _build_penalized_baseline_result(
    corrected: np.ndarray,
    source: Any,
    parameters: dict[str, object],
    diagnostics: dict[str, object],
    *,
    node_id: str | None = None,
):
    """Wrap canonical output with the same provenance on every public path."""

    result = build_dataset_like(corrected, source, units=source.units)
    add_processing_step(
        result,
        "baseline.penalized_ls",
        parameters,
        node_id=node_id,
        input_shape=source.shape,
        state_effects=[EFFECT_BASELINE_CORRECTED],
    )
    result.meta["baseline_diagnostics"] = diagnostics
    supervision_binding.rebind_sample_preserving_supervision(source, result)
    return result


def _penalized_baseline_export(params, inp, node_id, indent, use_scp):
    del use_scp
    return [
        f"{indent}# --- Canonical Penalized LS Baseline ({node_id}) ---",
        f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.penalized_baseline_node "
        "import _build_penalized_baseline_result, _penalized_baseline_dispatch",
        f"{indent}_corrected, _baseline_diagnostics = _penalized_baseline_dispatch("
        f"np.asarray({inp}.data, dtype=np.float64), **{params!r})",
        f"{indent}results[{node_id!r}] = _build_penalized_baseline_result("
        f"_corrected, {inp}, {params!r}, _baseline_diagnostics, node_id={node_id!r})",
    ]


@register_node
class BaselinePenalizedLSNode(TransformSpecNode):
    """Subtract a penalized least-squares baseline using exact saved parameters."""

    metadata = NodeMetadata(
        node_type="baseline.penalized_ls",
        category="preprocessing",
        label="Baseline (Penalized LS)",
        description=(
            "Estimate and subtract a smooth baseline with ALS, ArPLS, or AirPLS. "
            "The displayed parameters are the exact parameters executed and recorded."
        ),
        parameters=[
            NodeParameter(
                name="method",
                label="Algorithm",
                param_type="select",
                default="als",
                options=["als", "arpls", "airpls"],
                description="Closed penalized least-squares algorithm choice.",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="lam",
                label="Lambda (Smoothness)",
                param_type="number",
                default=1e5,
                min_value=1e2,
                description=(
                    "Exact smoothness penalty; larger values produce a smoother baseline. "
                    "Hosted execution requires lambda at most 1e9."
                ),
                required=False,
                category="basic",
                hint="Increase by about 10× for residual baseline curvature; decrease if peaks flatten.",
            ),
            NodeParameter(
                name="p",
                label="Asymmetry (ALS only)",
                param_type="number",
                default=_DEFAULT_ASYMMETRY,
                min_value=0.0001,
                max_value=0.9999,
                max_value_reason=(
                    "Keeps both ALS weight classes at or above 1e-4 so neither side "
                    "of the asymmetric fit becomes numerically zero-weighted."
                ),
                step=0.0001,
                description=(
                    "Exact ALS asymmetry; non-default values are rejected for ArPLS and AirPLS. "
                    "Hosted execution requires ALS asymmetry at most 0.1."
                ),
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
                max_value=1000,
                max_value_reason=(
                    "Caps the number of sparse linear solves per spectrum so the node "
                    "remains inside its declared local worker resource envelope."
                ),
                step=5,
                description=(
                    "Hard convergence limit; non-convergence fails the node. "
                    "Hosted execution admits at most 100 iterations per spectrum."
                ),
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=1e-6,
                min_value=1e-10,
                max_value=0.999999,
                max_value_reason=(
                    "Preserves the algorithm's strict tolerance-below-one invariant at the six-decimal UI precision."
                ),
                description=(
                    "Finite convergence tolerance strictly between zero and one. "
                    "Hosted execution requires tolerance at most 1e-2."
                ),
                required=False,
                category="advanced",
            ),
        ],
        input_types=["SpectralDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Finite spectra with at least three features.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Baseline-corrected Spectra",
                description="Corrected spectra with samples, axes, and value units preserved.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SpectralDataset",
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_penalized_ls_parameters,
        managed_parameter_validator=_managed_penalized_ls_parameters,
    )

    spec = TransformSpec(
        transform_fn=lambda data, **params: _penalized_baseline_dispatch(data, **params)[0],
        export_lines_fn=_penalized_baseline_export,
        extra_imports=["import numpy as np"],
        state_effects=[EFFECT_BASELINE_CORRECTED],
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        source = coerce_to_sherpa(input_data, input_name="input_data")
        params = self._resolve_params()
        corrected, diagnostics = _penalized_baseline_dispatch(to_numpy_2d(source, name="input_data"), **params)
        result = _build_penalized_baseline_result(
            corrected,
            source,
            params,
            diagnostics,
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)


bind_stable_execution_contract(
    BaselinePenalizedLSNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.baseline.penalized_ls",
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
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_distributions=("numpy", "scipy"),
    implementation_modules=(supervision_binding,),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1")),
    managed_optimization_profiles=("first_party_pls",),
    citations=(
        "Eilers and Boelens, Baseline Correction with Asymmetric Least Squares Smoothing (2005)",
        "Baek et al., Baseline correction using asymmetrically reweighted penalized least squares (2015)",
        "Zhang et al., Baseline correction using adaptive iteratively reweighted penalized least squares (2010)",
    ),
)


__all__ = [
    "BaselinePenalizedLSNode",
    "_build_penalized_baseline_result",
    "_canonical_penalized_ls_parameters",
    "_penalized_baseline_dispatch",
]
