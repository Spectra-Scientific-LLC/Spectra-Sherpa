"""Temporary staging diagnostics: closed events, never data or free-form errors."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GuiTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    seq: int = Field(ge=1, le=1000000)
    operation: Literal[
        "experiments",
        "projects",
        "catalogue",
        "workflow",
        "runs",
        "autosave",
        "other",
        "workbook_load",
        "workbook_reset",
        "workflow_reset",
        "workflow_apply",
        "guidance",
        "workflow_loading",
        "workflow_execute_http",
        "workflow_execute_apply",
        "workflow_execute_finalize",
    ]
    state: Literal["start", "ok", "error", "cancelled", "superseded", "reset", "refused"]
    elapsed_ms: int | None = Field(default=None, ge=0, le=3600000)
    status: int | None = Field(default=None, ge=0, le=599)
    project_id: int | None = Field(default=None, gt=0)
    workflow_id: int | None = Field(default=None, gt=0)
    node_count: int | None = Field(default=None, ge=0, le=100000)
    attempt_id: int | None = Field(default=None, ge=1, le=1000000)
    run_id: int | None = Field(default=None, gt=0)
    workbook_context_ready: bool | None = None
    workbook_loading: bool | None = None
    workflow_loading: bool | None = None
    workflow_id_matches: bool | None = None
    workflow_owner_current: bool | None = None
    execution_owner_current: bool | None = None
    loading_clear_authorized: bool | None = None


class GuiTraceBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: UUID
    events: list[GuiTraceEvent] = Field(min_length=1, max_length=30)
