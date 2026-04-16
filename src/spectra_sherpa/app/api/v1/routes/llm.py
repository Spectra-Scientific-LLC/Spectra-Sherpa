from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.core.app_paths import get_app_data_paths
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.llm import (
    LLMChatRequest,
    LLMChatResponse,
    LLMConversation,
    LLMMessage,
)
from spectra_sherpa.app.services.llm import LLMService, conversation_store
from spectra_sherpa.app.services.llm_rate_limits import allow_llm_request
from spectra_sherpa.app.services.rate_limiter import RateLimiter

router = APIRouter(prefix="/llm")

# Per-user rate limiting for LLM requests
# Configurable via MAX_LLM_REQUESTS_PER_HOUR environment variable (default: 100)
_llm_rate_limiter = RateLimiter(
    max_calls=settings.max_llm_requests_per_hour,
    period_sec=3600,
    state_path=get_app_data_paths(settings.data_dir).llm_rate_limits_state,
)


def _should_proxy_server_conversations() -> bool:
    return app_config.mode in ("hybrid", "enterprise") or app_config.site_profile == "demo"


def _server_proxy_target() -> tuple[str, dict[str, str]]:
    from spectra_sherpa.app.services.spectrasherpa import spectrasherpa_config

    if not spectrasherpa_config.api_key:
        raise HTTPException(status_code=503, detail="Sherpa subscription service is not configured.")

    base_url = spectrasherpa_config.api_base_url.rstrip("/")
    if not base_url.endswith("/api/v1"):
        base_url = f"{base_url}/api/v1"
    return base_url, {"X-Deployment-Key": spectrasherpa_config.api_key}


async def _proxy_server_request(
    method: str,
    path: str,
    *,
    params: dict[str, int | str] | None = None,
) -> httpx.Response:
    base_url, headers = _server_proxy_target()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(method, f"{base_url}{path}", params=params, headers=headers)
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=502, detail="Cannot connect to Sherpa subscription service.") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Sherpa subscription service timed out.") from exc

    if response.status_code >= 400:
        detail = response.text
        try:
            detail = response.json().get("detail", detail)
        except Exception:
            pass
        if response.status_code in (401, 403):
            raise HTTPException(
                status_code=503,
                detail="Sherpa subscription service authorization failed.",
            )
        raise HTTPException(status_code=response.status_code, detail=detail)

    return response


def _check_llm_rate_limit(user: User) -> None:
    """Check and enforce per-user LLM rate limiting."""
    if not allow_llm_request(_llm_rate_limiter, user):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="LLM rate limit exceeded. Try again later.",
            headers={"Retry-After": "3600"},
        )


@router.get("/debug/config")
async def debug_config(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Debug endpoint to show current LLM configuration."""
    service = LLMService(session, user=current_user)
    config = await service._get_llm_config()
    return {
        "provider": config["provider"],
        "base_url": config["base_url"],
        "model": config["model"],
        "verbose": config["verbose"],
    }


@router.post("/chat", response_model=LLMChatResponse)
async def chat(
    payload: LLMChatRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> LLMChatResponse:
    _check_llm_rate_limit(current_user)
    service = LLMService(session, user=current_user)

    try:
        conversation_id, response = await service.chat(
            message=payload.message,
            conversation_id=payload.conversation_id,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LLMChatResponse(conversation_id=conversation_id, response=response)


@router.get("/conversations")
async def list_conversations(
    project_id: int,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    if not _should_proxy_server_conversations():
        return []

    # If the deployment is configured to proxy server-backed conversations
    # but the subscription API key is missing, degrade gracefully with an
    # empty list rather than 503. A list-on-load endpoint breaking the
    # whole page just because the Sherpa chat feature isn't set up is a
    # much worse UX than silently showing no prior conversations.
    try:
        response = await _proxy_server_request(
            "GET",
            "/conversations",
            params={"local_user_id": current_user.id, "project_id": project_id},
        )
    except HTTPException as exc:
        if exc.status_code in (502, 503, 504):
            logger.warning(
                "list_conversations: proxy unavailable (%s: %s) — returning empty list",
                exc.status_code,
                exc.detail,
            )
            return []
        raise
    return response.json()


@router.get("/conversation/{conversation_id}", response_model=LLMConversation)
async def get_conversation(
    conversation_id: str,
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
) -> LLMConversation:
    if _should_proxy_server_conversations():
        if project_id is None:
            raise HTTPException(status_code=400, detail="project_id is required for server-backed conversations")
        response = await _proxy_server_request(
            "GET",
            f"/conversations/{conversation_id}",
            params={"local_user_id": current_user.id, "project_id": project_id},
        )
        data = response.json()
        return LLMConversation(
            conversation_id=conversation_id,
            messages=[
                LLMMessage(role=message["role"], content=message["content"]) for message in data.get("messages", [])
            ],
        )

    # Pass user_id to enforce ownership check
    user_id = current_user.id if current_user.id else 0
    messages = conversation_store.get(conversation_id, user_id=user_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return LLMConversation(
        conversation_id=conversation_id,
        messages=[LLMMessage(**message) for message in messages],
    )


@router.delete("/conversation/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
):
    if _should_proxy_server_conversations():
        if project_id is None:
            raise HTTPException(status_code=400, detail="project_id is required for server-backed conversations")
        await _proxy_server_request(
            "DELETE",
            f"/conversations/{conversation_id}",
            params={"local_user_id": current_user.id, "project_id": project_id},
        )
        return

    # Pass user_id to enforce ownership check
    user_id = current_user.id if current_user.id else 0
    removed = conversation_store.delete(conversation_id, user_id=user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Conversation not found")
