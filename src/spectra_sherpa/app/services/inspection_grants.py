"""Trusted Workbench credential lifecycle; never an agent-callable operation.

Callers supply an authenticated Workbench actor for issuance and revocation.
Possession of a bearer credential authenticates its registered client, not an
arbitrary handshake label. Admission rechecks account and project access.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.contracts.actors import CurrentActor
from spectra_sherpa.app.contracts.project_access import project_access_allowed
from spectra_sherpa.app.models.inspection_grant import InspectionGrant
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User

DEFAULT_DISCLOSURES = frozenset({"metadata", "statistics", "metrics"})
MAX_TTL_SECONDS = 30 * 24 * 60 * 60
_TOKEN_PREFIX = "ssmcp_"


class InspectionAccessDenied(ValueError):
    """Uniform refusal that does not disclose another client's grant or project."""


@dataclass(frozen=True)
class InspectionIdentity:
    client_id: str
    actor_id: int
    project_id: int
    disclosures: frozenset[str]
    project_summaries: bool = False


@dataclass(frozen=True)
class IssuedInspectionCredential:
    identity: InspectionIdentity
    expires_at: datetime
    token: str = field(repr=False)


def _utc(value: datetime) -> datetime:
    # SQLite returns timezone-naive values for DateTime(timezone=True).
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def _require_live_access(session: AsyncSession, actor_id: int, project_id: int) -> None:
    user = await session.get(User, actor_id, populate_existing=True)
    project = await session.get(Project, project_id, populate_existing=True)
    if (
        user is None
        or not user.is_active
        or project is None
        or not await project_access_allowed(session, actor_id, project, "read")
    ):
        raise InspectionAccessDenied("Inspection access denied")


async def issue_inspection_credential(
    session: AsyncSession,
    actor: CurrentActor,
    project_id: int,
    client_label: str,
    *,
    ttl_seconds: int = 24 * 60 * 60,
    disclosures: frozenset[str] = DEFAULT_DISCLOSURES,
    project_summaries: bool = False,
) -> IssuedInspectionCredential:
    """Issue once to a trusted Workbench caller; caller owns the transaction.

    Raw values and identifiers cannot be granted by this initial interface.
    The returned secret is shown once; only its SHA-256 digest is persisted.
    """
    if type(project_summaries) is not bool:
        raise ValueError("Invalid project summary consent")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError("Invalid inspection credential lifetime")
    if not isinstance(client_label, str) or not 1 <= len(client_label.strip()) <= 80:
        raise ValueError("Client label must contain 1 to 80 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in client_label):
        raise ValueError("Client label contains control characters")
    if not disclosures <= DEFAULT_DISCLOSURES:
        raise ValueError("Unsupported inspection disclosure")
    if not actor.is_active:
        raise InspectionAccessDenied("Inspection access denied")
    await _require_live_access(session, actor.id, project_id)
    now = datetime.now(timezone.utc)
    token = _TOKEN_PREFIX + secrets.token_urlsafe(32)
    grant = InspectionGrant(
        id=str(uuid.uuid4()),
        user_id=actor.id,
        project_id=project_id,
        client_label=client_label.strip(),
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        disclosures=sorted(disclosures),
        project_summaries=project_summaries,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    session.add(grant)
    await session.flush()
    return IssuedInspectionCredential(
        InspectionIdentity(grant.id, actor.id, project_id, frozenset(disclosures), project_summaries),
        grant.expires_at,
        token,
    )


async def authenticate_inspection_client(
    session: AsyncSession, token: str, *, client_id: str, project_id: int
) -> InspectionIdentity:
    """Resolve the registered client; never infer authority from a client name."""
    if not isinstance(token, str) or not token.startswith(_TOKEN_PREFIX) or len(token) != len(_TOKEN_PREFIX) + 43:
        raise InspectionAccessDenied("Inspection access denied")
    grant = await session.scalar(
        select(InspectionGrant)
        .where(InspectionGrant.token_digest == hashlib.sha256(token.encode()).hexdigest())
        .execution_options(populate_existing=True)
    )
    if (
        grant is None
        or grant.id != client_id
        or grant.project_id != project_id
        or grant.revoked_at is not None
        or _utc(grant.expires_at) <= datetime.now(timezone.utc)
        or not frozenset(grant.disclosures) <= DEFAULT_DISCLOSURES
    ):
        raise InspectionAccessDenied("Inspection access denied")
    await _require_live_access(session, grant.user_id, grant.project_id)
    return InspectionIdentity(
        grant.id, grant.user_id, grant.project_id, frozenset(grant.disclosures), grant.project_summaries
    )


async def revoke_inspection_credential(session: AsyncSession, actor: CurrentActor, client_id: str) -> None:
    """Revoke an actor's own credential, even after project access was removed."""
    grant = await session.get(InspectionGrant, client_id, populate_existing=True)
    if grant is None or grant.user_id != actor.id or not actor.is_active:
        raise InspectionAccessDenied("Inspection access denied")
    if grant.revoked_at is None:
        grant.revoked_at = datetime.now(timezone.utc)
        await session.flush()
