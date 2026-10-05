"""Deterministic audit record for feature-selection provenance.

Registered as ``selection.audit``.

This node does not rerun or validate a selector.  It projects the selection
entries already present in a dataset's append-only provenance into a closed,
bounded, digest-bound report.  Selector-specific reports remain the authority
for the scientific calculation; this report answers which recorded decisions
produced the dataset that reached this point in the DAG.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import get_processing_history
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    TargetAccess,
    WorkerCapability,
)

from ...io_contracts import bind_X, to_numpy_2d
from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, NodeResult, PortMetadata, register_node

logger = logging.getLogger(__name__)

_REPORT_SCHEMA = "spectrasherpa.selection.audit.report/1"
_MAX_HISTORY_STEPS = 128
_MAX_SELECTION_STEPS = 32
_MAX_CONTAINER_ITEMS = 4096
_MAX_STRING_LENGTH = 512
_MAX_PARAMETERS_BYTES = 65_536
_MAX_REPORT_BYTES = 262_144
_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "node_id",
        "parameters",
        "scope",
        "timestamp_policy",
        "input_shape",
        "input_matrix_sha256",
        "feature_axis",
        "selection_steps",
        "selection_steps_sha256",
        "n_selection_steps",
        "methods_applied",
        "total_provenance_steps",
        "report_sha256",
    }
)
_STEP_FIELDS = frozenset(
    {
        "source_ordinal",
        "operation_id",
        "operation_version",
        "node_id",
        "parameters",
        "parameters_sha256",
        "input_shape",
        "output_shape",
        "state_effects",
        "impact",
        "impact_sha256",
        "step_sha256",
    }
)
_FEATURE_AXIS_FIELDS = frozenset(
    {
        "n_features",
        "values",
        "values_sha256",
        "units",
        "selection_method",
        "include_mask",
        "include_mask_sha256",
        "selection_scores",
        "selection_scores_sha256",
    }
)

# Closed built-in vocabulary. Unknown ``selection.*`` provenance fails closed
# instead of being presented as an audited canonical operation.
_SELECTION_OPS = frozenset(
    {
        "selection.cars",
        "selection.compare",
        "selection.ipls",
        "selection.mcuve",
        "selection.nested_cv",
        "selection.spa",
        "selection.stability",
        "selection.variable_select",
    }
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_audit_parameters(parameters: Mapping[str, Any]) -> dict[str, bool]:
    if set(parameters) - {"include_scores"}:
        raise ValueError("selection.audit accepts only include_scores")
    include_scores = parameters.get("include_scores", True)
    if not isinstance(include_scores, bool):
        raise ValueError("include_scores must be boolean")
    return {"include_scores": include_scores}


def _bounded_json(value: Any, *, field: str, depth: int = 0) -> Any:
    """Return one deterministic JSON value or reject ambiguous provenance."""

    if depth > 8:
        raise ValueError(f"{field} exceeds the maximum nesting depth")
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str) and len(value) > _MAX_STRING_LENGTH:
            raise ValueError(f"{field} contains an overlong string")
        return value
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field} contains a non-finite number")
        return float(value)
    if isinstance(value, Mapping):
        if len(value) > _MAX_CONTAINER_ITEMS:
            raise ValueError(f"{field} contains too many fields")
        if any(not isinstance(key, str) or not key or len(key) > _MAX_STRING_LENGTH for key in value):
            raise ValueError(f"{field} contains an invalid field name")
        normalized: dict[str, Any] = {}
        for key in sorted(value):
            normalized[key] = _bounded_json(value[key], field=f"{field}.{key}", depth=depth + 1)
        return normalized
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_CONTAINER_ITEMS:
            raise ValueError(f"{field} contains too many values")
        return [_bounded_json(item, field=f"{field}[]", depth=depth + 1) for item in value]
    raise ValueError(f"{field} contains a non-JSON value")


def _bounded_text(value: Any, *, field: str, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or value.strip() != value or len(value) > _MAX_STRING_LENGTH:
        raise ValueError(f"{field} must be a bounded non-empty string")
    return value


def _shape(value: Any, *, field: str) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{field} must contain exactly sample and feature counts")
    if any(isinstance(item, bool) or not isinstance(item, (int, np.integer)) or int(item) < 0 for item in value):
        raise ValueError(f"{field} contains an invalid dimension")
    return [int(item) for item in value]


def _selection_step(step: Any, *, source_ordinal: int) -> dict[str, Any] | None:
    if not isinstance(step, Mapping):
        raise ValueError("processing history entries must be mappings")
    operation_id = step.get("op_id")
    if not isinstance(operation_id, str):
        raise ValueError("processing history op_id must be a string")
    if not operation_id.startswith("selection."):
        return None
    if operation_id not in _SELECTION_OPS:
        raise ValueError(f"selection audit does not admit unknown operation {operation_id!r}")

    parameters = _bounded_json(step.get("parameters", {}), field="selection_step.parameters")
    if not isinstance(parameters, dict):
        raise ValueError("selection step parameters must be a mapping")
    if len(_canonical_json(parameters)) > _MAX_PARAMETERS_BYTES:
        raise ValueError("selection step parameters exceed the audit bound")

    impact_value = step.get("impact")
    impact = None if impact_value is None else _bounded_json(impact_value, field="selection_step.impact")
    if impact is not None and not isinstance(impact, dict):
        raise ValueError("selection step impact must be a mapping")

    state_effects_value = step.get("state_effects", [])
    if not isinstance(state_effects_value, (list, tuple)):
        raise ValueError("selection step state_effects must be a sequence")
    state_effects: list[str] = []
    for effect in state_effects_value:
        admitted = _bounded_text(effect, field="selection_step.state_effect", required=True)
        assert admitted is not None
        state_effects.append(admitted)
    state_effects = sorted(set(state_effects))

    record = {
        "source_ordinal": source_ordinal,
        "operation_id": operation_id,
        "operation_version": _bounded_text(
            step.get("op_version", "1.0"), field="selection_step.op_version", required=True
        ),
        "node_id": _bounded_text(step.get("node_id"), field="selection_step.node_id", required=False),
        "parameters": parameters,
        "parameters_sha256": _digest(parameters),
        "input_shape": _shape(step.get("input_shape"), field="selection_step.input_shape"),
        "output_shape": _shape(step.get("output_shape"), field="selection_step.output_shape"),
        "state_effects": state_effects,
        "impact": impact,
        "impact_sha256": None if impact is None else _digest(impact),
    }
    record["step_sha256"] = _digest(record)
    return record


def _array_digest(array: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(array)
    identity = _canonical_json({"dtype": contiguous.dtype.str, "shape": list(contiguous.shape)})
    return hashlib.sha256(identity + b"\0" + contiguous.tobytes(order="C")).hexdigest()


def _require_sha256(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _verify_optional_array_digest(
    values: Any,
    digest: Any,
    *,
    field: str,
    dtype: np.dtype[Any],
) -> None:
    if values is None:
        if digest is not None:
            raise ValueError(f"{field} digest must be absent when values are absent")
        return
    array = np.asarray(values, dtype=dtype)
    expected = _require_sha256(digest, field=f"{field}_sha256")
    if expected != _array_digest(array):
        raise ValueError(f"{field} digest mismatch")


def _verify_feature_axis(value: Any, *, n_features: int, include_scores: bool) -> None:
    if not isinstance(value, dict) or set(value) != _FEATURE_AXIS_FIELDS:
        raise ValueError("selection audit report has an invalid feature-axis field set")
    if value["n_features"] != n_features:
        raise ValueError("selection audit feature count does not match the input shape")

    values = value["values"]
    if values is not None:
        array = np.asarray(values, dtype=np.float64)
        if array.shape != (n_features,) or not np.all(np.isfinite(array)):
            raise ValueError("selection audit feature-axis values are invalid")
    _verify_optional_array_digest(
        values,
        value["values_sha256"],
        field="feature_axis.values",
        dtype=np.dtype(np.float64),
    )

    units = value["units"]
    if units is not None and (not isinstance(units, str) or len(units) > _MAX_STRING_LENGTH):
        raise ValueError("selection audit feature-axis units are invalid")
    _bounded_text(value["selection_method"], field="feature_axis.selection_method", required=False)

    include_mask = value["include_mask"]
    if include_mask is not None:
        mask = np.asarray(include_mask)
        if mask.dtype.kind != "b" or mask.shape != (n_features,):
            raise ValueError("selection audit feature-axis mask is invalid")
    _verify_optional_array_digest(
        include_mask,
        value["include_mask_sha256"],
        field="feature_axis.include_mask",
        dtype=np.dtype(np.uint8),
    )

    scores = value["selection_scores"]
    score_digest = value["selection_scores_sha256"]
    if scores is None:
        if include_scores and score_digest is not None:
            raise ValueError("selection audit exact scores are missing despite include_scores=true")
        if score_digest is not None:
            _require_sha256(score_digest, field="feature_axis.selection_scores_sha256")
        return
    if not include_scores:
        raise ValueError("selection audit includes exact scores despite include_scores=false")
    scores_array = np.asarray(scores, dtype=np.float64)
    if scores_array.shape != (n_features,) or not np.all(np.isfinite(scores_array)):
        raise ValueError("selection audit feature-axis scores are invalid")
    _verify_optional_array_digest(
        scores,
        score_digest,
        field="feature_axis.selection_scores",
        dtype=np.dtype(np.float64),
    )


def verify_selection_audit_report(value: Any) -> dict[str, Any]:
    """Verify the closed report's internal integrity without overstating science."""

    if not isinstance(value, Mapping) or set(value) != _REPORT_FIELDS:
        raise ValueError("selection audit report has an invalid field set")
    report = _bounded_json(value, field="selection_audit_report")
    if not isinstance(report, dict):
        raise ValueError("selection audit report must be a mapping")
    if report["schema_version"] != _REPORT_SCHEMA:
        raise ValueError("selection audit report has an unsupported schema")
    if report["scope"] != "recorded_provenance_not_independent_scientific_verification":
        raise ValueError("selection audit report overstates its verification scope")
    if report["timestamp_policy"] != "source_timestamps_omitted_for_determinism":
        raise ValueError("selection audit report has an invalid timestamp policy")
    _bounded_text(report["node_id"], field="selection_audit_report.node_id", required=True)
    input_shape = _shape(report["input_shape"], field="selection_audit_report.input_shape")
    assert input_shape is not None
    _require_sha256(report["input_matrix_sha256"], field="selection_audit_report.input_matrix_sha256")
    parameters = _canonical_audit_parameters(report["parameters"])
    _verify_feature_axis(
        report["feature_axis"],
        n_features=input_shape[1],
        include_scores=parameters["include_scores"],
    )
    if (
        isinstance(report["total_provenance_steps"], bool)
        or not isinstance(report["total_provenance_steps"], int)
        or not 0 <= report["total_provenance_steps"] <= _MAX_HISTORY_STEPS
    ):
        raise ValueError("selection audit report has an invalid total_provenance_steps")

    steps = report["selection_steps"]
    if not isinstance(steps, list) or len(steps) > _MAX_SELECTION_STEPS:
        raise ValueError("selection audit report has invalid selection_steps")
    previous_ordinal = -1
    for step in steps:
        if not isinstance(step, dict) or set(step) != _STEP_FIELDS:
            raise ValueError("selection audit report has an invalid step field set")
        if step["operation_id"] not in _SELECTION_OPS:
            raise ValueError("selection audit report contains an unknown selection operation")
        if (
            isinstance(step["source_ordinal"], bool)
            or not isinstance(step["source_ordinal"], int)
            or not 0 <= step["source_ordinal"] < report["total_provenance_steps"]
        ):
            raise ValueError("selection audit report contains an invalid source ordinal")
        if step["source_ordinal"] <= previous_ordinal:
            raise ValueError("selection audit source ordinals must be strictly increasing")
        previous_ordinal = step["source_ordinal"]
        _bounded_text(step["operation_version"], field="selection_step.operation_version", required=True)
        _bounded_text(step["node_id"], field="selection_step.node_id", required=False)
        if not isinstance(step["parameters"], dict):
            raise ValueError("selection audit step parameters must be a mapping")
        if len(_canonical_json(step["parameters"])) > _MAX_PARAMETERS_BYTES:
            raise ValueError("selection audit step parameters exceed the audit bound")
        _shape(step["input_shape"], field="selection_step.input_shape")
        _shape(step["output_shape"], field="selection_step.output_shape")
        effects = step["state_effects"]
        if not isinstance(effects, list) or effects != sorted(set(effects)):
            raise ValueError("selection audit state effects must be sorted and unique")
        for effect in effects:
            _bounded_text(effect, field="selection_step.state_effect", required=True)
        if step["impact"] is not None and not isinstance(step["impact"], dict):
            raise ValueError("selection audit step impact must be a mapping")
        expected_step_digest = _require_sha256(step["step_sha256"], field="selection_step.step_sha256")
        unsigned_step = {key: item for key, item in step.items() if key != "step_sha256"}
        if expected_step_digest != _digest(unsigned_step):
            raise ValueError("selection audit step digest mismatch")
        if _require_sha256(step["parameters_sha256"], field="selection_step.parameters_sha256") != _digest(
            step["parameters"]
        ):
            raise ValueError("selection audit parameter digest mismatch")
        expected_impact_digest = None if step["impact"] is None else _digest(step["impact"])
        if step["impact_sha256"] is not None:
            _require_sha256(step["impact_sha256"], field="selection_step.impact_sha256")
        if step["impact_sha256"] != expected_impact_digest:
            raise ValueError("selection audit impact digest mismatch")

    methods = [step["operation_id"] for step in steps]
    if (
        isinstance(report["n_selection_steps"], bool)
        or not isinstance(report["n_selection_steps"], int)
        or report["n_selection_steps"] != len(steps)
        or report["methods_applied"] != methods
    ):
        raise ValueError("selection audit report summary does not match its steps")
    if _require_sha256(
        report["selection_steps_sha256"], field="selection_audit_report.selection_steps_sha256"
    ) != _digest(steps):
        raise ValueError("selection audit history digest mismatch")
    expected_report_digest = _require_sha256(report["report_sha256"], field="selection_audit_report.report_sha256")
    unsigned_report = {key: item for key, item in report.items() if key != "report_sha256"}
    if expected_report_digest != _digest(unsigned_report):
        raise ValueError("selection audit report digest mismatch")
    return report


def _feature_axis_record(dataset: Any, *, include_scores: bool, n_features: int) -> dict[str, Any]:
    feature_axis = getattr(dataset, "feature_axis", None)
    if feature_axis is None:
        return {
            "n_features": n_features,
            "values": None,
            "values_sha256": None,
            "units": None,
            "selection_method": None,
            "include_mask": None,
            "include_mask_sha256": None,
            "selection_scores": None,
            "selection_scores_sha256": None,
        }

    values_value = getattr(feature_axis, "values", None)
    values = None
    values_digest = None
    if values_value is not None:
        values_array = np.asarray(values_value, dtype=np.float64)
        if values_array.shape != (n_features,) or not np.all(np.isfinite(values_array)):
            raise ValueError("feature-axis values must be finite and match X")
        values = values_array.tolist()
        values_digest = _array_digest(values_array)

    include_mask_value = getattr(feature_axis, "include_mask", None)
    include_mask = None
    include_mask_digest = None
    if include_mask_value is not None:
        mask = np.asarray(include_mask_value)
        if mask.dtype.kind != "b" or mask.shape != (n_features,):
            raise ValueError("feature-axis include_mask must be boolean and match X")
        include_mask = mask.tolist()
        include_mask_digest = _array_digest(mask.astype(np.uint8, copy=False))

    scores_value = getattr(feature_axis, "selection_scores", None)
    scores = None
    scores_digest = None
    if scores_value is not None:
        scores_array = np.asarray(scores_value, dtype=np.float64)
        if scores_array.shape != (n_features,) or not np.all(np.isfinite(scores_array)):
            raise ValueError("feature-axis selection_scores must be finite and match X")
        scores_digest = _array_digest(scores_array)
        if include_scores:
            scores = scores_array.tolist()

    units_value = getattr(feature_axis, "units", None)
    units = None if units_value is None else str(units_value)
    if units is not None and len(units) > _MAX_STRING_LENGTH:
        raise ValueError("feature-axis units are overlong")
    method = _bounded_text(
        getattr(feature_axis, "selection_method", None),
        field="feature_axis.selection_method",
        required=False,
    )
    return {
        "n_features": n_features,
        "values": values,
        "values_sha256": values_digest,
        "units": units,
        "selection_method": method,
        "include_mask": include_mask,
        "include_mask_sha256": include_mask_digest,
        "selection_scores": scores,
        "selection_scores_sha256": scores_digest,
    }


def _selection_audit_execute(
    X: Any,
    *,
    node_id: str,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    canonical = _canonical_audit_parameters(parameters)
    dataset = bind_X(X, missing_message="Selection audit requires X", allow_array=True)
    matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
    if not np.all(np.isfinite(matrix)):
        raise ValueError("Selection audit requires finite X values")

    history = get_processing_history(dataset)
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
        raise ValueError("processing history must be a sequence")
    if len(history) > _MAX_HISTORY_STEPS:
        raise ValueError("processing history exceeds the audit bound")
    steps = [
        record
        for ordinal, step in enumerate(history)
        if (record := _selection_step(step, source_ordinal=ordinal)) is not None
    ]
    if len(steps) > _MAX_SELECTION_STEPS:
        raise ValueError("selection history exceeds the audit bound")

    feature_axis = _feature_axis_record(
        dataset,
        include_scores=canonical["include_scores"],
        n_features=matrix.shape[1],
    )
    methods = [str(step["operation_id"]) for step in steps]
    report = {
        "schema_version": _REPORT_SCHEMA,
        "node_id": node_id,
        "parameters": canonical,
        "scope": "recorded_provenance_not_independent_scientific_verification",
        "timestamp_policy": "source_timestamps_omitted_for_determinism",
        "input_shape": list(matrix.shape),
        "input_matrix_sha256": _array_digest(matrix),
        "feature_axis": feature_axis,
        "selection_steps": steps,
        "selection_steps_sha256": _digest(steps),
        "n_selection_steps": len(steps),
        "methods_applied": methods,
        "total_provenance_steps": len(history),
    }
    report["report_sha256"] = _digest(report)
    if len(_canonical_json(report)) > _MAX_REPORT_BYTES:
        raise ValueError("selection audit report exceeds the output bound")
    verify_selection_audit_report(report)

    diagnostics = {
        "n_selection_steps": len(steps),
        "final_n_features": matrix.shape[1],
        "methods_applied": methods,
        "report_sha256": report["report_sha256"],
        "scope": report["scope"],
    }
    return {"X_out": dataset, "audit": report}, diagnostics


@register_node
class SelectionAuditNode(Node):
    """Project selection provenance into a closed, deterministic report."""

    metadata = NodeMetadata(
        node_type="selection.audit",
        category="selection",
        label="Audit Feature Selection",
        description=(
            "Record the exact selection provenance that produced this dataset; "
            "the report does not independently re-run or validate each selector"
        ),
        parameters=[
            NodeParameter(
                name="include_scores",
                label="Include Exact Scores",
                param_type="boolean",
                default=True,
                description=("Include finite per-feature scores when present; their digest is always recorded"),
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Selected Data",
                description="Dataset whose canonical selection provenance will be recorded",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_out",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Pass-through Data",
            ),
            PortMetadata(
                name="audit",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Closed Selection Audit",
                description="Digest-bound provenance record, not independent scientific verification",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="dict",
        diagnostics=["n_selection_steps", "final_n_features", "methods_applied", "report_sha256", "scope"],
        policy=NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="none",
            required_worker_capabilities=[WorkerCapability.READ_DATASET.value],
        ),
    )

    def generate_python(
        self,
        inputs: Mapping[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        parameters = self._resolve_params()
        return [
            f"{indent}# --- Canonical feature-selection audit ({self.node_id}) ---",
            (
                f"{indent}from spectra_sherpa.app.services.dag.nodes.selection.selection_audit_node "
                "import _selection_audit_execute"
            ),
            f"{indent}_audit_outputs, _audit_diagnostics = _selection_audit_execute(",
            f"{indent}    {X_expression}, node_id={self.node_id!r}, parameters={parameters!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _audit_outputs",
        ]

    async def execute(self, X: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        outputs, diagnostics = _selection_audit_execute(
            X,
            node_id=self.node_id,
            parameters=self._resolve_params(),
        )
        logger.info(
            "Selection audit: %s selection steps, %s final features, report=%s",
            diagnostics["n_selection_steps"],
            diagnostics["final_n_features"],
            diagnostics["report_sha256"],
        )
        return NodeResult(outputs=outputs, diagnostics=diagnostics)


bind_stable_execution_contract(
    SelectionAuditNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.selection.audit",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 268_435_456},
    license_id="Apache-2.0",
    help_reference="docs/nodes/selection-validation.md",
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(),
    deterministic=True,
    seed_parameter=None,
    target_access=TargetAccess.NONE,
    group_access="none",
)


__all__ = [
    "SelectionAuditNode",
    "_canonical_audit_parameters",
    "_selection_audit_execute",
    "verify_selection_audit_report",
]
