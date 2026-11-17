"""Bounded projections of the existing retained-run navigation authority."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, String, cast, func, select

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.schemas.execution_runs import RunListItem
from spectra_sherpa.app.services.run_navigation import navigation_columns, run_navigation, workflow_name_query
from spectra_sherpa.app.services.tools.registry import ToolRegistry
from spectra_sherpa.app.services.tools.schemas import ToolCategory, ToolDefinition

MAX_NAVIGATION_FIELD_CHARS = 2048


class RunListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    offset: int = Field(default=0, ge=0, le=4096)
    limit: int = Field(default=10, ge=1, le=25)


class RunArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: int = Field(gt=0)


class RunNavigationPage(BaseModel):
    """Live navigation page; no claim of an immutable result snapshot."""

    runs: list[RunListItem]
    next_offset: int | None


async def _read_navigation(session, user, project_id, *, run_id=None, offset=0, limit=1):
    if session is None or user is None or type(project_id) is not int or project_id < 1:
        raise ValueError("Run inspection requires trusted owner/project context")
    # Select no scientific blobs. Bound text/JSON at the database boundary,
    # before decoding or constructing ORM models, including malformed old rows.
    columns = {column.key: column for column in navigation_columns()}
    projections = [
        (
            func.substr(cast(column, String), 1, MAX_NAVIGATION_FIELD_CHARS + 1).label(name)
            if isinstance(column.type, (JSON, String))
            else column
        )
        for name, column in columns.items()
    ]
    query = select(
        *projections, func.substr(workflow_name_query(), 1, MAX_NAVIGATION_FIELD_CHARS + 1).label("workflow_name")
    ).where(
        ExecutionRun.user_id == user.id,
        ExecutionRun.project_id == project_id,
    )
    if run_id is not None:
        query = query.where(ExecutionRun.id == run_id)
    query = query.order_by(ExecutionRun.executed_at.desc(), ExecutionRun.id.desc()).offset(offset).limit(limit)
    rows = (await session.execute(query)).mappings().all()
    result = []
    for row in rows:
        values = dict(row)
        for name, value in values.items():
            if isinstance(value, str) and len(value) > MAX_NAVIGATION_FIELD_CHARS:
                raise ValueError("Run navigation field exceeds inspection limit")
            if name in columns and isinstance(columns[name].type, JSON) and value is not None:
                values[name] = json.loads(value)
        workflow_name = values.pop("workflow_name")
        result.append(run_navigation(SimpleNamespace(**values), workflow_name))
    return result


async def list_runs(
    offset: int = 0, limit: int = 10, *, session: Any = None, user: Any = None, project_id: int | None = None
):
    args = RunListArguments(offset=offset, limit=limit)
    rows = await _read_navigation(session, user, project_id, offset=args.offset, limit=args.limit + 1)
    return RunNavigationPage(
        runs=rows[: args.limit],
        next_offset=args.offset + args.limit if len(rows) > args.limit else None,
    ).model_dump(mode="json")


async def get_run(run_id: int, *, session: Any = None, user: Any = None, project_id: int | None = None):
    args = RunArguments(run_id=run_id)
    rows = await _read_navigation(session, user, project_id, run_id=args.run_id)
    if not rows:
        raise ValueError("Run unavailable")
    return rows[0].model_dump(mode="json")


def inspection_run_catalog() -> ToolRegistry:
    """Confine project-context-only interfaces to the MCP discovery instance."""
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="list_runs",
            description="List retained run navigation facts in the granted project, newest first; no result values.",
            category=ToolCategory.workflow,
            requires_user=True,
            requires_session=True,
            version="1.0",
            mutation="read",
            distribution="oss",
            disclosure=["metadata"],
            mcp_name="list_runs",
            parameters=RunListArguments.model_json_schema(),
            output_schema=RunNavigationPage.model_json_schema(),
        ),
        list_runs,
    )
    registry.register(
        ToolDefinition(
            name="get_run",
            description=(
                "Read one retained run's navigation facts; "
                "status is not scientific validity or evidence completeness."
            ),
            category=ToolCategory.workflow,
            requires_user=True,
            requires_session=True,
            version="1.0",
            mutation="read",
            distribution="oss",
            disclosure=["metadata"],
            mcp_name="get_run",
            parameters=RunArguments.model_json_schema(),
            output_schema=RunListItem.model_json_schema(),
        ),
        get_run,
    )
    return registry
