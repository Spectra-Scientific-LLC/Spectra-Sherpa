from __future__ import annotations

from app.db.base import Base
from app.db.session import engine
from app import models  # noqa: F401  # Ensure models are registered


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
