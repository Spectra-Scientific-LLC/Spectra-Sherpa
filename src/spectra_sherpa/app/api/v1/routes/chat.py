"""OSS-only BYO chat streaming endpoint.

Capability-gated behind ``CHAT_ASSISTANT``. This is deliberately
NOT under ``/api/v1/llm/*`` so the OSS/server boundary is visible by URL prefix.
The ``chatAssistant`` capability is enabled whenever the BYO chat endpoint is
configured (see ``routes/config.py`` ``has_llm or byo_chat_configured()``).
"""

from __future__ import annotations

import json
import logging
from contextlib import aclosing

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from spectra_sherpa.app.api.deps import get_current_user
from spectra_sherpa.app.contracts.capabilities import CHAT_ASSISTANT
from spectra_sherpa.app.core.app_paths import get_app_data_paths
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.services import basic_chat
from spectra_sherpa.app.services.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat")

_chat_limiter = RateLimiter(
    max_calls=30,
    period_sec=3600,
    state_path=get_app_data_paths(settings.data_dir).rate_limits_dir / "byo_chat_stream.json",
)


@router.post("/stream")
async def chat_stream(
    request: Request,
    user=Depends(get_current_user),
):
    """Stream a single-turn chat completion via the BYO endpoint.

    Returns 503 when the BYO chat endpoint is not configured — which is
    exactly when the ``chatAssistant`` capability is disabled in ``/config``.
    The frontend checks the capability flag before showing the chat UI, so
    in practice this only fires on direct API calls when the endpoint is missing.
    """
    from spectra_sherpa.app.core.mode_policy import is_local

    if not is_local():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found.",
        )

    if not basic_chat.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "capability_unavailable",
                "capability": CHAT_ASSISTANT,
                "message": "BYO chat endpoint not configured. Check the provider, endpoint URL, and API key.",
            },
        )
    user_key = f"user:{getattr(user, 'id', None) or 'anonymous'}"
    if not _chat_limiter.allow(user_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Chat rate limit reached. Try again later.",
        )

    body = await request.json()
    message = body.get("message", "")
    if not message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing 'message' field.",
        )
    if not isinstance(message, str) or len(message) > basic_chat.MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Chat message is too long.",
        )
    verbose = bool(body.get("verbose", True))
    try:
        max_paragraphs = max(1, min(6, int(body.get("max_paragraphs", 2))))
    except (TypeError, ValueError):
        max_paragraphs = 2
    metadata = body.get("metadata", None)

    async def _generate():
        try:
            async with aclosing(
                basic_chat.stream_chat(
                    message, verbose=verbose, max_paragraphs=max_paragraphs, metadata=metadata, exchange_owner=user.id
                )
            ) as stream:
                async for chunk in stream:
                    yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except ValueError as exc:
            # ``ValueError`` from ``basic_chat`` carries operator-facing config
            # errors. Keep exception content out of both logs and the response:
            # a provider exception may contain an authenticated URL.
            logger.warning("BYO chat configuration error (%s)", type(exc).__name__)
            _public_detail = "Chat endpoint is not configured or unreachable."
            yield f"data: {json.dumps({'type': 'error', 'detail': _public_detail})}\n\n"
        except Exception as exc:
            logger.warning("BYO chat stream failed (%s)", type(exc).__name__)
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Chat request failed'})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


def _local_history_access(request: Request) -> None:
    from spectra_sherpa.app.core.mode_policy import is_local, is_loopback
    from spectra_sherpa.app.core.security import get_client_host

    if not is_local() or not is_loopback(get_client_host(request)):
        raise HTTPException(status_code=404, detail="Not found.")


@router.get("/exchanges")
async def exchanges(request: Request, user=Depends(get_current_user)):
    """Return only this local user's bounded, redacted process history."""
    _local_history_access(request)
    from spectra_sherpa.app.services.chat_exchange import history

    return {"exchanges": history(user.id), "retention": "Last 20 exchanges; cleared when the backend exits."}


@router.delete("/exchanges", status_code=204)
async def clear_exchanges(request: Request, user=Depends(get_current_user)):
    _local_history_access(request)
    from spectra_sherpa.app.services.chat_exchange import clear

    clear(user.id)
