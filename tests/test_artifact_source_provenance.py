"""Reader and replay must agree on source-bound response provenance."""

import pytest

from spectra_sherpa.app.services.artifact_preprocessing_authority import validate_experiment_source_provenance
from spectra_sherpa.core.target_authority import TargetAuthority


def source():
    return dict(
        dataset_id=7,
        file_count=33,
        stage="raw",
        asset_id="spectrum",
        source_manifest_sha256="a" * 64,
        collection_definition_sha256="b" * 64,
        scientific_collection_sha256="c" * 64,
    )


@pytest.mark.parametrize(
    "selection",
    [
        {},
        {"target_mode": "multi"},
        {
            "target_mode": "single",
            "target_authority": TargetAuthority(
                column="CO2", target_type="continuous", units="ppm", source_digest="c" * 64
            ).canonical_dict(),
        },
    ],
)
def test_reader_provenance_admits_closed_response_selection(selection):
    validate_experiment_source_provenance({**source(), **selection})


@pytest.mark.parametrize(
    "selection",
    [
        {"target_mode": "single"},
        {"unknown": True},
        {"target_mode": "single", "target_authority": None},
        {
            "target_mode": "multi",
            "target_authority": TargetAuthority(
                column="CO2", target_type="continuous", source_digest="c" * 64
            ).canonical_dict(),
        },
        {
            "target_mode": "single",
            "target_authority": TargetAuthority(
                column="CO2", target_type="continuous", source_digest="d" * 64
            ).canonical_dict(),
        },
    ],
)
def test_incomplete_or_foreign_response_authority_is_rejected(selection):
    with pytest.raises(ValueError):
        validate_experiment_source_provenance({**source(), **selection})


@pytest.mark.parametrize("asset_id", [None, "spectrum"])
@pytest.mark.parametrize("definition_digest", [None, "b" * 64])
def test_collection_reader_response_provenance_replays_without_changing_prediction_inputs(asset_id, definition_digest):
    import numpy as np

    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.dag.nodes.data.loaders import ExperimentDatasetReader
    from spectra_sherpa.app.services.model_application import _prepare_artifact_input

    training = SherpaDataset(X=np.arange(12, dtype=float).reshape(4, 3))
    authority = TargetAuthority(column="CO2", target_type="continuous", units="ppm", source_digest="c" * 64)
    training.target_context = training.target_context.model_copy(update={"selected_authority": authority})
    reader = ExperimentDatasetReader("source", {})
    provenance = {**source(), **reader._processing_parameters(dataset_id=7, file_count=33, dataset=training)}
    provenance.update(asset_id=asset_id, collection_definition_sha256=definition_digest)
    new_samples = np.array([[3.0, 4.0, 5.0], [6.0, 7.0, 8.0]])
    manifest = {"preprocessing_chain": [{"op_id": "spectrasherpa.experiment_dataset_read/2", "parameters": provenance}]}
    prepared, target, indices, warnings, _ = _prepare_artifact_input(new_samples, None, manifest, scope="all")
    np.testing.assert_array_equal(prepared, new_samples)
    np.testing.assert_array_equal(indices, [0, 1])
    assert target is None and warnings == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("asset_id", ""),
        ("asset_id", " "),
        ("asset_id", 1),
        ("collection_definition_sha256", ""),
        ("collection_definition_sha256", "invalid"),
        ("source_manifest_sha256", None),
        ("scientific_collection_sha256", None),
    ],
)
def test_default_asset_admission_keeps_source_identity_validation(field, value):
    with pytest.raises(ValueError):
        validate_experiment_source_provenance({**source(), field: value})
