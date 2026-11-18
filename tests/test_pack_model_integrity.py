"""Pack replay metadata is bound to the ordinary model's existing NPZ custody."""

import json
from copy import deepcopy

import numpy as np
import pytest

from spectra_sherpa.app.services.model_store import ModelStore
from spectra_sherpa.core.captured_model_artifacts import CapturedModelArtifact, CapturedModelArtifacts
from spectra_sherpa.core.model_artifact import (
    ModelArtifactIntegrityError,
    ReadOnlyModelArtifactReader,
    load_verified_artifact_directory,
)
from spectra_sherpa.core.pack_model_integrity import (
    PACK_MODEL_BINDING_ARRAY,
    bind_pack_model_integrity,
    require_pack_model_integrity,
)
from spectra_sherpa.core.pack_requirements import (
    PackNodeBinding,
    PackPreprocessingBinding,
    PackPreprocessingStep,
    preprocessing_chain_digest,
)
from tests.test_pack_manifest import pack


def manifest_with_replay():
    chain = [{"op_id": "preprocess.normalize", "parameters": {"method": "snv"}}] * 2
    producer = PackNodeBinding(
        node_id="pack",
        node_type="pro.reference.record",
        execution_contract_sha256="c" * 64,
        required=(pack().reference,),
    )
    binding = PackPreprocessingBinding(
        chain_sha256=preprocessing_chain_digest(chain),
        steps=tuple(PackPreprocessingStep(step_index=i, producer=producer) for i in range(2)),
    )
    return {
        "model_type": "pca",
        "preprocessing_chain": chain,
        "pack_preprocessing_binding": binding.model_dump(mode="json"),
    }


@pytest.mark.parametrize("alteration", ["remove", "subset", "replace", "chain"])
def test_manifest_only_changes_fail_every_reader_and_direct_application(tmp_path, alteration):
    from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import _apply_model_artifact

    store = ModelStore(tmp_path)
    manifest = manifest_with_replay()
    store.save("retained", manifest, {"mean": np.zeros(3)})
    directory = tmp_path / "models" / "retained"
    original, arrays = store.load("retained")
    assert arrays[PACK_MODEL_BINDING_ARRAY].dtype == np.uint8
    assert arrays[PACK_MODEL_BINDING_ARRAY].shape == (32,)
    changed = deepcopy(original)
    if alteration == "remove":
        changed.pop("pack_preprocessing_binding")
    elif alteration == "subset":
        changed["pack_preprocessing_binding"]["steps"].pop()
    elif alteration == "replace":
        changed["pack_preprocessing_binding"]["steps"][0]["producer"]["required"][0]["build_sha256"] = "b" * 64
    else:
        changed["preprocessing_chain"][0]["parameters"]["method"] = "scale"
    encoded = json.dumps(changed).encode()
    (directory / "manifest.json").write_bytes(encoded)

    def captured_read():
        captured = CapturedModelArtifacts(
            (CapturedModelArtifact("retained", encoded, (directory / "arrays.npz").read_bytes()),)
        )
        return captured.load("retained", verify=False)

    assert store.verify_integrity("retained") is False
    for read in (
        lambda: store.load("retained"),
        lambda: store.load("retained", verify=False),
        lambda: ReadOnlyModelArtifactReader(tmp_path).load("retained", verify=False),
        lambda: load_verified_artifact_directory(directory),
        captured_read,
        lambda: _apply_model_artifact(changed, arrays, np.ones((2, 3)), model_id="retained", replay=None),
    ):
        with pytest.raises(ModelArtifactIntegrityError, match="pack provenance"):
            read()


@pytest.mark.parametrize("marker", [np.zeros(31, dtype=np.uint8), np.zeros(32), np.zeros((1, 32), dtype=np.uint8)])
def test_malformed_marker_cannot_be_replaced(marker):
    with pytest.raises(ModelArtifactIntegrityError, match="marker is malformed"):
        bind_pack_model_integrity(manifest_with_replay(), {PACK_MODEL_BINDING_ARRAY: marker})


def test_legacy_oss_arrays_remain_unchanged_and_missing_marker_is_refused():
    arrays = {"mean": np.zeros(3)}
    assert bind_pack_model_integrity({"model_type": "pca"}, arrays) is arrays
    require_pack_model_integrity({"model_type": "pca"}, arrays)
    with pytest.raises(ModelArtifactIntegrityError, match="no retained custody binding"):
        require_pack_model_integrity(manifest_with_replay(), arrays)


@pytest.mark.parametrize("has_pack_fields", [False, True])
def test_canonical_schema_cannot_hide_a_preexisting_marker(has_pack_fields):
    from spectra_sherpa.core.model_artifact import CANONICAL_MODEL_ARTIFACT_AUTHORITY
    from spectra_sherpa.core.pack_model_integrity import scientific_model_arrays

    manifest = manifest_with_replay() if has_pack_fields else {"model_type": "pca"}
    arrays = bind_pack_model_integrity(manifest_with_replay(), {})
    manifest["artifact_authority"] = CANONICAL_MODEL_ARTIFACT_AUTHORITY
    for consume in (require_pack_model_integrity, bind_pack_model_integrity, scientific_model_arrays):
        with pytest.raises(ModelArtifactIntegrityError, match="explicitly qualified profile"):
            consume(manifest, arrays)


def test_removing_marker_changes_retained_array_checksum(tmp_path):
    store = ModelStore(tmp_path)
    store.save("retained", manifest_with_replay(), {"mean": np.zeros(3)})
    directory = tmp_path / "models" / "retained"
    np.savez_compressed(directory / "arrays.npz", mean=np.zeros(3))
    with pytest.raises(ModelArtifactIntegrityError, match="hash mismatch"):
        store.load("retained")


async def test_pack_processed_model_save_copy_reload_and_actual_application(tmp_path, monkeypatch):
    import shutil

    from spectra_sherpa.app.lib.pca import fit_pca
    from spectra_sherpa.app.services import model_application
    from spectra_sherpa.app.services.dag.fitted_input_identity import fitted_input_identity
    from spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder import _enrich_with_preprocessing
    from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node import NormalizeNode
    from spectra_sherpa.app.services.dag.pack_requirements import PackBindingAdmissionError
    from spectra_sherpa.sdk import data, runtime
    from tests.pack_retention_fixtures import make_retained_registry

    registry = make_retained_registry(monkeypatch, base_node=NormalizeNode)
    source = data.from_array(np.random.default_rng(936).normal(size=(8, 4)), x=np.arange(4.0), units="nm")
    spec, inputs, _ = runtime.operation_workflow(
        "pro.reference.record", parameters={"method": "snv"}, inputs={"default": source}
    )
    processed = (await runtime.execute_workflow_async(spec, deployment_inputs=inputs)).output()
    fitted = fit_pca(processed.X, n_components=2, standardized=False, scaled=False)
    manifest, arrays = fitted.to_artifact()
    manifest["input_identity"] = fitted_input_identity(processed, features=4)
    _enrich_with_preprocessing(manifest, processed)
    store = ModelStore(tmp_path / "original")
    store.save("retained", manifest, arrays)
    destination = tmp_path / "copied"
    shutil.copytree(tmp_path / "original" / "models" / "retained", destination / "models" / "retained")
    loaded_manifest, loaded_arrays = load_verified_artifact_directory(destination / "models" / "retained")
    assert loaded_manifest["pack_preprocessing_binding"] == manifest["pack_preprocessing_binding"]
    assert PACK_MODEL_BINDING_ARRAY in loaded_arrays
    copied_store = ModelStore(destination)
    monkeypatch.setattr(model_application, "get_model_store", lambda: copied_store)
    result = await model_application.apply_model_to_dataset("retained", source)
    np.testing.assert_allclose(result["transformed"], fitted.transform(processed.X), rtol=1e-12, atol=1e-12)
    registry._pack_manifests = (pack(build_sha256="b" * 64),)
    # Inert verified reading remains available; replay requires the retained build.
    assert copied_store.load("retained")[0] == loaded_manifest
    with pytest.raises(ValueError, match="Retained pack bindings") as denied:
        await model_application.apply_model_to_dataset("retained", source)
    assert isinstance(denied.value.__cause__, PackBindingAdmissionError)
