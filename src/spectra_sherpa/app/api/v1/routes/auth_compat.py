from __future__ import annotations

from fastapi import APIRouter, Depends

from spectra_sherpa.app import schemas
from spectra_sherpa.app.api.deps import get_current_active_user
from spectra_sherpa.app.models.user import User

router = APIRouter()


@router.get("/me", response_model=schemas.User)
async def read_current_user(current_user: User = Depends(get_current_active_user)) -> User:
    """Compatibility endpoint for OSS/hybrid bootstrapping.

    Frontend hybrid bootstrap expects ``GET /api/v1/auth/me`` even when
    server-only auth/admin route modules are not packaged in this repo.
    """
    return current_user
