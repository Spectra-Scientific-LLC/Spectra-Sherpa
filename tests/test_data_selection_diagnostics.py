"""Refusal diagnostics expose boundary names, never scientific payloads."""

import logging
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException

from spectra_sherpa.app.lib.dataset_view_receipts import LoadedProjectDataset, receipt_sha256, selection_receipt
from spectra_sherpa.app.models.dataset_view import DatasetView
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.schemas.workflow_data_selection import WorkflowSourceSelection
from spectra_sherpa.app.services.workflow_data_selections import (
    _log_selection_refusal,
    _portfolio_mismatch_fields,
    validate_selection,
)


def selection():
    return WorkflowSourceSelection(
        experiment_id=1,
        dataset_name="PRIVATE dataset /secret/path",
        stage="synthetic",
        selected_file_ids=None,
        asset_id="PRIVATE asset",
        source_manifest_sha256="a" * 64,
        scientific_collection_sha256="b" * 64,
        group_column="PRIVATE group",
        target_authority={
            "schema_version": "spectrasherpa-target-authority/1",
            "column": "PRIVATE concentration",
            "target_type": "continuous",
            "units": "ppm",
            "source_digest": "c" * 64,
        },
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("stage", "raw"),
        ("asset_id", "another private asset"),
        ("source_manifest_sha256", "d" * 64),
        ("collection_definition_sha256", "e" * 64),
        ("scientific_collection_sha256", "f" * 64),
        ("group_column", "another private group"),
        ("target_authority", None),
        ("selected_file_ids", [99]),
    ],
)
def test_refusal_identifies_only_changed_boundary_without_payload(field, value, caplog):
    requested = selection()
    receipt = {**requested.model_dump(mode="json"), "file_ids": [1]}
    receipt[field] = value
    fields = _portfolio_mismatch_fields(requested, receipt)
    assert fields == (field,)
    with caplog.at_level(logging.WARNING):
        _log_selection_refusal(requested, code="saved_portfolio", fields=fields)
    message = caplog.records[-1].getMessage()
    assert message == f"DATA_SELECTION_REFUSED code=saved_portfolio experiment_id=1 dataset_view_id=None fields={field}"
    assert "PRIVATE" not in message and "/secret" not in message
    assert not any(digest * 64 in message for digest in "abcdef")


def test_exact_captured_file_set_remains_equivalent_to_all_files():
    requested = selection()
    receipt = {**requested.model_dump(mode="json"), "file_ids": [4, 7]}
    assert not _portfolio_mismatch_fields(requested, receipt)
    assert not _portfolio_mismatch_fields(requested.model_copy(update={"selected_file_ids": [4, 7]}), receipt)
    assert _portfolio_mismatch_fields(requested.model_copy(update={"selected_file_ids": [4]}), receipt) == (
        "selected_file_ids",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["raw", "preprocessed", "synthetic"])
async def test_saved_portfolio_stage_conflict_is_observable_and_still_refused(
    test_session, test_user, monkeypatch, caplog, stage
):
    project = Project(user_id=test_user.id, name="Private audit")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id, project_id=project.id, name="Private source", metadata_path="meta.json"
    )
    test_session.add(experiment)
    await test_session.flush()
    loaded = LoadedProjectDataset(
        dataset=SimpleNamespace(
            n_samples=3,
            sample_axis=SimpleNamespace(include_mask=np.ones(3, dtype=bool)),
            meta={"source_collection": {"files": [{"file_name": "private.npz", "sha256": "a" * 64}]}},
        ),
        experiment_id=experiment.id,
        experiment_name=experiment.name,
        project_id=project.id,
        file_ids=[17],
        stage=stage,
        asset_id=None,
        source_manifest_sha256="a" * 64,
        scientific_collection_sha256="b" * 64,
    )

    async def load(*args, **kwargs):
        # Mirrors the existing raw→synthetic loader fallback. Scientific source
        # identity is unchanged, but that does not authorize a conflicting receipt.
        return loaded

    monkeypatch.setattr("spectra_sherpa.app.services.workflow_data_selections.load_project_dataset", load)
    receipt = selection_receipt(loaded, selected_file_ids=None)
    view = DatasetView(
        project_id=project.id,
        experiment_id=experiment.id,
        created_by_user_id=test_user.id,
        name="Private portfolio",
        name_key="private portfolio",
        selection=receipt,
        selection_sha256=receipt_sha256(receipt),
    )
    test_session.add(view)
    await test_session.commit()
    request = WorkflowSourceSelection(
        experiment_id=experiment.id,
        dataset_name=view.name,
        stage=stage,
        source_manifest_sha256="a" * 64,
        scientific_collection_sha256="b" * 64,
        dataset_view_id=view.id,
        dataset_view_sha256=view.selection_sha256,
    )
    await validate_selection(test_session, selection=request, user_id=test_user.id, workflow_project_id=project.id)
    assert not [r for r in caplog.records if "DATA_SELECTION_REFUSED" in r.getMessage()]
    wrong = request.model_copy(update={"stage": "raw" if stage != "raw" else "synthetic"})
    with caplog.at_level(logging.WARNING), pytest.raises(HTTPException) as refusal:
        await validate_selection(test_session, selection=wrong, user_id=test_user.id, workflow_project_id=project.id)
    assert refusal.value.status_code == 409
    assert refusal.value.detail == "Workflow selection differs from the saved dataset definition"
    message = next(r.getMessage() for r in caplog.records if "DATA_SELECTION_REFUSED" in r.getMessage())
    assert message.endswith("fields=stage")
    assert "Private" not in message and "a" * 64 not in message
