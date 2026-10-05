"""Read-only current-project provenance; missing evidence is never inferred."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session, require_project
from spectra_sherpa.app.contracts.project_provenance import hosted_project_provenance
from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
from spectra_sherpa.app.models.dataset_view import DatasetView
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project_choice_event import ProjectChoiceEvent
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.dataset_views import receipt_sha256, verify_selection_receipt
from spectra_sherpa.app.services.model_application import load_project_dataset
from spectra_sherpa.app.services.model_store import ModelArtifactIntegrityError, verify_model_artifact_storage_record
from spectra_sherpa.app.services.project_availability import project_availability

router = APIRouter(prefix="/projects/{project_id}/provenance")

# The top bar is opened on every page and rechecked on focus. Keep its last
# fully verified, small response briefly; explicit detail requests always run
# the live checks. Never cache across actors or projects.
_SUMMARY_TTL_SECONDS = 30
_summary_cache: dict[tuple[int, int], tuple[float, dict]] = {}

KINDS = ("source", "dataset", "workflow", "run", "environment", "model", "campaign", "package")
LABELS = {
    "source": "Source file",
    "dataset": "Dataset",
    "workflow": "Workflow",
    "run": "Run",
    "environment": "Environment",
    "model": "Calibrated model",
    "campaign": "Optimization campaign",
    "package": "Signed package",
}
DESTINATIONS = {
    "source": "/data?tab=my-dataset",
    "dataset": "/data?tab=my-dataset",
    "workflow": "/workflow",
    "run": "/runs",
    "environment": "/runs",
    "model": "/runs?tab=models",
    "campaign": "/campaigns",
    "package": "/deploy",
}


def _record(
    kind: str,
    *,
    state: str = "missing",
    name: str | None = None,
    digest: str | None = None,
    record_id: int | str | None = None,
    detail: str = "No recorded evidence in this project.",
    **extra: object,
) -> dict:
    return {
        "kind": kind,
        "label": LABELS[kind],
        "state": state,
        "name": name,
        "digest": digest,
        "record_id": record_id,
        "detail": detail,
        "destination": DESTINATIONS[kind],
        **extra,
    }


def _digest_present(value: str | None) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _run_uses_dataset_choice(run: ExecutionRun, choice: ProjectChoiceEvent) -> bool:
    """Require the run's frozen source revision to match the whole active cohort."""

    receipt = choice.selected_definition
    metadata = run.source_metadata
    if not isinstance(receipt, dict) or not isinstance(metadata, dict):
        return False
    revisions = metadata.get("data_selection_revisions")
    if not isinstance(revisions, list) or len(revisions) != 1:
        return False
    revision = revisions[0]
    selection = revision.get("selection") if isinstance(revision, dict) else None
    if not isinstance(selection, dict):
        return False
    expected = {
        "experiment_id": choice.selected_experiment_id,
        "stage": receipt.get("stage"),
        "selected_file_ids": receipt.get("selected_file_ids"),
        "asset_id": receipt.get("asset_id"),
        "source_manifest_sha256": receipt.get("source_manifest_sha256"),
        "collection_definition_sha256": receipt.get("collection_definition_sha256"),
        "scientific_collection_sha256": receipt.get("scientific_collection_sha256"),
        "target_authority": receipt.get("target_authority"),
        "group_column": receipt.get("group_column"),
        "dataset_view_id": choice.selected_dataset_view_id,
        "dataset_view_sha256": choice.selected_digest if choice.selected_dataset_view_id is not None else None,
    }
    if not all(selection.get(key) == value for key, value in expected.items()):
        return False
    return all(
        _digest_present(selection.get(key)) for key in ("source_manifest_sha256", "scientific_collection_sha256")
    )


@router.get("")
async def current_project_provenance(
    project_id: int,
    summary: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = await require_project(project_id, current_user.id, session, operation="read")
    cache_key = (current_user.id, project_id)
    if summary:
        cached = _summary_cache.get(cache_key)
        if cached is not None and time.monotonic() - cached[0] < _SUMMARY_TTL_SECONDS:
            return cached[1]
    else:
        _summary_cache.pop(cache_key, None)
    records = {kind: _record(kind) for kind in KINDS}
    current_choices: dict[str, ProjectChoiceEvent] = {}
    for kind in ("dataset", "workflow"):
        event = await session.scalar(
            select(ProjectChoiceEvent)
            .where(
                ProjectChoiceEvent.project_id == project_id,
                ProjectChoiceEvent.user_id == current_user.id,
                ProjectChoiceEvent.kind == kind,
            )
            .order_by(ProjectChoiceEvent.id.desc())
            .limit(1)
        )
        if event is not None:
            current_choices[kind] = event

    dataset_choice = current_choices.get("dataset")
    if dataset_choice is not None:
        experiment = await session.scalar(
            select(Experiment).where(
                Experiment.id == dataset_choice.selected_experiment_id, Experiment.project_id == project_id
            )
        )
        if experiment is None:
            records["dataset"] = _record(
                "dataset", state="faulty", record_id=dataset_choice.id, detail="Selected dataset was removed."
            )
        else:
            named_id = dataset_choice.selected_dataset_view_id
            view = (
                await session.scalar(
                    select(DatasetView).where(
                        DatasetView.id == named_id,
                        DatasetView.experiment_id == experiment.id,
                        DatasetView.project_id == project_id,
                    )
                )
                if named_id is not None
                else None
            )
            if named_id is not None and (view is None or view.deleted_at is not None):
                records["dataset"] = _record(
                    "dataset",
                    state="faulty",
                    name=dataset_choice.selected_name,
                    record_id=named_id,
                    detail="The active named definition was deleted or is unavailable.",
                    experiment_id=experiment.id,
                )
            else:
                receipt = dataset_choice.selected_definition
                state, detail = "healthy", "Exact source and sample cohort verified against the selected definition."
                try:
                    if not isinstance(receipt, dict) or receipt_sha256(receipt) != dataset_choice.selected_digest:
                        raise ValueError("Selected definition digest changed")
                    if view is not None and (
                        view.selection_sha256 != dataset_choice.selected_digest
                        or receipt_sha256(view.selection) != view.selection_sha256
                    ):
                        raise ValueError("Saved definition changed")
                    loaded = await load_project_dataset(
                        session,
                        user_id=current_user.id,
                        experiment_id=experiment.id,
                        stage=receipt["stage"],
                        file_ids=receipt["selected_file_ids"],
                        asset_id=receipt["asset_id"],
                    )
                    await asyncio.to_thread(verify_selection_receipt, loaded, receipt)
                except (KeyError, ValueError):
                    state, detail = "faulty", "The selected definition no longer matches its source or sample cohort."
                records["dataset"] = _record(
                    "dataset",
                    state=state,
                    name=dataset_choice.selected_name if view is not None else f"{experiment.name} / Default",
                    digest=dataset_choice.selected_digest,
                    record_id=named_id,
                    detail=detail,
                    experiment_id=experiment.id,
                    dataset_view_id=named_id,
                )
                files = receipt.get("source_files") if isinstance(receipt, dict) else None
                if isinstance(files, list) and files:
                    first = files[0]
                    file_digest = first.get("sha256") if isinstance(first, dict) else None
                    collection_digest = receipt.get("source_manifest_sha256")
                    digest = file_digest if len(files) == 1 else collection_digest
                    records["source"] = _record(
                        "source",
                        state=state if _digest_present(digest) else "faulty",
                        name=(
                            first.get("file_name")
                            if len(files) == 1 and isinstance(first, dict)
                            else f"{len(files)} files"
                        ),
                        digest=digest if _digest_present(digest) else None,
                        record_id=experiment.id,
                        detail=(
                            detail if _digest_present(digest) else "Source digest missing from the saved definition."
                        ),
                        experiment_id=experiment.id,
                        dataset_view_id=named_id,
                    )

    workflow_choice = current_choices.get("workflow")
    if workflow_choice is not None:
        workflow = await session.scalar(
            select(Workflow).where(
                Workflow.id == workflow_choice.selected_workflow_id, Workflow.project_id == project_id
            )
        )
        if workflow is None:
            records["workflow"] = _record(
                "workflow",
                state="faulty",
                name=workflow_choice.selected_name,
                digest=workflow_choice.selected_digest,
                record_id=workflow_choice.selected_workflow_id,
                detail="Selected sheet was removed.",
            )
        else:
            matched = (
                workflow.integrity_hash == workflow_choice.selected_digest
                and workflow.name == workflow_choice.selected_name
            )
            records["workflow"] = _record(
                "workflow",
                state="healthy" if matched and _digest_present(workflow.integrity_hash) else "faulty",
                name=workflow_choice.selected_name,
                digest=workflow_choice.selected_digest,
                record_id=workflow.id,
                detail=(
                    "Current saved sheet identity."
                    if matched and _digest_present(workflow.integrity_hash)
                    else "The selected sheet changed; open it again to record its current version."
                ),
            )

    # Immutable records are always the newest created record within the project,
    # not the last one a scientist opened or the most flattering successful one.
    run = await session.scalar(
        select(ExecutionRun).where(ExecutionRun.project_id == project_id).order_by(ExecutionRun.id.desc()).limit(1)
    )
    if run is not None:
        qualified = (
            isinstance(run.evidence_completeness, dict)
            and run.evidence_completeness.get("qualification") == "qualified"
        )
        run_linked = (
            workflow_choice is not None
            and run.workflow_id == workflow_choice.selected_workflow_id
            and _digest_present(run.integrity_hash)
            and _digest_present(workflow_choice.selected_digest)
            and run.integrity_hash == workflow_choice.selected_digest
        )
        run_state = (
            "faulty"
            if run.status in {"error", "failed", "cancelled"} or not run_linked
            else "healthy" if run.status == "completed" and qualified else "missing"
        )
        records["run"] = _record(
            "run",
            state=run_state,
            name=run.name,
            digest=run.integrity_hash if _digest_present(run.integrity_hash) else None,
            record_id=run.id,
            detail=(
                f"Latest run: {run.status}; retained evidence {'qualified' if qualified else 'unverified'}. "
                + ("Matches the active sheet." if run_linked else "Does not match the active sheet choice.")
            ),
            workflow_id=run.workflow_id,
        )
        environment = run.environment_snapshot
        if (
            isinstance(environment, dict)
            and environment.get("schema_version") == 2
            and isinstance(environment.get("packages"), dict)
        ):
            records["environment"] = _record(
                "environment",
                state="healthy" if run_linked else "faulty",
                name=f"Python {environment.get('python', 'unknown')}",
                record_id=run.id,
                detail="Package versions captured with the latest run; this is not a replay guarantee.",
                packages=environment["packages"],
            )

    model = await session.scalar(
        select(ModelArtifact).where(ModelArtifact.project_id == project_id).order_by(ModelArtifact.id.desc()).limit(1)
    )
    if model is not None:
        artifact_verified = False
        if model.is_active and _digest_present(model.integrity_hash):
            try:
                await asyncio.to_thread(verify_model_artifact_storage_record, model)
                artifact_verified = True
            except (FileNotFoundError, RuntimeError, ModelArtifactIntegrityError, ValueError):
                artifact_verified = False
        training_link = (
            run is not None
            and run.status == "completed"
            and run_linked
            and model.source_run_id == run.id
            and dataset_choice is not None
            and records["dataset"]["state"] == "healthy"
            and model.training_dataset_id == dataset_choice.selected_experiment_id
            and _run_uses_dataset_choice(run, dataset_choice)
        )
        application_link = (
            run is not None
            and run.status == "completed"
            and run.run_kind == "batch_inference"
            and model.artifact_uid in (run.succeeded_artifact_uids or [])
        )
        model_linked = training_link or application_link
        records["model"] = _record(
            "model",
            state="healthy" if artifact_verified and model_linked else "faulty",
            name=model.display_name or model.name,
            digest=model.integrity_hash if _digest_present(model.integrity_hash) else None,
            record_id=model.artifact_uid,
            detail=(
                "Verified model was applied by the latest batch run; its input cohort requires run-specific evidence."
                if artifact_verified and application_link
                else (
                    "Verified artifact links to the latest training run and chosen dataset."
                    if artifact_verified and training_link
                    else (
                        "Latest calibrated model is inactive."
                        if not model.is_active
                        else (
                            "Stored model integrity could not be verified."
                            if not artifact_verified
                            else (
                                "Model integrity verified; no active dataset selection is recorded. "
                                "Select the matching dataset in My Dataset to establish the provenance link."
                                if dataset_choice is None
                                else "Model integrity verified; its training context does not match the latest run "
                                "and active dataset selection. This does not invalidate the saved calibration."
                            )
                        )
                    )
                )
            ),
            source_run_id=model.source_run_id,
        )

    imported = await session.scalar(
        select(CanonicalProjectArtifact)
        .where(CanonicalProjectArtifact.project_id == project_id)
        .order_by(CanonicalProjectArtifact.id.desc())
        .limit(1)
    )
    if imported is not None:
        records["package"] = _record(
            "package",
            state="healthy" if _digest_present(imported.package_sha256) else "faulty",
            name="Imported Campaign Review Package",
            digest=imported.package_sha256,
            record_id=imported.id,
            created_at=imported.created_at,
            detail="Publisher-authenticated package admitted at import; no new data was bundled.",
        )

    # The hosted extension may add only the two records absent from OSS. It
    # cannot relabel any OSS source, workflow, run, environment or model proof.
    hosted = await hosted_project_provenance(session, project_id, current_user.id)
    for kind in ("campaign", "package"):
        item = hosted.get(kind)
        if isinstance(item, dict) and item.get("state") in {"healthy", "missing", "faulty"}:
            if kind == "package" and imported is not None and isinstance(item.get("created_at"), datetime):
                if _utc(imported.created_at) > _utc(item["created_at"]):
                    continue
            records[kind] = {
                **records[kind],
                **item,
                "kind": kind,
                "label": LABELS[kind],
                "destination": DESTINATIONS[kind],
            }

    availability = await project_availability(session, project_id, run=run, model=model, records=records)
    for kind in KINDS:
        records[kind]["availability"] = availability[kind]

    result = {
        "project_id": project.id,
        "project_name": project.name,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "records": [records[kind] for kind in KINDS],
        "choice_event_ids": {kind: event.id for kind, event in current_choices.items()},
    }
    if len(_summary_cache) >= 256:
        _summary_cache.clear()
    _summary_cache[cache_key] = (time.monotonic(), result)
    return result
