"""Application admission of real Run731 source history, not numerical replay."""

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.model_application import _prepare_artifact_input


@pytest.fixture
def exported_manifest():
    # Real source provenance only; all application numbers are synthetic.
    provenance = json.loads(
        (Path(__file__).parent / "fixtures/model_application/corn_run731_source_provenance.json").read_text()
    )
    return {
        "n_features": 700,
        "feature_axis": np.arange(1100.0, 2500.0, 2.0).tolist(),
        "preprocessing_chain": provenance["preprocessing_chain"],
    }


def application_input(manifest, rows=7):
    return SherpaDataset(
        X=np.arange(rows * 700, dtype=np.float64).reshape(rows, 700) / 700,
        feature_axis=SpectralAxis(values=manifest["feature_axis"], units="nm", quantity="wavelength"),
    )


def prepare(manifest, dataset):
    return _prepare_artifact_input(dataset.X, None, manifest, scope="all", source_dataset=dataset)


@pytest.mark.parametrize("rows", [1, 7, 160])
def test_actual_export_source_history_preserves_new_application_rows(exported_manifest, rows):
    source = application_input(exported_manifest, rows)
    before = source.X.copy()
    manifest_before = deepcopy(exported_manifest)
    matrix, target, indices, warnings, replay_source = prepare(exported_manifest, source)
    np.testing.assert_array_equal(matrix, before)
    np.testing.assert_array_equal(indices, np.arange(rows))
    np.testing.assert_array_equal(replay_source.X, before)
    assert target is None and warnings == []
    assert exported_manifest == manifest_before
    np.testing.assert_array_equal(source.X, before)


@pytest.mark.parametrize(
    "field,value",
    [
        ("image_view", "image-cube"),
        ("source_shape", [80, 10, 70]),
        ("source_shape", [700, 80]),
        ("source_shape", [True, 700]),
        ("parser_id", "another-parser"),
        ("parser_version", "unreviewed"),
        ("source_sha256", "0" * 64),
        ("source_size_bytes", True),
        ("asset_id", "mp5spec"),
        ("source_variable", "mp5spec"),
        ("source_dtype", "<c16"),
        ("source_dtype", "O"),
    ],
)
def test_reader_provenance_refuses_unadmitted_views_and_custody(exported_manifest, field, value):
    exported_manifest["preprocessing_chain"][0]["parameters"][field] = value
    with pytest.raises(ValueError, match="registered MATLAB source"):
        prepare(exported_manifest, application_input(exported_manifest))


@pytest.mark.parametrize(
    "field,value",
    [
        ("projection_id", "not-registered"),
        ("artifact_sha256", "0" * 64),
        ("member_sha256", "0" * 64),
        ("scientific_sha256", "0" * 64),
        ("target_object_name", "another_target"),
        ("analysis_profile", {}),
        ("dataset_package", {}),
        ("native_reader_contract", "unreviewed-reader"),
        ("unexpected_transform", {"scale": True}),
    ],
)
def test_registered_source_refuses_changed_registry_authority(exported_manifest, field, value):
    exported_manifest["preprocessing_chain"][1]["parameters"][field] = value
    with pytest.raises(ValueError):
        prepare(exported_manifest, application_input(exported_manifest))


@pytest.mark.parametrize("mutation", ["reader_only", "reference_only", "duplicate", "reordered", "after_transform"])
def test_source_provenance_requires_exact_leading_pair(exported_manifest, mutation):
    chain = exported_manifest["preprocessing_chain"]
    if mutation == "reader_only":
        del chain[1]
    elif mutation == "reference_only":
        del chain[0]
    elif mutation == "duplicate":
        chain.insert(1, deepcopy(chain[0]))
    elif mutation == "reordered":
        chain[:2] = reversed(chain[:2])
    else:
        chain.insert(0, {"op_id": "preprocess.smooth", "parameters": {}})
    with pytest.raises(ValueError, match="leading reader/reference pair"):
        prepare(exported_manifest, application_input(exported_manifest))


@pytest.mark.parametrize("operation", ["import.unreviewed_transform", "preprocess.unreviewed", "transfer.pds"])
def test_unknown_transform_still_refuses_after_valid_source(exported_manifest, operation):
    exported_manifest["preprocessing_chain"].append({"op_id": operation, "parameters": {}})
    with pytest.raises(ValueError, match="no certified artifact-application replay"):
        prepare(exported_manifest, application_input(exported_manifest))


def test_package_view_integer_type_cannot_be_coerced(exported_manifest):
    exported_manifest["preprocessing_chain"][1]["parameters"]["dataset_package"]["annotation_table"]["n_rows"] = 80.0
    with pytest.raises(ValueError, match="canonical authority"):
        prepare(exported_manifest, application_input(exported_manifest))


def test_invented_reader_storage_generation_refuses(exported_manifest):
    exported_manifest["preprocessing_chain"][0]["parameters"]["storage_version"] = "invented-storage"
    with pytest.raises(ValueError, match="canonical authority"):
        prepare(exported_manifest, application_input(exported_manifest))
