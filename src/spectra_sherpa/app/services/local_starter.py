"""Local Starter adapter over the existing BYO chat transport, not a second LLM client."""

from __future__ import annotations

from contextlib import aclosing
from typing import Any

from spectra_sherpa.app.contracts.starter_planning import GoalClassification
from spectra_sherpa.app.core.mode_policy import is_local
from spectra_sherpa.app.services import basic_chat
from spectra_sherpa.app.services.starter_goal_prompt import (
    MAX_GOAL_TOKENS,
    STARTER_GOAL_SYSTEM_PROMPT,
    build_starter_goal_prompt,
    parse_starter_goal_answer,
)


def local_starter_available() -> bool:
    return is_local() and basic_chat.is_configured()


async def classify_local_goal(
    *, goal: str, intents: list[dict[str, Any]], datasets: list[dict[str, Any]], user_id: int
) -> GoalClassification | None:
    if not local_starter_available():
        return None
    # Share the same per-user limit as local chat/Data Story. Do not fall back
    # from a managed provider to a local key or bypass hosted admission.
    if not basic_chat.chat_limiter.allow(f"user:{user_id}"):
        return None
    if any(dataset.get("kind") != "reference" for dataset in datasets):
        from spectra_sherpa.app.db.session import async_session
        from spectra_sherpa.app.services.starter_disclosure import private_starter_context_allowed

        async with async_session() as session:
            if not await private_starter_context_allowed(session, user_id):
                datasets = [dataset for dataset in datasets if dataset.get("kind") == "reference"]
    message = STARTER_GOAL_SYSTEM_PROMPT + "\n" + build_starter_goal_prompt(goal, intents, datasets)
    chunks: list[str] = []
    async with aclosing(
        basic_chat.stream_chat(message, verbose=True, exchange_owner=user_id, max_tokens=MAX_GOAL_TOKENS)
    ) as stream:
        async for chunk in stream:
            chunks.append(chunk)
    return parse_starter_goal_answer("".join(chunks))
