from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.llm import (
    LLMChatRequest,
    LLMChatResponse,
    LLMConversation,
    LLMDataStoryRequest,
    LLMMessage,
    LLMTextResponse,
)
from spectra_sherpa.app.services.llm import LLMService, conversation_store
from spectra_sherpa.app.services.rate_limiter import RateLimiter

router = APIRouter(prefix="/llm")

# Per-user rate limiting for LLM requests
# Configurable via MAX_LLM_REQUESTS_PER_HOUR environment variable (default: 100)
_llm_rate_limiter = RateLimiter(
    max_calls=settings.max_llm_requests_per_hour,
    period_sec=3600,
    state_path=settings.data_dir / "llm_rate_limits.json",
)


def _check_llm_rate_limit(user: User) -> None:
    """Check and enforce per-user LLM rate limiting."""
    user_key = f"user_{user.id}" if user.id else "anonymous"
    if not _llm_rate_limiter.allow(user_key):
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


@router.get("/conversation/{conversation_id}", response_model=LLMConversation)
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
) -> LLMConversation:
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
    current_user: User = Depends(get_current_user),
):
    # Pass user_id to enforce ownership check
    user_id = current_user.id if current_user.id else 0
    removed = conversation_store.delete(conversation_id, user_id=user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.post("/data-story", response_model=LLMTextResponse)
async def generate_data_story(
    payload: LLMDataStoryRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> LLMTextResponse:
    """Generate a narrative 'data story' for a reference dataset."""
    _check_llm_rate_limit(current_user)
    service = LLMService(session, user=current_user)
    try:
        response = await service.write_data_story(dataset_id=payload.dataset_id, tier=payload.tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LLMTextResponse(response=response)
