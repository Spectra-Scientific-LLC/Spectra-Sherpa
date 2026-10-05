"""
Regression nodes: PCR, SVR, Linear Regression.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

import numpy as np

from spectra_sherpa.app.lib import fitted_state
from spectra_sherpa.app.lib.fitted_state import LinearRegressionExtract, PCRExtract, SVRExtract
from spectra_sherpa.app.lib.sherpa_dataset import (
    EvaluationResult,
    TargetContext,
)
from spectra_sherpa.app.services.dag.meta_helpers import (
    add_processing_step,
    copy_processing_history,
    inherit_origin_flags,
    inherit_sample_flags,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    TargetAccess,
    WorkerCapability,
)

from ...io_contracts import (
    attach_evaluation,
    bind_X,
    bind_y,
    clean_regression_target_with_population,
    resolve_target_names,
    to_numpy_2d,
    to_numpy_y,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from . import _artifact_builder, regression_application
from .core_utils import (
    create_spectral_dataset as _create_spectral_dataset,
)
from .core_utils import (
    is_sequential_numeric as _is_sequential_numeric,
)
from .core_utils import (
    make_safe_coord as _make_safe_coord,
)

logger = logging.getLogger(__name__)

from sklearn.linear_model import LinearRegression
from sklearn.svm import SVR

from ...spec_nodes import EstimatorSpec, EstimatorSpecNode


def _as_target_matrix(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim == 1:
        return arr.reshape(-1, 1)
    return arr


def _target_metric_lists(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[list[float | None], list[float]]:
    from spectra_sherpa.sdk.validate import metrics

    observed, predicted = _as_target_matrix(y_true), _as_target_matrix(y_pred)
    records = [metrics(observed[:, i], predicted[:, i]) for i in range(observed.shape[1])]
    return [record.r2 for record in records], [record.rmse for record in records]


def _omit_multitarget_summaries(record: dict[str, Any]) -> None:
    """Keep per-response records; never combine dimensional response errors."""
    for key in ("r2", "rmse", "r2_cal", "rmse_cal", "score"):
        record.pop(key, None)
    record["metric_summary_scope"] = "per_response_only"
    # Explicit producer-owned containers, not arbitrary recursive payloads.
    for key in ("quality_summary", "metrics"):
        child = record.get(key)
        if isinstance(child, dict):
            _omit_multitarget_summaries(child)


def _target_names_from_context(X_ds, n_targets: int, params: dict[str, Any] | None = None) -> list[str]:
    params = params or {}
    selected_name = params.get("_selected_target_name")
    if selected_name:
        return [str(selected_name)]
    tc = getattr(X_ds, "target_context", None)
    if tc is not None and tc.target_names and len(tc.target_names) == n_targets:
        return [str(name) for name in tc.target_names]
    if tc is not None and tc.target_name and n_targets == 1:
        return [str(tc.target_name)]
    return [f"Target {idx + 1}" for idx in range(n_targets)]


def _target_identity_metadata(X_ds, target_names: list[str]) -> dict[str, Any]:
    tc = getattr(X_ds, "target_context", None)
    selected = getattr(tc, "selected_target", None) if tc is not None else None
    metadata: dict[str, Any] = {"target_names": target_names}
    if selected:
        metadata["target_mode"] = "single"
        metadata["selected_target"] = str(selected)
    elif target_names:
        metadata["target_mode"] = "multi" if len(target_names) > 1 else "single"
        if len(target_names) == 1:
            metadata["selected_target"] = target_names[0]
    target_type = getattr(tc, "target_type", None) if tc is not None else None
    if target_type:
        metadata["target_type"] = str(target_type)
    target_units = getattr(tc, "target_units", None) if tc is not None else None
    if target_units:
        metadata["target_units"] = str(target_units)
    return metadata


def _regression_response_context(X_ds: Any, y_raw: Any) -> TargetContext:
    """Identify the actual bound values, never an external dataset's own target."""
    if y_raw is None:
        context = X_ds.target_context
        return context.model_copy(update={"target_names": resolve_target_names(None, X_ds) or []})
    axis = getattr(y_raw, "feature_axis", None)
    names = list(axis.labels) if axis is not None and axis.labels else None
    units = getattr(y_raw, "units", None)
    context = getattr(y_raw, "target_context", None) if getattr(y_raw, "target", None) is None else None
    if context is not None:
        declared_names = list(context.target_names or [])
        if not declared_names and (context.selected_target or context.target_name):
            declared_names = [context.selected_target or context.target_name]
        if names and declared_names and names != declared_names:
            raise ValueError("response data columns contradict target-context names")
        if units and context.target_units and units != context.target_units:
            raise ValueError("response data units contradict target-context units")
        names = names or declared_names
        units = units or context.target_units
    return TargetContext(
        target_type=context.target_type if context is not None else None,
        target_names=names or [],
        target_units=units,
    )


def _response_input_columns(X_ds: Any, y_raw: Any, n_targets: int) -> list[int]:
    """Map the bound response columns back to the supplied response source."""
    if y_raw is None and X_ds.target is not None:
        context = X_ds.target_context
        if np.asarray(X_ds.target).ndim == 2 and context.selected_target:
            return [list(context.target_names).index(context.selected_target)]
    return list(range(n_targets))


def _bind_continuous_response_context(
    X_ds: Any,
    y_raw: Any,
    *,
    n_targets: int,
) -> None:
    """Bind the response actually fitted to the copied predictor dataset.

    An explicitly connected ``y`` is the scientific authority for response
    identity.  Predictor metadata is only a fallback when the response carries
    no metadata of its own.  The caller passes a copied ``X_ds`` so this helper
    cannot enrich or rewrite the scientist's source dataset.
    """

    context = _regression_response_context(X_ds, y_raw)
    target_type = context.target_type
    if target_type not in {None, "continuous"}:
        raise ValueError(f"regression requires continuous targets, got {target_type!r}")
    names = list(context.target_names or [])
    if names and len(names) != n_targets:
        raise ValueError(
            "connected response metadata must name every fitted target exactly once: "
            f"received {len(names)} name(s) for {n_targets} response column(s)"
        )
    if not names:
        names = [f"Target {index + 1}" for index in range(n_targets)]
    units = context.target_units
    if n_targets == 1:
        selected = str(names[0])
        X_ds.target_context = TargetContext(
            target_type="continuous",
            target_name=selected,
            target_names=[selected],
            target_units=str(units) if units else None,
            selected_target=selected,
        )
    else:
        X_ds.target_context = TargetContext(
            target_type="continuous",
            target_names=[str(name) for name in names],
            target_units=str(units) if units else None,
        )


def _canonical_pcr_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the closed scientist-visible Principal Components Regression choices."""

    if set(parameters) != {"n_components", "scale"}:
        raise ValueError("PCR parameters must contain exactly n_components and scale")
    components = parameters["n_components"]
    if isinstance(components, bool) or not isinstance(components, (int, float)) or int(components) != components:
        raise ValueError("PCR n_components must be a positive whole number")
    if int(components) < 1:
        raise ValueError("PCR n_components must be a positive whole number")
    if not isinstance(parameters["scale"], bool):
        raise ValueError("PCR scale must be boolean")
    return {"n_components": int(components), "scale": parameters["scale"]}


@register_node
class PCRNode(Node):
    """
    Principal Component Regression (PCR) node.

    Performs PCA followed by linear regression on the scores.
    """

    metadata = NodeMetadata(
        node_type="model.pcr",
        category="regression",
        label="Train PCR Regression",
        description=(
            "Fit ordinary least squares to retained PCA scores. Predictors are always centered by PCA; "
            "optional autoscaling standardizes them to unit variance first."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=3,
                min_value=1,
                step=1,
                description="Number of PCA components for regression",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="scale",
                label="Autoscale Predictors",
                param_type="boolean",
                default=True,
                description="Scale each predictor to unit variance before the PCA centering step.",
                required=False,
                category="basic",
            ),
        ],
        input_types=["SherpaDataset", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Data Matrix (X)",
                description="Spectral data or multivariate feature table (n_samples × n_variables)",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Targets (y)",
                description="Target values — optional if dataset has embedded target",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="population",
                type_ref="spectrasherpa://types/RegressionPopulation/1.0",
                required=True,
                label="Training population",
                description="Original row identities, admitted rows and missing-reference exclusions",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/RegressionModel/1.0",
                required=True,
                label="Fitted PCR Regression Model",
                description="Fitted PCR regression model produced by this training node",
            ),
            PortMetadata(
                name="scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="Scores",
                description="PCA Scores (n_samples × n_components)",
            ),
            PortMetadata(
                name="loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="Loadings",
                description="PCA Loadings (n_components × n_features)",
            ),
            PortMetadata(
                name="y_pred",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Training Predictions",
                description="In-sample training predictions for calibration diagnostics",
            ),
            PortMetadata(
                name="y_true",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Training Targets",
                description="Training target values aligned with y_pred",
            ),
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_pcr_parameters,
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python that calls the same PCR operation as the live DAG."""
        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        return [
            f"{indent}# --- Canonical Principal Components Regression ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes import _pcr_execute",
            f"{indent}_pcr_result = _pcr_execute(",
            f"{indent}    {X_expression}, {inputs.get('y', 'None')},",
            f"{indent}    node_id={self.node_id!r}, parameters={self._resolve_params()!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _pcr_result.outputs",
        ]

    def _execute_sync(self, X: Any = None, y: Any = None) -> NodeResult:
        """
        Execute PCR regression.

        Args:
            X: Dataset containing spectral data (predictors)
            y: Target values (concentrations)

        Returns:
            PCR model with regression results
        """
        from sklearn.decomposition import PCA as SkPCA
        from sklearn.linear_model import LinearRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (spectra)",
            dataset_error_message="X must be an dataset object",
            allow_array=True,
        ).copy()
        source_digest = X_ds.scientific_digest
        response_source = y

        y_value = bind_y(
            y,
            X=X_ds,
            required=True,
            infer_from_X=True,
            dataset_as_data=True,
            missing_message=(
                "No target values found. Either:\n"
                "  1. Use a data source with embedded targets (e.g., Corn M5, sklearn)\n"
                "  2. Connect target values to the 'y' input port\n"
                "  3. Use 'Attach Target' node to add targets to your dataset"
            ),
        )

        X_data = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = to_numpy_y(y_value, name="y", expected_samples=X_data.shape[0], dtype=np.float64)
        response_columns = _response_input_columns(X_ds, response_source, _as_target_matrix(y_array).shape[1])
        _bind_continuous_response_context(X_ds, response_source, n_targets=_as_target_matrix(y_array).shape[1])
        X_ds, y_array, population = clean_regression_target_with_population(
            X_ds,
            y_array,
            model_label="PCR",
            source_scientific_digest=source_digest,
            response_input_columns=response_columns,
            preserve_1d=False,
        )
        X_data = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_matrix = _as_target_matrix(y_array)

        parameters = _canonical_pcr_parameters(self._resolve_params())
        n_components = int(parameters["n_components"])
        scale = bool(parameters["scale"])

        max_components = min(X_data.shape[0] - 1, X_data.shape[1])
        if n_components > max_components:
            raise ValueError(
                f"n_components must be <= min(n_samples - 1, n_features). Got {n_components} with max {max_components}."
            )

        logger.debug("[PCR Node] Executing with:")
        logger.debug("  - n_components: %s", n_components)
        logger.debug("  - scale: %s", scale)
        logger.debug("  - X shape: %s", X_data.shape)
        logger.debug("  - y shape: %s", y_array.shape)

        scaler = StandardScaler(with_mean=scale, with_std=scale)
        # ``auto`` selects randomized SVD for sufficiently wide matrices. PCR
        # is a deterministic canonical operation, so use the exact full SVD.
        pca = SkPCA(n_components=n_components, svd_solver="full")
        regressor = LinearRegression()
        model = Pipeline(
            [
                ("scaler", scaler),
                ("pca", pca),
                ("regressor", regressor),
            ]
        )
        model.fit(X_data, y_array)

        y_pred = model.predict(X_data)
        y_pred_matrix = _as_target_matrix(y_pred)
        r2_per_target, rmse_per_target = _target_metric_lists(y_matrix, y_pred_matrix)
        r2 = r2_per_target[0] if y_matrix.shape[1] == 1 else None
        rmse = rmse_per_target[0] if y_matrix.shape[1] == 1 else None

        X_scores = model.named_steps["pca"].transform(model.named_steps["scaler"].transform(X_data))

        # Extract label_categories for categorical coloring
        label_categories = None
        _y_coord = X_ds.sample_axis
        if _y_coord is not None:
            try:
                if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, "tolist") else list(_y_coord.labels)
                    label_categories = sorted(set(str(l) for l in raw))
                elif hasattr(_y_coord, "data") and _y_coord.data is not None:
                    raw = _y_coord.data.tolist() if hasattr(_y_coord.data, "tolist") else list(_y_coord.data)
                    str_labels = [str(l) for l in raw]
                    unique = sorted(set(str_labels))
                    if len(unique) < 20 and not _is_sequential_numeric(raw):
                        label_categories = unique
            except Exception:
                label_categories = None

        # Get input coordinates for SherpaDataset creation
        _x_coord = X_ds.feature_axis

        # Build PC labels with explained variance ratio
        evr = pca.explained_variance_ratio_
        pc_labels = [f"PC{i + 1} ({evr[i] * 100:.1f}%)" for i in range(n_components)]

        # =====================================================================
        # Create proper SherpaDataset objects for scores and loadings with coordinate coupling
        # =====================================================================

        # Scores: shape (n_samples, n_components)
        scores_dataset = _create_spectral_dataset(
            data=X_scores,
            x_coord=_make_safe_coord(pc_labels, title="Principal Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="score",
            title="PCR Scores",
        )

        # Loadings: shape (n_components, n_features)
        loadings_dataset = _create_spectral_dataset(
            data=pca.components_,
            x_coord=_x_coord,
            y_coord=_make_safe_coord(pc_labels, title="Principal Component"),
            units="loading",
            title="PCR Loadings",
        )

        # Add processing history to SherpaDataset outputs
        copy_processing_history(X_ds, scores_dataset)
        copy_processing_history(X_ds, loadings_dataset)
        add_processing_step(
            scores_dataset,
            "model.pcr.scores",
            {"n_components": n_components},
            node_id=self.node_id,
        )
        add_processing_step(
            loadings_dataset,
            "model.pcr.loadings",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Propagate dataset-level flags. Scores rows are samples;
        # loadings rows are principal components — origin tags only.
        inherit_sample_flags(X_ds, scores_dataset)
        inherit_origin_flags(X_ds, scores_dataset)
        inherit_origin_flags(X_ds, loadings_dataset)

        target_names = _target_names_from_context(X_ds, y_matrix.shape[1])
        target_identity = _target_identity_metadata(X_ds, target_names)
        intercept_values = np.asarray(regressor.intercept_, dtype=np.float64).reshape(-1)
        intercept: float | list[float]
        intercept = float(intercept_values[0]) if intercept_values.size == 1 else intercept_values.tolist()

        # Store only scientific metadata that coordinates can't carry
        scores_dataset.meta.update(
            {
                "n_components": n_components,
                "n_samples": int(X_data.shape[0]),
                "n_features": int(X_data.shape[1]),
                "n_targets": int(y_matrix.shape[1]),
                "training_X_shape": [int(X_data.shape[0]), int(X_data.shape[1])],
                "training_y_shape": [int(y_matrix.shape[0]), int(y_matrix.shape[1])],
                "output_dimensions": {
                    "training_X": [int(X_data.shape[0]), int(X_data.shape[1])],
                    "training_y": [int(y_matrix.shape[0]), int(y_matrix.shape[1])],
                    "scores": list(scores_dataset.shape),
                    "loadings": list(loadings_dataset.shape),
                    "y_pred": list(y_pred_matrix.shape),
                    "y_true": list(y_matrix.shape),
                },
                "explained_variance_ratio": evr.tolist(),
                "label_categories": label_categories,
                "r2": r2,
                "rmse": rmse,
                "coef": regressor.coef_.tolist(),
                "intercept": intercept,
                "y_pred": y_pred_matrix.tolist(),
                "y_true": y_matrix.tolist(),
                **target_identity,
                "r2_per_target": r2_per_target,
                "rmse_per_target": rmse_per_target,
                "quality_summary": {
                    "n_components": int(n_components),
                    "r2": r2,
                    "rmse": rmse,
                    "n_samples": int(X_data.shape[0]),
                    "n_features": int(X_data.shape[1]),
                    "n_targets": int(y_matrix.shape[1]),
                    **target_identity,
                    "explained_variance_ratio": evr.tolist(),
                },
                "evidence_scope": "training_fit_only_not_predictive_validation",
            }
        )
        evaluation_digest = hashlib.sha256()
        evaluation_digest.update(np.asarray(X_data, dtype="<f8").tobytes(order="C"))
        evaluation_digest.update(np.asarray(y_matrix, dtype="<f8").tobytes(order="C"))
        evaluation_digest.update(f"{self.node_id}:{n_components}:{int(scale)}".encode("utf-8"))
        attach_evaluation(
            scores_dataset,
            EvaluationResult(
                evaluation_id=str(uuid.uuid5(uuid.NAMESPACE_OID, evaluation_digest.hexdigest())),
                model_type="PCR",
                n_components=n_components,
                r2=r2,
                rmse=rmse,
            ),
        )

        logger.debug("[PCR Node] Scores shape: %s, Loadings shape: %s", scores_dataset.shape, loadings_dataset.shape)

        from ._artifact_builder import build_model_artifact

        evidence_scope = "training_fit_only_not_predictive_validation"
        artifact = build_model_artifact(
            PCRExtract.from_sklearn(model),
            X_ds,
            node_id=self.node_id,
            metrics={
                "scope": evidence_scope,
                "r2_cal": r2,
                "rmse_cal": rmse,
                "per_target": [
                    {
                        "target_name": name,
                        "r2_cal": target_r2,
                        "rmse_cal": target_rmse,
                    }
                    for name, target_r2, target_rmse in zip(
                        target_names,
                        r2_per_target,
                        rmse_per_target,
                        strict=True,
                    )
                ],
            },
        )
        artifact["metadata"]["fitted_parameters"] = {
            "n_components": n_components,
            "scale": scale,
        }
        artifact["metadata"]["metrics_scope"] = evidence_scope
        artifact["metadata"]["population"] = population
        scores_dataset.meta["population"] = population

        result = NodeResult(
            outputs={
                "default": scores_dataset,  # SherpaDataset: scores + sample labels (y) + PC coords (x)
                "scores": scores_dataset,  # Alias of default for the declared scores port
                "loadings": loadings_dataset,  # SherpaDataset: loadings + wavenumbers (x) + PC coords (y)
                "model": model,  # Legacy estimator; applications use the portable state below.
                "fitted_state": regression_application.make_application_state(
                    artifact, X_ds, response_source, operation="model.pcr", targets=y_matrix.shape[1]
                ),
                "y_pred": y_pred_matrix,
                "y_true": y_matrix,
                "_model_artifact": artifact,
                "population": population,
            },
            diagnostics={
                "population": population,
                "r2": r2,
                "rmse": rmse,
                "r2_per_target": r2_per_target,
                "rmse_per_target": rmse_per_target,
                "evidence_scope": "training_fit_only_not_predictive_validation",
            },
        )

        if y_matrix.shape[1] > 1:
            _omit_multitarget_summaries(scores_dataset.meta)
            _omit_multitarget_summaries(artifact["metadata"])
            _omit_multitarget_summaries(result.diagnostics)
        return result

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        return _pcr_execute(X, y, node_id=self.node_id, parameters=self._resolve_params())

    def fit_fitted_state(self, input_data: Any, target: Any) -> dict[str, object]:
        """Fit and serialize the exact PCR state consumed by fold execution."""

        result = self._execute_sync(input_data, target)
        model = result.outputs["model"]
        extracted = PCRExtract.from_sklearn(model)
        matrix = to_numpy_2d(bind_X(input_data, allow_array=True), name="input_data", dtype=np.float64)
        coefficient_matrix = np.asarray(extracted.reg_coef, dtype=np.float64)
        targets = 1 if coefficient_matrix.ndim == 1 else int(coefficient_matrix.shape[0])
        parameters = _canonical_pcr_parameters(self._resolve_params())
        return {
            "serializer": "spectrasherpa.model-artifact.pcr/1",
            "n_components": extracted.n_components,
            "scale": parameters["scale"],
            "reference_samples": result.outputs["population"]["admitted_count"],
            "features": int(matrix.shape[1]),
            "targets": targets,
            "pca_components": extracted.pca_components.tolist(),
            "pca_mean": extracted.pca_mean.tolist(),
            "reg_coef": extracted.reg_coef.tolist(),
            "reg_intercept": extracted.reg_intercept.tolist(),
            "scaler_mean": None if extracted.scaler_mean is None else extracted.scaler_mean.tolist(),
            "scaler_scale": None if extracted.scaler_scale is None else extracted.scaler_scale.tolist(),
        }

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        """Apply only the closed, dimension-checked PCR serializer schema."""

        from collections.abc import Mapping

        required = {
            "serializer",
            "n_components",
            "scale",
            "reference_samples",
            "features",
            "targets",
            "pca_components",
            "pca_mean",
            "reg_coef",
            "reg_intercept",
            "scaler_mean",
            "scaler_scale",
        }
        if not isinstance(state, Mapping) or set(state) != required:
            raise ValueError("PCR fitted state does not use the closed serializer schema")
        if state["serializer"] != "spectrasherpa.model-artifact.pcr/1":
            raise ValueError("PCR fitted state has an unsupported serializer")
        for name in ("n_components", "reference_samples", "features", "targets"):
            value = state[name]
            if type(value) is not int or value < 1:
                raise ValueError(f"PCR fitted state has invalid {name}")
        if not isinstance(state["scale"], bool):
            raise ValueError("PCR fitted state has an invalid scale flag")

        components = np.asarray(state["pca_components"], dtype=np.float64)
        pca_mean = np.asarray(state["pca_mean"], dtype=np.float64)
        coefficients = np.asarray(state["reg_coef"], dtype=np.float64)
        intercept = np.asarray(state["reg_intercept"], dtype=np.float64)
        expected_coefficient_shape = (state["targets"], state["n_components"])
        if (
            components.shape != (state["n_components"], state["features"])
            or pca_mean.shape != (state["features"],)
            or coefficients.shape != expected_coefficient_shape
            or intercept.shape != (state["targets"],)
        ):
            raise ValueError("PCR fitted state dimensions are inconsistent")
        scaler_mean = None if state["scaler_mean"] is None else np.asarray(state["scaler_mean"], dtype=np.float64)
        scaler_scale = None if state["scaler_scale"] is None else np.asarray(state["scaler_scale"], dtype=np.float64)
        if state["scale"]:
            if scaler_mean is None or scaler_scale is None:
                raise ValueError("autoscaled PCR fitted state is missing scaler state")
            if scaler_mean.shape != (state["features"],) or scaler_scale.shape != (state["features"],):
                raise ValueError("PCR fitted scaler dimensions are inconsistent")
        elif scaler_mean is not None or scaler_scale is not None:
            raise ValueError("unscaled PCR fitted state must not carry scaler state")
        arrays = (components, pca_mean, coefficients, intercept)
        if not all(np.isfinite(array).all() for array in arrays):
            raise ValueError("PCR fitted state contains non-finite values")
        if scaler_mean is not None and (
            not np.isfinite(scaler_mean).all() or not np.isfinite(scaler_scale).all() or np.any(scaler_scale <= 0)
        ):
            raise ValueError("PCR fitted scaler state is invalid")

        matrix = to_numpy_2d(bind_X(input_data, allow_array=True), name="input_data", dtype=np.float64)
        if matrix.shape[1] != state["features"] or not np.isfinite(matrix).all():
            raise ValueError("PCR apply input does not match the fitted feature contract")
        return PCRExtract(
            pca_components=components,
            pca_mean=pca_mean,
            reg_coef=coefficients,
            reg_intercept=intercept,
            n_components=state["n_components"],
            scaler_mean=scaler_mean,
            scaler_scale=scaler_scale,
        ).predict(matrix)


def _pcr_execute(
    X: Any,
    y: Any,
    *,
    node_id: str,
    parameters: dict[str, object],
) -> NodeResult:
    """Fit one reference-faithful PCR model through the sole operation ABI."""

    canonical = _canonical_pcr_parameters(parameters)
    return PCRNode(node_id, canonical)._execute_sync(X, y)


PCRNode.metadata.output_ports.append(
    PortMetadata(
        name="fitted_state",
        type_ref="spectrasherpa://types/RegressionModel/1.0",
        label="Fitted State",
        description="Portable PCR state for Predict Regression.",
    )
)

bind_stable_execution_contract(
    PCRNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_MODEL,
    implementation_id="spectrasherpa.model.pcr",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="filters_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/regression.md",
    implementation_distributions=("numpy", "scipy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
    citations=(
        "Massy, Principal Components Regression in Exploratory Statistical Research, JASA 60 (1965) "
        "234-256, DOI 10.1080/01621459.1965.10480787",
    ),
    implementation_modules=(fitted_state, _artifact_builder, regression_application),
    fitted_state_serializer="spectrasherpa.model-artifact.pcr/1",
    deterministic=True,
    target_access=TargetAccess.FIT_ONLY,
    group_access="none",
)


def _svr_post_fit(model, X_data, y_array, X_ds, params, node_id):
    """Extra outputs for SVR: support vectors, obs/pred data, metadata."""
    # Extract the raw SVR estimator from Pipeline or bare model
    svr = model.named_steps["estimator"] if hasattr(model, "named_steps") else model

    y_pred = model.predict(X_data)
    y_true_2d = _as_target_matrix(y_array)
    y_pred_2d = _as_target_matrix(y_pred)
    r2_per_target, rmse_per_target = _target_metric_lists(y_true_2d, y_pred_2d)
    r2 = r2_per_target[0]
    rmse = rmse_per_target[0]
    target_names = _target_names_from_context(X_ds, y_true_2d.shape[1], params)
    target_identity = _target_identity_metadata(X_ds, target_names)

    # Extract sample labels from input data for categorical coloring
    sample_labels = None
    label_categories = None
    n_observations = X_data.shape[0]

    sample_coord = X_ds.sample_axis

    if sample_coord is not None:
        if hasattr(sample_coord, "labels") and sample_coord.labels is not None:
            try:
                labels = sample_coord.labels
                raw = labels.tolist() if hasattr(labels, "tolist") else list(labels)
                sample_labels = [str(l) for l in raw]
                label_categories = sorted(set(sample_labels))
            except Exception:
                sample_labels = None
                label_categories = None

        if sample_labels is None and hasattr(sample_coord, "data") and sample_coord.data is not None:
            try:
                y_data = sample_coord.data
                raw = y_data.tolist() if hasattr(y_data, "tolist") else list(y_data)
                sample_labels = [str(l) for l in raw]
                unique_values = sorted(set(sample_labels))
                if len(unique_values) < 20 and not _is_sequential_numeric(raw):
                    label_categories = unique_values
            except Exception:
                sample_labels = None
                label_categories = None

    if sample_labels is None:
        sample_labels = [f"Sample {i + 1}" for i in range(n_observations)]

    from ._artifact_builder import build_model_artifact

    evidence_scope = "training_fit_only_not_predictive_validation"
    artifact = build_model_artifact(
        SVRExtract.from_sklearn(model),
        X_ds,
        node_id=node_id,
        metrics={
            "scope": evidence_scope,
            "r2_cal": r2,
            "rmse_cal": rmse,
            "per_target": [
                {
                    "target_name": target_names[0],
                    "r2_cal": r2,
                    "rmse_cal": rmse,
                }
            ],
        },
    )
    artifact["metadata"]["fitted_parameters"] = {
        name: params[name] for name in ("kernel", "C", "epsilon", "gamma", "degree", "coef0", "target_index", "scale")
    }
    artifact["metadata"]["metrics_scope"] = evidence_scope

    return {
        "support_vectors": svr.support_vectors_.tolist(),
        "data": [[float(yt), float(yh)] for yt, yh in zip(y_true_2d[:, 0], y_pred_2d[:, 0])],
        "_model_artifact": artifact,
        "metadata": {
            "type": "SVR",
            "output_type": "regression",
            "n_observations": n_observations,
            "n_samples": int(X_data.shape[0]),
            "n_features": X_data.shape[1],
            "n_targets": 1,
            "kernel": params.get("kernel", "rbf"),
            "C": params.get("C", 1.0),
            "epsilon": params.get("epsilon", 0.1),
            "gamma": params.get("gamma", "scale"),
            "r2": r2,
            "rmse": rmse,
            "sample_labels": sample_labels,
            "label_categories": label_categories,
            "y_true": y_true_2d.tolist(),
            "y_pred": y_pred_2d.tolist(),
            **target_identity,
            "selected_target_index": params.get("_selected_target_index", 0),
            "selected_target_name": target_names[0],
            "available_target_names": params.get("_original_target_names"),
            "r2_per_target": r2_per_target,
            "rmse_per_target": rmse_per_target,
            "quality_summary": {
                "r2": r2,
                "rmse": rmse,
                "kernel": str(params.get("kernel", "rbf")),
                "C": float(params.get("C", 1.0)),
                "n_samples": int(X_data.shape[0]),
                "n_features": int(X_data.shape[1]),
                "n_targets": 1,
                "target": target_names[0],
                **target_identity,
            },
            "evidence_scope": "training_fit_only_not_predictive_validation",
        },
    }


def _canonical_svr_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the closed scientist-visible epsilon-SVR choices."""

    expected = {"kernel", "C", "epsilon", "gamma", "degree", "coef0", "target_index", "scale"}
    if set(parameters) != expected:
        raise ValueError(f"SVR parameters must contain exactly {', '.join(sorted(expected))}")
    kernel = parameters["kernel"]
    if kernel not in {"linear", "poly", "rbf", "sigmoid"}:
        raise ValueError("SVR kernel must be linear, poly, rbf, or sigmoid")
    numeric: dict[str, float] = {}
    for name in ("C", "epsilon", "coef0"):
        value = parameters[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
            raise ValueError(f"SVR {name} must be a finite number")
        numeric[name] = float(value)
    if numeric["C"] < 0.01:
        raise ValueError("SVR C must be at least 0.01")
    if numeric["epsilon"] < 0:
        raise ValueError("SVR epsilon must be non-negative")
    if numeric["coef0"] < -1:
        raise ValueError("SVR coef0 must be at least -1")
    if parameters["gamma"] not in {"scale", "auto"}:
        raise ValueError("SVR gamma must be scale or auto")
    integers: dict[str, int] = {}
    for name in ("degree", "target_index"):
        value = parameters[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or int(value) < 1:
            raise ValueError(f"SVR {name} must be a positive whole number")
        integers[name] = int(value)
    if not isinstance(parameters["scale"], bool):
        raise ValueError("SVR scale must be boolean")
    return {
        "kernel": kernel,
        "C": numeric["C"],
        "epsilon": numeric["epsilon"],
        "gamma": parameters["gamma"],
        "degree": integers["degree"],
        "coef0": numeric["coef0"],
        "target_index": integers["target_index"],
        "scale": parameters["scale"],
    }


def _svr_execute(
    X: Any,
    y: Any,
    *,
    node_id: str,
    parameters: dict[str, object],
) -> dict[str, Any]:
    """Fit epsilon-SVR through the sole live/export operation ABI."""

    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    params = _canonical_svr_parameters(parameters)
    X_ds = bind_X(X, missing_message="Train SVR Regression: missing required input X", allow_array=True).copy()
    source_digest = X_ds.scientific_digest
    response_context = _regression_response_context(X_ds, y)
    response_type = getattr(response_context, "target_type", None) if response_context is not None else None
    if response_type not in {None, "continuous"}:
        raise ValueError(f"SVR requires continuous targets, got {response_type!r}")
    target_names = list(response_context.target_names or [])
    y_value = bind_y(
        y,
        X=X_ds,
        required=True,
        infer_from_X=True,
        dataset_as_data=True,
        missing_message="Train SVR Regression: no target values found",
    )
    matrix = to_numpy_2d(X_ds, name="X", dtype=np.float64)
    raw_target = to_numpy_y(y_value, name="y", expected_samples=matrix.shape[0], dtype=np.float64)
    raw_matrix = _as_target_matrix(raw_target)
    response_columns = _response_input_columns(X_ds, y, raw_matrix.shape[1])
    if target_names and len(target_names) != raw_matrix.shape[1]:
        raise ValueError("connected response metadata must name every fitted target exactly once")
    target_index = int(params["target_index"])
    if target_index > raw_matrix.shape[1]:
        available = ", ".join(target_names) if target_names else f"{raw_matrix.shape[1]} target(s)"
        raise ValueError(
            f"Target Property {target_index} is out of range for this dataset. Available targets: {available}."
        )
    selected_index = target_index - 1
    selected_name = (
        str(target_names[selected_index]) if selected_index < len(target_names) else f"Target {target_index}"
    )
    target = raw_matrix[:, selected_index]
    target_units = getattr(response_context, "target_units", None) if response_context is not None else None
    X_ds.target_context = TargetContext(
        target_type="continuous",
        target_name=selected_name,
        target_names=[selected_name],
        target_units=str(target_units) if target_units else None,
        selected_target=selected_name,
    )
    X_ds, target, population = clean_regression_target_with_population(
        X_ds,
        target,
        model_label="Train SVR Regression",
        source_scientific_digest=source_digest,
        response_input_columns=[response_columns[selected_index]],
        preserve_1d=True,
    )
    matrix = to_numpy_2d(X_ds, name="X", dtype=np.float64)
    if matrix.shape[0] < 2 or matrix.shape[1] < 1 or not np.isfinite(matrix).all():
        raise ValueError("SVR requires at least two finite samples and one feature")
    if not np.isfinite(target).all():
        raise ValueError("SVR requires finite target values")

    estimator = SVR(
        kernel=str(params["kernel"]),
        C=float(params["C"]),
        epsilon=float(params["epsilon"]),
        gamma=str(params["gamma"]),
        degree=int(params["degree"]),
        coef0=float(params["coef0"]),
    )
    scale = bool(params["scale"])
    model = Pipeline(
        [
            ("scaler", StandardScaler(with_mean=scale, with_std=scale)),
            ("estimator", estimator),
        ]
    )
    model.fit(matrix, target)
    predictions = np.asarray(model.predict(matrix), dtype=np.float64)
    prediction_matrix = predictions.reshape(-1, 1)
    residual_matrix = (np.asarray(target) - predictions).reshape(-1, 1)
    runtime_params = {
        **params,
        "_selected_target_index": selected_index,
        "_selected_target_name": selected_name,
        "_original_target_names": list(target_names) if target_names else None,
    }
    outputs: dict[str, Any] = {
        "model": model,
        "y_pred": prediction_matrix.tolist(),
        "predictions": prediction_matrix.tolist(),
        "residuals": residual_matrix.tolist(),
        "r2": _target_metric_lists(target, predictions)[0][0],
        "rmse": _target_metric_lists(target, predictions)[1][0],
    }
    outputs.update(
        _svr_post_fit(
            model=model,
            X_data=matrix,
            y_array=target,
            X_ds=X_ds,
            params=runtime_params,
            node_id=node_id,
        )
    )
    outputs["population"] = population
    outputs["_model_artifact"]["metadata"]["population"] = population
    outputs["fitted_state"] = regression_application.make_application_state(
        outputs["_model_artifact"],
        X_ds,
        y,
        operation="model.svr",
        targets=raw_matrix.shape[1] if y is not None else 1,
        selected_index=selected_index if y is not None else None,
    )
    return outputs


@register_node
class SVRNode(EstimatorSpecNode):
    """
    Support Vector Regression (SVR) node.

    Performs SVR with optional scaling for calibration models.
    """

    metadata = NodeMetadata(
        node_type="model.svr",
        category="regression",
        label="Train SVR Regression",
        description="Train a Support Vector Regression model for calibration",
        parameters=[
            NodeParameter(
                name="kernel",
                label="Kernel",
                param_type="select",
                default="rbf",
                options=["rbf", "linear", "poly", "sigmoid"],
                description="Kernel type for SVR",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="C",
                label="C",
                param_type="number",
                default=1.0,
                min_value=0.01,
                step=0.1,
                description="Regularization parameter",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="epsilon",
                label="Epsilon",
                param_type="number",
                default=0.1,
                min_value=0.0,
                step=0.01,
                description="Epsilon-tube width",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="gamma",
                label="Gamma",
                param_type="select",
                default="scale",
                options=["scale", "auto"],
                description="Kernel coefficient for RBF/poly/sigmoid",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="degree",
                label="Polynomial Degree",
                param_type="number",
                default=3,
                min_value=1,
                step=1,
                description="Degree for polynomial kernel",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="coef0",
                label="Coef0",
                param_type="number",
                default=0.0,
                min_value=-1.0,
                step=0.1,
                description="Independent term for poly/sigmoid kernels",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="target_index",
                label="Target Property",
                param_type="number",
                default=1,
                min_value=1,
                step=1,
                description=(
                    "1-based target/property column to model when the dataset contains multiple reference properties"
                ),
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="scale",
                label="Scale Data",
                param_type="boolean",
                default=True,
                description="Apply mean centering and scaling",
                required=False,
                category="basic",
            ),
        ],
        input_types=["SherpaDataset", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Data Matrix (X)",
                description="Spectral data or multivariate feature table (n_samples × n_variables)",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Targets (y)",
                description="Target values — optional if dataset has embedded target",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="population",
                type_ref="spectrasherpa://types/RegressionPopulation/1.0",
                required=True,
                label="Training population",
                description="Original row identities, admitted rows and missing-reference exclusions",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/RegressionModel/1.0",
                required=True,
                label="Fitted SVR Regression Model",
                description="Fitted SVR regression model produced by this training node",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Predictions",
                description="Predicted target values (n_samples × n_targets)",
            ),
            PortMetadata(
                name="residuals",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Residuals",
                description="Regression residuals (y_true - y_pred; n_samples × n_targets)",
            ),
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_svr_parameters,
    )

    spec = EstimatorSpec(
        estimator_class=SVR,
        scale=True,
        scale_param="scale",
        single_target=True,
        post_fit_fn=_svr_post_fit,
        estimator_import="from sklearn.svm import SVR",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        return [
            f"{indent}# --- Canonical epsilon-Support Vector Regression ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes import _svr_execute",
            f"{indent}results[{self.node_id!r}] = _svr_execute(",
            f"{indent}    {X_expression}, {inputs.get('y', 'None')},",
            f"{indent}    node_id={self.node_id!r}, parameters={self._resolve_params()!r},",
            f"{indent})",
        ]

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return _svr_execute(X, y, node_id=self.node_id, parameters=self._resolve_params())

    def fit_fitted_state(self, input_data: Any, target: Any) -> dict[str, object]:
        """Fit and serialize the exact single-response epsilon-SVR state."""

        outputs = _svr_execute(
            input_data,
            target,
            node_id=self.node_id,
            parameters=self._resolve_params(),
        )
        metadata, arrays = SVRExtract.from_sklearn(outputs["model"]).to_artifact()
        return {
            "serializer": "spectrasherpa.model-artifact.svr/1",
            "kernel": metadata["kernel"],
            "gamma": metadata["gamma"],
            "degree": metadata["degree"],
            "coef0": metadata["coef0"],
            "scale": metadata["scale"],
            "features": metadata["features"],
            "support_vectors": arrays["support_vectors"].tolist(),
            "dual_coef": arrays["dual_coef"].tolist(),
            "intercept": arrays["intercept"].tolist(),
            "scaler_mean": None if arrays.get("scaler_mean") is None else arrays["scaler_mean"].tolist(),
            "scaler_scale": None if arrays.get("scaler_scale") is None else arrays["scaler_scale"].tolist(),
        }

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        """Apply only the closed, dimension-checked epsilon-SVR state."""

        from collections.abc import Mapping

        required = {
            "serializer",
            "kernel",
            "gamma",
            "degree",
            "coef0",
            "scale",
            "features",
            "support_vectors",
            "dual_coef",
            "intercept",
            "scaler_mean",
            "scaler_scale",
        }
        if not isinstance(state, Mapping) or set(state) != required:
            raise ValueError("SVR fitted state does not use the closed serializer schema")
        if state["serializer"] != "spectrasherpa.model-artifact.svr/1":
            raise ValueError("SVR fitted state has an unsupported serializer")
        arrays = {
            "support_vectors": np.asarray(state["support_vectors"], dtype=np.float64),
            "dual_coef": np.asarray(state["dual_coef"], dtype=np.float64),
            "intercept": np.asarray(state["intercept"], dtype=np.float64),
        }
        if state["scaler_mean"] is not None:
            arrays["scaler_mean"] = np.asarray(state["scaler_mean"], dtype=np.float64)
        if state["scaler_scale"] is not None:
            arrays["scaler_scale"] = np.asarray(state["scaler_scale"], dtype=np.float64)
        replay = SVRExtract.from_artifact(
            {
                "model_type": "svr",
                "serializer": state["serializer"],
                "kernel": state["kernel"],
                "gamma": state["gamma"],
                "degree": state["degree"],
                "coef0": state["coef0"],
                "scale": state["scale"],
                "features": state["features"],
            },
            arrays,
        )
        matrix = to_numpy_2d(bind_X(input_data, allow_array=True), name="input_data", dtype=np.float64)
        if matrix.shape[1] != state["features"] or not np.isfinite(matrix).all():
            raise ValueError("SVR apply input does not match the fitted feature contract")
        return replay.predict(matrix)


SVRNode.metadata.output_ports.append(
    PortMetadata(
        name="fitted_state",
        type_ref="spectrasherpa://types/RegressionModel/1.0",
        label="Fitted State",
        description="Portable SVR state for Predict Regression.",
    )
)

bind_stable_execution_contract(
    SVRNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_MODEL,
    implementation_id="spectrasherpa.model.svr",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="filters_samples",
    feature_effect="generates_features",
    axis_effect="removes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/regression.md",
    implementation_distributions=("numpy", "scipy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
    citations=(
        "Drucker, Burges, Kaufman, Smola & Vapnik, Support Vector Regression Machines, NeurIPS 9 (1997) 155-161",
        "Lesnoff, Metz & Roger, rchemo::svmr: SVM regression; delegates epsilon-regression to e1071::svm, "
        "https://search.r-project.org/CRAN/refmans/rchemo/html/svmr.html",
        "Meyer et al., e1071: Misc Functions of the Department of Statistics, Probability Theory Group, "
        "TU Wien; svm implements libsvm epsilon-regression, "
        "https://search.r-project.org/CRAN/refmans/e1071/html/svm.html",
        "Chang & Lin, LIBSVM: A Library for Support Vector Machines, ACM TIST 2 (2011), DOI 10.1145/1961189.1961199",
    ),
    implementation_modules=(fitted_state, _artifact_builder, regression_application),
    fitted_state_serializer="spectrasherpa.model-artifact.svr/1",
    deterministic=True,
    target_access=TargetAccess.FIT_ONLY,
    group_access="none",
)


def _lr_post_fit(model, X_data, y_array, X_ds, params, node_id):
    fit_intercept = params.get("fit_intercept", True)
    y_pred = model.predict(X_data)
    y_true_2d = _as_target_matrix(y_array)
    y_pred_2d = _as_target_matrix(y_pred)
    r2_per_target, rmse_per_target = _target_metric_lists(y_true_2d, y_pred_2d)
    target_names = _target_names_from_context(X_ds, y_true_2d.shape[1], params)
    target_identity = _target_identity_metadata(X_ds, target_names)
    intercept_values = np.asarray(model.intercept_, dtype=np.float64).reshape(-1)
    intercept: float | list[float]
    intercept = float(intercept_values[0]) if intercept_values.size == 1 else intercept_values.tolist()
    score = r2_per_target[0] if y_true_2d.shape[1] == 1 else None
    rmse = rmse_per_target[0] if y_true_2d.shape[1] == 1 else None
    from ._artifact_builder import build_model_artifact

    evidence_scope = "training_fit_only_not_predictive_validation"
    artifact = build_model_artifact(
        LinearRegressionExtract.from_sklearn(model),
        X_ds,
        node_id=node_id,
        metrics={
            "scope": evidence_scope,
            "r2_cal": score,
            "rmse_cal": rmse,
            "per_target": [
                {
                    "target_name": name,
                    "r2_cal": target_r2,
                    "rmse_cal": target_rmse,
                }
                for name, target_r2, target_rmse in zip(
                    target_names,
                    r2_per_target,
                    rmse_per_target,
                    strict=True,
                )
            ],
        },
    )
    artifact["metadata"]["fitted_parameters"] = {"fit_intercept": bool(fit_intercept)}
    artifact["metadata"]["metrics_scope"] = evidence_scope

    if fit_intercept:
        reported_intercept: float | list[float] = intercept
    elif y_true_2d.shape[1] == 1:
        reported_intercept = 0.0
    else:
        reported_intercept = [0.0] * y_true_2d.shape[1]

    return {
        "coef": model.coef_.tolist(),
        "intercept": reported_intercept,
        "score": score,
        "_model_artifact": artifact,
        "metadata": {
            "type": "LinearRegression",
            "output_type": "regression",
            "n_observations": int(X_data.shape[0]),
            "n_samples": int(X_data.shape[0]),
            "n_features": int(X_data.shape[1]),
            "n_targets": int(y_true_2d.shape[1]),
            "fit_intercept": bool(fit_intercept),
            "r2": score,
            "rmse": rmse,
            **target_identity,
            "y_true": y_true_2d.tolist(),
            "y_pred": y_pred_2d.tolist(),
            "r2_per_target": r2_per_target,
            "rmse_per_target": rmse_per_target,
            "quality_summary": {
                "r2": score,
                "rmse": rmse,
                "n_samples": int(X_data.shape[0]),
                "n_features": int(X_data.shape[1]),
                "n_targets": int(y_true_2d.shape[1]),
                **target_identity,
            },
        },
    }


def _canonical_linear_regression_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the sole scientist-visible ordinary-least-squares choice."""

    if set(parameters) != {"fit_intercept"} or not isinstance(parameters["fit_intercept"], bool):
        raise ValueError("linear-regression parameters must contain exactly one boolean fit_intercept")
    return {"fit_intercept": parameters["fit_intercept"]}


def _linear_regression_execute(
    X: Any,
    y: Any,
    *,
    node_id: str,
    parameters: dict[str, object],
) -> dict[str, Any]:
    """Fit one ordinary least-squares model and return its closed DAG outputs."""

    params = _canonical_linear_regression_parameters(parameters)
    X_ds = bind_X(X, missing_message="Train Linear Regression: missing required input X", allow_array=True).copy()
    source_digest = X_ds.scientific_digest
    y_value = bind_y(
        y,
        X=X_ds,
        required=True,
        infer_from_X=True,
        dataset_as_data=True,
        missing_message="Train Linear Regression: no target values found",
    )
    matrix = to_numpy_2d(X_ds, name="X", dtype=np.float64)
    target = to_numpy_y(y_value, name="y", expected_samples=matrix.shape[0], dtype=np.float64)
    response_columns = _response_input_columns(X_ds, y, _as_target_matrix(target).shape[1])
    _bind_continuous_response_context(
        X_ds,
        y,
        n_targets=_as_target_matrix(target).shape[1],
    )
    X_ds, target, population = clean_regression_target_with_population(
        X_ds,
        target,
        model_label="Train Linear Regression",
        source_scientific_digest=source_digest,
        response_input_columns=response_columns,
        preserve_1d=True,
    )
    matrix = to_numpy_2d(X_ds, name="X", dtype=np.float64)
    if matrix.shape[0] < 2 or matrix.shape[1] < 1 or not np.isfinite(matrix).all():
        raise ValueError("linear regression requires at least two finite samples and one feature")
    if not np.isfinite(target).all():
        raise ValueError("linear regression requires finite target values")

    model = LinearRegression(fit_intercept=bool(params["fit_intercept"]))
    model.fit(matrix, target)
    target_matrix = _as_target_matrix(target)
    predictions = _as_target_matrix(np.asarray(model.predict(matrix), dtype=np.float64))
    outputs: dict[str, Any] = {
        "model": model,
        "y_pred": predictions.tolist(),
        "predictions": predictions.tolist(),
        "residuals": (target_matrix - predictions).tolist(),
    }

    r2_values, rmse_values = _target_metric_lists(target, predictions)
    if target_matrix.shape[1] == 1:
        outputs["r2"], outputs["rmse"] = r2_values[0], rmse_values[0]
    outputs.update(
        _lr_post_fit(
            model=model,
            X_data=matrix,
            y_array=target,
            X_ds=X_ds,
            params=params,
            node_id=node_id,
        )
    )
    outputs["metadata"]["evidence_scope"] = "training_fit_only_not_predictive_validation"
    if target_matrix.shape[1] > 1:
        _omit_multitarget_summaries(outputs)
        _omit_multitarget_summaries(outputs["metadata"])
        _omit_multitarget_summaries(outputs["_model_artifact"]["metadata"])
    outputs["population"] = population
    outputs["_model_artifact"]["metadata"]["population"] = population
    outputs["fitted_state"] = regression_application.make_application_state(
        outputs["_model_artifact"], X_ds, y, operation="model.linear_regression", targets=target_matrix.shape[1]
    )
    return outputs


@register_node
class LinearRegressionNode(EstimatorSpecNode):
    """
    Simple Linear Regression node.

    Performs linear regression for calibration curves.
    """

    metadata = NodeMetadata(
        node_type="model.linear_regression",
        category="regression",
        label="Train Linear Regression",
        description="Train a linear regression model for calibration",
        parameters=[
            NodeParameter(
                name="fit_intercept",
                label="Fit Intercept",
                param_type="boolean",
                default=True,
                description="Calculate intercept (if False, force through origin)",
                required=False,
            ),
        ],
        input_types=["array", "array"],
        output_type="dict",
        # Named input ports for multi-input node
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Features (X)",
                description="Feature matrix (predictors)",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Targets (y)",
                description="Target values — optional if dataset has embedded target",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="population",
                type_ref="spectrasherpa://types/RegressionPopulation/1.0",
                required=True,
                label="Training population",
                description="Original row identities, admitted rows and missing-reference exclusions",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/RegressionModel/1.0",
                required=True,
                label="Fitted Linear Regression Model",
                description="Fitted Linear Regression model produced by this training node",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Predictions",
                description="Predicted values (y_pred)",
            ),
            PortMetadata(
                name="residuals",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Residuals",
                description="Regression residuals (y_true - y_pred)",
            ),
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_linear_regression_parameters,
    )

    spec = EstimatorSpec(
        estimator_class=LinearRegression,
        post_fit_fn=_lr_post_fit,
        estimator_import="from sklearn.linear_model import LinearRegression",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        return [
            f"{indent}# --- Canonical ordinary least-squares regression ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes "
            "import _linear_regression_execute",
            f"{indent}results[{self.node_id!r}] = _linear_regression_execute(",
            f"{indent}    {X_expression}, {inputs.get('y', 'None')},",
            f"{indent}    node_id={self.node_id!r}, parameters={self._resolve_params()!r},",
            f"{indent})",
        ]

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return _linear_regression_execute(
            X,
            y,
            node_id=self.node_id,
            parameters=self._resolve_params(),
        )

    def fit_fitted_state(self, input_data: Any, target: Any) -> dict[str, object]:
        """Fit the declared ordinary-least-squares state through the live authority."""

        outputs = _linear_regression_execute(
            input_data,
            target,
            node_id=self.node_id,
            parameters=self._resolve_params(),
        )
        extracted = LinearRegressionExtract.from_sklearn(outputs["model"])
        matrix = to_numpy_2d(bind_X(input_data, allow_array=True), name="input_data", dtype=np.float64)
        metadata, arrays = extracted.to_artifact()
        return {
            "serializer": "spectrasherpa.model-artifact.linear-regression/1",
            "fit_intercept": metadata["fit_intercept"],
            "features": int(matrix.shape[1]),
            "targets": metadata["target_count"],
            "coef": arrays["coef"].tolist(),
            "intercept": arrays["intercept"].tolist(),
        }

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        """Apply only the closed, dimension-checked OLS serializer schema."""

        from collections.abc import Mapping

        required = {"serializer", "fit_intercept", "features", "targets", "coef", "intercept"}
        if not isinstance(state, Mapping) or set(state) != required:
            raise ValueError("linear-regression fitted state has an invalid closed schema")
        if state["serializer"] != "spectrasherpa.model-artifact.linear-regression/1":
            raise ValueError("linear-regression fitted state has an unsupported serializer")
        features = state["features"]
        targets = state["targets"]
        if type(features) is not int or features < 1 or type(targets) is not int or targets < 1:
            raise ValueError("linear-regression fitted state has invalid dimensions")
        matrix = to_numpy_2d(bind_X(input_data, allow_array=True), name="input_data", dtype=np.float64)
        if matrix.shape[1] != features:
            raise ValueError("linear-regression application feature count does not match fitted state")
        extracted = LinearRegressionExtract.from_artifact(
            {"fit_intercept": state["fit_intercept"], "target_count": targets},
            {
                "coef": np.asarray(state["coef"], dtype=np.float64),
                "intercept": np.asarray(state["intercept"], dtype=np.float64),
            },
        )
        return extracted.predict(matrix)


LinearRegressionNode.metadata.output_ports.append(
    PortMetadata(
        name="fitted_state",
        type_ref="spectrasherpa://types/RegressionModel/1.0",
        label="Fitted State",
        description="Portable linear-regression state for Predict Regression.",
    )
)

bind_stable_execution_contract(
    LinearRegressionNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_MODEL,
    implementation_id="spectrasherpa.model.linear_regression",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="filters_samples",
    feature_effect="generates_features",
    axis_effect="removes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/regression.md",
    implementation_distributions=("numpy", "scipy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
    citations=(
        "rchemo::lmr linear-regression reference, https://search.r-project.org/CRAN/refmans/rchemo/html/lmr.html",
    ),
    implementation_modules=(fitted_state, _artifact_builder, regression_application),
    fitted_state_serializer="spectrasherpa.model-artifact.linear-regression/1",
    deterministic=True,
    target_access=TargetAccess.FIT_ONLY,
    group_access="none",
)
