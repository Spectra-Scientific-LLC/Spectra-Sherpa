"""Explicit fold-local fit/apply ports over the existing regression implementations."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag import fitted_input_identity as input_authority
from spectra_sherpa.app.services.dag.io_contracts import bind_y, coerce_to_sherpa
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import fitted_pls_node as response_authority
from . import regression_nodes, saved_native_model

_BINDING_FIELDS = frozenset(
    {"artifact_digest", "state_node_id", "state_digest", "state_content_digest", "serializer", "source_contract_digest"}
)


def _application_parameters(parameters):
    present = {name for name, value in parameters.items() if value is not None}
    if present and present != _BINDING_FIELDS:
        raise ValueError("Regression artifact binding must be absent or complete")
    return parameters


def _fit_metadata(core, family, label):
    return NodeMetadata(
        node_type=f"model.fitted_{family}",
        category="modeling",
        label=f"Fit {label}",
        description=f"Fit {label} using training rows only; "
        f"connect its fitted state to Apply {label} for held-out predictions.",
        parameters=deepcopy(core.metadata.parameters),
        canonical_parameter_validator=core.metadata.canonical_parameter_validator,
        input_types=["SherpaDataset"],
        output_type="array",
        policy=NodePolicy(),
        input_ports=[
            PortMetadata(name="default", type_ref="spectrasherpa://types/SpectralDataset/1.0", required=True),
            PortMetadata(name="y", type_ref="spectrasherpa://types/TargetMatrix/1.0", required=False),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Training predictions (not validation)",
            ),
            PortMetadata(name="fitted_state", type_ref="spectrasherpa://types/RegressionModel/1.0", required=True),
        ],
    )


class _FittedRegression(Node):
    core: Any

    @property
    def serializer(self):
        return f"spectrasherpa.{self.metadata.node_type}/1"

    def fit_fitted_state(self, input_data, target):
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        X = np.asarray(dataset.X, dtype=float)
        y = np.asarray(
            bind_y(target, X=dataset, required=True, dataset_as_data=True, target_type="continuous"), dtype=float
        )
        if (
            X.ndim != 2
            or y.ndim not in {1, 2}
            or len(X) != len(y)
            or len(X) < 2
            or not np.isfinite(X).all()
            or not np.isfinite(y).all()
        ):
            raise ValueError(
                "Fitted regression requires finite, aligned training predictors and targets; "
                "no rows are silently removed"
            )
        state = self.core(self.node_id, self._resolve_params()).fit_fitted_state(dataset, y)
        return {
            "serializer": self.serializer,
            "operation_id": self.metadata.node_type,
            "input_identity": input_authority.fitted_input_identity(dataset, features=X.shape[1]),
            "state": state,
        }

    def apply_fitted_state(self, input_data, state):
        if (
            not isinstance(state, Mapping)
            or set(state) != {"serializer", "operation_id", "input_identity", "state"}
            or state["serializer"] != self.serializer
            or state["operation_id"] != self.metadata.node_type
        ):
            raise ValueError("Fitted regression state belongs to a different model or schema")
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        matrix = np.asarray(dataset.X, dtype=float)
        if matrix.ndim != 2 or not np.isfinite(matrix).all():
            raise ValueError("Regression application requires finite two-dimensional predictors")
        input_authority.require_fitted_input_identity(dataset, state["input_identity"], features=matrix.shape[1])
        predictions = self.core(self.node_id, {}).apply_fitted_state(dataset, state["state"])
        predictions = np.asarray(predictions, dtype=float).reshape(len(matrix), -1)
        if not np.isfinite(predictions).all():
            raise ValueError("Regression application produced non-finite predictions")
        return predictions

    async def execute(self, input_data=None, y=None, **kwargs):
        from .saved_native_model import build_native_model_artifact

        state = self.fit_fitted_state(input_data, y)
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        predictions = self.apply_fitted_state(input_data, state)
        bound_response = np.asarray(bind_y(y, X=dataset, required=True, dataset_as_data=True, target_type="continuous"))
        response_count = 1 if bound_response.ndim == 1 else bound_response.shape[1]
        identity = response_authority._response_identity(
            dataset if y is None else y, targets=response_count, bound_names=[], embedded=y is None
        )
        if self.metadata.node_type == "model.fitted_svr":
            selected = int(self._resolve_params()["target_index"]) - 1
            identity = {
                "names": None if identity["names"] is None else [identity["names"][selected]],
                "units": [identity["units"][selected]],
            }
        artifact = build_native_model_artifact(self, dataset, state, response_identity=identity)
        return NodeResult(
            outputs={
                "default": predictions,
                "fitted_state": state,
                "_model_artifact": artifact,
            },
            diagnostics={"evidence_scope": "training_fit_only_not_predictive_validation"},
        )

    def generate_python(self, inputs, indent="    ", use_scp=True):
        return [
            f"{indent}from spectra_sherpa.app.services.dag.node_base import node_registry",
            f"{indent}_fit = node_registry.create_node("
            f"{self.metadata.node_type!r}, {self.node_id!r}, {self._resolve_params()!r})",
            f"{indent}_state = _fit.fit_fitted_state({inputs.get('default', 'input_data')}, {inputs.get('y', 'None')})",
            f"{indent}results[{self.node_id!r}] = {{'default': "
            f"_fit.apply_fitted_state({inputs.get('default', 'input_data')}, _state), 'fitted_state': _state}}",
        ]


@register_node
class FittedPCRNode(_FittedRegression):
    core = regression_nodes.PCRNode
    metadata = _fit_metadata(core, "pcr", "PCR")


@register_node
class FittedSVRNode(_FittedRegression):
    core = regression_nodes.SVRNode
    metadata = _fit_metadata(core, "svr", "SVR")


@register_node
class FittedLinearRegressionNode(_FittedRegression):
    core = regression_nodes.LinearRegressionNode
    metadata = _fit_metadata(core, "linear_regression", "Linear Regression")


def _apply_metadata(family, label):
    return NodeMetadata(
        node_type=f"model.apply_fitted_{family}",
        category="modeling",
        label=f"Apply {label}",
        description=f"Predict using a locally fitted {label} state "
        "without fitting on application rows or their targets.",
        parameters=[
            NodeParameter(name=name, label=name, param_type="text", default=None, required=False, category="internal")
            for name in sorted(_BINDING_FIELDS)
        ],
        canonical_parameter_validator=_application_parameters,
        input_types=["SherpaDataset"],
        output_type="array",
        policy=NodePolicy(),
        input_ports=[
            PortMetadata(name="default", type_ref="spectrasherpa://types/SpectralDataset/1.0", required=True),
            PortMetadata(name="fitted_state", type_ref="spectrasherpa://types/RegressionModel/1.0", required=False),
        ],
        output_ports=[PortMetadata(name="default", type_ref="spectrasherpa://types/TargetMatrix/1.0", required=True)],
    )


class _ApplyRegression(Node):
    producer: Any

    async def execute(self, input_data=None, fitted_state=None, **kwargs):
        parameters = _application_parameters(self._resolve_params())
        binding = {name: value for name, value in parameters.items() if value is not None}
        if bool(binding) == (fitted_state is not None):
            raise ValueError("Regression application requires exactly one local state or artifact binding")
        if binding:
            contract = self.producer.metadata.resolved_execution_contract()
            fitted_state = (
                self.require_execution_runtime()
                .require_canonical_artifact_reader()
                .load_bound_state(
                    binding,
                    expected_source_contract_digest=contract.digest,
                    expected_serializer=contract.payload["fitted_state_serializer"],
                )
            )
        return NodeResult(
            outputs={"default": self.producer(self.node_id, {}).apply_fitted_state(input_data, fitted_state)}
        )

    def requires_worker_capability_at_runtime(self, capability):
        if capability == WorkerCapability.READ_CANONICAL_FITTED_ARTIFACT.value:
            return any(value is not None for value in self.parameters.values())
        return super().requires_worker_capability_at_runtime(capability)

    def generate_python(self, inputs, indent="    ", use_scp=True):
        if any(value is not None for value in self.parameters.values()):
            raise ValueError("Export imported artifacts through the canonical project package")
        return [
            f"{indent}from spectra_sherpa.app.services.dag.node_base import node_registry",
            f"{indent}_fit = node_registry.create_node({self.producer.metadata.node_type!r}, {self.node_id!r}, {{}})",
            f"{indent}results[{self.node_id!r}] = {{'default': "
            f"_fit.apply_fitted_state({inputs.get('default', 'input_data')}, {inputs.get('fitted_state', 'None')})}}",
        ]


@register_node
class ApplyFittedPCRNode(_ApplyRegression):
    producer = FittedPCRNode
    metadata = _apply_metadata("pcr", "PCR")


@register_node
class ApplyFittedSVRNode(_ApplyRegression):
    producer = FittedSVRNode
    metadata = _apply_metadata("svr", "SVR")


@register_node
class ApplyFittedLinearRegressionNode(_ApplyRegression):
    producer = FittedLinearRegressionNode
    metadata = _apply_metadata("linear_regression", "Linear Regression")


for _node in (
    FittedPCRNode,
    FittedSVRNode,
    FittedLinearRegressionNode,
    ApplyFittedPCRNode,
    ApplyFittedSVRNode,
    ApplyFittedLinearRegressionNode,
):
    _fit = issubclass(_node, _FittedRegression)
    _producer = _node if _fit else _node.producer
    bind_stable_execution_contract(
        _node,
        runtime_family=RuntimeFamily.SHERPA_NATIVE,
        lifecycle_kind=LifecycleKind.FITTED_MODEL if _fit else LifecycleKind.ARTIFACT_APPLICATION,
        implementation_id=f"spectrasherpa.{_node.metadata.node_type}",
        implementation_version="1",
        required_worker_capabilities=(
            (WorkerCapability.READ_DATASET,) if _fit else (WorkerCapability.READ_CANONICAL_FITTED_ARTIFACT,)
        ),
        managed_optimization_eligibility=(
            (
                ManagedOptimizationEligibility.LOCAL,
                ManagedOptimizationEligibility.DEVELOPMENT,
                ManagedOptimizationEligibility.FULL_REFIT,
            )
            if _fit
            else (ManagedOptimizationEligibility.LOCAL,)
        ),
        sample_effect="preserves_samples",
        feature_effect="generates_features",
        axis_effect="removes_axis",
        unit_effect="changes_units",
        resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
        license_id="BSD-3-Clause",
        citations=tuple(_producer.core.metadata.resolved_execution_contract().payload["citations"]),
        help_reference="docs/nodes/regression.md",
        implementation_modules=(
            regression_nodes,
            response_authority,
            regression_nodes.fitted_state,
            regression_nodes._artifact_builder,
            input_authority,
            saved_native_model,
        ),
        implementation_distributions=("numpy", "scipy", "scikit-learn"),
        runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
        managed_optimization_profiles=("first_party_pls",) if _fit else (),
        fitted_state_serializer=f"spectrasherpa.{_producer.metadata.node_type}/1",
        target_access="fit_only" if _fit else "none",
        supervised_task="regression" if _fit else "none",
    )
