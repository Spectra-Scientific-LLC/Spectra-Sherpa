"""Account-scoped prediction capability injected by managed deployments."""

from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.config import app_config

PredictionAccessProvider = Callable[[AsyncSession, int], Awaitable[bool]]
_provider: PredictionAccessProvider | None = None


def set_prediction_access_provider(provider: PredictionAccessProvider | None) -> None:
    global _provider
    _provider = provider


async def private_prediction_allowed(session: AsyncSession, user_id: int) -> bool:
    if app_config.mode == "local":
        return True
    return bool(await _provider(session, user_id)) if _provider is not None else False


async def require_private_prediction(session: AsyncSession, user_id: int) -> None:
    if not await private_prediction_allowed(session, user_id):
        raise HTTPException(status_code=403, detail="Private prediction inputs require an active account entitlement.")
