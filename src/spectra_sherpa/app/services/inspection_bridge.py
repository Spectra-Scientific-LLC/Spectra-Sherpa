"""Bounded local inspection admission, with no arbitrary registry dispatch."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from spectra_sherpa.app.models.inspection_grant import InspectionCall
from spectra_sherpa.app.services.inspection_grants import (
    InspectionAccessDenied,
    InspectionIdentity,
    authenticate_inspection_client,
)

MAX_RESPONSE_BYTES = 64 * 1024
MAX_CATALOG_NODES = 4096
OPERATIONS = frozenset({"list_node_types"})


class NodeListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    category: str | None = Field(default=None, max_length=64)
    offset: int = Field(default=0, ge=0, le=MAX_CATALOG_NODES)
    limit: int = Field(default=25, ge=1, le=100)


class InspectionRefused(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _node_page(arguments: NodeListArguments) -> dict[str, Any]:
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.services.tools.builtin.spectral import list_node_types

    if len(node_registry.list_catalog_nodes()) > MAX_CATALOG_NODES:
        raise InspectionRefused("catalog_limit")
    rows = list_node_types(category=arguments.category)
    end = arguments.offset + arguments.limit
    return {"items": rows[arguments.offset : end], "next_offset": end if end < len(rows) else None}


class InspectionBridge:
    """Per-process capacity; construct once per Workbench application instance."""

    def __init__(self, *, concurrency: int = 4, timeout_seconds: float = 5):
        if concurrency < 1 or timeout_seconds <= 0:
            raise ValueError("Invalid inspection limits")
        self._slots = asyncio.Semaphore(concurrency)
        self._timeout = timeout_seconds

    async def call(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        token: str,
        client_id: str,
        project_id: int,
        operation: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        async with sessions() as session:
            identity = await authenticate_inspection_client(session, token, client_id=client_id, project_id=project_id)
        logged_operation = operation if operation in OPERATIONS else "unsupported"
        try:
            if operation not in OPERATIONS:
                raise InspectionRefused("unsupported_operation")
            if "metadata" not in identity.disclosures:
                raise InspectionRefused("disclosure_denied")
            try:
                parsed = NodeListArguments.model_validate(arguments)
            except ValidationError as exc:
                raise InspectionRefused("invalid_arguments") from exc
            try:
                await asyncio.wait_for(self._slots.acquire(), timeout=self._timeout)
            except TimeoutError as exc:
                raise InspectionRefused("busy") from exc
            # Cancellation cannot kill a Python worker thread. Keep its capacity
            # reserved until it actually exits, even after caller timeout/cancel.
            task = asyncio.create_task(asyncio.to_thread(_node_page, parsed))

            def finished(worker: asyncio.Task) -> None:
                self._slots.release()
                if not worker.cancelled():
                    worker.exception()

            task.add_done_callback(finished)
            try:
                result = await asyncio.wait_for(asyncio.shield(task), timeout=self._timeout)
            except TimeoutError as exc:
                raise InspectionRefused("timeout") from exc
            except InspectionRefused:
                raise
            except Exception as exc:
                raise InspectionRefused("inspection_failed") from exc
            try:
                encoded = json.dumps(result, allow_nan=False, ensure_ascii=False).encode()
            except (TypeError, ValueError, UnicodeError) as exc:
                raise InspectionRefused("invalid_response") from exc
            if len(encoded) > MAX_RESPONSE_BYTES:
                raise InspectionRefused("response_limit")
            # Fresh transaction: a concurrent revoke or lost project access
            # during inspection must prevent disclosure of the computed page.
            async with sessions() as session:
                current = await authenticate_inspection_client(
                    session, token, client_id=client_id, project_id=project_id
                )
                if "metadata" not in current.disclosures:
                    raise InspectionRefused("disclosure_denied")
                self._record(session, current, logged_operation, "success", len(encoded))
                await session.commit()
            return result
        except (InspectionRefused, InspectionAccessDenied) as exc:
            code = exc.code if isinstance(exc, InspectionRefused) else "access_denied"
            async with sessions() as session:
                self._record(session, identity, logged_operation, code)
                await session.commit()
            raise

    @staticmethod
    def _record(
        session: AsyncSession, identity: InspectionIdentity, operation: str, outcome: str, response_bytes: int = 0
    ) -> None:
        session.add(
            InspectionCall(
                client_id=identity.client_id,
                project_id=identity.project_id,
                operation=operation,
                outcome=outcome,
                response_bytes=response_bytes,
                created_at=datetime.now(timezone.utc),
            )
        )
