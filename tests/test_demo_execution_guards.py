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
    def test_data_ingress_routes_have_demo_guard(self) -> None:
        """Data ingress/compute routes should expose demo_guard("data_upload")."""
        guarded_paths = [
            "/api/v1/experiments/{experiment_id}/files",
            "/api/v1/projects/import",
            "/api/v1/builder/preprocess",
            "/api/v1/builder/blend",
            "/api/v1/builder/synthesize",
            "/api/v1/compute/execute",
        ]
        for path in guarded_paths:
            route = _find_route(path, "POST")
            assert _has_demo_guard(route), f"Expected demo_guard dependency on {path}"

    @pytest.mark.anyio
    async def test_demo_blocks_builder_preprocess_inline_data(
        self,
        auth_client: AsyncClient,
        demo_profile: None,
    ) -> None:
        payload = {
            "spectra": [
                {
                    "label": "inline-demo",
                    "wavenumber": [1000.0, 1001.0],
                    "absorbance": [0.1, 0.2],
                }
            ],
            "settings": {},
        }
        resp = await auth_client.post("/api/v1/builder/preprocess", json=payload)
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["blocked_capability"] == "data_upload"

    @pytest.mark.anyio
    async def test_demo_blocks_compute_execute_inline_data(
        self,
        auth_client: AsyncClient,
        demo_profile: None,
    ) -> None:
        payload = {
            "algorithm_id": "advanced_baseline",
            "data": {"values": [[1.0, 2.0]], "x_axis": [1000.0, 1001.0]},
            "metadata": {"x_title": "wn"},
        }
        resp = await auth_client.post("/api/v1/compute/execute", json=payload)
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["blocked_capability"] == "data_upload"

    @pytest.mark.anyio
    async def test_demo_should_block_workflow_execute_inline_initial_data(
        self,
        auth_client: AsyncClient,
        test_session: AsyncSession,
        test_user: User,
        demo_profile: None,
    ) -> None:
        workflow = Workflow(name="demo-inline-data", user_id=test_user.id)
        test_session.add(workflow)
        await test_session.commit()
        await test_session.refresh(workflow)

        payload = {
            "initial_data": {
                "data_1": {
                    "wavenumber": [1000.0, 1001.0],
                    "absorbance": [0.1, 0.2],
                }
            }
        }
        resp = await auth_client.post(
            f"/api/v1/workflows/{workflow.id}/execute",
            json=payload,
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_demo_should_block_trial_execute_inline_initial_data(
        self,
        auth_client: AsyncClient,
        demo_profile: None,
    ) -> None:
        payload = {
            "target_node_id": "snv_1",
            "trial_params": {},
            "nodes": [
                {
                    "node_id": "snv_1",
                    "node_type": "normalize.snv",
                    "parameters": {},
                }
            ],
            "edges": [],
            "initial_data": {
                "data_1": {
                    "wavenumber": [1000.0, 1001.0],
                    "absorbance": [0.1, 0.2],
                }
            },
        }
        resp = await auth_client.post("/api/v1/workflows/trial/execute", json=payload)
        assert resp.status_code == 403
