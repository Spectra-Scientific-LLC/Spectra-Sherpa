"""Consent for adding owned dataset metadata to a Starter model request."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.security import is_egress_enabled
from spectra_sherpa.app.models.data_egress import DataEgressPermission, UserEgressDefaults

logger = logging.getLogger(__name__)


async def private_starter_context_allowed(session: AsyncSession, user_id: int) -> bool:
    """Read current consent; a per-type allow cannot override disabled context.

    Missing per-type overrides inherit explicit enabled defaults, matching the
    Advisor disclosure policy. Missing defaults and policy-store failures deny
    private context. Read columns rather than cached ORM relationships so a
    revoked permission takes effect on the next request.
    """
    try:
        if not is_egress_enabled():
            return False
        defaults = (
            await session.execute(
                select(UserEgressDefaults.allow_llm_chat, UserEgressDefaults.allow_llm_context).where(
                    UserEgressDefaults.user_id == user_id
                )
            )
        ).one_or_none()
        if defaults is None or not all(value is True for value in defaults):
            return False
        overrides = (
            (
                await session.execute(
                    select(DataEgressPermission.allowed).where(
                        DataEgressPermission.user_id == user_id,
                        DataEgressPermission.destination == "llm_context",
                        DataEgressPermission.data_type.in_(("metadata", "experiments")),
                    )
                )
            )
            .scalars()
            .all()
        )
        return all(value is True for value in overrides)
    except Exception:
        # Policy errors must not disclose dataset details or block local planning.
        logger.warning("Starter private-context permission could not be verified")
        return False
