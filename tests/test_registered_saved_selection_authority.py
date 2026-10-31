"""Saved native response selection must retain registered-source custody.

Synthetic registered input, no database, provider access, or model fitting.
The SDK admission boundary is real; only the authorized source resolver is a
fixture. The source identity is issued once, before any selection or mutation.
"""

from __future__ import annotations

import copy
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.dataset_view_receipts import (
    LoadedProjectDataset,
    curation_receipt,
    materialize_selection_receipt,
    receipt_sha256,
    selection_receipt,
)
from spectra_sherpa.app.lib.reference_materialization import _bind_registered_reference_source
from spectra_sherpa.app.lib.registered_reference_collection_identity import (
    validate_registered_reference_collection_identity,
)
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.lib.target_authority import issue_target_authority
from spectra_sherpa.app.services.dag.fitted_input_identity import fitted_input_identity
from spectra_sherpa.app.services.dag.nodes.data.loaders import (
    CollectionLoadNode,
    ExperimentDatasetReader,
    _LoadedDataset,
)
from spectra_sherpa.app.services.dag.supervision_binding import (
    admit_attached_sample_table_supervision,
    attach_sample_table_supervision,
    bind_sample_table_supervision,
)
from spectra_sherpa.app.services.dataset_source_resolver import ApplicationDatasetSourceResolver
from spectra_sherpa.app.services.model_application import _loaded_files_to_sherpa
from spectra_sherpa.core.execution_runtime import ExecutionRuntime, ResolvedExperimentCollection, ResolvedExperimentFile
from spectra_sherpa.io.types import SourceMember
from spectra_sherpa.sdk.runtime import _bind_dataset


def _source(*, inconsistent_native: bool = False, native_selected: bool = False) -> SherpaDataset:
    rows = ["fixture-001", "fixture-002", "fixture-003"]
    native = np.array([[10.0, 1.0], [11.0, 2.0], [12.0, 3.0]])
    if inconsistent_native:
        native[0, 0] = 99.0
    dataset = SherpaDataset(
        X=np.array([[1.0, 2.0], [2.0, 4.0], [3.0, 7.0]]),
        feature_axis=SpectralAxis(values=np.array([1100.0, 1102.0]), units="nm"),
        sample_axis=SampleAxis(
            labels=rows,
            sample_table={
                "sample_id": rows,
                "Protein": [10.0, 11.0, 12.0],
                "Oil": [1.0, 2.0, 3.0],
                "batch": ["A", "A", "B"],
            },
        ),
        target=native[:, 0] if native_selected else native,
        target_context=(
            TargetContext(target_type="continuous", target_names=["Protein"], selected_target="Protein")
            if native_selected
            else TargetContext(target_type="continuous", target_names=["Protein", "Oil"])
        ),
        data_role="X_spectra",
        extra={
            "reference.artifact_id": "fixture-artifact",
            "reference.artifact_sha256": "a" * 64,
            "reference.member_sha256": "b" * 64,
            "reference.projection_id": "fixture-m5",
        },
    )
    return _bind_registered_reference_source(
        dataset, {"path": "fixture.mat", "expected_size_bytes": 12, "sha256": "b" * 64}
    )


def _selection(source, *, column="Protein", group=None, asset_id=None):
    manifest = source.meta["source_collection"]
    loaded = LoadedProjectDataset(
        source,
        205,
        "Fixture Corn",
        138,
        [1021],
        "raw",
        asset_id,
        manifest["manifest_digest"],
        manifest["collection_definition_sha256"],
        manifest["scientific_collection_sha256"],
    )
    authority = issue_target_authority(source, column=column, target_type="continuous")
    receipt = selection_receipt(
        loaded, selected_file_ids=[1021], target_authority=authority.canonical_dict(), group_column=group
    )
    return loaded, receipt


def _application_resolver(monkeypatch, loaded, receipt):
    """Real trial-snapshot unwrapping, collection/view resolver; fake persistence only."""
    from spectra_sherpa.app.services import dataset_source_resolver as module

    experiment = SimpleNamespace(id=205, name="Fixture Corn", project_id=138)
    record = SimpleNamespace(id=1021)
    view = SimpleNamespace(selection=receipt, selection_sha256=receipt_sha256(receipt), project_id=138)

    class Session:
        async def scalar(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            return view if entity.__name__ == "DatasetView" else experiment

        async def scalars(self, statement):
            return SimpleNamespace(all=lambda: [record])

        async def get(self, entity, identity):
            assert (entity.__name__, identity) == ("Experiment", 205)
            return experiment

    @asynccontextmanager
    async def session():
        yield Session()

    monkeypatch.setattr(module, "async_session", session)
    monkeypatch.setattr(module, "read_collection_definition", lambda _id: None)
    monkeypatch.setattr(
        module,
        "_resolved_experiment_file",
        lambda _record: ResolvedExperimentFile(
            "/not-read/fixture.mat",
            "fixture.mat",
            "2026-10-30",
            file_id=1021,
            size_bytes=12,
            sha256="b" * 64,
        ),
    )
    # TrialDatasetAdmission owns loaded_dataset; use the real resolver's
    # wrapper handling without introducing a private-server test dependency.
    return ApplicationDatasetSourceResolver(preloaded_datasets={"data_1": SimpleNamespace(loaded_dataset=loaded)})


def _node(loaded, receipt, resolver):
    node = CollectionLoadNode(
        "data_1",
        {
            "experiment_id": loaded.experiment_id,
            "stage": loaded.stage,
            "asset_id": loaded.asset_id or "",
            "selected_file_ids": [str(value) for value in loaded.file_ids],
            "source_manifest_sha256": loaded.source_manifest_sha256,
            "collection_definition_sha256": loaded.collection_definition_sha256,
            "scientific_collection_sha256": loaded.scientific_collection_sha256,
            "target_authority": receipt["target_authority"],
            "group_column": receipt["group_column"] or "",
            "dataset_view_id": 22,
            "dataset_view_sha256": receipt_sha256(receipt),
        },
    )
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=resolver))
    return node


@pytest.mark.asyncio
@pytest.mark.parametrize("column,expected", [("Protein", [10.0, 11.0, 12.0]), ("Oil", [1.0, 2.0, 3.0])])
@pytest.mark.parametrize("group", [None, "batch"])
@pytest.mark.parametrize("preloaded", [False, True])
async def test_saved_native_view_collection_node_is_sdk_admissible_without_resealing(
    monkeypatch, column, expected, group, preloaded
):
    source = _source()
    asset_id = None if preloaded else "fixture-m5"
    if not preloaded:
        parsed = _LoadedDataset(
            dataset=source,
            file_name="fixture.mat",
            selected_asset_id=asset_id,
            source_members=(SourceMember(name="fixture.mat", sha256="b" * 64, size_bytes=12),),
        )
        source = _loaded_files_to_sherpa([parsed], "Fixture Corn", definition=None)

        def load_file(self, path, *, file_name, asset_id, prepared_overrides):
            assert (path, file_name, asset_id, dict(prepared_overrides)) == (
                "/not-read/fixture.mat",
                "fixture.mat",
                "fixture-m5",
                {},
            )
            return copy.deepcopy(parsed)

        monkeypatch.setattr(ExperimentDatasetReader, "_load_file", load_file)
    loaded, receipt = _selection(source, column=column, group=group, asset_id=asset_id)
    original_manifest = copy.deepcopy(source.meta["source_collection"])
    original_table = copy.deepcopy(source.sample_axis.sample_table)
    original_digest = source.scientific_digest
    original_target = source.target.copy()

    class Resolver:
        async def resolve_experiment_collection(self, *, experiment_id, stage):
            assert (experiment_id, stage) == (205, "raw")
            return ResolvedExperimentCollection(
                experiment_id=205,
                experiment_name="Fixture Corn",
                files=(
                    ResolvedExperimentFile(
                        "/not-read/fixture.mat",
                        "fixture.mat",
                        "2026-10-30",
                        file_id=1021,
                        size_bytes=12,
                        sha256="b" * 64,
                    ),
                ),
                preloaded_dataset=source if preloaded else None,
            )

        async def resolve_dataset_view(self, *, experiment_id, view_id, selection_sha256):
            assert (experiment_id, view_id, selection_sha256) == (205, 22, receipt_sha256(receipt))
            return {"selection": receipt, "project_id": 138}

    resolver = _application_resolver(monkeypatch, loaded, receipt) if preloaded else Resolver()
    node = _node(loaded, receipt, resolver)
    selected = (await node.execute())["default"]

    _bind_dataset("source", selected, ordinal=0)
    binding = admit_attached_sample_table_supervision(selected)
    assert binding is not None
    assert (None if binding.groups is None else binding.groups.tolist()) == (None if group is None else ["A", "A", "B"])
    np.testing.assert_array_equal(selected.target, expected)
    np.testing.assert_array_equal(selected.X, source.X)
    assert selected.meta["source_collection"] == original_manifest
    assert selected.sample_axis.sample_table == original_table
    assert selected.target_context.selected_authority.canonical_dict() == receipt["target_authority"]
    assert fitted_input_identity(selected, features=2) == fitted_input_identity(source, features=2)
    assert source.scientific_digest == original_digest
    np.testing.assert_array_equal(source.target, original_target)
    assert "supervision_binding" not in source.meta
    # It remains a derived response projection, never a newly sealed raw source.
    with pytest.raises(ValueError, match="exact annotations"):
        validate_registered_reference_collection_identity(original_manifest, selected)


@pytest.mark.parametrize("group", [None, "batch"])
def test_native_response_and_table_must_agree_even_with_valid_original_identity(group):
    source = _source(inconsistent_native=True)
    validate_registered_reference_collection_identity(source.meta["source_collection"], source)
    loaded, receipt = _selection(source, group=group)
    with pytest.raises(ValueError, match="native response differs"):
        materialize_selection_receipt(loaded, receipt)


def _tamper(dataset, field):
    if field == "X":
        dataset.X[0, 0] = 99.0
    elif field == "target":
        dataset.target.flat[0] = 99.0
    elif field == "table":
        axis = dataset.sample_axis.model_copy(deep=True)
        axis.sample_table["Oil"][0] = 99.0
        dataset.sample_axis = axis
    elif field == "member":
        dataset.meta["source_collection"]["files"][0]["size_bytes"] += 1
    elif field == "manifest":
        dataset.meta["source_collection"]["manifest_digest"] = "f" * 64
    else:
        raise AssertionError(field)


@pytest.mark.parametrize("field", ["X", "target", "table", "member", "manifest"])
def test_saved_selection_refuses_tampered_original_source(field):
    loaded, receipt = _selection(_source())
    receipt = copy.deepcopy(receipt)
    changed = loaded.dataset.snapshot()
    _tamper(changed, field)
    with pytest.raises(ValueError):
        materialize_selection_receipt(replace(loaded, dataset=changed), receipt)


@pytest.mark.parametrize("field", ["X", "target", "table", "member", "manifest"])
def test_selected_view_still_refuses_post_binding_tamper_in_sdk(field):
    loaded, receipt = _selection(_source())
    selected = materialize_selection_receipt(loaded, receipt).dataset
    _bind_dataset("source", selected, ordinal=0)
    _tamper(selected, field)
    with pytest.raises(ValueError):
        _bind_dataset("source", selected, ordinal=0)


@pytest.mark.parametrize(
    "field", ["project_id", "experiment_id", "stage", "source_manifest_sha256", "target_authority"]
)
def test_saved_selection_requires_exact_receipt_and_target_authority(field):
    loaded, receipt = _selection(_source())
    changed = copy.deepcopy(receipt)
    if field == "target_authority":
        changed[field]["source_digest"] = "f" * 64
    else:
        changed[field] = "different"
    with pytest.raises(ValueError):
        materialize_selection_receipt(loaded, changed)


def test_reselection_of_derived_projection_requires_original_source():
    loaded, receipt = _selection(_source())
    selected = materialize_selection_receipt(loaded, receipt).dataset
    loaded_again, oil_receipt = _selection(selected, column="Oil")
    assert admit_attached_sample_table_supervision(selected) is not None
    with pytest.raises(ValueError, match="exact annotations"):
        materialize_selection_receipt(loaded_again, oil_receipt)


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [None, "batch"])
async def test_preloaded_original_native_selection_with_binding_is_reverified(monkeypatch, group):
    source = _source(native_selected=True)
    loaded, receipt = _selection(source, group=group)
    validate_registered_reference_collection_identity(source.meta["source_collection"], source)
    assert admit_attached_sample_table_supervision(source) is not None
    node = _node(loaded, receipt, _application_resolver(monkeypatch, loaded, receipt))
    selected = (await node.execute())["default"]
    _bind_dataset("source", selected, ordinal=0)
    np.testing.assert_array_equal(selected.target, [10.0, 11.0, 12.0])
    assert selected.meta["source_collection"] == source.meta["source_collection"]


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [None, "batch"])
@pytest.mark.parametrize("changed", ["rebound_X", "derived_selection"])
async def test_preloaded_self_issued_binding_cannot_replace_original_custody(monkeypatch, group, changed):
    source = _source(native_selected=changed == "rebound_X")
    loaded, receipt = _selection(source, group=group)
    original_manifest = copy.deepcopy(source.meta["source_collection"])
    receipt = copy.deepcopy(receipt)
    if changed == "rebound_X":
        source.X[0, 0] = 99.0
        binding = bind_sample_table_supervision(
            source,
            target_column="Protein",
            target_type="continuous",
            group_column=group,
        )
        source.meta["supervision_binding"] = {**binding.record, "supervision_binding_sha256": binding.digest}
    else:
        source = attach_sample_table_supervision(
            source,
            target_column="Protein",
            target_type="continuous",
            group_column=group,
            node_id="unproven-reentry",
        )
    assert source.meta["source_collection"] == original_manifest
    assert admit_attached_sample_table_supervision(source) is not None
    loaded = replace(loaded, dataset=source)
    with pytest.raises(ValueError, match="exact annotations"):
        materialize_selection_receipt(loaded, receipt)
    node = _node(loaded, receipt, _application_resolver(monkeypatch, loaded, receipt))
    with pytest.raises(ValueError, match="exact annotations"):
        await node.execute()


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("id_table", [False, True])
def test_native_selection_without_target_table_keeps_existing_behavior(registered, id_table):
    source = _source()
    if not registered:
        for key in list(source.extra):
            if key.startswith("reference."):
                del source.extra[key]
    labels = source.sample_axis.labels
    source.sample_axis = SampleAxis(labels=labels, sample_table={"sample_id": labels} if id_table else None)
    loaded, receipt = _selection(source)
    selected = materialize_selection_receipt(loaded, receipt).dataset
    np.testing.assert_array_equal(selected.target, [10.0, 11.0, 12.0])
    assert selected.sample_axis.sample_table == source.sample_axis.sample_table
    assert "supervision_binding" not in selected.meta
    assert selected.meta["source_collection"] == source.meta["source_collection"]


def test_unsupervised_view_does_not_require_optional_response_binding():
    loaded, _ = _selection(_source())
    source = loaded.dataset
    source.target = None
    source.sample_axis = SampleAxis(labels=source.sample_axis.labels)
    receipt = selection_receipt(loaded, selected_file_ids=[1021])
    result = materialize_selection_receipt(loaded, receipt)
    assert result.dataset is source
    assert result.dataset.target is None
    assert "supervision_binding" not in result.dataset.meta


def test_curated_selection_does_not_reseal_subset_as_original_registered_source():
    parsed = _LoadedDataset(
        dataset=_source(),
        file_name="fixture.mat",
        selected_asset_id="fixture-m5",
        source_members=(SourceMember(name="fixture.mat", sha256="b" * 64, size_bytes=12),),
    )
    source = _loaded_files_to_sherpa([parsed], "Fixture Corn", definition=None)
    loaded, receipt = _selection(source, asset_id="fixture-m5")
    from spectra_sherpa.app.lib.collection_assembly import verified_source_observations

    rows = verified_source_observations(source)
    curated = curation_receipt(
        loaded,
        receipt,
        parent_view_id=22,
        action="exclude",
        sample_ids=[rows[1]["sample_id"]],
        reason="Synthetic review exclusion",
    )
    selected = materialize_selection_receipt(loaded, curated).dataset
    assert admit_attached_sample_table_supervision(selected) is not None
    np.testing.assert_array_equal(selected.target, [10.0, 12.0])
    np.testing.assert_array_equal(selected.X, source.X[[0, 2]])
    assert selected.meta["source_collection"] == source.meta["source_collection"]
    assert selected.sample_axis.sample_table["Oil"] == [1.0, 3.0]
    assert source.sample_axis.sample_table["Oil"] == [1.0, 2.0, 3.0]
    # A subset needs its own explicit source-to-subset authority. This bounded
    # native-selection correction must not bypass the existing source guard.
    with pytest.raises(ValueError, match="exact annotations"):
        _bind_dataset("source", selected, ordinal=0)
