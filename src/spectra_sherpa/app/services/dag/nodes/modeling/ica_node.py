"""Canonical, deterministic FastICA fitted-transform node.

FastICA estimates independent latent source scores ``S`` and a linear mixing
matrix ``A`` such that ``X ~= S @ A.T + mean``.  ICA component sign and order
are not scientifically identifiable, so this implementation records and
applies one deterministic presentation convention after the seeded fit.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
from sklearn.decomposition import FastICA
from sklearn.exceptions import ConvergenceWarning

from spectra_sherpa.app.lib import fitted_state
from spectra_sherpa.app.lib.fitted_state import FastICAExtract
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers
from spectra_sherpa.app.services.dag.meta_helpers import (
    add_processing_step,
    copy_processing_history,
    inherit_origin_flags,
    inherit_sample_flags,
)
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    TargetAccess,
    WorkerCapability,
)

from ...io_contracts import bind_X, to_numpy_2d
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from ...stable_execution_contract import bind_stable_execution_contract
from . import _artifact_builder
from . import core_utils as modeling_core_utils
from .core_utils import create_spectral_dataset, make_safe_coord

ICA_FITTED_STATE_SERIALIZER = FastICAExtract.SERIALIZER
_ICA_MAX_COMPONENTS = 50
_ICA_MAX_ITERATIONS = 2_000
_ICA_MAX_RANDOM_SEED = 2_147_483_647
_ICA_SIGN_RULE = "largest_absolute_mixing_loading_positive"
_ICA_ORDER_RULE = "descending_reconstruction_contribution"
_ICA_PARAMETER_KEYS = {
    "n_components",
    "algorithm",
    "fun",
    "whiten",
    "max_iter",
    "tol",
    "random_seed",
}


def _canonical_ica_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Validate and return the exact current FastICA parameter schema."""

    if set(parameters) != _ICA_PARAMETER_KEYS:
        raise ValueError("FastICA parameters must use the exact current seven-field schema")
    n_components = parameters["n_components"]
    max_iter = parameters["max_iter"]
    tol = parameters["tol"]
    random_seed = parameters["random_seed"]
    if type(n_components) is not int or not 2 <= n_components <= _ICA_MAX_COMPONENTS:
        raise ValueError(f"FastICA n_components must be an integer in [2, {_ICA_MAX_COMPONENTS}]")
    if parameters["algorithm"] not in {"parallel", "deflation"}:
        raise ValueError("FastICA algorithm must be parallel or deflation")
    if parameters["fun"] not in {"logcosh", "exp", "cube"}:
        raise ValueError("FastICA contrast function must be logcosh, exp, or cube")
    if parameters["whiten"] not in {"unit-variance", "arbitrary-variance"}:
        raise ValueError("FastICA whiten must be unit-variance or arbitrary-variance")
    if type(max_iter) is not int or not 50 <= max_iter <= _ICA_MAX_ITERATIONS:
        raise ValueError(f"FastICA max_iter must be an integer in [50, {_ICA_MAX_ITERATIONS}]")
    if (
        isinstance(tol, bool)
        or not isinstance(tol, (int, float))
        or not np.isfinite(tol)
        or not 1e-8 <= float(tol) <= 0.1
    ):
        raise ValueError("FastICA tol must be finite and in [1e-8, 0.1]")
    if type(random_seed) is not int or not 0 <= random_seed <= _ICA_MAX_RANDOM_SEED:
        raise ValueError(f"FastICA random_seed must be an integer in [0, {_ICA_MAX_RANDOM_SEED}]")
    return {
        "n_components": n_components,
        "algorithm": parameters["algorithm"],
        "fun": parameters["fun"],
        "whiten": parameters["whiten"],
        "max_iter": max_iter,
        "tol": float(tol),
        "random_seed": random_seed,
    }


def _ica_parameter_summary(parameters: dict[str, object]) -> str:
    """Render every accepted solver setting in the user-visible failure contract."""

    return (
        f"n_components={parameters['n_components']}, algorithm={parameters['algorithm']}, "
        f"contrast={parameters['fun']}, whiten={parameters['whiten']}, "
        f"max_iter={parameters['max_iter']}, tol={parameters['tol']}, "
        f"random_seed={parameters['random_seed']}"
    )


def _ica_recovery_failure(
    failure: str,
    parameters: dict[str, object],
    *,
    recovery: str,
) -> RuntimeError:
    return RuntimeError(
        f"{failure} under the declared settings ({_ica_parameter_summary(parameters)}). "
        "No component scores were accepted and downstream nodes were not run. "
        f"{recovery}"
    )


def _canonicalize_ica_presentation(
    sources: np.ndarray,
    components: np.ndarray,
    mixing: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Resolve ICA's arbitrary sign/order for stable display and evidence.

    Components are ordered by descending reconstruction contribution.  Each
    mixing profile is signed so its largest absolute loading is positive.  The
    same permutation and signs are applied to sources and the unmixing rows,
    preserving both transform and reconstruction identities.
    """

    sources = np.asarray(sources, dtype=np.float64)
    components = np.asarray(components, dtype=np.float64)
    mixing = np.asarray(mixing, dtype=np.float64)
    contribution = np.var(sources, axis=0, dtype=np.float64) * np.sum(mixing * mixing, axis=0)
    if not np.isfinite(contribution).all():
        raise ValueError("FastICA component contributions must be finite")
    order = np.lexsort((np.arange(contribution.size), -contribution))
    sources = sources[:, order]
    components = components[order, :]
    mixing = mixing[:, order]
    for index in range(mixing.shape[1]):
        profile = mixing[:, index]
        anchor = int(np.argmax(np.abs(profile)))
        if not np.isfinite(profile[anchor]) or profile[anchor] == 0.0:
            raise ValueError("FastICA produced a degenerate mixing profile")
        if profile[anchor] < 0.0:
            sources[:, index] *= -1.0
            components[index, :] *= -1.0
            mixing[:, index] *= -1.0
    return sources, components, mixing, contribution[order]


def _ica_fitted_state_from_extract(extract: FastICAExtract) -> dict[str, object]:
    metadata, arrays = extract.to_artifact()
    return {
        "serializer": ICA_FITTED_STATE_SERIALIZER,
        "metadata": metadata,
        "arrays": {name: np.asarray(value, dtype=np.float64).tolist() for name, value in arrays.items()},
    }


def _ica_extract_from_state(state: Any) -> FastICAExtract:
    if not isinstance(state, dict) or set(state) != {"serializer", "metadata", "arrays"}:
        raise ValueError("FastICA fitted state must contain exact serializer, metadata, and arrays")
    if state["serializer"] != ICA_FITTED_STATE_SERIALIZER:
        raise ValueError("FastICA fitted state has an unsupported serializer")
    metadata = state["metadata"]
    arrays = state["arrays"]
    expected_metadata = {
        "model_type",
        "serializer",
        "n_components",
        "n_features",
        "algorithm",
        "fun",
        "whiten",
        "random_seed",
        "sign_rule",
        "order_rule",
    }
    if not isinstance(metadata, dict) or set(metadata) != expected_metadata:
        raise ValueError("FastICA fitted-state metadata is not closed")
    if not isinstance(arrays, dict):
        raise ValueError("FastICA fitted-state arrays must be a mapping")
    return FastICAExtract.from_artifact(
        metadata,
        {name: np.asarray(value, dtype=np.float64) for name, value in arrays.items()},
    )


def apply_ica_fitted_state(input_data: Any, state: Any) -> np.ndarray:
    """Project new observations through the exact fitted unmixing operator."""

    matrix = to_numpy_2d(input_data, name="input_data", dtype=np.float64)
    return _ica_extract_from_state(state).transform(matrix)


def _ica_scientific_core(input_data: Any, *, parameters: dict[str, object]) -> dict[str, Any]:
    """Fit one authoritative, seeded FastICA computation."""

    params = _canonical_ica_parameters(parameters)
    input_ds = bind_X(
        input_data,
        missing_message="Missing required input: input_data (spectral mixtures)",
        dataset_error_message="input_data must be a dataset object",
        allow_array=False,
    )
    matrix = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
    if matrix.shape[0] < 2 or matrix.shape[1] < 2 or not np.isfinite(matrix).all():
        raise ValueError("FastICA requires a finite two-dimensional matrix with at least two rows and features")
    n_samples, n_features = matrix.shape
    n_components = int(params["n_components"])
    # FastICA centers observations before whitening, so the identifiable rank
    # cannot exceed n_samples - 1.  Asking for one component per sample can
    # appear to converge while sklearn's fitted transform no longer reproduces
    # fit_transform (the exact 50x5401 atmospheric failure caught in J21).
    centered_rank_ceiling = min(n_samples - 1, n_features)
    if n_components > centered_rank_ceiling:
        raise _ica_recovery_failure(
            (
                f"FastICA cannot identify n_components={n_components} after centering {n_samples} samples; "
                f"the maximum identifiable component count is {centered_rank_ceiling} for {n_features} features"
            ),
            params,
            recovery=(f"Reduce Number of Components to {centered_rank_ceiling} or fewer first, then rerun."),
        )
    model = FastICA(
        n_components=n_components,
        algorithm=str(params["algorithm"]),
        fun=str(params["fun"]),
        whiten=str(params["whiten"]),
        whiten_solver="svd",
        max_iter=int(params["max_iter"]),
        tol=float(params["tol"]),
        random_state=int(params["random_seed"]),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        sources = model.fit_transform(matrix)
    if any(issubclass(item.category, ConvergenceWarning) for item in caught):
        raise _ica_recovery_failure(
            "FastICA did not converge",
            params,
            recovery=(
                "Increase Maximum Iterations up to 2000 first; if convergence still fails, reduce Number of "
                "Components, review preprocessing, and then deliberately try the deflation algorithm or a "
                "looser tolerance."
            ),
        )
    components = np.asarray(model.components_, dtype=np.float64)
    mixing = np.asarray(model.mixing_, dtype=np.float64)
    mean = np.asarray(model.mean_, dtype=np.float64)
    sources, components, mixing, contribution = _canonicalize_ica_presentation(sources, components, mixing)
    extract = FastICAExtract(
        components=components,
        mean=mean,
        mixing=mixing,
        n_components=n_components,
        n_features=n_features,
        algorithm=str(params["algorithm"]),
        fun=str(params["fun"]),
        whiten=str(params["whiten"]),
        random_seed=int(params["random_seed"]),
    )
    state = _ica_fitted_state_from_extract(extract)
    replayed = extract.transform(matrix)
    if not np.allclose(replayed, sources, rtol=1e-10, atol=1e-10):
        raise _ica_recovery_failure(
            "FastICA fitted-state replay validation failed",
            params,
            recovery=(
                "Reduce Number of Components first; then increase Maximum Iterations up to 2000. If validation "
                "still fails, review preprocessing and deliberately try the deflation algorithm or a looser "
                "tolerance."
            ),
        )
    reconstructed = sources @ mixing.T + mean
    residuals = matrix - reconstructed
    if not all(np.isfinite(value).all() for value in (sources, components, mixing, residuals)):
        raise ValueError("FastICA produced non-finite fitted outputs")
    return {
        "dataset": input_ds,
        "data": matrix,
        "sources": sources,
        "components": components,
        "mixing": mixing,
        "spectral_profiles": mixing.T,
        "mean": mean,
        "reconstructed": reconstructed,
        "residuals": residuals,
        "contribution": contribution,
        "n_iter": int(model.n_iter_),
        "fitted_state": state,
        "extract": extract,
        "parameters": params,
    }


def _ica_export_outputs(input_data: Any, *, parameters: dict[str, object]) -> dict[str, Any]:
    core = _ica_scientific_core(input_data, parameters=parameters)
    return {
        "model": core["fitted_state"],
        "fitted_state": core["fitted_state"],
        "sources": core["sources"],
        "components": core["spectral_profiles"],
        "mixing_matrix": core["mixing"],
        "unmixing_matrix": core["components"],
        "residuals": core["residuals"],
    }


@register_node
class FastICANode(Node):
    """Fit a seeded FastICA decomposition and expose its replayable state."""

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="model.ica",
        category="exploratory",
        label="Fit FastICA Decomposition",
        description=(
            "Separate centered spectral observations into statistically independent latent scores. "
            "The node records whitening, seed, convergence, sign, and component-order semantics; "
            "its component spectra are the fitted mixing profiles, not the unmixing operator."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=2,
                max_value=_ICA_MAX_COMPONENTS,
                max_value_reason="Bounds whitening and fixed-point solver cost.",
                step=1,
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="algorithm",
                label="Algorithm",
                param_type="select",
                default="parallel",
                options=["parallel", "deflation"],
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="fun",
                label="Contrast Function",
                param_type="select",
                default="logcosh",
                options=["logcosh", "exp", "cube"],
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="whiten",
                label="Whitening Scale",
                param_type="select",
                default="unit-variance",
                options=["unit-variance", "arbitrary-variance"],
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="max_iter",
                label="Maximum Iterations",
                param_type="number",
                default=400,
                min_value=50,
                max_value=_ICA_MAX_ITERATIONS,
                max_value_reason="Bounds fixed-point solver cost.",
                step=50,
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=0.0001,
                min_value=1e-8,
                step=0.0001,
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="random_seed",
                label="Random Seed",
                param_type="number",
                default=42,
                min_value=0,
                max_value=_ICA_MAX_RANDOM_SEED,
                max_value_reason="Matches the deterministic 32-bit solver seed domain.",
                step=1,
                required=False,
                category="advanced",
            ),
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
            ),
        ],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="Fitted FastICA State",
            ),
            PortMetadata(
                name="fitted_state",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="Replayable FastICA State",
            ),
            PortMetadata(
                name="sources",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="Independent Source Scores",
            ),
            PortMetadata(
                name="components",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Mixing Spectral Profiles",
            ),
            PortMetadata(
                name="mixing_matrix",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Feature-by-component Mixing Matrix",
            ),
            PortMetadata(
                name="unmixing_matrix",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Component-by-feature Unmixing Matrix",
            ),
            PortMetadata(
                name="residuals",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Reconstruction Residuals",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        del use_scp
        input_expression = inputs.get("default", inputs.get("X", "input_data"))
        parameters = _canonical_ica_parameters(self._resolve_params())
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.ica_node import _ica_export_outputs",
            f"{indent}results['{self.node_id}'] = _ica_export_outputs(",
            f"{indent}    {input_expression}, parameters={parameters!r},",
            f"{indent})",
        ]

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        core = _ica_scientific_core(input_data, parameters=self._resolve_params())
        input_ds = core["dataset"]
        n_components = int(core["parameters"]["n_components"])
        labels = [f"IC {index + 1}" for index in range(n_components)]
        sample_axis = input_ds.get_observation_axis()
        feature_axis = input_ds.get_feature_axis()
        component_axis = make_safe_coord(labels, title="Independent Component")
        sources = create_spectral_dataset(
            data=core["sources"],
            x_coord=component_axis,
            y_coord=sample_axis,
            units="unit variance" if core["parameters"]["whiten"] == "unit-variance" else "arbitrary",
            title="FastICA Independent Source Scores",
            data_role="X_features",
        )
        profiles = create_spectral_dataset(
            data=core["spectral_profiles"],
            x_coord=feature_axis,
            y_coord=component_axis,
            units=getattr(input_ds, "units", None),
            title="FastICA Mixing Spectral Profiles",
        )
        residuals = create_spectral_dataset(
            data=core["residuals"],
            x_coord=feature_axis,
            y_coord=sample_axis,
            units=getattr(input_ds, "units", None),
            title="FastICA Reconstruction Residuals",
        )
        for output, operation in (
            (sources, "model.ica.sources"),
            (profiles, "model.ica.components"),
            (residuals, "model.ica.residuals"),
        ):
            copy_processing_history(input_ds, output)
            add_processing_step(output, operation, core["parameters"], node_id=self.node_id)
            inherit_origin_flags(input_ds, output)
        inherit_sample_flags(input_ds, sources)
        inherit_sample_flags(input_ds, residuals)
        residual_rmse = float(np.sqrt(np.mean(np.square(core["residuals"]))))
        data_scale = float(np.sqrt(np.mean(np.square(core["data"]))))
        diagnostics = {
            "n_components": n_components,
            "n_iter": int(core["n_iter"]),
            "converged": True,
            "random_seed": int(core["parameters"]["random_seed"]),
            "whiten": core["parameters"]["whiten"],
            "sign_rule": _ICA_SIGN_RULE,
            "order_rule": _ICA_ORDER_RULE,
            "reconstruction_residual": "observed_minus_reconstructed",
            "reconstruction_rmse": residual_rmse,
            "relative_reconstruction_rmse": residual_rmse / data_scale if data_scale > 0.0 else 0.0,
        }
        artifact = _artifact_builder.build_model_artifact(
            core["extract"],
            input_ds,
            node_id=self.node_id,
            metrics={
                "n_iter": diagnostics["n_iter"],
                "reconstruction_rmse": residual_rmse,
                "relative_reconstruction_rmse": diagnostics["relative_reconstruction_rmse"],
            },
        )
        return NodeResult(
            outputs={
                "default": sources,
                "sources": sources,
                "components": profiles,
                "mixing_matrix": np.array(core["mixing"], copy=True),
                "unmixing_matrix": np.array(core["components"], copy=True),
                "residuals": residuals,
                "model": core["fitted_state"],
                "fitted_state": core["fitted_state"],
                "_model_artifact": artifact,
            },
            diagnostics=diagnostics,
        )

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, object]:
        del target
        return _ica_scientific_core(input_data, parameters=self._resolve_params())["fitted_state"]

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        return apply_ica_fitted_state(input_data, state)


bind_stable_execution_contract(
    FastICANode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.model.ica",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/exploratory.md",
    implementation_modules=(
        fitted_state,
        dag_io_contracts,
        meta_helpers,
        modeling_core_utils,
        _artifact_builder,
    ),
    implementation_distributions=("numpy", "scipy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
    citations=(
        "Hyvarinen & Oja, Independent Component Analysis: Algorithms and Applications, Neural Networks "
        "13 (2000) 411-430",
        "Hyvarinen, Fast and Robust Fixed-Point Algorithms for Independent Component Analysis, IEEE "
        "Transactions on Neural Networks 10 (1999) 626-634",
        "R package ica, icafast fixed-point independent component analysis reference implementation",
    ),
    fitted_state_serializer=ICA_FITTED_STATE_SERIALIZER,
    deterministic=True,
    target_access=TargetAccess.NONE,
    group_access="none",
)


__all__ = [
    "FastICANode",
    "ICA_FITTED_STATE_SERIALIZER",
    "_canonical_ica_parameters",
    "_ica_scientific_core",
    "apply_ica_fitted_state",
]
