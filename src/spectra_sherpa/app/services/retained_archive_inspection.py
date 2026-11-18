"""Read uploaded archived graphs as inert evidence, without importing a project."""

from __future__ import annotations

import asyncio
import io
import json
import threading
import zipfile
from contextlib import contextmanager
from functools import partial

import anyio
from pydantic import Field

from spectra_sherpa.app.services.sherpa_object import PROJECT_PAYLOAD, inspect_archive_bytes
from spectra_sherpa.core.pack_manifest import Frozen
from spectra_sherpa.core.retained_graph import RetainedGraph, RetainedGraphError, inspect_retained_graph


class RetainedArchiveWorkflow(Frozen):
    project_name: str = Field(max_length=1024)
    workflow_index: int = Field(ge=0)
    workflow_count: int = Field(ge=1, le=1024)
    graph: RetainedGraph


def inspect_archive_workflow(
    payload: bytes, *, workflow_index: int = 0, max_uncompressed_bytes: int
) -> RetainedArchiveWorkflow:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RetainedGraphError("Archived project repeats a JSON field")
            result[key] = value
        return result

    try:
        report = inspect_archive_bytes(
            payload,
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_project_bytes=8 * 1024 * 1024,
            max_manifest_bytes=8 * 1024 * 1024,
        )
        if not report.valid_zip or not report.has_project or report.errors:
            raise RetainedGraphError("Archive has no inspectable project payload")

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            info = archive.getinfo(PROJECT_PAYLOAD)
            if info.file_size > 8 * 1024 * 1024:
                raise RetainedGraphError("Archived project exceeds the inspection metadata limit")
            with archive.open(info) as stream:
                encoded = stream.read(8 * 1024 * 1024 + 1)
            if len(encoded) > 8 * 1024 * 1024:
                raise RetainedGraphError("Archived project exceeds the inspection metadata limit")
            project = json.loads(encoded, object_pairs_hook=unique_object)
        pending = [(project, 0)]
        graphs = []
        projects = 0
        while pending:
            current, depth = pending.pop()
            projects += 1
            if depth > 16 or projects > 1024 or not isinstance(current, dict):
                raise RetainedGraphError("Archived project hierarchy exceeds the inspection limit")
            workflows, children = current.get("workflows", []), current.get("children", [])
            if not isinstance(workflows, list) or not isinstance(children, list):
                raise RetainedGraphError("Archived project hierarchy is malformed")
            if len(graphs) + len(workflows) > 1024 or len(children) > 1024:
                raise RetainedGraphError("Archive has too many retained workflows")
            graphs.extend((current.get("name") or "Archived project", graph) for graph in workflows)
            pending.extend((child, depth + 1) for child in reversed(children))
        if type(workflow_index) is not int or not 0 <= workflow_index < len(graphs):
            raise RetainedGraphError("Archived workflow index is unavailable")
        name, graph = graphs[workflow_index]
        inspection = inspect_retained_graph(
            json.dumps(graph, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        )
        return RetainedArchiveWorkflow(
            project_name=name, workflow_index=workflow_index, workflow_count=len(graphs), graph=inspection
        )
    except RetainedGraphError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, zipfile.BadZipFile, RuntimeError) as exc:
        raise RetainedGraphError("Archived workflow is malformed") from exc


class ArchiveInspectionBusy(RuntimeError):
    pass


_inspection_slots = threading.BoundedSemaphore(2)


@contextmanager
def archive_inspection_slot():
    """Reserve process-wide parsing capacity before copying an upload to memory."""
    if not _inspection_slots.acquire(blocking=False):
        raise ArchiveInspectionBusy("Archive inspection capacity is occupied")
    try:
        yield
    finally:
        _inspection_slots.release()


async def inspect_archive_workflow_owned(payload: bytes, *, workflow_index: int, max_uncompressed_bytes: int):
    return await run_archive_inspection_owned(
        inspect_archive_workflow, payload, workflow_index=workflow_index, max_uncompressed_bytes=max_uncompressed_bytes
    )


async def run_archive_inspection_owned(function, /, *args, **kwargs):
    """Drain trusted parsing on cancellation before the caller releases its slot."""
    return await run_archive_operation_owned(asyncio.to_thread(partial(function, *args, **kwargs)))


async def run_archive_operation_owned(operation):
    """Drain composite preparation, including its nested reads, before custody exits."""
    task = asyncio.create_task(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
        if task.done() and not task.cancelled():
            task.exception()
        raise
