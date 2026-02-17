"""Regression coverage for demo-mode data execution guards."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.main import app
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow


def _find_route(path: str, method: str = "POST") -> APIRoute:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return route
    raise AssertionError(f"Route not found: {method} {path}")


def _has_demo_guard(route: APIRoute) -> bool:
    for dep in route.dependant.dependencies:
        call = dep.call
        if call and getattr(call, "__name__", None) == "_guard" and getattr(call, "__module__", "") == "spectra_sherpa.app.api.deps":
            return True
    return False


@pytest.fixture
async def auth_client(
    test_session: AsyncSession, test_user: User
) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client authenticated as test_user."""

    async def override_get_session():
        yield test_session

    async def override_get_current_user():
        return test_user

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def demo_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_config, "site_profile", "demo")


class TestDemoGuardCoverage:
    def test_file_upload_routes_have_demo_guard(self) -> None:
        """Actual file upload/import routes should have demo_guard("data_upload").

        Processing endpoints (preprocess, blend, synthesize, compute/execute) are
        intentionally NOT guarded — they must work with reference datasets in demo mode.
        """
        guarded_paths = [
            "/api/v1/experiments/{experiment_id}/files",
            "/api/v1/projects/import",
        ]
        for path in guarded_paths:
            route = _find_route(path, "POST")
            assert _has_demo_guard(route), f"Expected demo_guard dependency on {path}"

    def test_processing_routes_are_not_guarded(self) -> None:
        """Processing endpoints must remain open in demo mode for reference datasets."""
        open_paths = [
            "/api/v1/builder/preprocess",
            "/api/v1/builder/blend",
            "/api/v1/builder/synthesize",
            "/api/v1/compute/execute",
        ]
        for path in open_paths:
            route = _find_route(path, "POST")
            assert not _has_demo_guard(route), f"Unexpected demo_guard on {path}"

    @pytest.mark.anyio
    async def test_demo_allows_initial_data_for_reference_datasets(
        self,
        auth_client: AsyncClient,
        test_session: AsyncSession,
        test_user: User,
        demo_profile: None,
    ) -> None:
        """initial_data is used by ALL data sources (eigenvector, sklearn, etc.),
        not just file uploads. Workflow execution must NOT block initial_data
        in demo mode — reference datasets would be unusable otherwise."""
        workflow = Workflow(name="demo-ref-data", user_id=test_user.id)
        test_session.add(workflow)
        await test_session.commit()
        await test_session.refresh(workflow)

        payload = {
            "initial_data": {
                "data_1": {
                    "source": "eigenvector",
                    "eigenvector_dataset": "diesel_nir",
                }
            }
        }
        resp = await auth_client.post(
            f"/api/v1/workflows/{workflow.id}/execute",
            json=payload,
        )
        # Should not be 403 — reference datasets are allowed in demo mode.
        # May fail for other reasons (no nodes, etc.) but must not be blocked.
        assert resp.status_code != 403
