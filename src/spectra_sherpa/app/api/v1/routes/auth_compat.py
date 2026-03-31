"""OSS-compatible actor routes for local/hybrid modes.

When ``spectra-server`` is installed its full auth module takes priority.
This module intentionally exposes only the narrow actor endpoint needed by
the OSS frontend bootstrap. Password login and JWT issuance are server-owned.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from spectra_sherpa.app import schemas
from spectra_sherpa.app.api.deps import get_current_actor
from spectra_sherpa.app.contracts.actors import CurrentActor

router = APIRouter()

@router.get("/me", response_model=schemas.Actor)
async def read_current_user(
    current_user: CurrentActor = Depends(get_current_actor),
) -> CurrentActor:
    """Return the current actor for OSS local/hybrid bootstrap."""
    return current_user
