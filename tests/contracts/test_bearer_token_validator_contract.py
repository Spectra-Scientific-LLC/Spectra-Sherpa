from __future__ import annotations

import pytest

from spectra_sherpa.app.contracts.auth_resolver import (
    clear_extra_bearer_token_validator,
    get_extra_bearer_token_validator,
    set_extra_bearer_token_validator,
)


@pytest.fixture(autouse=True)
def _cleanup_validator():
    clear_extra_bearer_token_validator()
    yield
    clear_extra_bearer_token_validator()


@pytest.mark.asyncio
async def test_validator_contract_round_trip():
    """A server extension can register and retrieve an async token validator."""
    assert get_extra_bearer_token_validator() is None

    async def _validator(token: str) -> dict | None:
        if token == "valid":
            return {"sub": "1", "tv": 0}
        return None

    set_extra_bearer_token_validator(_validator)
    retrieved = get_extra_bearer_token_validator()
    assert retrieved is _validator
    assert await retrieved("valid") == {"sub": "1", "tv": 0}
    assert await retrieved("invalid") is None


def test_clear_resets_validator():
    async def _validator(_token: str) -> dict | None:
        return None

    set_extra_bearer_token_validator(_validator)
    clear_extra_bearer_token_validator()
    assert get_extra_bearer_token_validator() is None
