"""PLS-DA receipt keys belong to typed observations, not editable labels."""

from __future__ import annotations

import json
from copy import deepcopy

import numpy as np
import pytest

from spectra_sherpa.app.lib.sample_identity import sample_ids
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import (
    PLSDANode,
    _plsda_scientific_core,
    apply_plsda_fitted_state,
)
from spectra_sherpa.app.services.dag.nodes.classification.plsda_sample_diagnostics import build_sample_diagnostics
from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import SherpaPLSDAArtifact
from spectra_sherpa.app.services.diagnostic_review_summary import build_summary


def _dataset(n=18):
    rng = np.random.default_rng(1203)
    classes = np.tile(["a", "b", "c"], n // 3)
    matrix = rng.normal(size=(n, 4))
    matrix[:, 0] += np.tile([0.0, 1.0, 2.0], n // 3)
    return SherpaDataset(
        X=matrix,
        sample_axis=SampleAxis(
            labels=[f"Display {i}" for i in range(n)],
            sample_table={"sample_id": [f"observation-{i}" for i in range(n)]},
        ),
        feature_axis=SpectralAxis(values=np.arange(4) + 1000, units="cm-1"),
        target=classes,
        target_context=TargetContext(target_type="categorical", target_names=["class"]),
    )


def _core(dataset):
    return _plsda_scientific_core(dataset, None, parameters={"n_components": 2, "scale": True})


def _statistics(receipt):
    return [{k: v for k, v in row.items() if k not in {"id", "display_label"}} for row in receipt["rows"]]


@pytest.mark.parametrize("labels", [None, ["Repeated"] * 18, [f"Renamed {i}" for i in range(18)]])
def test_display_labels_never_change_identity_fit_or_statistics(labels):
    source = _dataset()
    core = _core(source)
    state = core["artifact"].to_fitted_state()
    original = build_sample_diagnostics(core)
    changed = source.copy()
    axis = changed.sample_axis
    axis.labels = labels
    changed.sample_axis = axis
    assert changed.sample_axis.labels == labels
    current = _core(changed)
    receipt = build_sample_diagnostics(current)
    assert receipt["identity_field"] == "sample_id"
    assert [row["id"] for row in receipt["rows"]] == sample_ids(source)
    assert _statistics(receipt) == _statistics(original)
    selected = sample_ids(source)[:2]
    packet = build_summary(original, selected_ids=selected)
    assert build_summary(receipt, selected_ids=selected) == packet
    without_display = deepcopy(receipt)
    for row in without_display["rows"]:
        row.pop("display_label", None)
    assert build_summary(without_display, selected_ids=selected) == packet
    assert not any(text in json.dumps(packet) for text in ["Display", "Repeated", "Renamed", *selected])
    assert current["artifact"].to_fitted_state() == state
    np.testing.assert_array_equal(current["train_predictions"], core["train_predictions"])
    np.testing.assert_array_equal(current["train_class_scores"], core["train_class_scores"])
    if labels is None:
        assert all("display_label" not in row for row in receipt["rows"])
    else:
        assert [row["display_label"] for row in receipt["rows"]] == labels
    # Deserialize/application remains independent of newly generated diagnostics.
    recovered = SherpaPLSDAArtifact.from_fitted_state(json.loads(json.dumps(state)))
    assert recovered.to_fitted_state() == state
    predictions, scores = apply_plsda_fitted_state(changed, state)
    np.testing.assert_array_equal(predictions, core["train_predictions"])
    np.testing.assert_array_equal(scores, core["train_class_scores"])


def test_reordered_rows_keep_exact_typed_identity_across_chunk_boundary():
    source = _dataset(72)
    order = np.arange(71, -1, -1)
    reordered = source[order]
    receipt = build_sample_diagnostics(_core(reordered))
    assert [row["id"] for row in receipt["rows"]] == [sample_ids(source)[i] for i in order]
    assert [row["display_label"] for row in receipt["rows"]] == [f"Display {i}" for i in order]
    for row, target in zip(receipt["rows"], reordered.target, strict=True):
        assert row["class"] == target
        terms = row["terms"]
        np.testing.assert_allclose(
            sum(term[1] for term in terms["variables"]) + terms["omitted_q"], row["q"], rtol=1e-10, atol=1e-12
        )
        np.testing.assert_allclose(
            sum(term[2] for term in terms["variables"]) + terms["omitted_t2"], row["t2"], rtol=1e-10, atol=1e-12
        )


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "blank", "whitespace"])
@pytest.mark.asyncio
async def test_invalid_typed_ids_refuse_diagnostics_without_label_fallback(invalid):
    source = _dataset()
    axis = source.sample_axis
    if invalid == "missing":
        axis.sample_table = None
    else:
        ids = list(axis.sample_table["sample_id"])
        ids[1] = {"duplicate": ids[0], "blank": "", "whitespace": " padded "}[invalid]
        axis.sample_table = {"sample_id": ids}
    source.sample_axis = axis
    core = _core(source)
    with pytest.raises(ValueError, match="sample_id"):
        build_sample_diagnostics(core)
    result = await PLSDANode("identity-refusal", {"n_components": 2, "scale": True}).execute(X=source)
    assert "sample_id" in result.outputs["sample_diagnostics"]["unavailable_reason"]
    assert "rows" not in result.outputs["sample_diagnostics"]
    np.testing.assert_array_equal(result.outputs["predictions"], core["train_predictions"])


@pytest.mark.parametrize("label", ["", "   ", "x" * 513])
def test_unusable_display_text_is_omitted_without_losing_rows(label):
    source = _dataset()
    axis = source.sample_axis
    axis.labels = [label] * source.n_samples
    source.sample_axis = axis
    receipt = build_sample_diagnostics(_core(source))
    assert [row["id"] for row in receipt["rows"]] == sample_ids(source)
    assert all("display_label" not in row for row in receipt["rows"])


@pytest.mark.asyncio
async def test_imported_iris_saved_receipt_and_typed_selection(auth_client, test_session, test_user, monkeypatch):
    """Real import/fit/retention/read routes; selection does not add workflow-review support."""
    import hashlib

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from spectra_sherpa.app.db import session as db_session
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.models.experiment_file import ExperimentFile
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.schemas.workflow_data_selection import WorkflowSourceSelection
    from spectra_sherpa.app.services.dag.nodes.data.transforms import FilterSamplesNode
    from spectra_sherpa.app.services.experiments import experiment_dir
    from spectra_sherpa.app.services.model_application import load_project_dataset
    from spectra_sherpa.app.services.pca_review_evidence import review_filter_parameters
    from spectra_sherpa.app.services.workflow_data_selections import source_parameters

    monkeypatch.setattr(db_session, "async_session", async_sessionmaker(test_session.bind, expire_on_commit=False))
    project = await auth_client.post("/api/v1/projects", json={"name": "Typed PLSDA identity"})
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    experiment = await auth_client.post("/api/v1/experiments", json={"name": "Iris", "project_id": pid})
    assert experiment.status_code == 201, experiment.text
    eid = experiment.json()["id"]
    imported = await auth_client.post(
        f"/api/v1/experiments/{eid}/import-reference", json={"datasets": [{"source": "sklearn", "name": "iris"}]}
    )
    assert imported.status_code == 201, imported.text
    file = await test_session.get(ExperimentFile, imported.json()["files"][0]["id"])
    path = experiment_dir(eid) / file.file_path
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    loaded = await load_project_dataset(test_session, user_id=test_user.id, experiment_id=eid)
    identities = sample_ids(loaded.dataset)
    display = list(loaded.dataset.sample_axis.labels)
    assert len(identities) == 150 and len(set(identities)) == 150
    assert set(identities).isdisjoint(display)
    binding = source_parameters(
        WorkflowSourceSelection(
            experiment_id=eid,
            dataset_name="Iris",
            stage="raw",
            selected_file_ids=loaded.file_ids,
            source_manifest_sha256=loaded.source_manifest_sha256,
            collection_definition_sha256=loaded.collection_definition_sha256,
            scientific_collection_sha256=loaded.scientific_collection_sha256,
            asset_id=loaded.asset_id,
        )
    )
    workflow = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Iris PLSDA",
            "project_id": pid,
            "nodes": [
                {"node_id": "source", "node_type": "data.collection_load", "parameters": binding},
                {
                    "node_id": "plsda",
                    "node_type": "classification.plsda",
                    "parameters": {"n_components": 2, "scale": True},
                },
            ],
            "edges": [{"from_node_id": "source", "to_node_id": "plsda", "from_output": "default", "to_input": "X"}],
        },
    )
    assert workflow.status_code == 201, workflow.text
    wid = workflow.json()["id"]
    executed = await auth_client.post(f"/api/v1/workflows/{wid}/execute", json={})
    assert executed.status_code == 200 and executed.json()["status"] == "completed", executed.text
    run = await test_session.scalar(select(ExecutionRun).where(ExecutionRun.workflow_id == wid))
    model = await test_session.scalar(select(ModelArtifact).where(ModelArtifact.source_run_id == run.id))
    assert model.node_id == "plsda" and model.artifact_uid in run.produced_artifact_uids
    endpoint = f"/api/v1/models/{model.artifact_uid}/plsda-diagnostics?project_id={pid}"
    saved = await auth_client.get(endpoint)
    assert saved.status_code == 200, saved.text
    receipt = saved.json()["receipt"]
    assert receipt["identity_field"] == "sample_id"
    assert [row["id"] for row in receipt["rows"]] == identities
    assert [row["display_label"] for row in receipt["rows"]] == display
    assert (await auth_client.get(endpoint)).json() == saved.json()
    packet = build_summary(receipt, selected_ids=[identities[0]])
    assert packet["selection_count"] == 1
    assert packet["facts"]["S1.q"]["value"] == receipt["rows"][0]["q"]
    legacy_presentation = deepcopy(receipt)
    for row in legacy_presentation["rows"]:
        row.pop("display_label")
    assert build_summary(legacy_presentation, selected_ids=[identities[0]]) == packet
    for row in legacy_presentation["rows"]:
        row["display_label"] = "PRIVATE duplicated display"
    assert build_summary(legacy_presentation, selected_ids=[identities[0]]) == packet
    assert "PRIVATE" not in json.dumps(packet)
    with pytest.raises(ValueError, match="unique saved calibration"):
        build_summary(receipt, selected_ids=[display[0]])
    # The canonical review filter consumes the retained typed ID without fitting.
    result = await FilterSamplesNode("selected", review_filter_parameters([receipt["rows"][0]["id"]])).execute(
        X=loaded.dataset
    )
    assert sample_ids(result["default"]) == identities[1:]
    # Current route admission is PCA/PLS only, not newly extended by this producer fix.
    review = await auth_client.get(f"/api/v1/workflows/{wid}/sample-review/plsda")
    assert review.status_code == 409 and review.json()["detail"] == "Choose a fitted PCA node."
    assert hashlib.sha256(path.read_bytes()).hexdigest() == source_hash
    fresh = await load_project_dataset(test_session, user_id=test_user.id, experiment_id=eid)
    assert sample_ids(fresh.dataset) == identities
    assert list(fresh.dataset.sample_axis.labels) == display
