"""Model-aware regression prediction without test-target access or refitting."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

import numpy as np

from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily

from . import apply_fitted_pls_node, fitted_pls_node, fitted_regression_nodes, regression_application, regression_nodes


@register_node
class PredictRegressionNode(Node):
    metadata = NodeMetadata(
        node_type="model.predict_regression",
        category="regression",
        label="Predict Regression",
        description="Predict held-out or new rows with fitted PLS, PCR, SVR or linear regression. "
        "Connect the trainer's Fitted State output. No fitting or test targets are used. "
        "Use Apply Sherpa PLS Regression when PLS-specific intervals and applicability are needed.",
        parameters=[],
        policy=NodePolicy(),
        input_types=["SherpaDataset"],
        output_type="array",
        input_ports=[
            PortMetadata("default", "spectrasherpa://types/SpectralDataset/1.0", label="Application Data"),
            PortMetadata("fitted_state", "spectrasherpa://types/RegressionModel/1.0", label="Fitted State"),
        ],
        output_ports=[
            PortMetadata("default", "spectrasherpa://types/TargetMatrix/1.0", label="Predicted Targets"),
            PortMetadata(
                "prediction_identity", "spectrasherpa://types/PredictionIdentity/1.0", label="Prediction Identity"
            ),
        ],
    )

    def _execute_sync(self, input_data, fitted_state):
        from .apply_fitted_pls_node import ApplyFittedPLSV2Node
        from .fitted_pls_node import FITTED_PLS_STATE_SERIALIZER
        from .fitted_regression_nodes import FittedLinearRegressionNode, FittedPCRNode, FittedSVRNode

        if not isinstance(fitted_state, Mapping):
            raise ValueError(
                "Predict Regression requires the trainer's Fitted State output, not its legacy Model output"
            )
        if fitted_state.get("serializer") == FITTED_PLS_STATE_SERIALIZER:
            result = ApplyFittedPLSV2Node(self.node_id, {})._execute_sync(input_data, fitted_state)
            return NodeResult(outputs={key: result.outputs[key] for key in ("default", "prediction_identity")})
        if fitted_state.get("schema_version") == regression_application.SCHEMA:
            predictions, identity = regression_application.apply_application_state(input_data, fitted_state)
        else:
            producers = {
                "model.fitted_pcr": FittedPCRNode,
                "model.fitted_svr": FittedSVRNode,
                "model.fitted_linear_regression": FittedLinearRegressionNode,
            }
            producer = producers.get(fitted_state.get("operation_id"))
            if producer is None:
                raise ValueError("Unsupported regression fitted state; connect a regression trainer's Fitted State")
            predictions = producer(self.node_id, {}).apply_fitted_state(input_data, fitted_state)
            # Historical fold-local states did not retain response identity.
            identity = {"names": None, "units": [None] * predictions.shape[1]}
        dataset = coerce_to_sherpa(input_data, input_name="Application Data")
        axis = dataset.sample_axis
        receipt = {
            "schema_version": "spectrasherpa.prediction-identity/1",
            "output_port": "default",
            "shape": list(predictions.shape),
            "response_identity": identity,
            "sample_labels": list(axis.labels) if axis is not None and axis.labels is not None else None,
            "sample_values": axis.values.tolist() if axis is not None and axis.values is not None else None,
            "fitted_state_custody": {"mode": "local_fitted_state"},
            "prediction_sha256": hashlib.sha256(np.asarray(predictions, dtype="<f8").tobytes(order="C")).hexdigest(),
            "prediction_digest_encoding": "row-major little-endian float64",
        }
        return NodeResult(outputs={"default": predictions, "prediction_identity": receipt})

    async def execute(self, default=None, input_data=None, fitted_state=None, **kwargs):
        return self._execute_sync(input_data if input_data is not None else default, fitted_state)

    def generate_python(self, inputs, indent="    ", use_scp=True):
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.predict_regression_node "
            "import PredictRegressionNode",
            f"{indent}results[{self.node_id!r}] = PredictRegressionNode({self.node_id!r}, {{}})._execute_sync("
            f"{inputs.get('default', 'input_data')}, {inputs.get('fitted_state', 'None')}).outputs",
        ]


bind_stable_execution_contract(
    PredictRegressionNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.ARTIFACT_APPLICATION,
    implementation_id="spectrasherpa.model.predict_regression",
    implementation_version="1",
    required_worker_capabilities=(),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/regression.md",
    implementation_modules=(
        regression_application,
        regression_nodes,
        fitted_pls_node,
        apply_fitted_pls_node,
        fitted_regression_nodes,
    ),
    implementation_distributions=("numpy", "scikit-learn", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
    fitted_state_serializer="spectrasherpa.regression-application-dispatch/1",
    target_access="none",
    citations=tuple(fitted_pls_node.FittedPLSV2Node.metadata.resolved_execution_contract().payload["citations"]),
)
