"""Canonical retained-run navigation projection shared by Workbench and readers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.execution_runs import RunListItem


def workflow_name_query():
    # Never expose a workflow name across ownership or project boundaries.
    return (
        select(Workflow.name)
        .where(
            Workflow.id == ExecutionRun.workflow_id,
            Workflow.user_id == ExecutionRun.user_id,
            Workflow.project_id.is_not_distinct_from(ExecutionRun.project_id),
        )
        .scalar_subquery()
    )


def run_navigation(run: Any, workflow_name: str | None) -> RunListItem:
    item = RunListItem.model_validate(run)
    item.workflow_name = workflow_name
    item.display_name = run.name
    return item


def navigation_columns():
    return [
        getattr(ExecutionRun, name)
        for name in RunListItem.model_fields
        if name not in {"display_name", "workflow_name"}
    ] + [ExecutionRun.source_type]
