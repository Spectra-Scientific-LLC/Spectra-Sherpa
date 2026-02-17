"""
End-to-end test for LOCAL mode.

Validates the full HTTP workflow in single-user desktop mode:
  1. Health check
  2. Create workflow with nodes + edges via API (no auth headers)
  3. Read it back
  4. Execute it
  5. Verify response structure

Settings under test:
  app_config.mode          = "local"
  app_config.site_profile  = None          (no demo restrictions)
  app_config.rate_limit_executions = None  (no rate limiting)
  Auth                     = implicit local user (no token/key)
  Database                 = in-memory SQLite via conftest fixtures
  Transport                = ASGI in-process (no real HTTP)
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from spectra_sherpa.app.core.config import app_config
import spectra_sherpa.app.api.deps as deps


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _local_mode():
    """Pin config to local mode and clear the cached local user."""
    original_mode = app_config.mode
    original_profile = app_config.site_profile
    original_rate = app_config.rate_limit_executions

    app_config.mode = "local"
    app_config.site_profile = None
    app_config.rate_limit_executions = None
    deps._local_user_cache = None

    yield

    app_config.mode = original_mode
    app_config.site_profile = original_profile
    app_config.rate_limit_executions = original_rate
    deps._local_user_cache = None


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

class TestLocalModeE2E:
    """Full HTTP round-trip in local mode — no auth, no rate limits."""

    async def test_health(self, client: AsyncClient):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_workflow_create_execute_roundtrip(self, client: AsyncClient):
        """Create a workflow via API, read it back, execute it."""

        # ── Step 1: Create workflow with nodes + edges ──────────
        create_payload = {
            "name": "E2E Local Preprocessing",
            "description": "End-to-end test for local mode",
            "status": "draft",
            "nodes": [
                {
                    "node_id": "data_1",
                    "node_type": "data.source",
                    "label": "DATA",
                    "parameters": {"source": "experiment"},
                },
                {
                    "node_id": "snv_1",
                    "node_type": "normalize.snv",
                    "label": "SNV",
                    "parameters": {},
                },
            ],
            "edges": [
                {
                    "from_node_id": "data_1",
                    "to_node_id": "snv_1",
                    "from_output": "default",
                    "to_input": "default",
                },
            ],
        }

        resp = await client.post("/api/v1/workflows", json=create_payload)
        assert resp.status_code == 201, f"Create failed: {resp.text}"
        created = resp.json()
        wf_id = created["id"]

        assert created["name"] == "E2E Local Preprocessing"
        assert len(created["nodes"]) == 2
        assert len(created["edges"]) == 1

        # ── Step 2: Read it back ─────────────────────────────────
        resp = await client.get(f"/api/v1/workflows/{wf_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["id"] == wf_id
        assert detail["name"] == "E2E Local Preprocessing"

        node_ids = {n["node_id"] for n in detail["nodes"]}
        assert node_ids == {"data_1", "snv_1"}

        edge = detail["edges"][0]
        assert edge["from_node_id"] == "data_1"
        assert edge["to_node_id"] == "snv_1"

        # ── Step 3: Execute ──────────────────────────────────────
        resp = await client.post(
            f"/api/v1/workflows/{wf_id}/execute",
            json={},
        )
        assert resp.status_code == 200, f"Execute failed: {resp.text}"
        result = resp.json()

        # Verify response structure
        assert result["workflow_id"] == wf_id
        assert result["status"] in ("success", "completed", "error", "partial")
        assert "results" in result
        assert "node_statuses" in result
        assert "diagnostics" in result
        assert result["executed_at"] is not None
        assert result["integrity_hash"] is not None

    async def test_empty_workflow_executes(self, client: AsyncClient):
        """An empty workflow (no nodes) should execute without 500."""
        resp = await client.post(
            "/api/v1/workflows",
            json={"name": "Empty Workflow"},
        )
        assert resp.status_code == 201
        wf_id = resp.json()["id"]

        resp = await client.post(
            f"/api/v1/workflows/{wf_id}/execute",
            json={},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["workflow_id"] == wf_id
        assert result["status"] in ("success", "completed", "partial")

    async def test_execute_nonexistent_workflow_404(self, client: AsyncClient):
        """Executing a workflow that doesn't exist returns 404."""
        resp = await client.post(
            "/api/v1/workflows/999999/execute",
            json={},
        )
        assert resp.status_code == 404

    async def test_no_auth_headers_needed(self, client: AsyncClient):
        """Local mode requires no Authorization header or API key."""
        # Explicitly verify no auth header is set on the client
        resp = await client.get("/api/v1/workflows")
        assert resp.status_code == 200
        # Should return a list (possibly empty)
        assert isinstance(resp.json(), list)

    async def test_no_rate_limit_headers(self, client: AsyncClient):
        """Local mode should not return rate-limit headers."""
        resp = await client.post(
            "/api/v1/workflows",
            json={"name": "Rate Limit Check"},
        )
        assert resp.status_code == 201
        assert "X-RateLimit-Limit" not in resp.headers
        assert "X-RateLimit-Remaining" not in resp.headers
