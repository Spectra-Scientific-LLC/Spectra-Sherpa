"""Regression tests for the ``AdminResolver`` contract added in v0.4.1 Phase 2.

After Trim A removed ``is_superuser`` from the OSS ``User`` model,
every OSS admin gate (WebSocket admin-jobs channel, tool admin scope,
LLM rate-limit bypass) that still called ``getattr(user, "is_superuser",
False)`` silently returned False for real server superusers — producing
subtle permission regressions instead of loud failures. Phase 2 adds
a server-registered ``AdminResolver`` contract + the ``is_admin_user``
helper; OSS admin gates must use the helper.

These tests pin the contract behavior so a future change cannot
quietly reintroduce the attribute-read pattern.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from spectra_sherpa.app.contracts.auth_resolver import (
    clear_extra_admin_resolver,
    is_admin_user,
    set_extra_admin_resolver,
)


@pytest.fixture(autouse=True)
def _reset_admin_resolver():
    clear_extra_admin_resolver()
    yield
    clear_extra_admin_resolver()


@pytest.mark.asyncio
async def test_is_admin_user_returns_false_for_none():
    assert await is_admin_user(None) is False


@pytest.mark.asyncio
async def test_is_admin_user_returns_false_when_no_resolver_registered():
    # Local-mode default path — no server, no admin concept.
    user = SimpleNamespace(id=42)
    assert await is_admin_user(user) is False


@pytest.mark.asyncio
async def test_is_admin_user_returns_false_for_user_missing_id():
    # Defensive: skips the resolver entirely rather than passing None.
    calls: list[int] = []

    async def _resolver(user_id: int) -> bool:
        calls.append(user_id)
        return True

    set_extra_admin_resolver(_resolver)
    user = SimpleNamespace()  # no `id`
    assert await is_admin_user(user) is False
    assert calls == []


@pytest.mark.asyncio
async def test_is_admin_user_forwards_id_to_registered_resolver():
    captured: list[int] = []

    async def _resolver(user_id: int) -> bool:
        captured.append(user_id)
        return user_id == 7

    set_extra_admin_resolver(_resolver)

    admin_user = SimpleNamespace(id=7)
    non_admin = SimpleNamespace(id=8)

    assert await is_admin_user(admin_user) is True
    assert await is_admin_user(non_admin) is False
    assert captured == [7, 8]


@pytest.mark.asyncio
async def test_is_admin_user_ignores_is_superuser_attribute():
    """OSS must NOT read ``user.is_superuser`` — after Trim A that
    attribute is meaningless on the OSS User model. A resolver that
    always returns False must win, even if the user happens to carry
    a truthy ``is_superuser`` attribute from some other code path.
    """

    async def _deny(user_id: int) -> bool:
        return False

    set_extra_admin_resolver(_deny)
    user = SimpleNamespace(id=1, is_superuser=True)
    assert await is_admin_user(user) is False
