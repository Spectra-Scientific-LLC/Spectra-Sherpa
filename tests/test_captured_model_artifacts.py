"""Captured readers retain exact immutable bytes without ambient file access."""

import hashlib
import io
import json
import pickle
import zipfile

import numpy as np
import pytest

from spectra_sherpa.core.captured_model_artifacts import CapturedModelArtifact, CapturedModelArtifacts
from spectra_sherpa.core.model_artifact import ModelArtifactIntegrityError


def envelope(uid="captured", *, payload=None, **changes):
    if payload is None:
        buffer = io.BytesIO()
        np.savez_compressed(buffer, weights=np.arange(6.0).reshape(2, 3))
        payload = buffer.getvalue()
    manifest = {
        "artifact_uid": uid,
        "artifact_authority": "workbench_native_or_imported_model",
        "integrity_hash": hashlib.sha256(payload).hexdigest(),
        **changes,
    }
    return CapturedModelArtifact(uid, json.dumps(manifest).encode(), payload)


def test_pickled_worker_reader_returns_fresh_copies_without_storage():
    captured = envelope()
    reader = pickle.loads(pickle.dumps(CapturedModelArtifacts((captured,))))
    reader.require_exact_ids(("captured",))
    manifest, arrays = reader.load("captured")
    manifest["artifact_uid"] = "mutated"
    arrays["weights"][:] = -1
    again, fresh = reader.load("captured", verify=False)
    assert again["artifact_uid"] == "captured"
    np.testing.assert_array_equal(fresh["weights"], np.arange(6.0).reshape(2, 3))
    with pytest.raises(FileNotFoundError):
        reader.load("ambient")


@pytest.mark.parametrize("admitted", [None, (), ("other",), ("captured", "extra")])
def test_inventory_must_equal_admitted_ids(admitted):
    with pytest.raises(ValueError, match="match"):
        CapturedModelArtifacts((envelope(),)).require_exact_ids(admitted)


def test_inventory_rejects_duplicates_mutability_and_aggregate_budget(monkeypatch):
    captured = envelope()
    with pytest.raises(ValueError, match="repeats"):
        CapturedModelArtifacts((captured, captured))
    with pytest.raises(ValueError, match="immutable"):
        CapturedModelArtifacts([captured])
    with pytest.raises(TypeError, match="unsupported"):
        CapturedModelArtifacts((object(),))
    monkeypatch.setattr("spectra_sherpa.core.captured_model_artifacts.MAX_CAPTURED_MODEL_BYTES", 1)
    with pytest.raises(ValueError, match="aggregate"):
        CapturedModelArtifacts((captured,))


@pytest.mark.parametrize("change", [{"integrity_hash": "wrong"}, {"artifact_authority": "unknown"}])
def test_existing_integrity_and_authority_cannot_be_bypassed(change):
    with pytest.raises(ModelArtifactIntegrityError):
        envelope(**change)


def test_rejects_mutable_bytes_missing_identity_and_mismatched_uid():
    original = envelope()
    with pytest.raises(TypeError, match="immutable"):
        CapturedModelArtifact("captured", bytearray(original.manifest_bytes), original.arrays_bytes)
    with pytest.raises(ValueError, match="identity"):
        CapturedModelArtifact(None, original.manifest_bytes, original.arrays_bytes)
    with pytest.raises(ModelArtifactIntegrityError, match="mismatch"):
        CapturedModelArtifact("other", original.manifest_bytes, original.arrays_bytes)


@pytest.mark.parametrize("kind", ["object", "duplicate", "path", "allocation"])
def test_refuses_unsafe_npz_before_numpy_allocation(kind):
    array = io.BytesIO()
    if kind == "allocation":
        np.lib.format.write_array_header_1_0(array, {"descr": "<f8", "fortran_order": False, "shape": (2**40,)})
    else:
        np.save(array, np.array([object()]) if kind == "object" else np.arange(3.0))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        name = "../weights.npy" if kind == "path" else "weights.npy"
        archive.writestr(name, array.getvalue())
        if kind == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr(name, array.getvalue())
    with pytest.raises(ModelArtifactIntegrityError):
        envelope(payload=buffer.getvalue())


def test_runtime_uses_same_captured_reader_in_parent_and_worker():
    from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime

    reader = CapturedModelArtifacts((envelope(),))
    runtime = build_application_execution_runtime(
        allowed_model_artifact_uids=("captured",), captured_model_artifacts=reader
    )
    assert runtime.model_artifact_reader is reader
    assert runtime.for_worker(("read_model_artifact",)).model_artifact_reader is reader
    with pytest.raises(ValueError, match="match"):
        build_application_execution_runtime(allowed_model_artifact_uids=(), captured_model_artifacts=reader)
    with pytest.raises(ValueError, match="concrete"):
        build_application_execution_runtime(
            allowed_model_artifact_uids=("captured",), captured_model_artifacts=object()
        )


@pytest.mark.asyncio
async def test_canonical_spawned_application_uses_capture_after_live_files_deleted(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.dag.executor import DAGExecutor
    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool, get_default_pool, set_default_pool
    from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
    from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime
    from spectra_sherpa.app.services.model_store import ModelStore
    from tests.test_model_training_source_persistence import fitted

    store = ModelStore(tmp_path)
    with monkeypatch.context() as patch:
        saved = await fitted(store, None, patch)
    uid = saved["artifact_uid"]
    directory = Path(store.artifact_directory(uid))
    captured = CapturedModelArtifacts(
        (
            CapturedModelArtifact(
                uid, (directory / "manifest.json").read_bytes(), (directory / "arrays.npz").read_bytes()
            ),
        )
    )
    data = SherpaDataset(
        X=np.random.default_rng(127).normal(size=(3, 4)),
        feature_axis=SpectralAxis(values=np.arange(4.0) + 1000, units="nm"),
        sample_axis=SampleAxis(labels=["new-1", "new-2", "new-3"]),
    )

    async def apply():
        executor = DAGExecutor(
            runtime=build_application_execution_runtime(
                allowed_model_artifact_uids=(uid,), captured_model_artifacts=captured
            )
        )
        executor.add_node(WorkflowNode("source", "deploy.input", {"stream_name": "inference"}))
        executor.add_node(WorkflowNode("apply", "model.load_apply", {"model_id": uid}))
        executor.add_edge(WorkflowEdge("source", "apply", "default", "X_new"))
        executor.inject_deployment_input("source", data, stream_name="inference")
        return await executor.execute()

    old_pool, pool = get_default_pool(), IsolatedWorkerPool(1)
    try:
        set_default_pool(None)
        expected = await apply()
        shutil.rmtree(directory)
        set_default_pool(pool)
        actual = await apply()
        np.testing.assert_allclose(actual["apply"]["result"], expected["apply"]["result"], rtol=1e-12, atol=1e-12)
        assert actual["apply"]["model_id"] == uid
        assert not pool._active
    finally:
        pool.shutdown()
        set_default_pool(old_pool)


def test_aggregate_decoded_budget_counts_compressed_models_together(monkeypatch):
    first, second = envelope("first"), envelope("second")
    monkeypatch.setattr("spectra_sherpa.core.captured_model_artifacts.MAX_DECODED_MODEL_BYTES", first.decoded_bytes)
    with pytest.raises(ValueError, match="aggregate decoded"):
        CapturedModelArtifacts((first, second))
