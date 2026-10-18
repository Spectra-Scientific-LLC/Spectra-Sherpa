"""Explicit local evaluation jobs for the shared Runs comparison journey."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import demo_guard, enforce_demo_execution_quota, get_current_user, get_session
from spectra_sherpa.app.contracts.demo_capabilities import MODEL_USE
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.job_manager import job_manager
from spectra_sherpa.app.services.paired_evaluation import (
    PairedEvaluationRequest,
    evaluate_pair,
    load_recipe,
    paired_comparison,
    prepare_protocol,
)
from spectra_sherpa.app.services.run_output_retention import read_output, retain_run_outputs

router = APIRouter(prefix="/runs/paired-evaluations")


async def _authorized_run(session, run_id, user_id, operation="read"):
    run = await session.get(ExecutionRun, run_id)
    if run is None:
        raise HTTPException(404, "Saved run not found")
    await require_scientific_access(session, user_id, run.project_id, operation, resource_owner_id=run.user_id)
    return run


async def _prepare(session, user_id, payload):
    runs = [await _authorized_run(session, r.run_id, user_id, "execute") for r in payload.recipes]
    if len({r.project_id for r in runs}) != 1:
        raise HTTPException(422, "Select runs from one project.")
    try:
        recipes = [
            await asyncio.to_thread(load_recipe, run, selection) for run, selection in zip(runs, payload.recipes)
        ]
        population, _, _, _, splits = prepare_protocol(recipes, payload)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return runs, recipes, population, splits


@router.post("/preview", dependencies=[Depends(demo_guard(MODEL_USE))])
async def preview(
    payload: PairedEvaluationRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Read and qualify the frozen protocol without fitting any model."""
    _, recipes, population, splits = await _prepare(session, current_user.id, payload)
    return {
        "development_count": len(population.development_indices),
        "held_out_count": len(population.held_out_indices),
        "fits": len(recipes) * sum(len(s.folds) for s in splits),
        "split_digests": [s.digest for s in splits],
        "resume_supported": False,
        "notice": (
            "Only retained development samples are used. Every learned transform is refitted inside each fold. "
            "Cancel stops between recipe evaluations; restart creates a new record."
        ),
    }


@router.post("", status_code=202, dependencies=[Depends(demo_guard(MODEL_USE))])
async def start(
    payload: PairedEvaluationRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    runs, recipes, population, _ = await _prepare(session, current_user.id, payload)
    enforce_demo_execution_quota(current_user.id)
    source = next(r for r in runs if r.id == payload.population_run_id)
    run = ExecutionRun(
        user_id=current_user.id,
        project_id=source.project_id,
        workflow_id=source.workflow_id,
        name="Paired robustness" if payload.repetitions > 1 else "Common-protocol evaluation",
        status="running",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        run_kind="other",
        source_type="paired_evaluation",
        source_metadata={"protocol": payload.model_dump(), "source_run_ids": [r.id for r in runs]},
        produced_artifact_uids=[],
        attempted_artifact_uids=[],
        succeeded_artifact_uids=[],
    )
    session.add(run)
    await session.flush()
    job = BackgroundJob(
        user_id=current_user.id, job_type="paired_evaluation", execution_run_id=run.id, status="pending"
    )
    session.add(job)
    await session.commit()
    run_id, job_id, user_id = run.id, job.id, current_user.id

    async def checkpoint(done, total):
        async with async_session() as check:
            state = await check.scalar(select(BackgroundJob.status).where(BackgroundJob.id == job_id))
            if state != "running":
                raise ValueError(
                    "Evaluation stopped. Partial work is not complete evidence; restart creates a new record."
                )
            for selection in payload.recipes:
                await _authorized_run(check, selection.run_id, user_id, "execute")
            await job_manager.update_progress(
                check, job_id, int(100 * done / total), f"{done}/{total} recipe evaluations completed"
            )
            await check.commit()

    async def work():
        record = await evaluate_pair(recipes, payload, checkpoint)
        evidence = await asyncio.to_thread(retain_run_outputs, user_id, {"__evaluation__": {"record": record}}, {})
        item = RunEvidence.model_validate(evidence).outputs.get("__evaluation__", {}).get("record")
        if item is None or item.state != "exact":
            raise ValueError("Evaluation output could not be retained exactly; no completed comparison was recorded.")
        async with async_session() as finish:
            # Cancel and access revocation must not become successful evidence.
            for selection in payload.recipes:
                await _authorized_run(finish, selection.run_id, user_id, "execute")
            await finish.execute(
                update(ExecutionRun)
                .where(
                    ExecutionRun.id == run_id,
                    ExecutionRun.status == "running",
                    ExecutionRun.id.in_(
                        select(BackgroundJob.execution_run_id).where(
                            BackgroundJob.id == job_id, BackgroundJob.status == "running"
                        )
                    ),
                )
                .values(
                    status="completed",
                    evidence_completeness=evidence,
                    results_summary={"paired_evaluation": record["summary"]},
                    diagnostics={"interpretation": record["interpretation"]},
                )
            )
            await finish.commit()

    asyncio.create_task(job_manager.run_job(job_id, work))
    return {"run_id": run_id, "job_id": job_id}


@router.get("/{run_id}")
async def result(
    run_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    repetition: int = Query(default=0, ge=0, le=9),
):
    run = await _authorized_run(session, run_id, current_user.id)
    if run.source_type != "paired_evaluation":
        raise HTTPException(404, "Paired evaluation not found")
    record = None
    comparison = None
    if run.status == "completed":
        item = RunEvidence.model_validate(run.evidence_completeness).outputs.get("__evaluation__", {}).get("record")
        if item is None or item.state != "exact":
            raise HTTPException(409, "Exact evaluation evidence is unavailable.")
        record = await asyncio.to_thread(read_output, run.user_id, item)
        try:
            comparison = await asyncio.to_thread(
                paired_comparison, run, repetition if isinstance(repetition, int) else 0
            )
        except (ValueError, TypeError, KeyError, AttributeError, OSError, IndexError) as exc:
            raise HTTPException(422, str(exc)) from exc
    return {
        "run_id": run.id,
        "status": run.status,
        "error": run.error,
        "record": record,
        "scientific_comparison": comparison,
    }
