"""Generic Phase 8A saved-model application and replay boundaries."""

from __future__ import annotations

import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.api.v1.routes import models as model_routes
from spectra_sherpa.app.api.v1.routes.models import CanonicalFullRefitImportRequest
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.canonical_model_bridge import (
    CANONICAL_MODEL_ORIGIN,
    CanonicalModelBridgeError,
    bridge_canonical_plsda_artifact,
    persist_canonical_plsda_bridge,
    validate_canonical_plsda_model_artifact,
)
from spectra_sherpa.app.services.dag.classification_application import (
    CLASS_RESPONSE_SEMANTICS,
    ClassificationApplication,
    ClassificationApplicationError,
    validate_classification_application,
)
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    execute_candidate_validation,
    execute_selected_candidate_full_refit,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset
from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import LoadApplyModelNode
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.supervision_binding import bind_sample_table_supervision
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.services.execution_runtime import (
    ApplicationModelArtifactReplay,
    ApplicationModelArtifactSemanticValidator,
)
from spectra_sherpa.app.services.model_application import apply_model_to_dataset
from spectra_sherpa.app.services.model_store import (
    ModelArtifactCollisionError,
    ModelStore,
    parse_model_manifest_json,
)
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.core.model_artifact import (
    CANONICAL_MODEL_ARTIFACT_AUTHORITY,
    ORDINARY_MODEL_ARTIFACT_AUTHORITY,
    ModelArtifactIntegrityError,
    ReadOnlyModelArtifactReader,
    load_verified_artifact_directory,
)
from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifact
from spectra_sherpa.sdk.validate import make_leave_one_group_out_classification_plan

_STATE_DIGEST = "a" * 64


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def test_canonical_import_request_refuses_coerced_feature_mask_values() -> None:
    payload = {
        "project_id": 1,
        "canonical_workflow_id": 1,
        "training_experiment_id": 1,
        "asset_id": "table",
        "graph": {},
        "validation_execution": {},
        "original_capability_metadata": {},
        "custody_id": "qualification",
        "target_attachment_node_id": "attach",
        "target_authority": {
            "column": "class",
            "target_type": "categorical",
            "units": None,
            "source_digest": "0" * 64,
        },
        "group_column": "batch",
        "feature_mask": [True, 0],
        "selection_report": {},
    }
    with pytest.raises(ValidationError, match="feature_mask.1"):
        CanonicalFullRefitImportRequest.model_validate(payload)


@pytest.mark.asyncio
async def test_canonical_import_route_never_discloses_a_missing_private_path(monkeypatch) -> None:
    payload = CanonicalFullRefitImportRequest.model_validate(
        {
            "project_id": 1,
            "canonical_workflow_id": 1,
            "training_experiment_id": 1,
            "asset_id": "table",
            "graph": {},
            "validation_execution": {},
            "original_capability_metadata": {},
            "custody_id": "qualification",
            "target_attachment_node_id": "attach",
            "target_authority": {
                "column": "class",
                "target_type": "categorical",
                "units": None,
                "source_digest": "0" * 64,
            },
            "group_column": "batch",
            "feature_mask": [True],
            "selection_report": {},
        }
    )

    async def allow_project(*_args, **_kwargs) -> None:
        return None

    async def grant(*_args, **_kwargs):
        return SimpleNamespace(
            project_id=1,
            artifact_dir=Path("/srv/private-canonical-artifacts/secret"),
            artifact_digest="2" * 64,
        )

    def missing_artifact(_cls, directory: Path):
        raise FileNotFoundError(str(directory / "manifest.json"))

    from spectra_sherpa.app.services import canonical_project_custody

    monkeypatch.setattr(model_routes, "require_project", allow_project)
    monkeypatch.setattr(canonical_project_custody, "resolve_canonical_artifact_read_grant", grant)
    monkeypatch.setattr(CanonicalFittedArtifact, "load", classmethod(missing_artifact))

    with pytest.raises(HTTPException) as caught:
        await model_routes.import_canonical_full_refit(
            payload,
            _dg=None,
            session=object(),  # type: ignore[arg-type]
            current_user=SimpleNamespace(id=7),  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 409
    assert caught.value.detail == "Canonical import files are unavailable"
    assert "/srv/" not in str(caught.value.detail)


def test_classification_application_is_one_issued_immutable_authority() -> None:
    record = validate_classification_application(
        fitted_state_digest=_STATE_DIGEST,
        predictions=np.array(["B", "A"], dtype=object),
        responses=np.array([[0.2, 0.8], [0.7, 0.3]], dtype=np.float64),
        classes=("A", "B"),
    )

    assert record.semantics == CLASS_RESPONSE_SEMANTICS
    assert record.predictions.tolist() == ["B", "A"]
    assert record.margins.tolist() == pytest.approx([0.6, 0.4])
    assert len(record.application_digest) == 64
    assert not record.responses.flags.writeable
    record.assert_valid()
    with pytest.raises(TypeError, match="shared validator"):
        ClassificationApplication(
            _STATE_DIGEST,
            record.predictions,
            record.responses,
            record.classes,
            record.margins,
            record.application_digest,
            record.semantics,
            _authority=object(),
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"predictions": ["A", "A"]}, "argmax"),
        ({"responses": [[0.2, np.nan], [0.7, 0.3]]}, "responses"),
        ({"classes": [2**53, "B"]}, "lossless JSON scalars"),
        ({"classes": ["A", "A"]}, "duplicate typed identities"),
        ({"fitted_state_digest": "not-a-digest"}, "fitted-state"),
        ({"semantics": "probabilities"}, "semantics"),
    ],
)
def test_classification_application_refuses_semantic_mutations(mutation: dict[str, object], match: str) -> None:
    values: dict[str, object] = {
        "fitted_state_digest": _STATE_DIGEST,
        "predictions": ["B", "A"],
        "responses": [[0.2, 0.8], [0.7, 0.3]],
        "classes": ["A", "B"],
        "semantics": CLASS_RESPONSE_SEMANTICS,
    }
    values.update(mutation)
    with pytest.raises(ClassificationApplicationError, match=match):
        validate_classification_application(**values)  # type: ignore[arg-type]


def _replay_fixture() -> tuple[SherpaDataset, SherpaDataset, dict[str, object], np.ndarray]:
    axis = np.array([4000.0, 3000.0, 2000.0, 1000.0, 400.0], dtype=np.float64)
    matrix = np.arange(15, dtype=np.float64).reshape(3, 5)
    mask = np.array([False, True, True, True, False], dtype=bool)
    source = SherpaDataset(
        matrix,
        feature_axis=SpectralAxis(values=axis, units="cm-1", title="Wavenumber"),
    )
    selected = SherpaDataset(
        matrix[:, mask],
        feature_axis=SpectralAxis(values=axis[mask], units="cm-1", title="Wavenumber"),
    )
    report = {
        "schema": "spectrasherpa.selection.variable_select.report/1",
        "method": "interval",
        "parameters": {
            "method": "interval",
            "invert": False,
            "region_start": 3100.0,
            "region_end": 650.0,
        },
        "selection_scope": "target_free_feature_rule_not_predictive_validation",
        "predictive_performance_claimed": False,
        "reference_samples": 3,
        "reference_features": 5,
        "selected_features": 3,
        "feature_axis_values_sha256": hashlib.sha256(axis.astype("<f8").tobytes()).hexdigest(),
        "feature_mask_sha256": hashlib.sha256(mask.astype("?").tobytes()).hexdigest(),
        "score_sha256": None,
        "detected_extrema_indices": [],
    }
    manifest: dict[str, object] = {
        "n_features": 3,
        "feature_axis": axis[mask].tolist(),
        "feature_axis_units": "cm-1",
        "feature_mask": mask.tolist(),
        "preprocessing_chain": [
            {
                "op_id": "spectrasherpa.experiment_dataset_read/2",
                "parameters": {
                    "dataset_id": 7,
                    "file_count": 3,
                    "stage": "raw",
                    "asset_id": "spectrum",
                    "source_manifest_sha256": "1" * 64,
                    "collection_definition_sha256": "2" * 64,
                    "scientific_collection_sha256": "3" * 64,
                },
            },
            {
                "op_id": "selection.variable_select",
                "parameters": {"selection_report": report, "feature_mask": mask.tolist()},
            },
        ],
    }
    return source, selected, manifest, mask


def test_saved_model_replay_applies_exact_interval_mask_once_for_raw_or_selected_input() -> None:
    source, selected, manifest, mask = _replay_fixture()
    replay = ApplicationModelArtifactReplay()

    raw_result, raw_warnings = replay.prepare(source.X, source, manifest)
    selected_result, selected_warnings = replay.prepare(selected.X, selected, manifest)

    np.testing.assert_array_equal(raw_result, source.X[:, mask])
    np.testing.assert_array_equal(selected_result, selected.X)
    assert raw_warnings == ("Applied saved feature mask (5 -> 3 features)",)
    assert selected_warnings == ()


@pytest.mark.parametrize("mutation", ["source-axis", "mask", "report", "selected-axis", "unknown-step"])
def test_saved_model_replay_refuses_provenance_and_axis_mutations(mutation: str) -> None:
    source, selected, manifest, _mask = _replay_fixture()
    replay = ApplicationModelArtifactReplay()
    if mutation == "source-axis":
        source = SherpaDataset(
            source.X,
            feature_axis=SpectralAxis(
                values=np.asarray(source.feature_axis.values) + 1.0,
                units="cm-1",
                title="Wavenumber",
            ),
        )
        matrix, dataset = source.X, source
    elif mutation == "selected-axis":
        selected = SherpaDataset(
            selected.X,
            feature_axis=SpectralAxis(
                values=np.asarray(selected.feature_axis.values) + 1.0,
                units="cm-1",
                title="Wavenumber",
            ),
        )
        matrix, dataset = selected.X, selected
    else:
        matrix, dataset = source.X, source
        if mutation == "mask":
            manifest["preprocessing_chain"][1]["parameters"]["feature_mask"][0] = True  # type: ignore[index]
        elif mutation == "report":
            manifest["preprocessing_chain"][1]["parameters"]["selection_report"]["selected_features"] = 2  # type: ignore[index]
        else:
            manifest["preprocessing_chain"].append({"op_id": "unknown.transform", "parameters": {}})  # type: ignore[union-attr]
    with pytest.raises(ValueError):
        replay.prepare(matrix, dataset, manifest)


def _canonical_bridge_dataset(*, dataset_id: str | None = None) -> SherpaDataset:
    labels = [f"sample-{index + 1}" for index in range(6)]
    return SherpaDataset(
        dataset_id=dataset_id,
        X=np.asarray(
            [
                [2.0, 1.1, 0.0, 0.2],
                [0.1, 0.2, 1.0, 2.0],
                [2.1, 1.0, 0.1, 0.2],
                [0.2, 0.1, 1.2, 1.9],
                [1.9, 1.2, 0.0, 0.1],
                [0.0, 0.2, 0.9, 2.1],
            ],
            dtype=np.float64,
        ),
        feature_axis=SpectralAxis(
            values=np.asarray([1800.0, 1600.0, 1400.0, 1200.0]),
            units="cm-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(
            labels=labels,
            sample_table={
                "sample_id": labels,
                "specimen_id": ["A", "B", "A", "B", "A", "B"],
                "block": [1, 1, 2, 2, 3, 3],
            },
        ),
        units="absorbance",
        data_role="X_spectra",
        extra={
            "source_collection": {
                "schema_version": "spectrasherpa-source-collection/1",
                "file_count": 6,
                "files": [{"file_name": f"source-{index}.spa", "asset_id": "spectrum"} for index in range(6)],
                "manifest_digest": "1" * 64,
                "collection_definition_sha256": "2" * 64,
                "scientific_collection_sha256": "3" * 64,
            }
        },
    )


async def _canonical_bridge_fixture(*, experiment_id: int = 7):
    source = _canonical_bridge_dataset()
    attached = attach_target_dataset(
        source,
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    binding = bind_sample_table_supervision(
        attached,
        target_column="specimen_id",
        target_type="categorical",
        group_column="block",
    )
    plan = make_leave_one_group_out_classification_plan(
        binding.target,
        binding.groups,
        require_one_per_class_group=True,
    )
    capability = SpectralDatasetCapability.from_dataset(
        attached,
        custody_id="phase8-synthetic",
        dataset_ref_digest=binding.digest,
        split_plan_digest=plan.digest,
        groups=binding.groups,
    )
    graph = admit_validation_graph(
        [
            WorkflowNode(
                "window",
                "selection.variable_select",
                {"method": "interval", "region_start": 1700.0, "region_end": 1300.0},
            ),
            WorkflowNode("model", "classification.plsda", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.classification_evaluator", {}),
        ],
        [
            WorkflowEdge("window", "model"),
            WorkflowEdge("model", "score", from_output="predictions", to_input="default"),
        ],
    )
    validation = await execute_candidate_validation(graph, capability, plan)
    refit = await execute_selected_candidate_full_refit(graph, capability, validation)
    artifact = CanonicalFittedArtifact.from_full_refit_execution(refit)
    selector = node_registry.create_node(
        "selection.variable_select",
        "window",
        {"method": "interval", "region_start": 1700.0, "region_end": 1300.0},
    )
    selection = await selector.execute(X=attached)
    selection_outputs = selection.outputs
    bridge = bridge_canonical_plsda_artifact(
        artifact,
        graph_payload=graph.as_dict(),
        training_dataset=attached,
        experiment_id=experiment_id,
        asset_id="spectrum",
        validation_execution=validation.as_dict(),
        original_capability_metadata=capability.to_wire()["metadata"],
        custody_id="phase8-synthetic",
        feature_mask=selection_outputs["mask"].tolist(),
        selection_report=selection_outputs["selection_report"],
    )
    return attached, selection_outputs["default"], artifact, bridge


@pytest.mark.asyncio
async def test_canonical_bridge_round_trips_one_native_state_without_refit() -> None:
    source, selected, artifact, bridge = await _canonical_bridge_fixture()

    assert bridge.manifest["artifact_origin"] == CANONICAL_MODEL_ORIGIN
    assert bridge.manifest["artifact_authority"] == CANONICAL_MODEL_ARTIFACT_AUTHORITY
    assert bridge.manifest["canonical_training_lineage"]["canonical_artifact_digest"] == artifact.artifact_digest
    assert bridge.manifest["classification_output_semantics"] == CLASS_RESPONSE_SEMANTICS
    assert bridge.receipt["validation_role"] == "linked_held_out_validation_evidence_not_full_refit_performance"
    validate_canonical_plsda_model_artifact(bridge.manifest, bridge.arrays, training_dataset=source)
    prepared, _warnings = ApplicationModelArtifactReplay().prepare(source.X, source, bridge.manifest)
    np.testing.assert_array_equal(prepared, selected.X)


@pytest.mark.asyncio
async def test_canonical_bridge_refuses_a_replacement_training_capability() -> None:
    source, _selected, artifact, bridge = await _canonical_bridge_fixture()
    lineage = bridge.manifest["canonical_training_lineage"]
    replacement_raw = _canonical_bridge_dataset(dataset_id=source.dataset_id)
    replacement_raw = replacement_raw.with_data(np.asarray(replacement_raw.X) + 50.0)
    replacement = attach_target_dataset(
        replacement_raw,
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )

    with pytest.raises(CanonicalModelBridgeError, match="canonical refit capability"):
        bridge_canonical_plsda_artifact(
            artifact,
            graph_payload=lineage["graph"],
            training_dataset=replacement,
            experiment_id=7,
            asset_id="spectrum",
            validation_execution=lineage["validation_execution"],
            original_capability_metadata=lineage["capability"]["original_metadata"],
            custody_id=lineage["capability"]["custody_id"],
            feature_mask=lineage["selection"]["feature_mask"],
            selection_report=lineage["selection"]["selection_report"],
        )


@pytest.mark.parametrize("location", ["top", "nested"])
def test_model_manifest_json_rejects_recursive_duplicate_keys(location: str) -> None:
    if location == "top":
        payload = b'{"artifact_uid":"first","artifact_uid":"second"}'
    else:
        payload = b'{"canonical_training_lineage":{"origin":"first","origin":"second"}}'
    with pytest.raises(ValueError, match="repeats JSON key"):
        parse_model_manifest_json(payload)


@pytest.mark.asyncio
async def test_model_store_load_rejects_duplicate_canonical_manifest_keys(tmp_path: Path) -> None:
    _source, _selected, _artifact, bridge = await _canonical_bridge_fixture()
    store = ModelStore(tmp_path)
    artifact_uid = "12121212-1212-4212-8212-121212121212"
    store.save_new(artifact_uid, deepcopy(bridge.manifest), bridge.arrays)
    manifest_path = Path(store.artifact_directory(artifact_uid)) / "manifest.json"
    payload = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        payload.replace('{\n  "model_type"', '{\n  "model_type": "rogue",\n  "model_type"', 1), encoding="utf-8"
    )

    with pytest.raises(ModelArtifactIntegrityError, match="ambiguous or malformed"):
        store.load(artifact_uid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin_mutation",
    ["removed", "null", "wrong", "all_markers_removed", "authority_removed"],
)
async def test_worker_application_cannot_downgrade_canonical_origin(
    tmp_path: Path,
    origin_mutation: str,
) -> None:
    source, _selected, _artifact, bridge = await _canonical_bridge_fixture()
    store = ModelStore(tmp_path)
    artifact_uid = "14141414-1414-4414-8414-141414141414"
    store.save_new(artifact_uid, deepcopy(bridge.manifest), bridge.arrays)
    manifest_path = Path(store.artifact_directory(artifact_uid)) / "manifest.json"
    manifest = parse_model_manifest_json(manifest_path.read_bytes())
    if origin_mutation == "removed":
        del manifest["artifact_origin"]
    elif origin_mutation == "null":
        manifest["artifact_origin"] = None
    elif origin_mutation == "wrong":
        manifest["artifact_origin"] = "ordinary"
    elif origin_mutation == "all_markers_removed":
        for key in ("artifact_origin", "canonical_training_lineage", "classification_output_semantics"):
            del manifest[key]
    else:
        for key in (
            "artifact_authority",
            "artifact_origin",
            "canonical_training_lineage",
            "classification_output_semantics",
        ):
            del manifest[key]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ModelArtifactIntegrityError, match="authority|canonical scientific lineage"):
        store.load(artifact_uid)

    node = LoadApplyModelNode("apply", {"model_id": artifact_uid})
    node.bind_execution_runtime(
        ExecutionRuntime(
            model_artifact_reader=ReadOnlyModelArtifactReader(tmp_path),
            model_artifact_replay=ApplicationModelArtifactReplay(),
            model_artifact_semantic_validator=ApplicationModelArtifactSemanticValidator(),
        )
    )
    with pytest.raises(ValueError, match="corrupt|exact imported full-refit origin"):
        await node.execute(X_new=source)


def test_model_store_assigns_and_requires_closed_ordinary_authority(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    artifact_uid = "16161616-1616-4616-8616-161616161616"
    manifest = {"model_type": "test"}
    store.save_new(artifact_uid, manifest, {"state": np.asarray([1], dtype=np.int64)})
    assert manifest["artifact_authority"] == ORDINARY_MODEL_ARTIFACT_AUTHORITY
    assert store.load_manifest(artifact_uid)["artifact_authority"] == ORDINARY_MODEL_ARTIFACT_AUTHORITY

    manifest_path = Path(store.artifact_directory(artifact_uid)) / "manifest.json"
    persisted = parse_model_manifest_json(manifest_path.read_bytes())
    persisted["artifact_authority"] = None
    manifest_path.write_text(json.dumps(persisted), encoding="utf-8")
    with pytest.raises(ModelArtifactIntegrityError, match="supported persisted authority"):
        store.load_manifest(artifact_uid)


def test_archived_model_training_link_is_derived_only_from_exact_experiment_authority() -> None:
    from spectra_sherpa.app.api.v1.routes.projects import _bind_archived_model_training_source

    manifest = {
        "preprocessing_chain": [
            {
                "op_id": "spectrasherpa.experiment_dataset_read/2",
                "parameters": {
                    "asset_id": "spectrum",
                    "dataset_id": 7,
                    "file_count": 1,
                    "collection_definition_sha256": "a" * 64,
                    "source_manifest_sha256": "b" * 64,
                    "scientific_collection_sha256": "c" * 64,
                },
            }
        ]
    }
    experiment = {
        "id": 7,
        "file_count": 1,
        "collection_definition": {"rows": [{"asset_id": "spectrum"}]},
        "collection_definition_sha256": "a" * 64,
        "collection_source_manifest_sha256": "b" * 64,
        "scientific_collection_sha256": "c" * 64,
    }
    model_record: dict[str, object] = {}
    _bind_archived_model_training_source(
        manifest,
        model_record,
        owner_project_id=3,
        experiments={7: (3, experiment)},
    )
    assert model_record["training_dataset_id"] == 7

    for mutation in ("source_manifest_sha256", "scientific_collection_sha256", "file_count"):
        changed = deepcopy(manifest)
        changed["preprocessing_chain"][0]["parameters"][mutation] = "d" * 64
        with pytest.raises(HTTPException, match="cannot be derived exactly"):
            _bind_archived_model_training_source(
                changed,
                {},
                owner_project_id=3,
                experiments={7: (3, experiment)},
            )
    with pytest.raises(HTTPException, match="outside project custody"):
        _bind_archived_model_training_source(
            manifest,
            {},
            owner_project_id=4,
            experiments={7: (3, experiment)},
        )


@pytest.mark.asyncio
async def test_worker_and_editable_directory_reject_duplicate_manifest_keys(tmp_path: Path) -> None:
    _source, _selected, _artifact, bridge = await _canonical_bridge_fixture()
    store = ModelStore(tmp_path)
    artifact_uid = "15151515-1515-4515-8515-151515151515"
    store.save_new(artifact_uid, deepcopy(bridge.manifest), bridge.arrays)
    artifact_dir = Path(store.artifact_directory(artifact_uid))
    manifest_path = artifact_dir / "manifest.json"
    payload = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        payload.replace(
            '"artifact_origin": "imported_canonical_full_refit_application_artifact",',
            '"artifact_origin": null,\n  "artifact_origin": "imported_canonical_full_refit_application_artifact",',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ModelArtifactIntegrityError, match="ambiguous or malformed"):
        ReadOnlyModelArtifactReader(tmp_path).load(artifact_uid)
    with pytest.raises(ModelArtifactIntegrityError, match="ambiguous or malformed"):
        load_verified_artifact_directory(artifact_dir)


def test_model_store_create_new_is_atomic_under_same_uid(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    artifact_uid = "13131313-1313-4313-8313-131313131313"

    def publish(marker: int) -> tuple[int, str]:
        manifest = {"model_type": "test", "marker": marker}
        try:
            store.save_new(artifact_uid, manifest, {"state": np.asarray([marker], dtype=np.int64)})
        except ModelArtifactCollisionError:
            return marker, "collision"
        return marker, "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(publish, (1, 2)))
    assert sorted(status for _marker, status in outcomes) == ["collision", "saved"]
    winner = next(marker for marker, status in outcomes if status == "saved")
    manifest, arrays = store.load(artifact_uid)
    assert manifest["marker"] == winner
    np.testing.assert_array_equal(arrays["state"], np.asarray([winner], dtype=np.int64))


@pytest.mark.asyncio
async def test_saved_canonical_plsda_application_exposes_one_response_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _selected, _artifact, bridge = await _canonical_bridge_fixture()
    store = ModelStore(tmp_path)
    monkeypatch.setattr("spectra_sherpa.app.services.model_store._store", store)
    artifact_uid = "11111111-1111-4111-8111-111111111111"
    store.save(artifact_uid, deepcopy(bridge.manifest), bridge.arrays)

    response = await apply_model_to_dataset(artifact_uid, source)

    assert response["classification_output_semantics"] == CLASS_RESPONSE_SEMANTICS
    assert "probabilities" not in response
    assert np.asarray(response["class_responses"]).shape == (6, 2)
    assert np.asarray(response["decision_margins"]).shape == (6,)
    assert len(response["classification_application_digest"]) == 64
    assert response["predictions"] == [
        bridge.manifest["classes"][int(index)] for index in np.argmax(np.asarray(response["class_responses"]), axis=1)
    ]


@pytest.mark.asyncio
async def test_model_store_load_rejects_rehashed_but_semantically_mutated_canonical_state(
    tmp_path: Path,
) -> None:
    _source, _selected, _artifact, bridge = await _canonical_bridge_fixture()
    store = ModelStore(tmp_path)
    artifact_uid = "22222222-2222-4222-8222-222222222222"
    arrays = {name: np.array(value, copy=True) for name, value in bridge.arrays.items()}
    arrays["coefficients"][0, 0] += 1.0
    store.save(artifact_uid, deepcopy(bridge.manifest), arrays)

    with pytest.raises(ModelArtifactIntegrityError, match="canonical scientific lineage"):
        store.load(artifact_uid)


@pytest.mark.asyncio
async def test_canonical_bridge_publication_is_transactional_and_inspectable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    test_session,
    test_user,
) -> None:
    from sqlalchemy import select

    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.project import Project

    project = Project(user_id=test_user.id, name="Canonical import project")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Canonical training collection",
        metadata_path="",
    )
    test_session.add(experiment)
    await test_session.commit()
    _source, _selected, _artifact, bridge = await _canonical_bridge_fixture(experiment_id=experiment.id)
    store = ModelStore(tmp_path)
    monkeypatch.setattr("spectra_sherpa.app.services.model_store._store", store)

    row, receipt = await persist_canonical_plsda_bridge(
        test_session,
        user_id=test_user.id,
        project_id=project.id,
        training_dataset_id=experiment.id,
        bridge=bridge,
        re_admit_training_dataset=lambda: _awaited(_source),
        display_name="Imported canonical model",
    )

    observed = await test_session.scalar(select(ModelArtifact).where(ModelArtifact.id == row.id))
    assert observed is not None
    assert observed.artifact_origin == CANONICAL_MODEL_ORIGIN
    assert observed.training_dataset_id == experiment.id
    assert observed.metrics_json is None
    assert observed.description and "not full-refit or in-sample performance" in observed.description
    assert receipt["artifact_uid"] == observed.artifact_uid
    assert receipt["verified_after_storage"] is True
    manifest, arrays = store.load(observed.artifact_uid)
    validate_canonical_plsda_model_artifact(manifest, arrays)
    detail = await model_routes.get_model(observed.artifact_uid, session=test_session, current_user=test_user)
    assert detail.artifact_uid == observed.artifact_uid

    manifest_path = Path(store.artifact_directory(observed.artifact_uid)) / "manifest.json"
    original_manifest_bytes = manifest_path.read_bytes()
    downgraded = parse_model_manifest_json(original_manifest_bytes)
    for key in ("artifact_origin", "canonical_training_lineage", "classification_output_semantics"):
        del downgraded[key]
    downgraded["artifact_authority"] = ORDINARY_MODEL_ARTIFACT_AUTHORITY
    manifest_path.write_text(json.dumps(downgraded), encoding="utf-8")
    with pytest.raises(HTTPException) as downgraded_detail:
        await model_routes.get_model(observed.artifact_uid, session=test_session, current_user=test_user)
    assert downgraded_detail.value.status_code == 409
    manifest_path.write_bytes(original_manifest_bytes)

    tampered_arrays = {name: np.array(value, copy=True) for name, value in arrays.items()}
    tampered_arrays["coefficients"][0, 0] += 1.0
    store.save(observed.artifact_uid, deepcopy(manifest), tampered_arrays)
    with pytest.raises(HTTPException) as tampered:
        await model_routes.get_model(observed.artifact_uid, session=test_session, current_user=test_user)
    assert tampered.value.status_code == 409

    store.delete(observed.artifact_uid)
    with pytest.raises(HTTPException) as caught:
        await model_routes.get_model(observed.artifact_uid, session=test_session, current_user=test_user)
    assert caught.value.status_code == 409
    assert str(tmp_path) not in str(caught.value.detail)


@pytest.mark.asyncio
async def test_canonical_import_route_publishes_the_verified_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    test_session,
    test_user,
) -> None:
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.services import canonical_project_custody, model_application

    source, _selected, artifact, bridge = await _canonical_bridge_fixture()
    project = Project(user_id=test_user.id, name="Canonical route import")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Canonical route training collection",
        metadata_path="",
    )
    test_session.add(experiment)
    await test_session.commit()
    raw_source = _canonical_bridge_dataset(dataset_id=source.dataset_id)
    loaded = SimpleNamespace(project_id=project.id, experiment_id=experiment.id, dataset=raw_source)

    async def grant(*_args, **_kwargs):
        return SimpleNamespace(
            project_id=project.id,
            artifact_dir=tmp_path / "private-canonical-artifact",
            artifact_digest=artifact.artifact_digest,
        )

    async def load_training_dataset(*_args, **_kwargs):
        return loaded

    monkeypatch.setattr(canonical_project_custody, "resolve_canonical_artifact_read_grant", grant)
    monkeypatch.setattr(model_application, "load_project_dataset", load_training_dataset)
    monkeypatch.setattr(CanonicalFittedArtifact, "load", classmethod(lambda _cls, _path: artifact))
    store = ModelStore(tmp_path / "models")
    monkeypatch.setattr("spectra_sherpa.app.services.model_store._store", store)

    lineage = bridge.manifest["canonical_training_lineage"]
    payload = CanonicalFullRefitImportRequest.model_validate(
        {
            "project_id": project.id,
            "canonical_workflow_id": 1,
            "training_experiment_id": experiment.id,
            "asset_id": "spectrum",
            "graph": lineage["graph"],
            "validation_execution": lineage["validation_execution"],
            "original_capability_metadata": lineage["capability"]["original_metadata"],
            "custody_id": lineage["capability"]["custody_id"],
            "target_attachment_node_id": lineage["supervision_attachment_node_id"],
            "target_authority": lineage["supervision_binding"]["target_authority"],
            "group_column": lineage["supervision_binding"]["group_column"],
            "feature_mask": lineage["selection"]["feature_mask"],
            "selection_report": lineage["selection"]["selection_report"],
            "display_name": "Canonical route model",
        }
    )
    response = await model_routes.import_canonical_full_refit(
        payload,
        _dg=None,
        session=test_session,
        current_user=test_user,
    )

    assert response.model.artifact_origin == CANONICAL_MODEL_ORIGIN
    assert response.model.display_name == "Canonical route model"
    assert response.receipt["verified_after_storage"] is True
    assert store.list_artifacts() == [response.model.artifact_uid]


@pytest.mark.asyncio
async def test_canonical_bridge_publication_compensates_audit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    test_session,
    test_user,
) -> None:
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.project import Project

    project = Project(user_id=test_user.id, name="Failed canonical import")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Canonical training collection",
        metadata_path="",
    )
    test_session.add(experiment)
    await test_session.commit()
    _source, _selected, _artifact, bridge = await _canonical_bridge_fixture(experiment_id=experiment.id)
    store = ModelStore(tmp_path)
    monkeypatch.setattr("spectra_sherpa.app.services.model_store._store", store)

    def fail_audit(**_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("spectra_sherpa.app.services.audit.audit_emitter.emit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await persist_canonical_plsda_bridge(
            test_session,
            user_id=test_user.id,
            project_id=project.id,
            training_dataset_id=experiment.id,
            bridge=bridge,
            re_admit_training_dataset=lambda: _awaited(_source),
        )
    assert store.list_artifacts() == []


@pytest.mark.asyncio
async def test_canonical_bridge_collision_never_overwrites_or_deletes_the_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    test_session,
    test_user,
) -> None:
    import uuid

    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.project import Project

    project = Project(user_id=test_user.id, name="Canonical collision project")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Canonical collision collection",
        metadata_path="",
    )
    test_session.add(experiment)
    await test_session.commit()
    source, _selected, _artifact, bridge = await _canonical_bridge_fixture(experiment_id=experiment.id)
    store = ModelStore(tmp_path)
    monkeypatch.setattr("spectra_sherpa.app.services.model_store._store", store)
    collision_uid = "14141414-1414-4414-8414-141414141414"
    fresh_uid = "15151515-1515-4515-8515-151515151515"
    store.save_new(collision_uid, {"model_type": "winner"}, {"state": np.asarray([42], dtype=np.int64)})
    winner_manifest_before = (Path(store.artifact_directory(collision_uid)) / "manifest.json").read_bytes()
    identities = iter((uuid.UUID(collision_uid), uuid.UUID(fresh_uid)))
    from types import SimpleNamespace

    # Scope the collision to artifact allocation; typed replay legitimately
    # creates dataset identities and must retain the real UUID implementation.
    monkeypatch.setattr(
        "spectra_sherpa.app.services.canonical_model_bridge.uuid",
        SimpleNamespace(uuid4=lambda: next(identities)),
    )

    row, _receipt = await persist_canonical_plsda_bridge(
        test_session,
        user_id=test_user.id,
        project_id=project.id,
        training_dataset_id=experiment.id,
        bridge=bridge,
        re_admit_training_dataset=lambda: _awaited(source),
    )

    assert row.artifact_uid == fresh_uid
    assert (Path(store.artifact_directory(collision_uid)) / "manifest.json").read_bytes() == winner_manifest_before
    winner_manifest, winner_arrays = store.load(collision_uid)
    assert winner_manifest["model_type"] == "winner"
    np.testing.assert_array_equal(winner_arrays["state"], np.asarray([42], dtype=np.int64))


@pytest.mark.asyncio
async def test_canonical_bridge_publication_refuses_source_drift_before_database_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    test_session,
    test_user,
) -> None:
    from sqlalchemy import select

    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.project import Project

    project = Project(user_id=test_user.id, name="Drifted canonical import")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Canonical training collection",
        metadata_path="",
    )
    test_session.add(experiment)
    await test_session.commit()
    source, _selected, _artifact, bridge = await _canonical_bridge_fixture(experiment_id=experiment.id)
    store = ModelStore(tmp_path)
    monkeypatch.setattr("spectra_sherpa.app.services.model_store._store", store)
    drifted = source.with_data(np.asarray(source.X) + 0.01)

    with pytest.raises(CanonicalModelBridgeError, match="live training dataset"):
        await persist_canonical_plsda_bridge(
            test_session,
            user_id=test_user.id,
            project_id=project.id,
            training_dataset_id=experiment.id,
            bridge=bridge,
            re_admit_training_dataset=lambda: _awaited(drifted),
        )
    assert store.list_artifacts() == []
    assert await test_session.scalar(select(ModelArtifact.id)) is None


async def _awaited(dataset: SherpaDataset) -> SherpaDataset:
    return dataset


@pytest.mark.anyio
async def test_canonical_saved_model_project_roundtrip_remaps_only_storage_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_client,
    test_session,
    test_user,
) -> None:
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext
    from spectra_sherpa.app.services.collection_definitions import remove_collection_definition
    from spectra_sherpa.app.services.model_application import load_project_dataset

    store = ModelStore(tmp_path / "portable-model-store")
    monkeypatch.setattr("spectra_sherpa.app.services.model_store._store", store)
    project = (await auth_client.post("/api/v1/projects", json={"name": "Portable canonical model"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Six-source training collection", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    experiment_id = int(experiment["id"])
    remove_collection_definition(experiment_id)
    spectra = (
        (2.0, 1.2, 0.2, 0.1, 0.0),
        (0.0, 0.1, 0.2, 1.2, 2.0),
        (2.1, 1.1, 0.1, 0.2, 0.0),
        (0.1, 0.0, 0.3, 1.1, 1.9),
        (1.9, 1.3, 0.2, 0.1, 0.1),
        (0.0, 0.2, 0.1, 1.3, 2.1),
    )
    source_records: list[tuple[dict[str, object], str]] = []
    for index, values in enumerate(spectra, start=1):
        csv_bytes = (
            "Wavenumber (cm-1),Absorbance\n"
            + "\n".join(f"{1000 + offset},{value}" for offset, value in enumerate(values))
            + "\n"
        ).encode()
        uploaded = await auth_client.post(
            f"/api/v1/experiments/{experiment_id}/files",
            data={"stage": "raw"},
            files={"file": (f"source-{index}.csv", csv_bytes, "text/csv")},
        )
        assert uploaded.status_code == 201, uploaded.text
        source_records.append((uploaded.json(), hashlib.sha256(csv_bytes).hexdigest()))
    rows = []
    for index, (record, source_sha256) in enumerate(source_records):
        sample_id = f"sample-{index + 1}"
        rows.append(
            {
                "file_name": record["file_path"],
                "sha256": source_sha256,
                "asset_id": "table",
                "source_row_index": 0,
                "sample_id": sample_id,
                "annotations": {
                    "sample_id": sample_id,
                    "specimen_id": "A" if index % 2 == 0 else "B",
                    "block": (index // 2) + 1,
                },
            }
        )
    definition = {
        "schema_version": "spectrasherpa-collection-definition/1",
        "columns": ["sample_id", "specimen_id", "block"],
        "collection": {
            "dataset_id": "phase8-portable-training/1",
            "title": "Portable canonical PLS-DA training collection",
            "units": "absorbance",
            "data_role": "X_spectra",
            "domain": DomainContext(
                technique="IR",
                expected_units="cm-1",
                data_quantity="Absorbance",
            ).model_dump(mode="json", exclude_none=False),
            "sample_axis": {"title": "Verified samples", "units": None, "values_policy": "omit"},
        },
        "rows": rows,
    }
    definition_bytes = (json.dumps(definition, sort_keys=True, separators=(",", ":")) + "\n").encode()
    attached_response = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files={"file": ("collection-definition.json", definition_bytes, "application/json")},
    )
    assert attached_response.status_code == 200, attached_response.text

    loaded = await load_project_dataset(
        test_session,
        user_id=test_user.id,
        experiment_id=experiment_id,
        stage="raw",
        asset_id="table",
        strict_prepared_data=True,
    )
    attached = attach_target_dataset(
        loaded.dataset,
        None,
        target_type="categorical",
        node_id="canonical-full-refit-import",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    binding = bind_sample_table_supervision(
        attached,
        target_column="specimen_id",
        target_type="categorical",
        group_column="block",
    )
    plan = make_leave_one_group_out_classification_plan(
        binding.target,
        binding.groups,
        require_one_per_class_group=True,
    )
    capability = SpectralDatasetCapability.from_dataset(
        attached,
        custody_id="phase8-portable",
        dataset_ref_digest=binding.digest,
        split_plan_digest=plan.digest,
        groups=binding.groups,
    )
    graph = admit_validation_graph(
        [
            WorkflowNode(
                "window",
                "selection.variable_select",
                {"method": "interval", "region_start": 1001.0, "region_end": 1003.0},
            ),
            WorkflowNode("model", "classification.plsda", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.classification_evaluator", {}),
        ],
        [
            WorkflowEdge("window", "model"),
            WorkflowEdge("model", "score", from_output="predictions", to_input="default"),
        ],
    )
    validation = await execute_candidate_validation(graph, capability, plan)
    refit = await execute_selected_candidate_full_refit(graph, capability, validation)
    canonical = CanonicalFittedArtifact.from_full_refit_execution(refit)
    selector = node_registry.create_node(
        "selection.variable_select",
        "window",
        {"method": "interval", "region_start": 1001.0, "region_end": 1003.0},
    )
    selection = (await selector.execute(X=attached)).outputs
    bridge = bridge_canonical_plsda_artifact(
        canonical,
        graph_payload=graph.as_dict(),
        training_dataset=attached,
        experiment_id=experiment_id,
        asset_id="table",
        validation_execution=validation.as_dict(),
        original_capability_metadata=capability.to_wire()["metadata"],
        custody_id="phase8-portable",
        feature_mask=selection["mask"].tolist(),
        selection_report=selection["selection_report"],
    )

    from spectra_sherpa.app.services.canonical_model_bridge import _dataset_record

    fresh_loaded = await load_project_dataset(
        test_session,
        user_id=test_user.id,
        experiment_id=experiment_id,
        stage="raw",
        asset_id="table",
        strict_prepared_data=True,
    )
    fresh_attached = attach_target_dataset(
        fresh_loaded.dataset,
        None,
        target_type="categorical",
        node_id="canonical-full-refit-import",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    assert {**_dataset_record(fresh_attached), "asset_id": "table"} == bridge.manifest["canonical_training_lineage"][
        "source_dataset"
    ]
    fresh_binding = bind_sample_table_supervision(
        fresh_attached,
        target_column="specimen_id",
        target_type="categorical",
        group_column="block",
    )
    assert fresh_binding.digest == bridge.manifest["canonical_training_lineage"]["supervision_binding_sha256"]

    async def re_admit():
        return fresh_attached

    model_row, _receipt = await persist_canonical_plsda_bridge(
        test_session,
        user_id=test_user.id,
        project_id=project["id"],
        training_dataset_id=experiment_id,
        bridge=bridge,
        re_admit_training_dataset=re_admit,
    )
    original_result = await apply_model_to_dataset(model_row.artifact_uid, loaded.dataset)

    from spectra_sherpa.app.models.model_artifact import ModelArtifact

    pca_uid = "17171717-1717-4717-8717-171717171717"
    pca_chain = [
        {
            "op_id": "spectrasherpa.experiment_dataset_read/2",
            "parameters": {
                "asset_id": "table",
                "dataset_id": experiment_id,
                "stage": "raw",
            },
        }
    ]
    pca_manifest = {
        "artifact_authority": ORDINARY_MODEL_ARTIFACT_AUTHORITY,
        "model_type": "pca",
        "node_id": "pca",
        "n_features": 5,
        "n_components": 1,
        "feature_axis": [1000.0, 1001.0, 1002.0, 1003.0, 1004.0],
        "preprocessing_chain": deepcopy(pca_chain),
        "training_data_hash": "f" * 64,
    }
    pca_integrity = store.save(
        pca_uid,
        pca_manifest,
        {"loadings": np.ones((1, 5), dtype=np.float64)},
    )
    test_session.add(
        ModelArtifact(
            artifact_uid=pca_uid,
            user_id=test_user.id,
            project_id=project["id"],
            training_dataset_id=experiment_id,
            node_id="pca",
            model_type="pca",
            name="Portable ordinary PCA",
            artifact_dir=str(store._artifact_dir(pca_uid)),
            integrity_hash=pca_integrity,
            n_features=5,
            n_components=1,
            feature_axis_json=json.dumps(pca_manifest["feature_axis"]),
            preprocessing_summary=json.dumps(pca_chain),
            training_data_hash=pca_manifest["training_data_hash"],
        )
    )
    await test_session.commit()

    exported = await auth_client.get(f"/api/v1/projects/{project['id']}/export/sherpa")
    assert exported.status_code == 200, exported.text
    imported = await auth_client.post(
        "/api/v1/projects/import",
        files={"file": ("portable-canonical.sherpa", io.BytesIO(exported.content), "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    imported_payload = imported.json()
    imported_model = next(item for item in imported_payload["models"] if item["model_type"] == "plsda")
    imported_pca = next(item for item in imported_payload["models"] if item["model_type"] == "pca")
    imported_experiment_id = int(imported_payload["experiments"][0]["id"])
    assert imported_model["artifact_uid"] != model_row.artifact_uid

    imported_dataset = await load_project_dataset(
        test_session,
        user_id=test_user.id,
        experiment_id=imported_experiment_id,
        stage="raw",
        asset_id="table",
        strict_prepared_data=True,
    )
    result = await apply_model_to_dataset(imported_model["artifact_uid"], imported_dataset.dataset)
    assert result["classification_output_semantics"] == CLASS_RESPONSE_SEMANTICS
    assert result["class_responses"] == original_result["class_responses"]
    assert result["decision_margins"] == original_result["decision_margins"]
    assert result["classification_application_digest"] == original_result["classification_application_digest"]
    imported_manifest, imported_arrays = store.load(imported_model["artifact_uid"])
    imported_lineage = validate_canonical_plsda_model_artifact(imported_manifest, imported_arrays)
    assert imported_lineage["lineage_digest"] == bridge.receipt["lineage_digest"]
    assert imported_experiment_id != experiment_id
    assert imported_manifest["preprocessing_chain"][0]["parameters"]["dataset_id"] == imported_experiment_id
    assert imported_manifest["canonical_training_lineage"] == bridge.manifest["canonical_training_lineage"]
    imported_pca_manifest, _ = store.load(imported_pca["artifact_uid"])
    assert imported_pca_manifest["preprocessing_chain"][0]["parameters"]["dataset_id"] == imported_experiment_id
    original_manifest, original_arrays = store.load(model_row.artifact_uid)
    assert validate_canonical_plsda_model_artifact(original_manifest, original_arrays)["lineage_digest"] == (
        bridge.receipt["lineage_digest"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "state",
        "mask",
        "graph",
        "validation",
        "capability",
        "attachment-node",
        "source",
        "top-mask-integer",
        "preprocessing-source",
        "preprocessing-report",
        "original-capability-metadata",
        "extra-manifest-field",
    ],
)
async def test_canonical_bridge_refuses_scientific_identity_mutations(mutation: str) -> None:
    source, _selected, _artifact, bridge = await _canonical_bridge_fixture()
    manifest = deepcopy(bridge.manifest)
    arrays = {name: np.array(value, copy=True) for name, value in bridge.arrays.items()}
    if mutation == "state":
        arrays["coefficients"][0, 0] += 1.0
    elif mutation == "mask":
        manifest["canonical_training_lineage"]["selection"]["feature_mask"][0] = True
        unsigned = {
            key: value for key, value in manifest["canonical_training_lineage"].items() if key != "lineage_digest"
        }
        manifest["canonical_training_lineage"]["lineage_digest"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
    elif mutation == "graph":
        manifest["canonical_training_lineage"]["graph"]["nodes"][1]["parameters"]["n_components"] = 2
        unsigned = {
            key: value for key, value in manifest["canonical_training_lineage"].items() if key != "lineage_digest"
        }
        manifest["canonical_training_lineage"]["lineage_digest"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
    elif mutation == "validation":
        manifest["canonical_training_lineage"]["validation_execution"]["split_plan_digest"] = "f" * 64
        _rehash_lineage(manifest)
    elif mutation == "capability":
        manifest["canonical_training_lineage"]["capability"]["original_content_digest"] = "f" * 64
        _rehash_lineage(manifest)
    elif mutation == "attachment-node":
        manifest["canonical_training_lineage"]["supervision_attachment_node_id"] = "rogue-attachment"
        _rehash_lineage(manifest)
    elif mutation == "source":
        source = source.with_data(np.asarray(source.X) + 0.01)
    elif mutation == "top-mask-integer":
        manifest["feature_mask"] = [int(value) for value in manifest["feature_mask"]]
    elif mutation == "preprocessing-source":
        manifest["preprocessing_chain"][0]["parameters"]["source_manifest_sha256"] = "f" * 64
    elif mutation == "preprocessing-report":
        manifest["preprocessing_chain"][1]["parameters"]["selection_report"]["reference_samples"] = 999
    elif mutation == "original-capability-metadata":
        manifest["canonical_training_lineage"]["capability"]["original_metadata"]["custody_id"] = "replacement"
        _rehash_lineage(manifest)
    else:
        manifest["unbound_metadata"] = "not allowed"
    with pytest.raises(CanonicalModelBridgeError):
        validate_canonical_plsda_model_artifact(manifest, arrays, training_dataset=source)


def _rehash_lineage(manifest: dict[str, object]) -> None:
    lineage = manifest["canonical_training_lineage"]
    assert isinstance(lineage, dict)
    unsigned = {key: value for key, value in lineage.items() if key != "lineage_digest"}
    lineage["lineage_digest"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
