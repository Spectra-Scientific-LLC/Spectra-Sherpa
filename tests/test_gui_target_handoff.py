"""Inspection must issue authority that workflow admission can verify."""

import hashlib

import numpy as np
import pytest

from spectra_sherpa.app.api.v1.routes import builder
from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.collection_assembly import CollectionMember, prepared_data_digest
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.lib.target_authority import issue_target_authority, verify_target_authority
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.services import experiments, model_application
from spectra_sherpa.app.services.dag.nodes.data import loaders
from spectra_sherpa.io.types import SourceMember


@pytest.mark.asyncio
@pytest.mark.parametrize("registered", [False, True], ids=["ordinary", "registered"])
async def test_collection_inspection_authority_survives_workflow_admission(
    tmp_path, monkeypatch, test_session, test_user, registered
):
    experiment = Experiment(user_id=test_user.id, name="Target handoff", metadata_path="metadata.json")
    test_session.add(experiment)
    await test_session.flush()
    file = ExperimentFile(experiment_id=experiment.id, file_path="raw/fixture.mat", stage="raw", file_size_bytes=7)
    test_session.add(file)
    await test_session.flush()
    path = tmp_path / file.file_path
    path.parent.mkdir()
    path.write_bytes(b"fixture")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    asset_id = "fixture-reference-v1" if registered else "spectra"
    dataset = SherpaDataset(
        X=np.asarray([[1, 4], [2, 3], [3, 2], [4, 1]], dtype=float),
        feature_axis=SpectralAxis(values=np.asarray([1000.0, 1100.0]), units="nm"),
        sample_axis=SampleAxis(
            labels=["C01", "C02", "T01", "T02"],
            sample_table={"assay": [1.0, 1.0, 2.0, 3.0]},
        ),
        target=np.asarray([1.0, 1.0, 2.0, 3.0]),
        target_context=TargetContext(target_type="continuous", target_name="assay", target_units="wt%"),
        data_role="X_spectra",
    )
    if registered:
        dataset.extra.update(
            {
                "reference.projection_id": asset_id,
                "reference.artifact_id": "fixture-artifact-v1",
                "reference.artifact_sha256": "a" * 64,
                "reference.member_sha256": digest,
            }
        )
    for module in (builder, experiments):
        monkeypatch.setattr(module, "experiment_dir", lambda _id: tmp_path)
    for module in (builder, model_application):
        monkeypatch.setattr(module, "read_collection_definition", lambda _id: None, raising=False)

    # Mock the native parser only; exercise both real collection/admission paths.
    monkeypatch.setattr(
        builder,
        "_file_as_collection_member",
        lambda *args, **kwargs: CollectionMember(
            dataset.snapshot(),
            file.file_path,
            7,
            digest,
            prepared_data_sha256=prepared_data_digest({}),
            asset_id=asset_id,
        ),
    )
    monkeypatch.setattr(
        loaders.ExperimentDatasetReader,
        "_load_file",
        lambda *args, **kwargs: loaders._LoadedDataset(
            dataset=dataset.snapshot(),
            file_name=kwargs["file_name"],
            prepared_overrides={},
            source_members=(SourceMember(path.name, digest, 7),),
            selected_asset_id=asset_id,
        ),
    )

    inspected, _, _, _, manifest = await builder._experiment_contents_as_sherpa(
        experiment.id,
        test_session,
        test_user,
        asset_id=asset_id,
    )
    admitted = await model_application.load_project_dataset(
        test_session,
        user_id=test_user.id,
        experiment_id=experiment.id,
        asset_id=asset_id,
    )
    authority = issue_target_authority(inspected, column="assay", target_type="continuous")
    verify_target_authority(admitted.dataset, authority)
    assert manifest["scientific_collection_sha256"] == admitted.scientific_collection_sha256
    assert manifest.get("collection_definition_sha256") == admitted.collection_definition_sha256
    assert bool(admitted.collection_definition_sha256) is registered
    assert authority.units == "wt%"


@pytest.mark.parametrize(
    ("target_type", "values"),
    [("continuous", ["1", "1", "2", "3"]), ("categorical", ["case", "control", "case", "control"])],
)
def test_single_file_preview_preserves_declared_csv_target(tmp_path, target_type, values):
    path = tmp_path / "declared.csv"
    path.write_text("sample,1000,1100,target\n" + "".join(f"S{i},1,2,{value}\n" for i, value in enumerate(values)))
    prepared = {"data_role": "X_spectra", "target_column": "target", "target_type": target_type}
    single = builder._file_as_sherpa(path, prepared_overrides=prepared)
    member = builder._file_as_collection_member(
        path,
        file_name=path.name,
        asset_id=None,
        prepared_overrides=prepared,
    ).dataset
    assert single.target_context.target_type == target_type
    assert single.target_context.target_name == "target"
    np.testing.assert_array_equal(single.target, member.target)
    np.testing.assert_array_equal(single.X, member.X)
    assert single.shape == (4, 2)
