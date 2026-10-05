from __future__ import annotations

from types import SimpleNamespace

import pytest

from spectra_sherpa.app.contracts.auth_resolver import (
    clear_user_compute_access_resolver,
    set_user_compute_access_resolver,
    user_allows_compute,
)


@pytest.fixture(autouse=True)
def _reset_resolver():
    clear_user_compute_access_resolver()
    yield
    clear_user_compute_access_resolver()


@pytest.mark.asyncio
async def test_oss_default_does_not_introduce_managed_trial_policy() -> None:
    assert await user_allows_compute(None) is True
    assert await user_allows_compute(SimpleNamespace(id=7)) is True


@pytest.mark.asyncio
async def test_managed_resolver_requires_identity_and_forwards_exact_user() -> None:
    seen: list[int] = []

    async def _resolver(user_id: int) -> bool:
        seen.append(user_id)
        return user_id == 7

    set_user_compute_access_resolver(_resolver)

    assert await user_allows_compute(None) is False
    assert await user_allows_compute(SimpleNamespace()) is False
    assert await user_allows_compute(SimpleNamespace(id=7)) is True
    assert await user_allows_compute(SimpleNamespace(id=8)) is False
    assert seen == [7, 8]
