"""Local Workbench connection control and credential-only inspection bridge."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from spectra_sherpa.app.api.deps import get_current_user, get_session, require_project
from spectra_sherpa.app.core.mode_policy import is_local, is_loopback
from spectra_sherpa.app.core.security import get_client_host
from spectra_sherpa.app.models.inspection_grant import InspectionCall, InspectionGrant
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.inspection_bridge import InspectionBridge, InspectionRefused
from spectra_sherpa.app.services.inspection_grants import (
    MAX_TTL_SECONDS,
    InspectionAccessDenied,
    issue_inspection_credential,
    revoke_inspection_credential,
)


class BoundedInspectionRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request):
            body = bytearray()
            try:
                async with asyncio.timeout(5):
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > 8192:
                            raise HTTPException(413, "Inspection request exceeds limit")
                        body.extend(chunk)
            except TimeoutError as exc:
                raise HTTPException(408, "Inspection request timed out") from exc

            async def receive():
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            response = await handler(Request(request.scope, receive))
            response.headers["Cache-Control"] = "no-store"
            return response

        return bounded


router = APIRouter(route_class=BoundedInspectionRoute)
bearer = HTTPBearer(auto_error=False)


class CreateInspectionClient(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    client_label: str = Field(min_length=1, max_length=80)
    ttl_seconds: int = Field(default=86400, ge=1, le=MAX_TTL_SECONDS)
    confirm_external_provider: Literal[True]
    project_summaries: bool = False
    retained_results: bool = False


class InspectionClientInfo(BaseModel):
    project_summaries: bool
    retained_results: bool
    client_id: str
    project_id: int
    client_label: str
    expires_at: datetime
    revoked_at: datetime | None


class CreatedInspectionClient(InspectionClientInfo):
    credential: str = Field(repr=False)


class InspectionCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class InspectionCallInfo(BaseModel):
    id: int
    client_id: str
    operation: str
    outcome: str
    response_bytes: int
    created_at: datetime


def _local_only(request: Request) -> None:
    if not is_local() or not is_loopback(get_client_host(request)):
        raise HTTPException(404, "Not found")


def _workbench_control(request: Request) -> None:
    _local_only(request)
    # The bridge credential is not a Workbench control credential. Browser
    # origin checks also prevent credential issuance through cross-site forms.
    if request.headers.get("authorization", "").lower().startswith("bearer ssmcp_"):
        raise HTTPException(403, "Workbench control required")
    from spectra_sherpa.app.main import get_cors_origins

    # Same-origin browser GETs may omit Origin. A non-simple header is
    # mandatory so cross-site forms cannot invoke connection control.
    if request.headers.get("x-spectra-workbench") != "inspection":
        raise HTTPException(403, "Workbench control required")
    origin = request.headers.get("origin")
    same_local_origin = (
        request.url.hostname in {"localhost", "127.0.0.1", "::1"}
        and origin == f"{request.url.scheme}://{request.url.netloc}"
    )
    if origin is not None and origin not in get_cors_origins() and not same_local_origin:
        raise HTTPException(403, "Workbench origin required")


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _info(grant: InspectionGrant) -> InspectionClientInfo:
    return InspectionClientInfo(
        client_id=grant.id,
        project_summaries=grant.project_summaries,
        retained_results=grant.retained_results,
        project_id=grant.project_id,
        client_label=grant.client_label,
        expires_at=_utc(grant.expires_at),
        revoked_at=_utc(grant.revoked_at),
    )


@router.post("/projects/{project_id}/inspection-clients", response_model=CreatedInspectionClient, status_code=201)
async def create_client(
    project_id: int,
    body: CreateInspectionClient,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CreatedInspectionClient:
    _workbench_control(request)
    await require_project(project_id, user.id, session, operation="read")
    try:
        credential = await issue_inspection_credential(
            session,
            user,
            project_id,
            body.client_label,
            ttl_seconds=body.ttl_seconds,
            disclosures=(
                frozenset({"metadata", "metrics", "statistics"}) if body.retained_results else frozenset({"metadata"})
            ),
            project_summaries=body.project_summaries,
            retained_results=body.retained_results,
        )
    except (InspectionAccessDenied, ValueError) as exc:
        raise HTTPException(400, "Inspection connection refused") from exc
    grant = await session.get(InspectionGrant, credential.identity.client_id)
    info = _info(grant)
    await session.commit()
    return CreatedInspectionClient(**info.model_dump(), credential=credential.token)


@router.get("/projects/{project_id}/inspection-clients", response_model=list[InspectionClientInfo])
async def list_clients(
    project_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[InspectionClientInfo]:
    _workbench_control(request)
    await require_project(project_id, user.id, session, operation="read")
    rows = (
        await session.scalars(
            select(InspectionGrant)
            .where(
                InspectionGrant.project_id == project_id,
                InspectionGrant.user_id == user.id,
            )
            .order_by(InspectionGrant.created_at.desc())
            .limit(100)
        )
    ).all()
    return [_info(row) for row in rows]


@router.delete("/projects/{project_id}/inspection-clients/{client_id}", status_code=204)
async def revoke_client(
    project_id: int,
    client_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    _workbench_control(request)
    grant = await session.get(InspectionGrant, client_id)
    if grant is None or grant.project_id != project_id:
        raise HTTPException(404, "Connection not found")
    try:
        await revoke_inspection_credential(session, user, client_id)
    except InspectionAccessDenied as exc:
        raise HTTPException(404, "Connection not found") from exc
    await session.commit()
    return Response(status_code=204)


def inspection_sessions() -> async_sessionmaker[AsyncSession]:
    from spectra_sherpa.app.db.session import async_session

    return async_session


@router.post("/inspection/{project_id}/{client_id}/call")
async def inspect(
    project_id: int,
    client_id: str,
    body: InspectionCallRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    sessions: async_sessionmaker[AsyncSession] = Depends(inspection_sessions),
) -> dict[str, Any]:
    _local_only(request)
    if credentials is None:
        raise HTTPException(401, "Inspection access denied")
    bridge = getattr(request.app.state, "inspection_bridge", None)
    if bridge is None:
        bridge = request.app.state.inspection_bridge = InspectionBridge()
    try:
        async with asyncio.timeout(20):
            return await bridge.call(
                sessions,
                token=credentials.credentials,
                client_id=client_id,
                project_id=project_id,
                operation=body.operation,
                arguments=body.arguments,
            )
    except InspectionAccessDenied as exc:
        raise HTTPException(403, "Inspection access denied") from exc
    except InspectionRefused as exc:
        raise HTTPException(429 if exc.code == "busy" else 422, exc.code) from exc
    except TimeoutError as exc:
        raise HTTPException(408, "Inspection timed out") from exc


@router.get("/projects/{project_id}/inspection-calls", response_model=list[InspectionCallInfo])
async def call_history(
    project_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[InspectionCallInfo]:
    _workbench_control(request)
    await require_project(project_id, user.id, session, operation="read")
    rows = (
        await session.scalars(
            select(InspectionCall)
            .join(InspectionGrant)
            .where(
                InspectionCall.project_id == project_id,
                InspectionGrant.user_id == user.id,
            )
            .order_by(InspectionCall.id.desc())
            .limit(100)
        )
    ).all()
    return [
        InspectionCallInfo(
            id=row.id,
            client_id=row.client_id,
            operation=row.operation,
            outcome=row.outcome,
            response_bytes=row.response_bytes,
            created_at=_utc(row.created_at),
        )
        for row in rows
    ]
