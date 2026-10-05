"""C2h canonical saved-model application contract and execution proofs."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.fitted_state import (
    LinearRegressionExtract,
    NMFExtract,
    PCRExtract,
    SVRExtract,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import CANONICAL_MODEL_ORIGIN
from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import (
    LoadApplyModelNode,
    _apply_model_artifact,
)
from spectra_sherpa.app.services.execution_runtime import ApplicationModelArtifactReplay
from spectra_sherpa.app.services.model_store import ModelStore
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.core.model_artifact import (
    CANONICAL_MODEL_ARTIFACT_AUTHORITY,
    ORDINARY_MODEL_ARTIFACT_AUTHORITY,
    ModelArtifactIntegrityError,
    ReadOnlyModelArtifactReader,
    load_verified_artifact_directory,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling

_REPLAY = ApplicationModelArtifactReplay()


def _declare_ordinary(manifest: dict[str, object]) -> None:
    manifest["artifact_authority"] = ORDINARY_MODEL_ARTIFACT_AUTHORITY


def _application_matrix() -> np.ndarray:
    return np.array([[1.0, 2.0], [2.5, -1.0], [-0.5, 3.0]], dtype=np.float64)


def test_saved_model_application_has_one_exact_local_contract() -> None:
    metadata = node_registry.get_metadata("model.load_apply")
    contract = metadata.resolved_execution_contract()
    assert contract is not None
    assert contract.payload["operation_id"] == "model.load_apply"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.ARTIFACT_APPLICATION.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["fitted_state_serializer"] == "spectrasherpa.model-artifact.application-dispatch/1"
    assert contract.payload["required_worker_capabilities"] == ("read_model_artifact",)
    assert contract.payload["runtime_requirements"] == (
        {"distribution": "numpy", "version": "1.26.4"},
        {"distribution": "scikit-learn", "version": "1.9.0"},
        {"distribution": "scipy", "version": "1.17.1"},
    )
    assert {component["component_id"] for component in contract.payload["implementation_components"]} == {
        "distribution.numpy",
        "distribution.scipy",
        "distribution.scikit-learn",
        "spectra_sherpa.app.lib.fitted_state",
        "spectra_sherpa.app.lib.model_extract_registry",
        "spectra_sherpa.app.lib.pca",
        "spectra_sherpa.app.services.dag.classification_application",
        "spectra_sherpa.app.services.dag.nodes.classification.plsda_state",
        "spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node",
        "spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model",
        "spectra_sherpa.app.services.dag.nodes.preprocessing._shared",
        "spectra_sherpa.app.services.dag.nodes.preprocessing.derivative_node",
        "spectra_sherpa.app.services.dag.nodes.preprocessing.emsc_node",
        "spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node",
        "spectra_sherpa.app.services.dag.nodes.preprocessing.penalized_baseline_node",
        "spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node",
        "spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_node",
        "spectra_sherpa.app.services.dag.nodes.selection.variable_select_node",
        "spectra_sherpa.core.execution_runtime",
        "spectra_sherpa.core.model_artifact",
    }
    assert [(port.name, port.type_ref) for port in metadata.output_ports or ()] == [
        ("result", "spectrasherpa://types/Array2D/1.0"),
        ("labels", "spectrasherpa://types/Categorical/1.0"),
        ("model_id", "spectrasherpa://types/ModelReference/1.0"),
    ]


def test_saved_model_application_dispatches_regression_artifacts_without_shape_drift() -> None:
    matrix = _application_matrix()
    extracts = (
        LinearRegressionExtract(
            coef=np.array([2.0, -1.0]),
            intercept=np.array([0.5]),
            fit_intercept=True,
        ),
        PCRExtract(
            pca_components=np.array([[1.0, 0.0]]),
            pca_mean=np.zeros(2),
            reg_coef=np.array([1.5]),
            reg_intercept=np.array([-0.25]),
            n_components=1,
        ),
        SVRExtract(
            support_vectors=np.array([[0.0, 0.0], [1.0, 1.0]]),
            dual_coef=np.array([-0.5, 0.5]),
            intercept=0.2,
            kernel="linear",
            gamma=0.5,
            degree=3,
            coef0=0.0,
        ),
    )
    for extract in extracts:
        manifest, arrays = extract.to_artifact()
        _declare_ordinary(manifest)
        artifact_uid = f"artifact-{manifest['model_type']}"
        manifest["artifact_uid"] = artifact_uid
        manifest["n_features"] = matrix.shape[1]
        result = _apply_model_artifact(manifest, arrays, matrix, model_id=artifact_uid, replay=_REPLAY)
        expected = np.asarray(extract.predict(matrix), dtype=np.float64)
        if expected.ndim == 1:
            expected = expected.reshape(-1, 1)
        assert result["result"].shape == (matrix.shape[0], expected.shape[1])
        np.testing.assert_allclose(result["result"], expected, rtol=0.0, atol=0.0)
        assert result["result"] is result["predictions"] is result["y_pred"]


def test_saved_model_application_has_a_representative_absolute_performance_ceiling() -> None:
    rng = np.random.default_rng(504)
    matrix = rng.normal(size=(200, 1_600))
    extract = LinearRegressionExtract(
        coef=rng.normal(size=1_600),
        intercept=np.array([0.5]),
        fit_intercept=True,
    )
    manifest, arrays = extract.to_artifact()
    _declare_ordinary(manifest)
    manifest["artifact_uid"] = "representative-ols-artifact"
    manifest["n_features"] = matrix.shape[1]

    with PerformanceCeiling("model.load_apply", "200x1600-linear-regression-replay", 5.0).measure():
        result = _apply_model_artifact(
            manifest,
            arrays,
            matrix,
            model_id="representative-ols-artifact",
            replay=_REPLAY,
        )

    assert result["result"].shape == (200, 1)


def test_generated_application_calls_the_live_dispatcher(tmp_path) -> None:
    matrix = _application_matrix()
    extract = LinearRegressionExtract(
        coef=np.array([2.0, -1.0]),
        intercept=np.array([0.5]),
        fit_intercept=True,
    )
    manifest, arrays = extract.to_artifact()
    _declare_ordinary(manifest)
    manifest["artifact_uid"] = "ols-artifact"
    manifest["n_features"] = matrix.shape[1]
    np.savez(tmp_path / "arrays.npz", **arrays)
    manifest["integrity_hash"] = hashlib.sha256((tmp_path / "arrays.npz").read_bytes()).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    node = LoadApplyModelNode("apply", {"model_id": "ols-artifact"})
    source = "\n".join(node.generate_python({"X_new": "matrix"}, indent=""))
    assert "_apply_model_artifact" in source
    assert "if _model_type" not in source
    assert "model_id='ols-artifact'" in source
    # The editable wrapper deliberately publishes an OS-neutral forward-slash
    # path. Windows accepts that spelling, while embedding ``str(tmp_path)``
    # would turn ``C:\\Users`` into a Python ``\\U`` escape before execution.
    source = source.replace("path/to/model/artifact", tmp_path.as_posix())
    namespace = {"matrix": matrix, "np": np, "results": {}}
    exec(source, namespace)  # noqa: S102 - generated-Python conformance proof

    expected = _apply_model_artifact(manifest, arrays, matrix, model_id="ols-artifact", replay=_REPLAY)
    np.testing.assert_allclose(namespace["results"]["apply"]["result"], expected["result"], rtol=0.0, atol=0.0)
    assert namespace["results"]["apply"]["model_id"] == "ols-artifact"

    (tmp_path / "arrays.npz").write_bytes((tmp_path / "arrays.npz").read_bytes() + b"tampered")
    with pytest.raises(ModelArtifactIntegrityError, match="hash mismatch"):
        load_verified_artifact_directory(tmp_path)


def test_generated_application_preserves_connected_expected_identity() -> None:
    node = LoadApplyModelNode("apply", {})
    source = "\n".join(
        node.generate_python(
            {
                "X_new": "matrix",
                "model_ref": "results['fit']['model_id']",
            },
            indent="",
        )
    )

    assert "model_id=results['fit']['model_id']" in source


def test_application_identity_is_manifest_authoritative() -> None:
    matrix = _application_matrix()
    extract = LinearRegressionExtract(
        coef=np.array([2.0, -1.0]),
        intercept=np.array([0.5]),
        fit_intercept=True,
    )
    manifest, arrays = extract.to_artifact()
    _declare_ordinary(manifest)
    manifest.update(artifact_uid="artifact-authority", n_features=matrix.shape[1])

    derived = _apply_model_artifact(manifest, arrays, matrix, model_id=None, replay=_REPLAY)
    assert derived["model_id"] == "artifact-authority"
    with pytest.raises(ValueError, match="identity mismatch"):
        _apply_model_artifact(manifest, arrays, matrix, model_id="stale-caller-label", replay=_REPLAY)

    manifest.pop("artifact_uid")
    with pytest.raises(ValueError, match="artifact_uid"):
        _apply_model_artifact(manifest, arrays, matrix, model_id=None, replay=_REPLAY)


@pytest.mark.asyncio
async def test_live_node_requires_semantic_admission_before_application() -> None:
    matrix = _application_matrix()
    extract = LinearRegressionExtract(
        coef=np.array([2.0, -1.0]),
        intercept=np.array([0.5]),
        fit_intercept=True,
    )
    manifest, arrays = extract.to_artifact()
    manifest.update(
        artifact_authority=CANONICAL_MODEL_ARTIFACT_AUTHORITY,
        artifact_uid="semantic-refusal",
        artifact_origin=CANONICAL_MODEL_ORIGIN,
        canonical_training_lineage={},
        classification_output_semantics="class_response_scores_not_probabilities",
        n_features=matrix.shape[1],
    )

    class _Reader:
        def load(self, artifact_uid: str, *, verify: bool = True):
            assert artifact_uid == "semantic-refusal"
            assert verify is True
            return manifest, arrays

    class _RefusingValidator:
        def validate(self, observed_manifest, observed_arrays) -> None:
            assert observed_manifest is manifest
            assert observed_arrays is arrays
            raise ValueError("semantic authority refused")

    class _UnreachableReplay:
        def prepare(self, *args, **kwargs):
            raise AssertionError("application began before semantic admission")

        def applicability(self, *args, **kwargs):
            raise AssertionError("application began before semantic admission")

    node = LoadApplyModelNode("apply", {"model_id": "semantic-refusal"})
    node.bind_execution_runtime(
        ExecutionRuntime(
            model_artifact_reader=_Reader(),
            model_artifact_replay=_UnreachableReplay(),
            model_artifact_semantic_validator=_RefusingValidator(),
        )
    )

    with pytest.raises(ValueError, match="semantic authority refused"):
        await node.execute(X_new=matrix)


def test_live_artifact_readers_reject_path_manifest_identity_mismatch(tmp_path) -> None:
    store = ModelStore(tmp_path)
    store.save(
        "directory-authority",
        {"model_type": "linear_regression"},
        {"coef": np.array([1.0])},
    )
    manifest_path = tmp_path / "models" / "directory-authority" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_uid"] = "contradictory-manifest-authority"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ModelArtifactIntegrityError, match="identity mismatch"):
        store.load("directory-authority")
    with pytest.raises(ModelArtifactIntegrityError, match="identity mismatch"):
        ReadOnlyModelArtifactReader(tmp_path).load("directory-authority")


def test_nmf_application_fails_instead_of_switching_algorithms(monkeypatch: pytest.MonkeyPatch) -> None:
    from spectra_sherpa.app.lib import nmf_core

    extract = NMFExtract(
        H=np.array([[1.0, 0.5], [0.25, 1.0]]),
        n_components=2,
        solver="cd",
        max_iter=500,
        tol=1e-5,
        random_state=42,
    )

    def fail_canonical_solver(*args: object, **kwargs: object) -> tuple[np.ndarray, np.ndarray, int]:
        del args, kwargs
        raise RuntimeError("declared fixed-basis NMF implementation failed")

    monkeypatch.setattr(nmf_core, "non_negative_factorization", fail_canonical_solver)
    with pytest.raises(RuntimeError, match="declared fixed-basis NMF implementation failed"):
        extract.transform(np.abs(_application_matrix()))


def test_application_rejects_unreplayed_material_provenance() -> None:
    matrix = _application_matrix()
    extract = LinearRegressionExtract(
        coef=np.array([2.0, -1.0]),
        intercept=np.array([0.5]),
        fit_intercept=True,
    )
    manifest, arrays = extract.to_artifact()
    _declare_ordinary(manifest)
    manifest.update(
        artifact_uid="artifact-with-unreplayed-step",
        n_features=matrix.shape[1],
        preprocessing_chain=[
            {"op_id": "data.file_load", "parameters": {"experiment_id": 1, "file_id": 2, "stage": "raw"}},
            {"op_id": "transfer.pds", "parameters": {}},
        ],
    )

    with pytest.raises(ValueError, match="transfer.pds.*no certified artifact-application replay"):
        _apply_model_artifact(
            manifest,
            arrays,
            matrix,
            model_id="artifact-with-unreplayed-step",
            replay=_REPLAY,
        )


def test_model_select_parameter_is_closed_text_identity() -> None:
    assert LoadApplyModelNode("apply", {"model_id": "artifact-001"}).parameters == {"model_id": "artifact-001"}
    for invalid in (True, 7, ["artifact-001"]):
        try:
            LoadApplyModelNode("apply", {"model_id": invalid})
        except ValueError as exc:
            assert "must be text" in str(exc)
        else:  # pragma: no cover - explicit fail message is clearer than a parametrized bare assertion.
            raise AssertionError(f"invalid model identity was admitted: {invalid!r}")
