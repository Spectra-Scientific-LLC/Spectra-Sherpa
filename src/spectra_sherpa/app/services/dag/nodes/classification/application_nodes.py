"""Serializer-bound application nodes for canonical classifiers."""

from __future__ import annotations

from typing import Any, Callable, Mapping

import numpy as np

from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    node_registry,
    register_node,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.core import execution_runtime as execution_runtime_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import knn_nodes, plsda_state, simca_nodes
from .knn_nodes import KNN_FITTED_STATE_SERIALIZER, apply_knn_fitted_state
from .plsda_state import FITTED_STATE_SERIALIZER as PLSDA_FITTED_STATE_SERIALIZER
from .plsda_state import apply_fitted_state as apply_plsda_fitted_state
from .simca_nodes import SIMCA_FITTED_STATE_SERIALIZER, apply_simca_fitted_state

_BINDING_FIELDS = frozenset(
    {
        "artifact_digest",
        "state_node_id",
        "state_digest",
        "state_content_digest",
        "serializer",
        "source_contract_digest",
    }
)


def _canonical_application_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Admit either a local fitted-state edge or one complete artifact binding."""

    present = frozenset(name for name, value in parameters.items() if value is not None)
    if present not in {frozenset(), _BINDING_FIELDS}:
        raise ValueError("canonical classifier artifact binding must be either absent or complete")
    return parameters


def _application_result(
    input_data: Any,
    fitted_state: Any,
    *,
    node_id: str,
    method: str,
    serializer: str,
    apply: Callable[[Any, Any], tuple[np.ndarray, np.ndarray]],
    numeric_port: str,
    numeric_semantics: str,
) -> NodeResult:
    labels, numeric = apply(input_data, fitted_state)
    labels = np.asarray(labels, dtype=object)
    matrix = np.asarray(numeric, dtype=np.float64)
    outputs = {"y_pred": labels.tolist(), numeric_port: matrix.tolist()}
    diagnostics = {
        "node_id": node_id,
        "method": method,
        "serializer": serializer,
        "n_predicted": int(labels.size),
        "n_classes": int(matrix.shape[1]),
        "numeric_output_semantics": numeric_semantics,
    }
    if method == "simca":
        diagnostics["n_rejected"] = int(np.sum(labels == "unassigned"))
    return NodeResult(outputs=outputs, diagnostics=diagnostics)


class _ClassifierApplicationNode(Node):
    """Common typed DAG projection; subclasses bind one serializer and core."""

    METHOD: str
    SERIALIZER: str
    NUMERIC_PORT: str
    NUMERIC_SEMANTICS: str
    APPLY: Callable[[Any, Any], tuple[np.ndarray, np.ndarray]]
    SOURCE_OPERATION: str

    def _binding(self) -> dict[str, object] | None:
        present = {name for name, value in self.parameters.items() if value is not None}
        if not present:
            return None
        if present != _BINDING_FIELDS:
            raise ValueError("canonical classifier artifact binding must be complete")
        return {name: self.parameters[name] for name in sorted(_BINDING_FIELDS)}

    def requires_worker_capability_at_runtime(self, capability: str) -> bool:
        """Require artifact custody only for the imported application path."""

        if capability == WorkerCapability.READ_CANONICAL_FITTED_ARTIFACT.value:
            return self._binding() is not None
        return super().requires_worker_capability_at_runtime(capability)

    async def execute(
        self,
        default: Any = None,
        X_new: Any = None,
        fitted_state: Mapping[str, object] | None = None,
        **kwargs: Any,
    ) -> NodeResult:
        """Apply one local or imported state through the shared classifier core."""

        del kwargs
        if default is not None and X_new is not None:
            raise ValueError(f"{self.METHOD} application accepts one input spectra port")
        input_data = default if default is not None else X_new
        if input_data is None:
            raise ValueError(f"{self.METHOD} application requires X_new")
        binding = self._binding()
        if (binding is None) == (fitted_state is None):
            raise ValueError(f"{self.METHOD} application requires exactly one local-state or artifact-binding source")
        custody: dict[str, object]
        if binding is None:
            assert fitted_state is not None
            state: Mapping[str, object] = fitted_state
            custody = {"mode": "local_fitted_state"}
        else:
            source_contract = node_registry.get_metadata(self.SOURCE_OPERATION).resolved_execution_contract()
            if source_contract is None:
                raise ValueError(f"{self.METHOD} source execution contract is unavailable")
            state = (
                self.require_execution_runtime()
                .require_canonical_artifact_reader()
                .load_bound_state(
                    binding,
                    expected_source_contract_digest=source_contract.digest,
                    expected_serializer=self.SERIALIZER,
                )
            )
            custody = {
                "mode": "canonical_artifact",
                "artifact_digest": binding["artifact_digest"],
                "state_node_id": binding["state_node_id"],
                "state_digest": binding["state_digest"],
                "state_content_digest": binding["state_content_digest"],
            }
        result = _application_result(
            input_data,
            state,
            node_id=self.node_id,
            method=self.METHOD,
            serializer=self.SERIALIZER,
            apply=self.APPLY,
            numeric_port=self.NUMERIC_PORT,
            numeric_semantics=self.NUMERIC_SEMANTICS,
        )
        return NodeResult(
            outputs=result.outputs,
            diagnostics={
                **result.diagnostics,
                "fitted_state_custody": custody,
                **({"canonical_artifact": custody} if binding else {}),
            },
        )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        if self._binding() is not None:
            raise ValueError("imported classifier artifacts must be exported through the canonical project package")
        del use_scp
        input_expression = inputs.get("default", inputs.get("X_new", "None"))
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.classification.application_nodes import "
            "_application_result",
            f"{indent}from {self.APPLY.__module__} import {self.APPLY.__name__}",
            f"{indent}results[{self.node_id!r}] = _application_result(",
            f"{indent}    {input_expression}, {inputs.get('fitted_state', 'None')},",
            f"{indent}    node_id={self.node_id!r}, method={self.METHOD!r}, serializer={self.SERIALIZER!r},",
            f"{indent}    apply={self.APPLY.__name__}, numeric_port={self.NUMERIC_PORT!r},",
            f"{indent}    numeric_semantics={self.NUMERIC_SEMANTICS!r},",
            f"{indent}).outputs",
        ]

    def exported_output_ports(self) -> set[str]:
        return {"y_pred", self.NUMERIC_PORT}


def _metadata(
    node_type: str,
    label: str,
    state_label: str,
    numeric_port: PortMetadata,
    *,
    canonical_artifact_binding: bool = False,
    local_input_alias: bool = False,
) -> NodeMetadata:
    parameters = (
        [
            NodeParameter(
                name=field,
                label=field.replace("_", " ").title(),
                param_type="text",
                default=None,
                required=False,
                category="internal",
            )
            for field in sorted(_BINDING_FIELDS)
        ]
        if canonical_artifact_binding
        else []
    )
    return NodeMetadata(
        policy=NodePolicy(),
        node_type=node_type,
        category="classification",
        label=label,
        description="Apply one explicit fitted classifier state without fitting or algorithm guessing.",
        parameters=parameters,
        input_ports=[
            *(
                [
                    PortMetadata(
                        name="default",
                        type_ref="spectrasherpa://types/Array2D/1.0",
                        required=not local_input_alias,
                        label="Artifact Inference Spectra",
                        accepted_data_roles=["X_spectra", "X_features"],
                    )
                ]
                if canonical_artifact_binding
                else []
            ),
            *(
                [
                    PortMetadata(
                        name="X_new",
                        type_ref="spectrasherpa://types/Array2D/1.0",
                        required=not canonical_artifact_binding,
                        label="Inference Spectra",
                        accepted_data_roles=["X_spectra", "X_features"],
                    )
                ]
                if local_input_alias or not canonical_artifact_binding
                else []
            ),
            PortMetadata(
                name="fitted_state",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=not canonical_artifact_binding,
                label=state_label,
                description=(
                    "Typed state emitted by the fitted classifier; omit for imported-artifact application."
                    if canonical_artifact_binding
                    else None
                ),
            ),
        ],
        output_ports=[
            PortMetadata(
                name="y_pred",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=True,
                label="Predicted Classes",
            ),
            numeric_port,
        ],
        input_types=["SherpaDataset", "dict"],
        output_type="dict",
        canonical_parameter_validator=(_canonical_application_parameters if canonical_artifact_binding else None),
    )


@register_node
class ApplyKNNNode(_ClassifierApplicationNode):
    METHOD = "knn"
    SERIALIZER = KNN_FITTED_STATE_SERIALIZER
    NUMERIC_PORT = "y_prob"
    NUMERIC_SEMANTICS = "class_probabilities"
    APPLY = staticmethod(apply_knn_fitted_state)
    SOURCE_OPERATION = "classification.knn"
    metadata = _metadata(
        "classification.apply_knn",
        "Apply Fitted KNN",
        "Fitted KNN State",
        PortMetadata(
            name="y_prob",
            type_ref="spectrasherpa://types/Array2D/1.0",
            required=True,
            label="Class Probabilities",
        ),
        canonical_artifact_binding=True,
        local_input_alias=True,
    )


@register_node
class ApplyPLSDANode(_ClassifierApplicationNode):
    METHOD = "plsda"
    SERIALIZER = PLSDA_FITTED_STATE_SERIALIZER
    NUMERIC_PORT = "class_scores"
    NUMERIC_SEMANTICS = "class_response_scores_not_probabilities"
    APPLY = staticmethod(apply_plsda_fitted_state)
    SOURCE_OPERATION = "classification.plsda"
    metadata = _metadata(
        "classification.apply_plsda",
        "Apply Fitted PLS-DA",
        "Fitted PLS-DA State",
        PortMetadata(
            name="class_scores",
            type_ref="spectrasherpa://types/Array2D/1.0",
            required=True,
            label="PLS-DA Class Responses",
        ),
        canonical_artifact_binding=True,
    )

    def _binding(self) -> dict[str, object] | None:
        present = {name for name, value in self.parameters.items() if value is not None}
        if not present:
            return None
        if present != _BINDING_FIELDS:
            raise ValueError("canonical PLS-DA artifact binding must be complete")
        return {name: self.parameters[name] for name in sorted(_BINDING_FIELDS)}

    def requires_worker_capability_at_runtime(self, capability: str) -> bool:
        """Require artifact custody only for the imported application path."""

        if capability == WorkerCapability.READ_CANONICAL_FITTED_ARTIFACT.value:
            return self._binding() is not None
        return super().requires_worker_capability_at_runtime(capability)

    async def execute(
        self,
        default: Any = None,
        fitted_state: Mapping[str, object] | None = None,
        **kwargs: Any,
    ) -> NodeResult:
        """Apply one local or imported state through the same Sherpa PLS-DA core."""

        del kwargs
        if default is None:
            raise ValueError("PLS-DA application requires input spectra")
        binding = self._binding()
        if (binding is None) == (fitted_state is None):
            raise ValueError("PLS-DA application requires exactly one local-state or artifact-binding source")
        custody: dict[str, object]
        if binding is None:
            assert fitted_state is not None
            state: Mapping[str, object] = fitted_state
            custody = {"mode": "local_fitted_state"}
        else:
            source_contract = node_registry.get_metadata("classification.plsda").resolved_execution_contract()
            if source_contract is None:
                raise ValueError("PLS-DA source execution contract is unavailable")
            state = (
                self.require_execution_runtime()
                .require_canonical_artifact_reader()
                .load_bound_state(
                    binding,
                    expected_source_contract_digest=source_contract.digest,
                    expected_serializer=PLSDA_FITTED_STATE_SERIALIZER,
                )
            )
            custody = {
                "mode": "canonical_artifact",
                "artifact_digest": binding["artifact_digest"],
                "state_node_id": binding["state_node_id"],
                "state_digest": binding["state_digest"],
                "state_content_digest": binding["state_content_digest"],
            }
        result = _application_result(
            default,
            state,
            node_id=self.node_id,
            method=self.METHOD,
            serializer=self.SERIALIZER,
            apply=self.APPLY,
            numeric_port=self.NUMERIC_PORT,
            numeric_semantics=self.NUMERIC_SEMANTICS,
        )
        return NodeResult(
            outputs=result.outputs,
            diagnostics={
                **result.diagnostics,
                "fitted_state_custody": custody,
                **plsda_state.feature_identity_diagnostics(state),
                **({"canonical_artifact": custody} if binding else {}),
            },
        )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate only the explicit local fitted-state application path."""

        if self._binding() is not None:
            raise ValueError("imported PLS-DA artifacts must be exported through the canonical project package")
        normalized = {
            "X_new": inputs.get("default", inputs.get("X_new", "None")),
            "fitted_state": inputs.get("fitted_state", "None"),
        }
        return super().generate_python(normalized, indent=indent, use_scp=use_scp)


@register_node
class ApplySIMCANode(_ClassifierApplicationNode):
    METHOD = "simca"
    SERIALIZER = SIMCA_FITTED_STATE_SERIALIZER
    NUMERIC_PORT = "class_affinity"
    NUMERIC_SEMANTICS = "normalized_inverse_distance_affinity_not_probability"
    APPLY = staticmethod(apply_simca_fitted_state)
    SOURCE_OPERATION = "classification.simca"
    metadata = _metadata(
        "classification.apply_simca",
        "Apply Fitted SIMCA",
        "Fitted SIMCA State",
        PortMetadata(
            name="class_affinity",
            type_ref="spectrasherpa://types/Array2D/1.0",
            required=True,
            label="Class Affinity",
        ),
        canonical_artifact_binding=True,
        local_input_alias=True,
    )


def _bind_application(
    node_class: type[_ClassifierApplicationNode],
    *,
    implementation_id: str,
    source_module: Any,
    serializer: str,
    runtime_family: RuntimeFamily,
    distributions: tuple[str, ...],
    requirements: tuple[tuple[str, str], ...],
    citations: tuple[str, ...],
    implementation_version: str = "1.0.0",
) -> None:
    artifact_bound = True
    bind_stable_execution_contract(
        node_class,
        runtime_family=runtime_family,
        lifecycle_kind=LifecycleKind.ARTIFACT_APPLICATION,
        implementation_id=implementation_id,
        implementation_version=implementation_version,
        required_worker_capabilities=(
            (WorkerCapability.READ_CANONICAL_FITTED_ARTIFACT,) if artifact_bound else (WorkerCapability.READ_DATASET,)
        ),
        managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
        sample_effect="preserves_samples",
        feature_effect="generates_features",
        axis_effect="changes_axis",
        unit_effect="changes_units",
        resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
        license_id="BSD-3-Clause",
        help_reference="docs/nodes/classification.md",
        implementation_modules=((execution_runtime_contract, source_module) if artifact_bound else (source_module,)),
        implementation_distributions=distributions,
        runtime_requirements=requirements,
        citations=citations,
        fitted_state_serializer=serializer,
        deterministic=True,
        target_access="none",
        group_access="none",
    )


_bind_application(
    ApplyKNNNode,
    implementation_id="spectrasherpa.classification.apply_knn",
    source_module=knn_nodes,
    serializer=ApplyKNNNode.SERIALIZER,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    distributions=("numpy", "scikit-learn"),
    requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0")),
    citations=(
        "Cover & Hart, Nearest Neighbor Pattern Classification, IEEE Transactions on Information Theory "
        "13 (1967) 21-27, DOI 10.1109/TIT.1967.1053964",
    ),
)
_bind_application(
    ApplyPLSDANode,
    implementation_id="spectrasherpa.classification.apply_plsda",
    source_module=plsda_state,
    serializer=ApplyPLSDANode.SERIALIZER,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    distributions=("numpy",),
    requirements=(("numpy", "1.26.4"),),
    implementation_version="4.0.0",
    citations=(
        "Barker & Rayens, Partial least squares for discrimination, Journal of Chemometrics 17 (2003) "
        "166-173, DOI 10.1002/cem.785",
    ),
)
_bind_application(
    ApplySIMCANode,
    implementation_id="spectrasherpa.classification.apply_simca",
    source_module=simca_nodes,
    serializer=ApplySIMCANode.SERIALIZER,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    distributions=("numpy", "scipy", "scikit-learn"),
    requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
    citations=(
        "Wold, Pattern recognition by means of disjoint principal components models, Pattern Recognition "
        "8 (1976) 127-139, DOI 10.1016/0031-3203(76)90014-5",
    ),
)


__all__ = ["ApplyKNNNode", "ApplyPLSDANode", "ApplySIMCANode"]
