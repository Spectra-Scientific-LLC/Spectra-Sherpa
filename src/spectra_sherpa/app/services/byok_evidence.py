"""Fixed Workbench reads for local BYOK. No model-driven dispatch."""

import asyncio
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from spectra_sherpa.app.schemas.prediction_context import retained_prediction_context
from spectra_sherpa.app.services.inspection_bridge import MAX_RESPONSE_BYTES, InspectionRefused
from spectra_sherpa.app.services.inspection_comparison import ComparisonArguments, authorize_comparison, read_comparison
from spectra_sherpa.app.services.inspection_grants import DEFAULT_DISCLOSURES, InspectionIdentity, _require_live_access
from spectra_sherpa.app.services.inspection_readers import (
    DatasetArguments,
    WorkflowArguments,
    authorize_reader,
    read_project_facts,
)
from spectra_sherpa.app.services.inspection_runs import authorize_run_reader, read_run_facts
from spectra_sherpa.app.services.inspection_science import (
    ScientificArguments,
    authorize_scientific_reader,
    read_scientific_facts,
)
from spectra_sherpa.app.services.tools.builtin.runs import RunArguments


class WorkbenchView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    screen: Literal["dataset", "workflow", "results", "compare"]
    project_id: PositiveInt
    dataset_id: str | None = Field(default=None, min_length=1, max_length=128)
    workflow_id: PositiveInt | None = None
    run_id: PositiveInt | None = None
    run_ids: list[PositiveInt] | None = Field(default=None, max_length=2)

    @model_validator(mode="after")
    def check_selection(self):
        selected = {
            "dataset": self.dataset_id,
            "workflow": self.workflow_id,
            "results": self.run_id,
            "compare": self.run_ids,
        }
        if any(value is not None for key, value in selected.items() if key != self.screen):
            raise ValueError("Selection does not match active view")
        if self.run_ids is not None and len(set(self.run_ids)) != 2:
            raise ValueError("Select two distinct runs")
        return self


@dataclass
class WorkbenchEvidence:
    view: WorkbenchView
    identity: InspectionIdentity
    facts: dict
    prediction: dict[int, dict]

    async def revalidate(self, sessions):
        async with sessions() as session:
            await _require_live_access(session, self.identity.actor_id, self.identity.project_id)
            if "describe_dataset" in self.facts:
                await authorize_reader(
                    session, self.identity, "describe_dataset", DatasetArguments(dataset_id=self.view.dataset_id)
                )
            elif "inspect_workflow" in self.facts:
                await authorize_reader(
                    session, self.identity, "inspect_workflow", WorkflowArguments(workflow_id=self.view.workflow_id)
                )
            elif "get_results" in self.facts:
                await authorize_run_reader(
                    session, self.identity, RunArguments(run_id=self.view.run_id), self.facts["get_run"]
                )
                await authorize_scientific_reader(
                    session, self.identity, ScientificArguments(run_id=self.view.run_id), self.facts["get_results"]
                )
            elif "compare_runs" in self.facts:
                await authorize_comparison(
                    session, self.identity, ComparisonArguments(run_ids=self.view.run_ids), self.facts["compare_runs"]
                )


async def _read_evidence(sessions, actor_id: int, view: WorkbenchView) -> WorkbenchEvidence:
    # This internal identity is scoped by the logged-in actor and existing AI-sharing policy.
    # It is never a bearer credential or an entry point to the MCP bridge.
    identity = InspectionIdentity("local-byok", actor_id, view.project_id, DEFAULT_DISCLOSURES, True, True)
    async with sessions() as session:
        await _require_live_access(session, actor_id, view.project_id)
    evidence = WorkbenchEvidence(view, identity, {}, {})
    if view.dataset_id is not None:
        evidence.facts["describe_dataset"] = await read_project_facts(
            sessions, identity, "describe_dataset", DatasetArguments(dataset_id=view.dataset_id)
        )
    elif view.workflow_id is not None:
        evidence.facts["inspect_workflow"] = await read_project_facts(
            sessions, identity, "inspect_workflow", WorkflowArguments(workflow_id=view.workflow_id)
        )
    elif view.run_id is not None:
        evidence.facts["get_run"] = await read_run_facts(sessions, identity, RunArguments(run_id=view.run_id))
        args = ScientificArguments(run_id=view.run_id)
        metrics = await read_scientific_facts(sessions, identity, args)
        evidence.facts["get_results"] = metrics
        async with sessions() as session:
            run, _ = await authorize_scientific_reader(session, identity, args, metrics)
        if context := retained_prediction_context(run.source_metadata):
            evidence.prediction[run.id] = context
    elif view.run_ids is not None:
        args = ComparisonArguments(run_ids=view.run_ids)
        comparison = await read_comparison(sessions, identity, args)
        evidence.facts["compare_runs"] = comparison
        async with sessions() as session:
            snapshots = await authorize_comparison(session, identity, args, comparison)
        for run, _ in snapshots:
            if context := retained_prediction_context(run.source_metadata):
                evidence.prediction[run.id] = context
    if len(json.dumps(evidence.facts, allow_nan=False).encode()) > MAX_RESPONSE_BYTES:
        raise InspectionRefused("response_limit")
    return evidence


_slots = asyncio.Semaphore(4)


async def read_workbench_evidence(sessions, actor_id: int, view: WorkbenchView) -> WorkbenchEvidence:
    # Shield workers so cancellation or timeout cannot release capacity while
    # retained-artifact reads are still running in a thread.
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=5)
    except TimeoutError as exc:
        raise InspectionRefused("busy") from exc
    task = asyncio.create_task(_read_evidence(sessions, actor_id, view))

    def finished(worker):
        _slots.release()
        if not worker.cancelled():
            worker.exception()

    task.add_done_callback(finished)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=5)
    except TimeoutError as exc:
        raise InspectionRefused("timeout") from exc
