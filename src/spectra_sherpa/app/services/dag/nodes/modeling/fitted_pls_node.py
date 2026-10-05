"""The sole canonical fitted PLS producer and numerical application core."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, cast

import numpy as np

import spectra_sherpa.app.services.dag.regression_comparison as regression_comparison
from spectra_sherpa.app.services.dag.feature_axis_identity import (
    feature_axis_identity as _canonical_feature_axis_identity,
)
from spectra_sherpa.app.services.dag.feature_axis_identity import (
    validated_axis_quantity,
)
from spectra_sherpa.app.services.dag.fitted_input_identity import (
    fitted_input_identity,
    require_fitted_input_identity,
    validate_fitted_input_identity,
)
from spectra_sherpa.app.services.dag.io_contracts import (
    bind_y,
    coerce_to_sherpa,
    resolve_target_names,
    to_numpy_2d,
)
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.nodes.selection import _vip
from spectra_sherpa.app.services.dag.presentation_contract import (
    NodePresentationContract,
    ScientificPresentation,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.core.node_identity import node_contract_digest_is_compatible
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import pls_applicability, pls_core, saved_native_model
from .pls_core import ALGORITHM_ID, ALGORITHM_VERSION, PLSFit, apply_pls_affine_state, fit_simpls

FITTED_PLS_STATE_SERIALIZER = "spectra.sherpa-simpls-regression-json/9"
_LOCAL_STATE_SCHEMA = "spectrasherpa.fitted-pls-state/9"


def _admit_response_identity(value: object, *, targets: int) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {"names", "units"}:
        raise ValueError("fitted PLS response identity must contain names and units")
    names, units = value["names"], value["units"]
    if names is not None and (
        not isinstance(names, list)
        or len(names) != targets
        or any(not isinstance(name, str) or not name.strip() for name in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("fitted PLS response names must uniquely identify every target")
    if (
        not isinstance(units, list)
        or len(units) != targets
        or any(unit is not None and (not isinstance(unit, str) or not unit.strip()) for unit in units)
    ):
        raise ValueError("fitted PLS response units must describe every target or be explicitly unavailable")
    return {"names": list(names) if names is not None else None, "units": list(units)}


def _response_identity(source: Any, *, targets: int, bound_names: list[str], embedded: bool) -> dict[str, object]:
    """Read only the response's authority, never unrelated predictor metadata."""
    context = getattr(source, "target_context", None)
    if embedded:
        names = resolve_target_names(None, source)
        unit = getattr(context, "target_units", None)
    else:
        axis = getattr(source, "feature_axis", None)
        names = list(axis.labels) if axis is not None and axis.labels else None
        unit = getattr(source, "units", None)
        # A connected dataset contributes its data matrix, not its embedded
        # target. Only response-only datasets may use target_context as a
        # declaration for their data columns.
        if getattr(source, "target", None) is not None:
            context = None
        if context is not None:
            declared = list(context.target_names) if context.target_names else None
            declared_unit = context.target_units
            if names and declared and names != declared:
                raise ValueError("response data columns contradict target-context names")
            if unit and declared_unit and unit != declared_unit:
                raise ValueError("response data units contradict target-context units")
            names = names or declared
            unit = unit or declared_unit
    if names is None and targets == 1 and context is not None:
        name = context.selected_target or context.target_name
        names = [name] if name else None
    if names and bound_names and names != bound_names:
        raise ValueError("fitted PLS target metadata conflicts with its bound target identity")
    names = names or bound_names or None
    return _admit_response_identity({"names": names, "units": [unit] * targets}, targets=targets)


def _finite_matrix(
    value: object,
    *,
    name: str,
    rows: int | None = None,
    columns: int | None = None,
) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if (
        array.ndim != 2
        or (rows is not None and array.shape[0] != rows)
        or (columns is not None and array.shape[1] != columns)
        or not np.isfinite(array).all()
    ):
        raise ValueError(f"fitted PLS state has an invalid {name} matrix")
    return np.array(array, copy=True)


def _target_matrix(value: object, *, samples: int) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim == 1:
        array = array.reshape(-1, 1)
    if array.ndim != 2 or array.shape[0] != samples or not np.isfinite(array).all():
        raise ValueError("fitted PLS requires a finite target matrix aligned to training samples")
    return np.array(array, copy=True)


def _feature_axis_identity(dataset: Any, *, features: int) -> tuple[str | None, str | None, str | None, str | None]:
    return _canonical_feature_axis_identity(dataset, features=features, context="fitted PLS")


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"fitted PLS state has an invalid {name}")
    return value


def _canonical_pls_parameters(parameters: dict[str, object]) -> dict[str, object]:
    components = parameters["n_components"]
    assert isinstance(components, (int, float))
    if int(components) != components:
        raise ValueError("parameter n_components must be an integer")
    return parameters


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _source_contract_digest() -> str:
    contract = FittedPLSV2Node.metadata.resolved_execution_contract()
    if contract is None:  # pragma: no cover - import-time binding is mandatory
        raise RuntimeError("canonical fitted PLS execution contract is unavailable")
    digest = contract.digest
    if not isinstance(digest, str):  # pragma: no cover - contract constructor enforces this
        raise RuntimeError("canonical fitted PLS execution contract digest is invalid")
    return digest


def make_fitted_pls_state_envelope(state: Mapping[str, object]) -> dict[str, object]:
    """Bind local fitted state to the exact producer contract and serializer."""

    normalized = FittedPLSV2Node("pls-state-validator", {}).validate_fitted_state(state)
    return {
        "schema_version": _LOCAL_STATE_SCHEMA,
        "serializer": FITTED_PLS_STATE_SERIALIZER,
        "source_contract_digest": _source_contract_digest(),
        "state_content_digest": hashlib.sha256(_canonical_json(normalized)).hexdigest(),
        "state": normalized,
    }


def verify_fitted_pls_state_envelope(value: object) -> dict[str, object]:
    """Return closed PLS state only when its local producer binding verifies."""

    required = {
        "schema_version",
        "serializer",
        "source_contract_digest",
        "state_content_digest",
        "state",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("fitted PLS state envelope does not use the closed schema")
    if value["schema_version"] != _LOCAL_STATE_SCHEMA or value["serializer"] != FITTED_PLS_STATE_SERIALIZER:
        raise ValueError("fitted PLS state envelope has an unsupported identity")
    if not node_contract_digest_is_compatible(
        "model.fitted_pls",
        value["source_contract_digest"],
        _source_contract_digest(),
    ):
        raise ValueError("fitted PLS state envelope producer contract is not compatible")
    state = FittedPLSV2Node("pls-state-validator", {}).validate_fitted_state(value["state"])
    if value["state_content_digest"] != hashlib.sha256(_canonical_json(state)).hexdigest():
        raise ValueError("fitted PLS state envelope content digest does not match")
    return state


@register_node
class FittedPLSV2Node(Node):
    """Fit PLS once and emit both predictions and a typed reusable state."""

    metadata = NodeMetadata(
        node_type="model.fitted_pls",
        category="modeling",
        label="Sherpa PLS Regression",
        description=(
            "Fit the canonical Sherpa-native de Jong SIMPLS model on training spectra and targets, emit "
            "its typed fitted state, and calculate predictions through the same numerical authority."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="Latent Variables",
                param_type="number",
                default=2,
                min_value=1,
                step=1,
                required=True,
                hint=(
                    "Requested maximum; the fit reports the effective predictive rank and stops before "
                    "an unidentifiable direction. Must not exceed min(training samples - 1, input features)."
                ),
            ),
            NodeParameter(
                name="scale",
                label="Autoscale",
                param_type="boolean",
                default=False,
                required=False,
            ),
            NodeParameter(
                name="target_names",
                label="Target Identities",
                param_type="string_list",
                default=[],
                required=False,
                category="internal",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectra to fit or apply with the explicit PLS-v2 lifecycle.",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Training Targets",
                description="Targets aligned to the training spectra; embedded targets are accepted.",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Predicted Targets",
                description="Predictions from JSON-serialized PLS-v2 state.",
            ),
            PortMetadata(
                name="fitted_state",
                type_ref="spectrasherpa://types/RegressionModel/1.0",
                required=True,
                label="Fitted PLS State",
                description="Closed local state bound to this producer contract and serializer.",
            ),
            PortMetadata(
                name="vip_scores",
                type_ref="spectrasherpa://types/VariableImportance/1.0",
                required=True,
                label="VIP Scores",
                description="Combined Chong-Jun VIP scores derived from this exact fitted PLS state.",
            ),
            PortMetadata(
                name="calibration_comparison",
                type_ref="spectrasherpa://types/RegressionComparison/1.0",
                required=True,
                label="Calibration Fit",
                description="Training references, predictions, and residuals; not held-out validation evidence.",
            ),
            PortMetadata(
                name="x_scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="PLS Scores",
                description="Calibration-sample coordinates in the fitted latent-variable space.",
            ),
            PortMetadata(
                name="x_loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="PLS X Loadings",
                description="Component-by-variable X loading matrix from the exact fitted model.",
            ),
            PortMetadata(
                name="explained_variance",
                type_ref="spectrasherpa://types/ExplainedVarianceMatrix/1.0",
                required=True,
                label="Explained Variance",
                description="Component-wise explained X and Y variance fractions.",
            ),
            PortMetadata(
                name="regression_coefficients",
                type_ref="spectrasherpa://types/RegressionCoefficientMatrix/1.0",
                required=True,
                label="Regression Coefficients",
                description="One final fitted coefficient per spectral variable and response target.",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="array",
        policy=NodePolicy(),
        presentation_contract=NodePresentationContract(
            default_presentation="calibration_fit",
            presentations=(
                ScientificPresentation(
                    "calibration_fit",
                    "Calibration Fit: Predicted vs Reference",
                    "regression_comparison",
                    ("calibration_comparison",),
                    ("plot", "table"),
                    "Training-fit diagnostic; it is not held-out validation evidence.",
                ),
                ScientificPresentation("scores", "PLS Scores", "pls_scores", ("x_scores",), ("plot", "table")),
                ScientificPresentation(
                    "loadings", "PLS X Loadings", "pls_loadings", ("x_loadings",), ("plot", "table")
                ),
                ScientificPresentation("vip", "VIP Scores", "variable_profile", ("vip_scores",), ("plot", "table")),
                ScientificPresentation(
                    "explained_variance",
                    "Explained Variance",
                    "pls_explained_variance",
                    ("explained_variance",),
                    ("plot", "table"),
                ),
                ScientificPresentation(
                    "coefficients",
                    "Regression Coefficients",
                    "regression_coefficients",
                    ("regression_coefficients",),
                    ("plot", "table"),
                ),
                ScientificPresentation(
                    "model",
                    "Fitted Model Summary",
                    "model_summary",
                    ("fitted_state",),
                    ("model_summary",),
                ),
            ),
        ),
        canonical_parameter_validator=_canonical_pls_parameters,
    )

    def _fit_model_and_state(
        self, input_data: Any, target: object, *, response_source: Any = None, response_is_embedded: bool = False
    ) -> tuple[Any, np.ndarray, np.ndarray, PLSFit, dict[str, object]]:
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        X = to_numpy_2d(dataset, name="input_data", dtype=np.float64)
        if X.shape[0] < 2 or not np.isfinite(X).all():
            raise ValueError("fitted PLS requires at least two finite training spectra")
        y = _target_matrix(target, samples=X.shape[0])
        params = self._resolve_params()
        response_identity = _response_identity(
            response_source,
            targets=y.shape[1],
            bound_names=list(params.get("target_names") or []),
            embedded=response_is_embedded,
        )
        component_value = params["n_components"]
        if (
            isinstance(component_value, bool)
            or not isinstance(component_value, (int, float))
            or not np.isfinite(component_value)
            or int(component_value) != component_value
        ):
            raise ValueError("n_components must be a positive whole number")
        components = int(component_value)
        if components < 1 or components > min(X.shape[0] - 1, X.shape[1]):
            raise ValueError("n_components exceeds the fitted PLS training rank")
        scale = params["scale"]
        if not isinstance(scale, bool):
            raise ValueError("scale must be a boolean")
        model = fit_simpls(X, y, n_components=components, scale=scale)
        feature_offset = model.x_offset.reshape(1, -1)
        coefficients = model.coefficients
        prediction_offset = model.y_offset.reshape(1, -1)
        vip_scores = _vip.calculate_vip(
            model.x_scores,
            model.x_weights,
            model.y_loadings,
            X.shape[1],
        )
        axis_values_digest, axis_labels_digest, axis_units, axis_quantity = _feature_axis_identity(
            dataset, features=X.shape[1]
        )
        if not np.isfinite(coefficients).all() or not np.isfinite(prediction_offset).all():
            raise ValueError("fitted PLS produced non-finite reference parameters")
        state = {
            "serializer": FITTED_PLS_STATE_SERIALIZER,
            "algorithm_id": model.algorithm_id,
            "algorithm_version": model.algorithm_version,
            "n_components": components,
            "effective_n_components": model.n_components,
            "scale": scale,
            "reference_samples": X.shape[0],
            "features": X.shape[1],
            "targets": y.shape[1],
            "response_identity": response_identity,
            "input_identity": fitted_input_identity(dataset, features=X.shape[1]),
            "diagnostic_state": pls_applicability.fit_screening(X, model),
            "feature_axis_values_sha256": axis_values_digest,
            "feature_axis_labels_sha256": axis_labels_digest,
            "feature_axis_units": axis_units,
            "feature_axis_quantity": axis_quantity,
            "coefficients": coefficients.tolist(),
            "feature_offset": feature_offset.tolist(),
            "prediction_offset": prediction_offset.tolist(),
            "vip_scores": vip_scores.tolist(),
            "x_explained_variance": model.x_explained_variance.tolist(),
            "y_explained_variance": model.y_explained_variance.tolist(),
        }
        return dataset, X, y, model, state

    def fit_fitted_state(self, input_data: Any, target: object) -> dict[str, object]:
        """Fit once and return only the portable model state ABI."""
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        # The fold ABI supplies a positional response. Named response datasets
        # can additionally carry their own checked identity. Predictor metadata
        # is authoritative only when the response was actually inferred from it.
        source = dataset if target is None else target
        values = bind_y(target, X=dataset, required=True, dataset_as_data=True, target_type="continuous")
        return self._fit_model_and_state(dataset, values, response_source=source, response_is_embedded=target is None)[
            4
        ]

    def validate_fitted_state(self, state: object) -> dict[str, object]:
        """Validate and normalize the sole closed numerical state ABI."""

        required = {
            "serializer",
            "algorithm_id",
            "algorithm_version",
            "n_components",
            "effective_n_components",
            "scale",
            "reference_samples",
            "features",
            "targets",
            "response_identity",
            "input_identity",
            "diagnostic_state",
            "feature_axis_values_sha256",
            "feature_axis_labels_sha256",
            "feature_axis_units",
            "feature_axis_quantity",
            "coefficients",
            "feature_offset",
            "prediction_offset",
            "vip_scores",
            "x_explained_variance",
            "y_explained_variance",
        }
        if (
            not isinstance(state, Mapping)
            or set(state) != required
            or state["serializer"] != FITTED_PLS_STATE_SERIALIZER
        ):
            raise ValueError(
                "fitted PLS state does not use the closed serializer schema; "
                "legacy state without response authority must be rebuilt with the current producer"
            )
        input_identity = validate_fitted_input_identity(state["input_identity"])
        components = _positive_int(state["n_components"], name="n_components")
        effective_components = _positive_int(state["effective_n_components"], name="effective_n_components")
        reference_samples = _positive_int(state["reference_samples"], name="reference_samples")
        features = _positive_int(state["features"], name="features")
        targets = _positive_int(state["targets"], name="targets")
        if input_identity["features"] != features or input_identity["axis"] != [
            state["feature_axis_values_sha256"],
            state["feature_axis_labels_sha256"],
            state["feature_axis_units"],
            state["feature_axis_quantity"],
        ]:
            raise ValueError("fitted PLS input identity contradicts its feature contract")
        response_identity = _admit_response_identity(state["response_identity"], targets=targets)
        if not isinstance(state["scale"], bool):
            raise ValueError("fitted PLS state has an invalid scale flag")
        if state["algorithm_id"] != ALGORITHM_ID or state["algorithm_version"] != ALGORITHM_VERSION:
            raise ValueError("fitted PLS state has an unsupported Sherpa algorithm identity")
        for name in ("feature_axis_values_sha256", "feature_axis_labels_sha256"):
            digest = state[name]
            if digest is not None and (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError(f"fitted PLS state has an invalid {name}")
        if state["feature_axis_units"] is not None and not isinstance(state["feature_axis_units"], str):
            raise ValueError("fitted PLS state has invalid feature_axis_units")
        axis_quantity = validated_axis_quantity(state["feature_axis_quantity"], context="fitted PLS")
        if components > min(reference_samples - 1, features):
            raise ValueError("fitted PLS state has an invalid n_components for its reference dimensions")
        if effective_components > components:
            raise ValueError("fitted PLS state effective component count exceeds the requested maximum")
        coefficients = _finite_matrix(
            state["coefficients"],
            name="coefficients",
            rows=features,
            columns=targets,
        )
        feature_offset = _finite_matrix(state["feature_offset"], name="feature_offset", rows=1, columns=features)
        prediction_offset = _finite_matrix(
            state["prediction_offset"],
            name="prediction_offset",
            rows=1,
            columns=targets,
        )
        vip_scores = np.asarray(state["vip_scores"], dtype=np.float64)
        if vip_scores.shape != (features,) or not np.isfinite(vip_scores).all() or np.any(vip_scores < 0.0):
            raise ValueError("fitted PLS state has invalid VIP scores")
        explained: dict[str, np.ndarray] = {}
        for name in ("x_explained_variance", "y_explained_variance"):
            values = np.asarray(state[name], dtype=np.float64)
            if (
                values.shape != (effective_components,)
                or not np.isfinite(values).all()
                or np.any(values < -1e-12)
                or float(np.sum(values)) > 1.0 + 1e-10
            ):
                raise ValueError(f"fitted PLS state has invalid {name}")
            explained[name] = np.maximum(values, 0.0)
        screening = pls_applicability.validate_screening(
            state["diagnostic_state"], features=features, components=effective_components, samples=reference_samples
        )
        return {
            "serializer": FITTED_PLS_STATE_SERIALIZER,
            "algorithm_id": ALGORITHM_ID,
            "algorithm_version": ALGORITHM_VERSION,
            "n_components": components,
            "effective_n_components": effective_components,
            "scale": state["scale"],
            "reference_samples": reference_samples,
            "features": features,
            "targets": targets,
            "response_identity": response_identity,
            "input_identity": input_identity,
            "diagnostic_state": screening,
            "feature_axis_values_sha256": state["feature_axis_values_sha256"],
            "feature_axis_labels_sha256": state["feature_axis_labels_sha256"],
            "feature_axis_units": state["feature_axis_units"],
            "feature_axis_quantity": axis_quantity,
            "coefficients": coefficients.tolist(),
            "feature_offset": feature_offset.tolist(),
            "prediction_offset": prediction_offset.tolist(),
            "vip_scores": vip_scores.tolist(),
            "x_explained_variance": explained["x_explained_variance"].tolist(),
            "y_explained_variance": explained["y_explained_variance"].tolist(),
        }

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]) -> np.ndarray:
        normalized = self.validate_fitted_state(state)
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        X = to_numpy_2d(dataset, name="input_data", dtype=np.float64)
        if not np.isfinite(X).all():
            raise ValueError("fitted PLS apply input or state dimensions are invalid")
        features = _positive_int(normalized["features"], name="features")
        targets = _positive_int(normalized["targets"], name="targets")
        coefficients = _finite_matrix(normalized["coefficients"], name="coefficients", rows=features, columns=targets)
        feature_offset = _finite_matrix(
            normalized["feature_offset"],
            name="feature_offset",
            rows=1,
            columns=features,
        )
        prediction_offset = _finite_matrix(
            normalized["prediction_offset"],
            name="prediction_offset",
            rows=1,
            columns=targets,
        )
        if X.shape[1] != features:
            raise ValueError("fitted PLS apply input does not match the fitted feature count")
        if _feature_axis_identity(dataset, features=features) != (
            normalized["feature_axis_values_sha256"],
            normalized["feature_axis_labels_sha256"],
            normalized["feature_axis_units"],
            normalized["feature_axis_quantity"],
        ):
            raise ValueError("fitted PLS apply input does not match the fitted feature axis")
        require_fitted_input_identity(dataset, normalized["input_identity"], features=features)
        return apply_pls_affine_state(
            X,
            coefficients=coefficients,
            feature_offset=feature_offset,
            prediction_offset=prediction_offset,
        )

    def _execute_sync(self, input_data: Any = None, y: object = None) -> NodeResult:
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        target = bind_y(
            y,
            X=dataset,
            required=True,
            infer_from_X=True,
            dataset_as_data=True,
            target_type="continuous",
            missing_message="fitted PLS requires training targets",
        )
        dataset, _X, target_matrix, model, state = self._fit_model_and_state(
            dataset, target, response_source=dataset if y is None else y, response_is_embedded=y is None
        )
        from .saved_native_model import build_native_model_artifact

        envelope = make_fitted_pls_state_envelope(state)
        artifact = build_native_model_artifact(self, dataset, state)
        predictions = self.apply_fitted_state(dataset, state)
        response_identity = cast(dict[str, object], state["response_identity"])
        target_names = cast(list[str] | None, response_identity["names"])
        explained_variance = np.column_stack((model.x_explained_variance, model.y_explained_variance))
        return NodeResult(
            outputs={
                "default": predictions,
                "fitted_state": envelope,
                "_model_artifact": artifact,
                "vip_scores": np.asarray(state["vip_scores"], dtype=np.float64),
                "calibration_comparison": regression_comparison.build_regression_comparison(
                    target_matrix,
                    predictions,
                    role="calibration",
                    target_names=target_names,
                ),
                "x_scores": np.asarray(model.x_scores, dtype=np.float64),
                "x_loadings": np.asarray(model.x_loadings.T, dtype=np.float64),
                "explained_variance": explained_variance,
                "regression_coefficients": np.asarray(model.coefficients, dtype=np.float64),
            },
            diagnostics={
                "fitted_state_serializer": FITTED_PLS_STATE_SERIALIZER,
                "response_identity": response_identity,
                "algorithm_id": ALGORITHM_ID,
                "algorithm_version": ALGORITHM_VERSION,
                "requested_n_components": state["n_components"],
                "effective_n_components": state["effective_n_components"],
                "x_explained_variance": state["x_explained_variance"],
                "y_explained_variance": state["y_explained_variance"],
                "vip_method": "mdatools_combined",
            },
        )

    async def execute(self, input_data: Any = None, y: object = None, **kwargs: Any) -> NodeResult:
        del kwargs
        return self._execute_sync(input_data, y)

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate code that calls the same fitted-state lifecycle authority."""

        del use_scp
        input_expression = inputs.get("default", next(iter(inputs.values()), "input_data"))
        parameters = self._resolve_params()
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import execute_fitted_pls_v2",
            f"{indent}results[{self.node_id!r}] = execute_fitted_pls_v2(",
            f"{indent}    {input_expression}, {inputs.get('y', 'None')},",
            f"{indent}    node_id={self.node_id!r}, parameters={parameters!r},",
            f"{indent}).outputs",
        ]


def execute_fitted_pls_v2(
    input_data: Any,
    y: object,
    *,
    node_id: str,
    parameters: dict[str, object],
) -> NodeResult:
    """Execute the live and generated producer through one implementation."""

    return FittedPLSV2Node(node_id, parameters)._execute_sync(input_data, y)


bind_stable_execution_contract(
    FittedPLSV2Node,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_MODEL,
    implementation_id="spectrasherpa.simpls.pls_regression",
    implementation_version="9.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(
        ManagedOptimizationEligibility.LOCAL,
        ManagedOptimizationEligibility.DEVELOPMENT,
        ManagedOptimizationEligibility.FULL_REFIT,
    ),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/regression.md",
    implementation_modules=(pls_core, _vip, regression_comparison, pls_applicability, saved_native_model),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    managed_optimization_profiles=("first_party_pls",),
    fitted_state_serializer=FITTED_PLS_STATE_SERIALIZER,
    citations=(
        "de Jong, Chemometrics and Intelligent Laboratory Systems 18 (1993) 251-263, DOI 10.1016/0169-7439(93)85002-X",
        "Chong and Jun, Chemometrics and Intelligent Laboratory Systems 78 (2005) 103-112",
        "mdatools vipscores reference, https://mda.tools/docs/pls--variable-selection.html",
    ),
    target_access="fit_only",
    supervised_task="regression",
)


__all__ = [
    "FITTED_PLS_STATE_SERIALIZER",
    "FittedPLSV2Node",
    "execute_fitted_pls_v2",
    "make_fitted_pls_state_envelope",
    "verify_fitted_pls_state_envelope",
]
