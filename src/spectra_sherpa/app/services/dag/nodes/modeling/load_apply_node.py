"""
Apply Saved Model Artifact node — generic model-artifact loading and inference.

Loads a persisted model artifact (manifest + arrays) and applies it to inference data.
Works with all model types: PCA, PLS, MCR, SIMPLISMA, PLSDA, KNN, SIMCA.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Any

import numpy as np

from spectra_sherpa.app.lib import fitted_state, model_extract_registry
from spectra_sherpa.app.lib import pca as pca_authority
from spectra_sherpa.app.lib.model_extract_registry import EXTRACT_REGISTRY
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag import classification_application
from spectra_sherpa.app.services.dag.classification_application import (
    CLASS_RESPONSE_SEMANTICS,
    validate_classification_application,
)
from spectra_sherpa.app.services.dag.nodes.classification import plsda_state as plsda_state_authority
from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import (
    CANONICAL_MODEL_ORIGIN,
    SherpaPLSDAArtifact,
    canonical_model_validation_required,
)
from spectra_sherpa.app.services.dag.nodes.preprocessing import (
    _shared as preprocessing_shared,
)
from spectra_sherpa.app.services.dag.nodes.preprocessing import (
    derivative_node,
    emsc_node,
    normalize_node,
    penalized_baseline_node,
    scale_node,
    smooth_node,
)
from spectra_sherpa.app.services.dag.nodes.selection import variable_select_node
from spectra_sherpa.core import execution_runtime as execution_runtime_contract
from spectra_sherpa.core import model_artifact as model_artifact_contract
from spectra_sherpa.core.model_artifact import ModelArtifactIntegrityError
from spectra_sherpa.execution_contract_vocabulary import (
    DatasetRankPolicy,
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    PortMetadata,
    register_node,
)
from ...stable_execution_contract import bind_stable_execution_contract
from . import saved_native_model

logger = logging.getLogger(__name__)

# Model types that support prediction (classification/regression)
_PREDICT_TYPES = {"pls", "pcr", "linear_regression", "svr", "plsda", "knn", "simca"}
# Model types that support transform (decomposition)
_TRANSFORM_TYPES = {"pca", "mcr", "simplisma", "nmf", "fastica"}
# Model types that are diagnostic only (no prediction/transform on new data)
_DIAGNOSTIC_TYPES = {"efa"}

# Map model types to their output category
_OUTPUT_TYPE_MAP = {
    "pca": "decomposition",
    "pls": "regression",
    "pcr": "regression",
    "linear_regression": "regression",
    "svr": "regression",
    "mcr": "decomposition",
    "nmf": "decomposition",
    "fastica": "decomposition",
    "simplisma": "decomposition",
    "plsda": "classification",
    "knn": "classification",
    "simca": "classification",
}

_APPLICATION_DISPATCH_SERIALIZER = "spectrasherpa.model-artifact.application-dispatch/1"


def _finite_result_matrix(value: Any, *, model_type: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)
    if matrix.ndim != 2 or not np.isfinite(matrix).all():
        raise ValueError(f"{model_type} application did not produce a finite two-dimensional result")
    return matrix


def _apply_model_artifact(
    manifest: dict[str, Any],
    arrays: dict[str, np.ndarray],
    X_new: Any,
    *,
    model_id: str | None,
    replay: execution_runtime_contract.ModelArtifactReplay,
    semantic_validator: execution_runtime_contract.ModelArtifactSemanticValidator | None = None,
) -> dict[str, Any]:
    """Apply one verified saved artifact through the sole model-type adapter registry."""

    artifact_uid = manifest.get("artifact_uid")
    if not isinstance(artifact_uid, str) or not artifact_uid or artifact_uid != artifact_uid.strip():
        raise ValueError("model artifact manifest has no valid artifact_uid")
    if model_id is not None and model_id != artifact_uid:
        raise ValueError(
            f"model artifact identity mismatch (requested {model_id!r}, manifest declares {artifact_uid!r})"
        )
    model_type = manifest.get("model_type", "")
    if not isinstance(model_type, str) or not model_type:
        raise ValueError("model artifact has no valid model_type")
    if model_type in _DIAGNOSTIC_TYPES:
        raise ValueError(f"{model_type.upper()} is diagnostic only — it cannot be applied to new data")
    extract_cls = SherpaPLSDAArtifact if model_type == "plsda" else EXTRACT_REGISTRY.get(model_type)
    from .saved_native_model import has_native_model_state

    native_state = has_native_model_state(manifest, arrays)
    if extract_cls is None and not native_state:
        raise ValueError(f"Unsupported model type: '{model_type}'")
    if canonical_model_validation_required(manifest):
        if manifest.get("artifact_origin") != CANONICAL_MODEL_ORIGIN:
            raise ValueError("canonical model markers require the exact imported full-refit origin")
        if semantic_validator is None:
            raise ValueError("canonical model semantic admission is required before application")
        semantic_validator.validate(manifest, arrays)
        if model_type != "plsda":
            raise ValueError("canonical full-refit bridge is supported only for native PLS-DA artifacts")

    if isinstance(X_new, SherpaDataset):
        X_data = np.asarray(X_new.data, dtype=np.float64)
    elif isinstance(X_new, np.ndarray):
        X_data = np.asarray(X_new, dtype=np.float64)
    elif hasattr(X_new, "data"):
        X_data = np.asarray(X_new.data, dtype=np.float64)
    else:
        raise ValueError("X_new must be a SherpaDataset or numpy array")
    if X_data.ndim == 1:
        X_data = X_data.reshape(1, -1)

    if native_state and model_type == "parafac":
        from .saved_native_model import apply_saved_native_model

        # Multiway input retains every axis; two-dimensional preprocessing
        # replay must not reinterpret it as rows and columns.
        if manifest.get("preprocessing_chain"):
            # Use the same typed replay authority; unsupported multiway steps
            # must not silently disappear from a saved application.
            X_new, _ = replay.prepare_dataset(X_data, X_new, manifest)
            X_data = np.asarray(X_new.X)
        return apply_saved_native_model(manifest, arrays, X_new, X_data)
    if X_data.ndim != 2:
        raise ValueError("This saved model requires two-dimensional application data")
    if native_state:
        X_new, replay_warnings = replay.prepare_dataset(X_data, X_new, manifest)
        X_data = np.asarray(X_new.X)
    else:
        X_data, replay_warnings = replay.prepare(X_data, X_new, manifest)
    for warning in replay_warnings:
        logger.warning("Load & Apply %s: %s", artifact_uid, warning)

    if native_state:
        from .saved_native_model import apply_saved_native_model

        return apply_saved_native_model(manifest, arrays, X_new, X_data)

    extract = extract_cls.from_artifact(manifest, arrays)  # type: ignore[attr-defined]
    if model_type == "plsda":
        extract.validate_application_features(X_new, feature_mask=manifest.get("feature_mask"))
    result: dict[str, Any] = {"model_id": artifact_uid}
    metadata: dict[str, Any] = {
        "type": model_type.upper(),
        "output_type": _OUTPUT_TYPE_MAP.get(model_type, "unknown"),
    }
    if model_type in _TRANSFORM_TYPES:
        transformed = _finite_result_matrix(extract.transform(X_data), model_type=model_type)
        result.update(result=transformed, transformed=transformed)
    elif model_type in {"pls", "pcr", "linear_regression", "svr"}:
        predicted = _finite_result_matrix(extract.predict(X_data), model_type=model_type)
        result.update(result=predicted, y_pred=predicted, predictions=predicted)
        applicability = replay.applicability(extract, X_data)
        if applicability is not None:
            result["applicability"] = applicability
            if applicability.get("unavailable_reason"):
                metadata["applicability_warning"] = (
                    "Applicability unavailable: refit to retain exact projection and screening authority"
                )
            n_out = int(applicability.get("n_out_of_domain", 0) or 0)
            if n_out:
                metadata["applicability_warning"] = (
                    f"{n_out} sample{'s' if n_out != 1 else ''} outside saved model applicability domain"
                )
    elif model_type in _PREDICT_TYPES:
        labels, numeric_output = extract._predict_matrix(X_data) if model_type == "plsda" else extract.predict(X_data)
        numeric_matrix = _finite_result_matrix(numeric_output, model_type=model_type)
        result.update(result=numeric_matrix, labels=list(labels))
        metadata["classes"] = list(extract.classes)
        if model_type == "plsda":
            application = validate_classification_application(
                predictions=labels,
                responses=numeric_matrix,
                classes=extract.classes,
                fitted_state_digest=_plsda_application_state_digest(manifest, extract),
                semantics=CLASS_RESPONSE_SEMANTICS,
            )
            result.update(
                decision_margins=application.margins,
                classification_application_digest=application.application_digest,
            )
            metadata["classification_output_semantics"] = CLASS_RESPONSE_SEMANTICS
            metadata["feature_identity_mode"] = extract.feature_identity_mode
            metadata["feature_identity_verified"] = extract.feature_identity_mode == "typed_axis"
    else:  # EXTRACT_REGISTRY and the lifecycle sets must remain closed together.
        raise ValueError(f"Unsupported application lifecycle for model type: '{model_type}'")
    result["metadata"] = metadata
    return result


@register_node
class LoadApplyModelNode(Node):
    """
    Load a saved model artifact and apply it to new data.

    Resolves the model_id from either:
    1. The ``model_ref`` input port (from a training node's output) — takes priority
    2. The ``model_id`` parameter (user selection from saved models)

    For decomposition models (PCA, MCR, SIMPLISMA): calls ``transform(X)``.
    For regression models (PLS): calls ``predict(X)``.
    For classification models: calls ``predict(X)`` and preserves each model's
    declared numeric semantics. PLS-DA returns class-response scores, not
    probabilities.
    EFA is diagnostic-only and raises an error.
    """

    metadata = NodeMetadata(
        node_type="model.load_apply",
        category="regression",
        label="Apply Saved Model Artifact",
        description="Load a saved model artifact and apply it to inference data",
        parameters=[
            NodeParameter(
                name="model_id",
                label="Artifact",
                param_type="model_select",
                description="Saved model artifact to load and apply",
                required=False,
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X_new",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Inference Data",
                description="Spectral data to apply the saved artifact to",
            ),
            PortMetadata(
                name="model_ref",
                type_ref="spectrasherpa://types/ModelReference/1.0",
                required=False,
                label="Artifact Reference",
                description="Artifact ID from a training node or saved model artifact (overrides parameter)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="result",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Applied Result Matrix",
                description="Predictions, class responses/probabilities, or decomposition scores",
            ),
            PortMetadata(
                name="labels",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=False,
                label="Labels",
                description="Predicted class labels (classification models only)",
            ),
            PortMetadata(
                name="model_id",
                type_ref="spectrasherpa://types/ModelReference/1.0",
                required=True,
                label="Artifact ID",
                description="Artifact UID of the loaded model (for provenance tracing)",
            ),
        ],
        input_types=["SpectralDataset"],
        output_type="array",
        policy=NodePolicy(required_worker_capabilities=["read_model_artifact"]),
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate an editable artifact-path wrapper around the live application operation."""
        del use_scp
        X_expr = inputs.get("X_new", inputs.get("default", "input_data"))
        model_id = self.parameters.get("model_id", "")
        connected_model_ref = inputs.get("model_ref")
        expected_identity = connected_model_ref if connected_model_ref is not None else repr(model_id or None)
        return [
            f"{indent}# --- Apply Saved Model Artifact ({self.node_id}) ---",
            f"{indent}# >>> EDIT: provide path to model artifact directory <<<",
            f"{indent}# Original model_id: {model_id!r}",
            f"{indent}from pathlib import Path as _Path",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import _apply_model_artifact",
            f"{indent}from spectra_sherpa.core.model_artifact import load_verified_artifact_directory",
            f"{indent}from spectra_sherpa.app.services.execution_runtime import (",
            f"{indent}    ApplicationModelArtifactReplay, ApplicationModelArtifactSemanticValidator,",
            f"{indent})",
            f"{indent}_mdir = _Path('path/to/model/artifact')  # EDIT THIS",
            f"{indent}_manifest, _arrays = load_verified_artifact_directory(_mdir)",
            f"{indent}results[{self.node_id!r}] = _apply_model_artifact(",
            f"{indent}    _manifest, _arrays, {X_expr}, model_id={expected_identity},",
            f"{indent}    replay=ApplicationModelArtifactReplay(),",
            f"{indent}    semantic_validator=ApplicationModelArtifactSemanticValidator(),",
            f"{indent})",
        ]

    async def execute(self, X_new: Any = None, model_ref: Any = None, **kwargs: Any) -> dict[str, Any]:
        # --- Resolve model_id ---
        model_id = self._resolve_model_id(model_ref)

        # --- Load artifact ---
        store = self.require_execution_runtime().require_model_artifact_reader()
        try:
            # verify=True (default): a corrupt/truncated npz raises
            # ModelArtifactIntegrityError rather than silently applying
            # wrong arrays to new data.
            manifest, arrays = store.load(model_id)
        except FileNotFoundError:
            raise ValueError(f"Model artifact '{model_id}' not found")
        except ModelArtifactIntegrityError as exc:
            raise ValueError(
                f"Model artifact '{model_id}' is corrupt and cannot be applied: {exc}. Re-train or re-import the model."
            ) from exc

        semantic_validator = None
        if canonical_model_validation_required(manifest):
            semantic_validator = self.require_execution_runtime().require_model_artifact_semantic_validator()
        replay = self.require_execution_runtime().require_model_artifact_replay()
        return _apply_model_artifact(
            manifest,
            arrays,
            X_new,
            model_id=model_id,
            replay=replay,
            semantic_validator=semantic_validator,
        )

    def _resolve_model_id(self, model_ref: Any) -> str:
        """Resolve model_id from port value or parameter, port takes priority."""
        # Port value takes priority
        if model_ref is not None:
            if isinstance(model_ref, str) and model_ref:
                return model_ref
            if isinstance(model_ref, dict) and model_ref.get("model_id"):
                return str(model_ref["model_id"])

        # Fall back to parameter
        param_id = self.parameters.get("model_id", "")
        if param_id:
            return str(param_id)

        raise ValueError("No model specified — provide a model_id parameter or connect a model_ref input")


def _plsda_application_state_digest(manifest: Mapping[str, Any], extract: SherpaPLSDAArtifact) -> str:
    """Return the canonical application-state identity, independent of storage UID."""

    lineage = manifest.get("canonical_training_lineage")
    if isinstance(lineage, Mapping):
        digest = lineage.get("application_state_digest")
        if (
            isinstance(digest, str)
            and len(digest) == 64
            and digest == digest.lower()
            and all(char in "0123456789abcdef" for char in digest)
        ):
            return digest
        raise ValueError("canonical PLS-DA lineage has no valid application-state identity")
    encoded = json.dumps(
        extract.to_fitted_state(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


bind_stable_execution_contract(
    LoadApplyModelNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.ARTIFACT_APPLICATION,
    implementation_id="spectrasherpa.model.load_apply",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_MODEL_ARTIFACT,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/regression.md",
    implementation_modules=(
        model_extract_registry,
        saved_native_model,
        pca_authority,
        fitted_state,
        classification_application,
        plsda_state_authority,
        execution_runtime_contract,
        model_artifact_contract,
        preprocessing_shared,
        derivative_node,
        emsc_node,
        normalize_node,
        penalized_baseline_node,
        scale_node,
        smooth_node,
        variable_select_node,
    ),
    implementation_distributions=("numpy", "scipy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
    fitted_state_serializer=_APPLICATION_DISPATCH_SERIALIZER,
    input_rank_policy=DatasetRankPolicy.PROJECTS_TO_2D,
)


__all__ = ["LoadApplyModelNode", "_apply_model_artifact"]
