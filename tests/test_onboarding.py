"""Tests for onboarding endpoint (Issue #15).

Tests the GET /health/onboarding endpoint response structure.
Since these tests use the async DB test infrastructure, they verify
the endpoint logic via direct function calls with mocked sessions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from spectra_sherpa.app.api.v1.routes.health import get_onboarding_status


class _FakeUser:
    id = 1


class TestOnboardingEndpoint:
    @pytest.mark.asyncio
    async def test_first_run_empty_user(self):
        """A user with no projects/workflows should see is_first_run=True."""
        session = AsyncMock()
        # All counts return 0
        session.scalar = AsyncMock(return_value=0)

        result = await get_onboarding_status(session=session, current_user=_FakeUser())

        assert result["is_first_run"] is True
        assert result["steps"]["has_project"] is False
        assert result["steps"]["has_data"] is False
        assert result["steps"]["has_workflow"] is False
        assert result["steps"]["has_executed"] is False
        assert result["steps"]["has_model"] is False
        assert result["counts"]["projects"] == 0

    @pytest.mark.asyncio
    async def test_not_first_run_with_project(self):
        """A user with projects is not on first run."""
        session = AsyncMock()
        # First scalar call is project_count, return 1. Others return 0.
        call_count = 0

        async def mock_scalar(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # project_count
                return 1
            return 0

        session.scalar = mock_scalar

        result = await get_onboarding_status(session=session, current_user=_FakeUser())

        assert result["is_first_run"] is False
        assert result["steps"]["has_project"] is True
        assert result["counts"]["projects"] == 1

    @pytest.mark.asyncio
    async def test_response_structure(self):
        """Verify the response has all expected keys."""
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=0)

        result = await get_onboarding_status(session=session, current_user=_FakeUser())

        # Top-level keys
        assert "is_first_run" in result
        assert "steps" in result
        assert "counts" in result

        # Steps keys
        steps = result["steps"]
        assert "has_project" in steps
        assert "has_data" in steps
        assert "has_workflow" in steps
        assert "has_executed" in steps
        assert "has_model" in steps

        # Counts keys
        counts = result["counts"]
        assert "projects" in counts
        assert "experiments" in counts
        assert "workflows" in counts
        assert "models" in counts

    @pytest.mark.asyncio
    async def test_all_steps_complete(self):
        """A user with everything should have all steps true."""
        session = AsyncMock()
        # All counts return 5
        session.scalar = AsyncMock(return_value=5)

        result = await get_onboarding_status(session=session, current_user=_FakeUser())

        assert result["is_first_run"] is False
        assert result["steps"]["has_project"] is True
        assert result["steps"]["has_data"] is True
        assert result["steps"]["has_workflow"] is True
        assert result["steps"]["has_executed"] is True
        assert result["steps"]["has_model"] is True
