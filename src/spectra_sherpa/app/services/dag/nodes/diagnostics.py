"""
Diagnostics nodes for model validation and quality control.

These nodes provide statistical diagnostics, outlier detection,
and cross-validation metrics for chemometrics models.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)
from spectra_sherpa.app.lib.sherpa_dataset import EvaluationResult, SherpaDataset
from spectra_sherpa.app.services.dag import presentation_limits
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from spectra_sherpa.sdk import validate as regression_metric_registry

from .. import out_of_fold_evidence
from ..io_contracts import to_numpy_1d, to_numpy_2d
from ..node_base import Node, NodeMetadata, NodeParameter, NodePolicy, NodeResult, PortMetadata, register_node
from ..presentation_contract import NodePresentationContract, ScientificPresentation


def _unwrap_data(value: Any) -> Any:
    """Return raw numeric data for dataset-like inputs, otherwise passthrough."""
    if isinstance(value, SherpaDataset):
        return value.data
    # Avoid ndarray.data memoryview by checking ndarray first.
    if not isinstance(value, np.ndarray) and hasattr(value, "data"):
        try:
            return value.data
        except Exception:
            return value
    return value


def _canonical_cross_validation_parameters(parameters: Mapping[str, Any]) -> dict[str, str]:
    """Close the evaluator to the regression evidence its sole producer emits."""
    if parameters:
        raise ValueError("diagnostics.cross_validation accepts no parameters")
    return {"task_type": "regression"}


def _regression_oof_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    """Project registry-v2 metrics with explicit cross-validation aliases."""
    registered = regression_metric_registry.metrics(y_true, y_pred).as_dict()
    residuals = y_pred - y_true
    press = float(np.sum(residuals**2))
    r2 = registered["r2"]
    sep = registered["sep"]
    rer = registered["rer"]
    return {
        **registered,
        "rmsecv": registered["rmse"],
        "r2_cv": r2,
        "q2": r2,
        "r2_q2_status": "finite" if r2 is not None else "undefined_zero_reference_variance",
        "PRESS": press,
        "sep_status": "finite" if sep is not None else "undefined_single_sample",
        "rer_status": "finite" if rer is not None else "undefined_zero_or_missing_sep",
    }


def _cross_validation_execute(
    evidence: Any,
    *,
    node_id: str,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate one producer-bound out-of-fold record without refitting a model."""
    canonical = _canonical_cross_validation_parameters(parameters)
    normalized_evidence, observed, predicted, assignments = out_of_fold_evidence.validate_out_of_fold_evidence(evidence)
    if normalized_evidence["task_type"] != canonical["task_type"]:
        raise ValueError("cross-validation task_type does not match the bound out-of-fold evidence")
    folds = np.unique(assignments)

    observed = np.asarray(observed, dtype=np.float64)
    predicted = np.asarray(predicted, dtype=np.float64)
    if not np.isfinite(observed).all() or not np.isfinite(predicted).all():
        raise ValueError("regression observations and predictions must be finite")
    overall = _regression_oof_metrics(observed, predicted)
    fold_metrics = [
        {
            "fold_id": int(fold),
            **_regression_oof_metrics(observed[assignments == fold], predicted[assignments == fold]),
        }
        for fold in folds
    ]
    plots = {"true_vs_pred": np.column_stack((observed, predicted)).tolist()}
    diagnostics = {
        key: overall[key]
        for key in (
            "registry_version",
            "rmsecv",
            "mae",
            "r2_cv",
            "q2",
            "sep",
            "slope",
            "intercept",
            "rer",
            "bias",
        )
    }

    report = {
        "schema_version": "spectrasherpa-cross-validation-evaluation/3",
        "node_id": node_id,
        "task_type": canonical["task_type"],
        "scope": "producer_bound_out_of_fold_evidence_not_model_refitting",
        "n_samples": int(observed.size),
        "n_folds": int(folds.size),
        "evidence_sha256": normalized_evidence["evidence_sha256"],
        "producer": dict(normalized_evidence["producer"]),
        "split_plan_digest": normalized_evidence["split_plan_digest"],
        "fold_metrics": fold_metrics,
        "overall_metrics": overall,
    }
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    outputs = {
        "cv_metrics": report,
        "observations": observed.tolist(),
        "predictions": predicted.tolist(),
        "fold_assignments": assignments.tolist(),
        "plots": plots,
    }
    diagnostics.update({"n_samples": int(observed.size), "n_folds": int(folds.size), "scope": report["scope"]})
    return outputs, diagnostics


def verify_cross_validation_report(
    report: Mapping[str, Any],
    evidence: Any,
) -> dict[str, Any]:
    """Recompute the complete report from its indivisible source evidence."""
    expected_fields = {
        "schema_version",
        "node_id",
        "task_type",
        "scope",
        "n_samples",
        "n_folds",
        "evidence_sha256",
        "producer",
        "split_plan_digest",
        "fold_metrics",
        "overall_metrics",
        "report_sha256",
    }
    if set(report) != expected_fields:
        raise ValueError("cross-validation report fields do not match the closed schema")
    if report.get("schema_version") != "spectrasherpa-cross-validation-evaluation/3":
        raise ValueError("unsupported cross-validation report schema")
    node_id = report.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        raise ValueError("cross-validation report node_id must be non-empty")
    expected, _ = _cross_validation_execute(
        evidence,
        node_id=node_id,
        parameters={},
    )
    if dict(report) != expected["cv_metrics"]:
        raise ValueError("cross-validation report does not match recomputed metrics")
    return dict(report)


def _canonical_outlier_parameters(parameters: Mapping[str, Any]) -> dict[str, float]:
    if set(parameters) - {"confidence_level"}:
        raise ValueError("diagnostics.outliers accepts only confidence_level")
    raw = parameters.get("confidence_level", 0.95)
    if isinstance(raw, bool):
        raise ValueError("confidence_level must be a finite number in [0.80, 0.999]")
    try:
        confidence = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence_level must be a finite number in [0.80, 0.999]") from exc
    if not np.isfinite(confidence) or not 0.80 <= confidence <= 0.999:
        raise ValueError("confidence_level must be a finite number in [0.80, 0.999]")
    return {"confidence_level": confidence}


def _outlier_dispatch(pca_result: Any, *, confidence_level: Any = 0.95) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate one fitted PCA result through the sole outlier authority.

    Hotelling T-squared uses the true PCA eigenvalues supplied by the PCA
    producer. Q/SPE is measured in the exact fitted feature space. The Q
    threshold is deliberately an empirical calibration-set quantile; it is
    not presented as an independent or theoretical confidence limit.
    """

    presentation_limits.require_bounded_presentation(pca_result, surface="PCA outlier diagnostics", max_values=500_000)
    confidence = _canonical_outlier_parameters({"confidence_level": confidence_level})["confidence_level"]
    if not isinstance(pca_result, Mapping):
        raise ValueError("input must be a fitted PCA decomposition result")
    required = {"model", "scores", "n_components", "n_observations", "eigenvalues", "_internal"}
    missing = sorted(required - set(pca_result))
    if missing:
        raise ValueError(f"PCA decomposition result is missing required fields: {', '.join(missing)}")

    model = pca_result["model"]
    scores = to_numpy_2d(_unwrap_data(pca_result["scores"]), name="scores", dtype=np.float64)
    eigenvalues = to_numpy_1d(_unwrap_data(pca_result["eigenvalues"]), name="eigenvalues", dtype=np.float64)
    if not np.isfinite(scores).all() or not np.isfinite(eigenvalues).all():
        raise ValueError("PCA scores and eigenvalues must be finite")

    n_components = int(pca_result["n_components"])
    n_observations = int(pca_result["n_observations"])
    if scores.shape != (n_observations, n_components):
        raise ValueError("PCA scores shape must match n_observations and n_components")
    if eigenvalues.shape != (n_components,) or np.any(eigenvalues <= 0.0):
        raise ValueError("PCA eigenvalues must contain one finite positive value per component")
    if n_components < 1 or n_observations <= n_components:
        raise ValueError("Hotelling T-squared requires n_observations greater than n_components")

    from scipy.stats import f

    t2 = np.sum((scores**2) / eigenvalues, axis=1)
    f_critical = float(f.ppf(confidence, n_components, n_observations - n_components))
    t2_limit = float(
        (n_components * (n_observations - 1) * (n_observations + 1))
        / (n_observations * (n_observations - n_components))
        * f_critical
    )
    if not np.isfinite(t2).all() or not np.isfinite(t2_limit):
        raise ValueError("Hotelling T-squared calculation produced a non-finite result")

    internal = pca_result["_internal"]
    if not isinstance(internal, Mapping) or internal.get("input_data") is None:
        raise ValueError("PCA decomposition result is missing fitted-space input data required for Q/SPE")
    input_matrix = to_numpy_2d(_unwrap_data(internal["input_data"]), name="input_data", dtype=np.float64)
    if not np.isfinite(input_matrix).all():
        raise ValueError("PCA fitted-space input data must be finite")

    from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import pca_q_residuals_in_fitted_space

    if input_matrix.shape[0] != n_observations:
        raise ValueError("PCA fitted-space input must have the declared sample shape")
    q = pca_q_residuals_in_fitted_space(input_matrix, scores, model)
    q_limit = float(np.quantile(q, confidence))
    flags = (t2 > t2_limit) | (q > q_limit)
    outlier_indices = np.flatnonzero(flags).tolist()
    score_dataset = pca_result.get("scores")
    sample_labels: list[str] = []
    if isinstance(score_dataset, SherpaDataset):
        sample_axis = score_dataset.get_observation_axis()
        raw_labels = getattr(sample_axis, "labels", None) if sample_axis is not None else None
        if raw_labels is not None and len(raw_labels) == n_observations:
            sample_labels = [str(value) for value in raw_labels]
    outlier_sample_labels = [sample_labels[index] for index in outlier_indices] if sample_labels else []
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(t2, dtype="<f8").tobytes())
    digest.update(np.ascontiguousarray(q, dtype="<f8").tobytes())
    digest.update(f"{confidence:.17g}".encode("ascii"))

    evaluation = EvaluationResult(
        evaluation_id=f"outlier-{digest.hexdigest()[:24]}",
        model_type="PCA",
        outlier_indices=outlier_indices,
        outlier_percentage=float(100.0 * len(outlier_indices) / n_observations),
        hotelling_t2=t2.tolist(),
        q_residuals=q.tolist(),
        t2_limit=t2_limit,
        q_limit=q_limit,
    )
    outputs = {
        "model": pca_result,
        "flags": flags.tolist(),
        "T2": t2.tolist(),
        "Q": q.tolist(),
        "T2_limit": t2_limit,
        "Q_limit": q_limit,
        "outliers": flags.tolist(),
        "outlier_indices": outlier_indices,
        "sample_labels": sample_labels,
        "outlier_sample_labels": outlier_sample_labels,
        "n_outliers": len(outlier_indices),
        "confidence_level": confidence,
        "data": t2.tolist(),
        "evaluation": evaluation,
        "metadata": {
            "type": "OutlierDetection",
            "output_type": "diagnostics",
            "n_outliers": len(outlier_indices),
            "outlier_percentage": float(100.0 * len(outlier_indices) / n_observations),
            "T2_limit": t2_limit,
            "Q_limit": q_limit,
            "Q_mean": float(np.mean(q)),
            "q_residual_space": "preprocessed_model_space",
            "q_limit_method": "empirical_calibration_quantile",
        },
    }
    diagnostics = {
        "n_outliers": len(outlier_indices),
        "outlier_percentage": float(100.0 * len(outlier_indices) / n_observations),
        "confidence_level": confidence,
        "t2_limit": t2_limit,
        "t2_limit_method": "nomikos_macgregor_f_distribution",
        "q_limit": q_limit,
        "q_residual_space": "preprocessed_model_space",
        "q_limit_method": "empirical_calibration_quantile",
        "method": "hotelling_t2_q",
        "sample_labels": sample_labels,
        "outlier_sample_labels": outlier_sample_labels,
    }
    return outputs, diagnostics


@register_node
class OutlierDetectionNode(Node):
    """
    Outlier Detection node using Hotelling T² and Q statistics.

    Identifies outlier samples based on PCA model diagnostics.
    Uses Hotelling T² (distance in model space) and Q residuals (distance to model).

    Critical for quality control in pharmaceutical and process industries.

    Reference: Nomikos & MacGregor (1995), Technometrics
    """

    metadata = NodeMetadata(
        node_type="diagnostics.outliers",
        category="validation",
        label="Detect Outliers",
        description=(
            "Identifies samples that deviate from the PCA model using Hotelling T² (distance within "
            "model space) and Q/SPE residuals (distance to model). "
            "Connect directly to a PCA node output — eigenvalues from the PCA model are required to "
            "compute correct T² control limits (Nomikos & MacGregor 1995). "
            "Hotelling T² uses the selected confidence level; the Q/SPE boundary is the corresponding "
            "quantile of the fitted calibration samples and is a screening aid, not independent validation."
        ),
        parameters=[
            NodeParameter(
                name="confidence_level",
                label="Confidence Level",
                param_type="number",
                default=0.95,
                min_value=0.80,
                max_value=0.999,
                max_value_reason=("Keeps the F-distribution limit finite and bounds unstable extreme-tail screening"),
                step=0.01,
                description=(
                    "Confidence level for the Hotelling T² limit and calibration-set quantile used to screen Q/SPE"
                ),
                required=True,
            ),
        ],
        input_types=["dict"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="PCA Diagnostic State",
                description="Typed fitted PCA state emitted by Fit PCA Transform",
            ),
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_outlier_parameters,
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="PCA Model",
                description="Original model with outlier flags",
            ),
            PortMetadata(
                name="flags",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Outlier Flags",
                description="Boolean mask (True=Outlier)",
            ),
            PortMetadata(
                name="T2",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Hotelling T²",
                description="T² statistics for each sample",
            ),
            PortMetadata(
                name="Q",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Q Residuals",
                description="Q (SPE) statistics for each sample",
            ),
        ],
        presentation_contract=NodePresentationContract(
            default_presentation="diagnostics",
            presentations=(
                ScientificPresentation(
                    "diagnostics",
                    "T² vs Q Diagnostics",
                    "t2_q_diagnostics",
                    ("T2", "Q", "flags"),
                    ("plot", "table"),
                    "Per-sample model distance, residual distance, screening limits, and outlier decisions.",
                ),
            ),
        ),
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for outlier detection.

        Emits code that computes Hotelling T² and Q residuals from a PCA
        model dict (scores + eigenvalues).  Both SCP and pure-numpy modes
        use the same numpy-only path since the computation is independent of
        the PCA backend.
        """
        input_expr = inputs.get("default", "input_data")
        params = self._resolve_params()
        return [
            f"{indent}# --- Canonical PCA outlier evaluation ({self.node_id}) ---",
            (f"{indent}from spectra_sherpa.app.services.dag.nodes.diagnostics import _outlier_dispatch"),
            f"{indent}_outlier_outputs, _outlier_diagnostics = _outlier_dispatch(",
            f"{indent}    {input_expr}, **{params!r}",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _outlier_outputs",
        ]

    async def execute(self, pca_model: Any) -> Any:
        """
        Execute outlier detection on PCA model.

        Args:
            pca_model: PCA model output from PCANode

        Returns:
            Dict containing outlier flags and statistics
        """
        result, diagnostics = _outlier_dispatch(pca_model, **self._resolve_params())

        logger.debug(
            "[Outlier Detection] Found %s outliers (%.1f%%) at %.1f%% confidence",
            result["n_outliers"],
            result["metadata"]["outlier_percentage"],
            result["confidence_level"] * 100.0,
        )

        return NodeResult(
            outputs=result,
            diagnostics=diagnostics,
        )


bind_stable_execution_contract(
    OutlierDetectionNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.EVALUATOR,
    implementation_id="spectrasherpa.diagnostics.outliers",
    implementation_modules=(presentation_limits,),
    implementation_version="1.0.2",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/selection-validation.md",
    implementation_distributions=("numpy", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1")),
    deterministic=True,
    target_access="none",
    group_access="none",
    citations=("Nomikos and MacGregor, Technometrics 37 (1995) 41-59",),
)


@register_node
class CrossValidationNode(Node):
    """
    Evaluate predictions that an upstream authority produced out of fold.

    This node never fits or splits a model.  Its one input binds observations,
    predictions, fold assignments, the exact split plan, and the current
    canonical producer identity before any metric is reported.
    """

    metadata = NodeMetadata(
        node_type="diagnostics.cross_validation",
        category="validation",
        label="Evaluate Out-of-Fold Predictions",
        description=(
            "Summarizes one producer-bound regression out-of-fold evidence record. Reports per-fold and "
            "overall metrics; it does not split data or refit a model."
        ),
        parameters=[],
        input_types=["dict"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="evidence",
                type_ref=out_of_fold_evidence.OUT_OF_FOLD_EVIDENCE_TYPE,
                required=True,
                label="Out-of-Fold Evidence",
                description=(
                    "Indivisible observations, predictions, assignments, split plan, and canonical producer binding"
                ),
            ),
        ],
        output_ports=[
            PortMetadata(
                name="cv_metrics",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="CV Metrics",
                description=(
                    "Registry-v2 regression performance metrics, including RMSECV, SEP, slope, intercept, and RER"
                ),
            ),
            PortMetadata(
                name="observations",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Observed Values",
                description="Validated reference values used to recompute the report",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Reported Predictions",
                description="Predictions extracted from the already validated evidence for display",
            ),
            PortMetadata(
                name="fold_assignments",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Reported Fold Assignments",
                description="Fold identifiers extracted from the already validated evidence for display",
            ),
            PortMetadata(
                name="plots",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=False,
                label="Plots",
                description="Bound plotting data derived from the supplied out-of-fold evidence",
            ),
        ],
        diagnostics=["n_samples", "n_folds", "scope"],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_cross_validation_parameters,
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate the same closed out-of-fold evaluator used by the live DAG."""
        evidence_expr = inputs.get("evidence", inputs.get("default", "oof_evidence"))
        return [
            f"{indent}# --- Canonical out-of-fold evaluation ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.diagnostics import _cross_validation_execute",
            f"{indent}_cv_outputs, _cv_diagnostics = _cross_validation_execute(",
            f"{indent}    {evidence_expr},",
            f"{indent}    node_id={self.node_id!r}, parameters={self._resolve_params()!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _cv_outputs",
        ]

    async def execute(
        self,
        evidence: Any = None,
        **kwargs: Any,
    ) -> NodeResult:
        """Evaluate one bound out-of-fold evidence record."""
        del kwargs
        if evidence is None:
            raise ValueError("out-of-fold evidence is required")
        outputs, diagnostics = _cross_validation_execute(
            evidence,
            node_id=self.node_id,
            parameters=self._resolve_params(),
        )
        logger.info(
            "Out-of-fold evaluation: task=%s samples=%s folds=%s",
            "regression",
            diagnostics["n_samples"],
            diagnostics["n_folds"],
        )
        return NodeResult(outputs=outputs, diagnostics=diagnostics)


bind_stable_execution_contract(
    CrossValidationNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.EVALUATOR,
    implementation_id="spectrasherpa.diagnostics.cross_validation",
    implementation_version="3.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/selection-validation.md",
    implementation_modules=(out_of_fold_evidence, regression_metric_registry),
    implementation_distributions=("numpy", "scipy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
    citations=(
        "mdatools cross-validation of a regression model, "
        "https://search.r-project.org/CRAN/refmans/mdatools/html/crossval.regmodel.html",
    ),
    deterministic=True,
    target_access="required",
    group_access="none",
)
