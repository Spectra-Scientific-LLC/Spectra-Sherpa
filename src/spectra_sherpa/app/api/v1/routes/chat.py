"""OSS-only BYO chat streaming endpoint.

Capability-gated behind ``CHAT_ASSISTANT``. This is deliberately
NOT under ``/api/v1/llm/*`` so the OSS/server boundary is visible by URL prefix.
The ``chatAssistant`` capability is enabled whenever the BYO chat endpoint is
configured (see ``routes/config.py`` ``has_llm or byo_chat_configured()``).
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from spectra_sherpa.app.api.deps import get_current_user
from spectra_sherpa.app.contracts.capabilities import CHAT_ASSISTANT
from spectra_sherpa.app.services import basic_chat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat")


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
                "message": ("BYO chat endpoint not configured. " "Set CHAT_ENDPOINT_URL and CHAT_ENDPOINT_KEY."),
            },
        )

    body = await request.json()
    message = body.get("message", "")
    if not message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing 'message' field.",
        )
    verbose = bool(body.get("verbose", True))
    max_paragraphs = int(body.get("max_paragraphs", 2))
    metadata = body.get("metadata", None)

    async def _generate():
        try:
            async for chunk in basic_chat.stream_chat(
                message, verbose=verbose, max_paragraphs=max_paragraphs, metadata=metadata
            ):
                yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except ValueError as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
        except Exception as exc:
            logger.exception("BYO chat stream failed: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Chat request failed'})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")
