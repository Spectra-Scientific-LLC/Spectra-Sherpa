"""FastAPI middleware — populate AuditContext for every HTTP request.

Read order (first available wins):

  1. Authenticated user id from ``request.state.user`` (set upstream by
     the auth middleware).
  2. API-key actor id from ``request.state.api_key`` when an API-key
     authenticated the request.
  3. Fallback: ``actor_id=None``, ``actor_kind="user"`` (anonymous, or
     unauthenticated public route).

The tenant id is resolved from app config (single-tenant-per-droplet)
or a server-side resolver if registered. The request id is read from
the ``X-Request-ID`` header (or minted) — same source as
``RequestIDMiddleware`` so audit and logs correlate trivially.

Skipped when ``app_config.audit_enabled == False`` so OSS-Local installs
pay zero overhead per request.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.core.request_id import REQUEST_ID_HEADER, get_request_id, mint_request_id
from spectra_sherpa.app.services.audit.context import AuditContext, reset_audit_context, set_audit_context

logger = logging.getLogger(__name__)

_DEFAULT_TENANT_ID = "default"


class AuditMiddleware(BaseHTTPMiddleware):
    """Bind an ``AuditContext`` for the duration of the request.

    Must be installed **after** the request-id middleware so the
    request id is already populated. Must be installed **after** the
    auth middleware so user / api-key state is available.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not app_config.audit_enabled:
            return await call_next(request)

        tenant_id = _resolve_tenant_id(request)
        actor_id, actor_kind = _resolve_actor(request)
        request_id = get_request_id() or request.headers.get(REQUEST_ID_HEADER, "").strip() or mint_request_id()

        ctx = AuditContext(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_kind=actor_kind,
            request_id=request_id,
            extra=_collect_request_extra(request),
        )

        token = set_audit_context(ctx)
        try:
            response: Response = await call_next(request)
        finally:
            reset_audit_context(token)
        return response


def _resolve_tenant_id(request: Request) -> str:
    """Return the tenant id for this request.

    Resolution order:

      1. ``request.state.tenant_id`` if upstream middleware populated it.
      2. ``app_config.site_profile`` (or a future deployment-key id).
      3. Constant ``"default"`` for OSS Local.

    A server-side resolver registered via a future Protocol seam can
    inject a stricter strategy without changing this module.
    """
    state_tenant = getattr(request.state, "tenant_id", None)
    if state_tenant:
        return str(state_tenant)
    if app_config.site_profile:
        return app_config.site_profile
    return _DEFAULT_TENANT_ID


def _resolve_actor(request: Request) -> tuple[int | None, str]:
    """Return ``(actor_id, actor_kind)`` for this request.

    Inspects ``request.state``; the upstream auth layer puts a ``user``
    or ``api_key`` object there when present. Anonymous / unauthenticated
    requests get ``(None, "user")`` — service code that emits in those
    paths is responsible for deciding whether the action is auditable.
    """
    api_key = getattr(request.state, "api_key", None)
    if api_key is not None:
        # ``user_id`` is the FK on APIKey; falls back to None for
        # service tokens not bound to a user.
        return getattr(api_key, "user_id", None), "api_key"

    user = getattr(request.state, "user", None)
    if user is not None:
        return getattr(user, "id", None), "user"

    return None, "user"


def _collect_request_extra(request: Request) -> dict | None:
    """Capture small, audit-useful request metadata.

    Intentionally bounded — no headers wholesale, no body. Just the few
    fields that show up on every "who did this and from where" audit
    review.
    """
    client_host = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return {
        "method": request.method,
        "path": request.url.path,
        "client_host": client_host,
        "user_agent": user_agent[:256] if user_agent else None,
    }
