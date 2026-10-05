"""Canonical native PARAFAC decomposition for explicitly-modeled multiway data."""

from __future__ import annotations

import copy
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib import parafac_core
from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext, SherpaDataset
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.rank_projection import input_axis_identity
from spectra_sherpa.core.dimension_roles import DimensionRole
from spectra_sherpa.execution_contract_vocabulary import (
    DatasetRankPolicy,
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    TargetAccess,
    WorkerCapability,
)

from ...io_contracts import bind_X
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from ...stable_execution_contract import bind_stable_execution_contract, execution_contract_digest
from . import saved_native_model


def _input_mode_roles(dataset: SherpaDataset) -> tuple[str, ...]:
    roles = tuple(str(role) for role in dataset.layout.mode_roles)
    if len(roles) != dataset.ndim:
        raise ValueError(
            "PARAFAC requires explicit canonical dimension roles for every mode; "
            "inspect or correct the dataset layout before fitting"
        )
    if roles[0] not in {
        DimensionRole.SAMPLE.value,
        DimensionRole.OBSERVATION.value,
        DimensionRole.SPATIAL_COORDINATE.value,
        DimensionRole.SPATIAL_X.value,
        DimensionRole.SPATIAL_Y.value,
        DimensionRole.SPATIAL_Z.value,
    }:
        raise ValueError("PARAFAC requires samples, observations, or a spatial coordinate on the first mode")
    return roles


def _spatial_mask(dataset: SherpaDataset) -> np.ndarray | None:
    projection = dataset.layout.image_include
    if projection is None:
        return None
    if dataset.ndim != 3 or dataset.layout.image_size != tuple(dataset.shape[:2]):
        raise ValueError(
            "PARAFAC can honor an image inclusion mask only on an exact spatial-by-spatial-by-feature cube"
        )
    if len(projection) != dataset.shape[0] * dataset.shape[1]:
        raise ValueError("PARAFAC image inclusion mask does not match the two spatial modes")
    return np.asarray(projection, dtype=bool).reshape(dataset.shape[:2], order="F")


def _fit_parafac_dataset(input_data: Any, *, parameters: Mapping[str, object]) -> tuple[SherpaDataset, dict[str, Any]]:
    dataset = bind_X(
        input_data,
        missing_message="Missing required input: input_data (multiway dataset)",
        dataset_error_message="PARAFAC input_data must be a SherpaDataset",
        allow_array=False,
    )
    if dataset.ndim < 3:
        raise ValueError("PARAFAC requires a multiway dataset with at least three dimensions")
    roles = _input_mode_roles(dataset)
    spatial_mask = _spatial_mask(dataset)
    fit = parafac_core.fit_parafac(
        dataset.X,
        parameters=parameters,
        input_axis_identity_sha256=input_axis_identity(dataset),
        mode_roles=roles,
        source_contract_digest=execution_contract_digest(PARAFACNode.metadata),
        spatial_mask=spatial_mask,
    )
    return dataset, fit


def _parafac_export_outputs(input_data: Any, *, parameters: Mapping[str, object]) -> dict[str, Any]:
    """Return numerical outputs through the same authority as live execution."""

    _dataset, fit = _fit_parafac_dataset(input_data, parameters=parameters)
    metadata = fit["state"]["metadata"]
    return {
        "model": fit["state"],
        "sample_scores": fit["sample_scores"],
        "component_weights": fit["component_weights"],
        "relative_reconstruction_error": metadata["relative_reconstruction_error"],
    }


def _score_dataset(
    source: SherpaDataset,
    scores: np.ndarray,
    *,
    node_id: str,
    spatial_mask: np.ndarray | None,
) -> SherpaDataset:
    labels = [f"Component {index + 1}" for index in range(scores.shape[1])]
    result = SherpaDataset(
        X=scores,
        feature_axis=FeatureAxis(
            values=np.arange(1, scores.shape[1] + 1, dtype=np.float64),
            labels=labels,
            title="PARAFAC Component",
        ),
        sample_axis=source.sample_axis.copy() if source.sample_axis is not None else None,
        target=source.target.copy() if source.target is not None else None,
        target_context=source.target_context.model_copy(deep=True),
        domain=source.domain.model_copy(deep=True),
        descriptive=source.descriptive.model_copy(deep=True),
        source_identity=source.source_identity.model_copy(deep=True),
        source_history=source.source_history.model_copy(deep=True),
        layout=DatasetLayoutContext(
            kind="generic",
            source_type="parafac-mode-1-scores",
            source_dtype=scores.dtype.str,
            source_shape=tuple(scores.shape),
            mode_roles=(source.layout.mode_roles[0], DimensionRole.COMPONENT),
            original_unfolded_shape=tuple(source.shape),
        ),
        provenance=source.provenance.copy(),
        quality=source.quality.model_copy(deep=True),
        backend=source.backend,
        title="PARAFAC Mode-1 Scores",
        units="relative contribution",
        extra=copy.deepcopy(source.extra),
        is_time_series=source.is_time_series,
        data_role="X_features",
    )
    add_processing_step(
        result,
        "model.parafac.observation_scores",
        {
            "input_shape": list(source.shape),
            "input_mode_roles": [str(role) for role in source.layout.mode_roles],
            "input_axis_identity_sha256": input_axis_identity(source),
            "rank_policy": DatasetRankPolicy.PRESERVES_ND.value,
            "unfolding": "none",
            "spatial_mask_policy": (parafac_core.PARAFAC_SPATIAL_MASK_POLICY if spatial_mask is not None else "none"),
            "included_spatial_cells": (
                int(np.count_nonzero(spatial_mask)) if spatial_mask is not None else source.shape[0] * source.shape[1]
            ),
        },
        node_id=node_id,
        input_shape=tuple(source.shape),
        state_effects=["multiway_decomposed"],
    )
    return result


@register_node
class PARAFACNode(Node):
    """Fit a deterministic CP-ALS model without collapsing multiway modes."""

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="model.parafac",
        category="exploratory",
        label="Fit PARAFAC Decomposition",
        description=(
            "Decompose a sample-first or spatial multiway dataset into one factor matrix per mode. "
            "The native deterministic CP-ALS fit keeps spatial, time, excitation, emission, "
            "and spectral modes distinct; it never silently unfolds them into ordinary features."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=1,
                max_value=20,
                max_value_reason="Bounds factor-state size and CP-ALS computation.",
                step=1,
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="max_iter",
                label="Maximum Iterations",
                param_type="number",
                default=200,
                min_value=1,
                max_value=500,
                max_value_reason="Bounds deterministic CP-ALS execution time.",
                step=10,
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="tol",
                label="Relative Convergence Tolerance",
                param_type="number",
                default=0.000001,
                min_value=0.0000000001,
                max_value=0.1,
                max_value_reason="Prevents accepting a tolerance too loose for meaningful convergence.",
                step=0.000001,
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="ridge",
                label="ALS Ridge Stabilization",
                param_type="number",
                default=0.000000000001,
                min_value=0.0,
                max_value=1.0,
                max_value_reason="Bounds regularization so it cannot dominate the decomposition.",
                step=0.000000000001,
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
                label="Multiway Dataset",
                description="Sample-first tensor with explicit canonical roles for every mode",
            )
        ],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="Mode-1 Scores",
            ),
            PortMetadata(
                name="sample_scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="Mode-1 Scores",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="Data-free PARAFAC Factor State",
            ),
            PortMetadata(
                name="component_weights",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Component Weights",
            ),
            PortMetadata(
                name="relative_reconstruction_error",
                type_ref="spectrasherpa://types/Scalar/1.0",
                required=True,
                label="Relative Reconstruction Error",
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
        parameters = parafac_core.canonical_parafac_parameters(self._resolve_params())
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.parafac_node import _parafac_export_outputs",
            f"{indent}results[{self.node_id!r}] = _parafac_export_outputs(",
            f"{indent}    {input_expression}, parameters={parameters!r},",
            f"{indent})",
        ]

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, Any]:
        del target
        _dataset, fit = _fit_parafac_dataset(input_data, parameters=self._resolve_params())
        return fit["state"]

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        dataset = bind_X(
            input_data,
            missing_message="Missing required input: input_data (multiway dataset)",
            dataset_error_message="PARAFAC input_data must be a SherpaDataset",
            allow_array=False,
        )
        _input_mode_roles(dataset)
        normalized_state = parafac_core.validate_parafac_state(state)
        if normalized_state["metadata"]["source_contract_digest"] != execution_contract_digest(PARAFACNode.metadata):
            raise ValueError("PARAFAC fitted state source contract differs from the current implementation")
        return parafac_core.apply_parafac(
            dataset.X,
            normalized_state,
            input_axis_identity_sha256=input_axis_identity(dataset),
            spatial_mask=_spatial_mask(dataset),
        )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        dataset, fit = _fit_parafac_dataset(input_data, parameters=self._resolve_params())
        state = fit["state"]
        metadata = state["metadata"]
        spatial_mask = _spatial_mask(dataset)
        scores = _score_dataset(
            dataset,
            np.asarray(fit["sample_scores"], dtype=np.float64),
            node_id=self.node_id,
            spatial_mask=spatial_mask,
        )
        diagnostics = {
            "n_components": int(metadata["n_components"]),
            "input_shape": list(dataset.shape),
            "mode_roles": list(metadata["mode_roles"]),
            "input_axis_identity_sha256": metadata["input_axis_identity_sha256"],
            "n_iter": int(metadata["n_iter"]),
            "converged": bool(metadata["converged"]),
            "relative_reconstruction_error": float(metadata["relative_reconstruction_error"]),
            "unfolding": "none",
            "spatial_mask_policy": metadata["spatial_mask_policy"],
            "included_spatial_cells": int(metadata["included_spatial_cells"]),
            "excluded_spatial_cells": int(metadata["excluded_spatial_cells"]),
        }
        from .saved_native_model import build_native_model_artifact

        artifact = build_native_model_artifact(self, dataset, state)
        artifact["metadata"]["metrics"] = diagnostics
        return NodeResult(
            outputs={
                "default": scores,
                "sample_scores": scores,
                "model": state,
                "component_weights": np.asarray(fit["component_weights"], dtype=np.float64),
                "relative_reconstruction_error": float(metadata["relative_reconstruction_error"]),
                "_model_artifact": artifact,
            },
            diagnostics=diagnostics,
        )


bind_stable_execution_contract(
    PARAFACNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.model.parafac",
    implementation_version="1.1.0",
    # Model artifacts are assembled in memory and returned through the normal
    # private worker result channel.  The worker never writes an artifact to a
    # repository or external store, so granting a write capability here would
    # both overstate its authority and make this node unrunnable in the shared
    # read-only scientific worker.
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 120, "cpu_seconds": 120, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/exploratory.md",
    implementation_modules=(parafac_core, dag_io_contracts, meta_helpers, saved_native_model),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "Kolda and Bader, Tensor Decompositions and Applications, SIAM Review 51 (2009) 455-500",
        "Bro, PARAFAC. Tutorial and applications, Chemometrics and Intelligent Laboratory Systems 38 (1997) 149-171",
    ),
    fitted_state_serializer=parafac_core.PARAFAC_STATE_SERIALIZER,
    deterministic=True,
    target_access=TargetAccess.NONE,
    group_access="none",
    input_rank_policy=DatasetRankPolicy.PRESERVES_ND,
)


__all__ = ["PARAFACNode", "_parafac_export_outputs"]
