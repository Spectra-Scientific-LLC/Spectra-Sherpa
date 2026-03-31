"""
Tests for ProjectScript API endpoints — CRUD, generate-from-workflow, snapshot integration.

Covers:
  1. Create script manually
  2. List scripts (returns summaries without code)
  3. Get script detail (includes code)
  4. Update script (name, code, priority)
  5. Delete script
  6. Generate script from workflow export
  7. Script included in project snapshot (Save All)
  8. Script count reflected in project summary
  9. Deleting project cascades to scripts
  10. Ownership enforcement (can't access other user's project scripts)
  11. Import recreates scripts from snapshot

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_project_scripts.py -v --no-cov
"""

from __future__ import annotations

import io
import json
import zipfile
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.project_script import ProjectScript
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
async def user2(test_session: AsyncSession) -> User:
    """Create a second test user for ownership tests."""
    user = User(username="otheruser")
    test_session.add(user)
    await test_session.commit()
    await test_session.refresh(user)
    return user


@pytest.fixture
async def sample_project(auth_client: AsyncClient) -> dict:
    """Create a project via API and return the response data."""
    resp = await auth_client.post(
        "/api/v1/projects",
        json={"name": "Script Test Project", "technique": "FTIR"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
async def sample_workflow(test_session: AsyncSession, test_user: User) -> Workflow:
    """Create a sample workflow for generate tests."""
    wf = Workflow(
        user_id=test_user.id,
        name="Export Workflow",
        description="Workflow for script generation",
        status="draft",
    )
    test_session.add(wf)
    await test_session.commit()
    await test_session.refresh(wf)
    return wf


# ── CRUD Tests ────────────────────────────────────────────────────────


class TestScriptCRUD:
    """Script create, list, get, update, delete."""

    @pytest.mark.anyio
    async def test_create_script(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]
        resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={
                "name": "preprocess.py",
                "description": "Data preprocessing",
                "code": "import numpy as np\nprint('hello')",
                "language": "python",
                "priority": 10.0,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "preprocess.py"
        assert data["description"] == "Data preprocessing"
        assert data["language"] == "python"
        assert data["priority"] == 10.0
        assert data["code"] == "import numpy as np\nprint('hello')"
        assert data["code_length"] == len("import numpy as np\nprint('hello')")
        assert data["project_id"] == proj_id
        assert data["source_workflow_id"] is None

    @pytest.mark.anyio
    async def test_create_script_minimal(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]
        resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "min.py", "code": "pass"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "min.py"
        assert data["language"] == "python"  # default
        assert data["priority"] == 50.0  # default

    @pytest.mark.anyio
    async def test_create_script_validation(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]
        # Missing name
        resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"code": "pass"},
        )
        assert resp.status_code == 422

        # Missing code
        resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "no_code.py"},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_list_scripts_empty(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]
        resp = await auth_client.get(f"/api/v1/projects/{proj_id}/scripts")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.anyio
    async def test_list_scripts(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "first.py", "code": "# first", "priority": 20.0},
        )
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "second.py", "code": "# second", "priority": 10.0},
        )

        resp = await auth_client.get(f"/api/v1/projects/{proj_id}/scripts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Ordered by priority (10.0 first, 20.0 second)
        assert data[0]["name"] == "second.py"
        assert data[1]["name"] == "first.py"
        # Summaries should NOT include code
        assert "code" not in data[0]
        # But should have code_length
        assert data[0]["code_length"] == len("# second")

    @pytest.mark.anyio
    async def test_get_script_detail(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]
        create_resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "detail.py", "code": "x = 42"},
        )
        script_id = create_resp.json()["id"]

        resp = await auth_client.get(f"/api/v1/projects/{proj_id}/scripts/{script_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "detail.py"
        assert data["code"] == "x = 42"

    @pytest.mark.anyio
    async def test_get_script_not_found(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]
        resp = await auth_client.get(f"/api/v1/projects/{proj_id}/scripts/9999")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_update_script(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]
        create_resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "orig.py", "code": "# original", "priority": 50.0},
        )
        script_id = create_resp.json()["id"]

        resp = await auth_client.put(
            f"/api/v1/projects/{proj_id}/scripts/{script_id}",
            json={
                "name": "renamed.py",
                "code": "# updated code",
                "priority": 5.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "renamed.py"
        assert data["code"] == "# updated code"
        assert data["priority"] == 5.0

    @pytest.mark.anyio
    async def test_update_script_partial(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]
        create_resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "partial.py", "code": "# code", "priority": 30.0},
        )
        script_id = create_resp.json()["id"]

        # Only update description
        resp = await auth_client.put(
            f"/api/v1/projects/{proj_id}/scripts/{script_id}",
            json={"description": "Added desc"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "partial.py"  # unchanged
        assert data["code"] == "# code"  # unchanged
        assert data["priority"] == 30.0  # unchanged
        assert data["description"] == "Added desc"

    @pytest.mark.anyio
    async def test_delete_script(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]
        create_resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "to_delete.py", "code": "pass"},
        )
        script_id = create_resp.json()["id"]

        resp = await auth_client.delete(f"/api/v1/projects/{proj_id}/scripts/{script_id}")
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = await auth_client.get(f"/api/v1/projects/{proj_id}/scripts/{script_id}")
        assert get_resp.status_code == 404

    @pytest.mark.anyio
    async def test_delete_script_not_found(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]
        resp = await auth_client.delete(f"/api/v1/projects/{proj_id}/scripts/9999")
        assert resp.status_code == 404


# ── Generate from Workflow Tests ──────────────────────────────────────


class TestGenerateScript:
    """Generate script from workflow Python export."""

    @pytest.mark.anyio
    async def test_generate_script_from_workflow(
        self,
        auth_client: AsyncClient,
        sample_project: dict,
        sample_workflow: Workflow,
    ):
        proj_id = sample_project["id"]

        # Link workflow to project
        await auth_client.post(f"/api/v1/projects/{proj_id}/workflows/{sample_workflow.id}")

        with patch(
            "spectra_sherpa.app.api.v1.routes.project_scripts.generate_python_code",
            return_value="# Generated code\nimport numpy as np\n",
        ):
            resp = await auth_client.post(
                f"/api/v1/projects/{proj_id}/scripts/generate",
                json={
                    "workflow_id": sample_workflow.id,
                    "name": "generated.py",
                    "description": "Auto-generated",
                    "priority": 1.0,
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "generated.py"
        assert data["code"] == "# Generated code\nimport numpy as np\n"
        assert data["source_workflow_id"] == sample_workflow.id
        assert data["priority"] == 1.0
        assert data["description"] == "Auto-generated"

    @pytest.mark.anyio
    async def test_generate_script_default_description(
        self,
        auth_client: AsyncClient,
        sample_project: dict,
        sample_workflow: Workflow,
    ):
        proj_id = sample_project["id"]

        with patch(
            "spectra_sherpa.app.api.v1.routes.project_scripts.generate_python_code",
            return_value="pass",
        ):
            resp = await auth_client.post(
                f"/api/v1/projects/{proj_id}/scripts/generate",
                json={
                    "workflow_id": sample_workflow.id,
                    "name": "auto.py",
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "Export Workflow" in data["description"]

    @pytest.mark.anyio
    async def test_generate_script_workflow_not_found(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]

        resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts/generate",
            json={"workflow_id": 9999, "name": "no_wf.py"},
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_generate_script_export_fails(
        self,
        auth_client: AsyncClient,
        sample_project: dict,
        sample_workflow: Workflow,
    ):
        proj_id = sample_project["id"]

        with patch(
            "spectra_sherpa.app.api.v1.routes.project_scripts.generate_python_code",
            side_effect=ValueError("Node 'bad_node' has no generate_python()"),
        ):
            resp = await auth_client.post(
                f"/api/v1/projects/{proj_id}/scripts/generate",
                json={
                    "workflow_id": sample_workflow.id,
                    "name": "fail.py",
                },
            )
        assert resp.status_code == 422
        assert "Cannot export" in resp.json()["detail"]


# ── Snapshot Integration Tests ────────────────────────────────────────


class TestScriptSnapshot:
    """Scripts in project snapshots and import."""

    @pytest.mark.anyio
    async def test_script_in_snapshot(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]

        # Create a script
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={
                "name": "snap.py",
                "code": "print('snapshot')",
                "priority": 15.0,
                "description": "Snapshot test",
            },
        )

        # Save project
        save_resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/save",
            json={"change_description": "With script"},
        )
        assert save_resp.status_code == 201
        version_id = save_resp.json()["id"]

        # Retrieve version and check snapshot
        ver_resp = await auth_client.get(f"/api/v1/projects/{proj_id}/versions/{version_id}")
        snapshot = ver_resp.json()["snapshot"]
        assert "scripts" in snapshot
        assert len(snapshot["scripts"]) == 1
        s = snapshot["scripts"][0]
        assert s["name"] == "snap.py"
        assert s["code"] == "print('snapshot')"
        assert s["priority"] == 15.0
        assert s["description"] == "Snapshot test"

    @pytest.mark.anyio
    async def test_script_count_in_summary(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]

        # Create two scripts
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "a.py", "code": "# a"},
        )
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "b.py", "code": "# b"},
        )

        # Check project detail
        resp = await auth_client.get(f"/api/v1/projects/{proj_id}")
        data = resp.json()
        assert data["script_count"] == 2
        assert len(data["scripts"]) == 2

    @pytest.mark.anyio
    async def test_scripts_in_project_detail(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]

        await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "detail.py", "code": "x = 1", "priority": 5.0},
        )

        resp = await auth_client.get(f"/api/v1/projects/{proj_id}")
        data = resp.json()
        scripts = data["scripts"]
        assert len(scripts) == 1
        s = scripts[0]
        assert s["name"] == "detail.py"
        assert s["language"] == "python"
        assert s["priority"] == 5.0
        assert s["code_length"] == 5  # len("x = 1")
        # ScriptBrief should NOT include code
        assert "code" not in s

    @pytest.mark.anyio
    async def test_import_recreates_scripts(self, auth_client: AsyncClient):
        """Import a .spectrapy archive with scripts and verify they are recreated."""
        snapshot = {
            "name": "Imported With Scripts",
            "description": "Has scripts",
            "metadata": {},
            "technique": "Raman",
            "experiments": [],
            "workflows": [],
            "scripts": [
                {
                    "name": "imported.py",
                    "description": "From archive",
                    "language": "python",
                    "code": "import spectrochempy as scp",
                    "priority": 10.0,
                    "source_workflow_id": None,
                },
                {
                    "name": "analysis.py",
                    "description": None,
                    "language": "python",
                    "code": "# analysis",
                    "priority": 20.0,
                    "source_workflow_id": None,
                },
            ],
            "children": [],
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(snapshot))
        buf.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("scripts.spectrapy", buf, "application/zip")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Imported With Scripts"
        assert data["script_count"] == 2

        # Verify scripts were created
        proj_id = data["id"]
        scripts_resp = await auth_client.get(f"/api/v1/projects/{proj_id}/scripts")
        scripts = scripts_resp.json()
        assert len(scripts) == 2
        names = {s["name"] for s in scripts}
        assert names == {"imported.py", "analysis.py"}

    @pytest.mark.anyio
    async def test_export_includes_scripts(self, auth_client: AsyncClient, sample_project: dict):
        proj_id = sample_project["id"]

        await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "export.py", "code": "# exported"},
        )

        resp = await auth_client.get(f"/api/v1/projects/{proj_id}/export")
        assert resp.status_code == 200

        buf = io.BytesIO(resp.content)
        with zipfile.ZipFile(buf, "r") as zf:
            project_json = json.loads(zf.read("project.json"))
        assert "scripts" in project_json
        assert len(project_json["scripts"]) == 1
        assert project_json["scripts"][0]["name"] == "export.py"
        assert project_json["scripts"][0]["code"] == "# exported"


# ── Cascade Delete Tests ──────────────────────────────────────────────


class TestScriptCascade:
    """Deleting project cascades to scripts."""

    @pytest.mark.anyio
    async def test_delete_project_cascades_scripts(
        self,
        auth_client: AsyncClient,
        sample_project: dict,
        test_session: AsyncSession,
    ):
        proj_id = sample_project["id"]

        # Create scripts
        s1_resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "cascade1.py", "code": "# 1"},
        )
        s1_id = s1_resp.json()["id"]

        await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "cascade2.py", "code": "# 2"},
        )

        # Delete project
        resp = await auth_client.delete(f"/api/v1/projects/{proj_id}")
        assert resp.status_code == 204

        # Scripts should be gone
        result = await test_session.execute(select(ProjectScript).where(ProjectScript.id == s1_id))
        assert result.scalar_one_or_none() is None


# ── Ownership Tests ──────────────────────────────────────────────────


class TestScriptOwnership:
    """Users can only access scripts in their own projects."""

    @pytest.mark.anyio
    async def test_cannot_access_other_users_scripts(
        self,
        auth_client: AsyncClient,
        test_user: User,
        user2: User,
        swap_user,
        sample_project: dict,
    ):
        proj_id = sample_project["id"]

        # User1 creates a script
        create_resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "private.py", "code": "# private"},
        )
        assert create_resp.status_code == 201

        # Swap to user2
        swap_user(user2)

        # User2 should get 404 trying to list scripts in user1's project
        list_resp = await auth_client.get(f"/api/v1/projects/{proj_id}/scripts")
        assert list_resp.status_code == 404

        # Restore user1
        swap_user(test_user)

    @pytest.mark.anyio
    async def test_cannot_create_script_in_other_project(
        self,
        auth_client: AsyncClient,
        test_user: User,
        user2: User,
        swap_user,
        sample_project: dict,
    ):
        proj_id = sample_project["id"]

        # Swap to user2
        swap_user(user2)

        resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/scripts",
            json={"name": "hack.py", "code": "# injected"},
        )
        assert resp.status_code == 404

        # Restore user1
        swap_user(test_user)
