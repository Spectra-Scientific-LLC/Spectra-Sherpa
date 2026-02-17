"""
Tests for Project API endpoints — CRUD, link/unlink, versioning, and export/import.

Covers:
  1. Project CRUD (create, list, get, update, delete)
  2. Sub-project hierarchy (create child, delete parent cascades)
  3. Link/unlink experiments and workflows
  4. Save All (ProjectVersion snapshot creation)
  5. Version listing and retrieval
  6. Export/import .spectrapy archive
  7. Ownership enforcement (user can only see own projects)
  8. Delete project unlinks experiments/workflows (SET NULL)

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_projects.py -v --no-cov
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.main import app
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.project import Project, ProjectVersion
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
async def user2(test_session: AsyncSession) -> User:
    """Create a second test user for ownership tests."""
    user = User(username="otheruser", password_hash="otherhash")
    test_session.add(user)
    await test_session.commit()
    await test_session.refresh(user)
    return user


@pytest.fixture
async def auth_client(
    test_session: AsyncSession, test_user: User
) -> AsyncClient:
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
def swap_user(test_session: AsyncSession):
    """Context helper to temporarily swap the authenticated user for ownership tests."""

    class _Swapper:
        def __call__(self, user: User):
            async def override_get_session():
                yield test_session

            async def override_get_current_user():
                return user

            app.dependency_overrides[get_session] = override_get_session
            app.dependency_overrides[get_current_user] = override_get_current_user

    return _Swapper()


@pytest.fixture
async def sample_experiment(
    test_session: AsyncSession, test_user: User
) -> Experiment:
    """Create a sample experiment for linking tests."""
    exp = Experiment(
        user_id=test_user.id,
        name="Test Experiment",
        description="Sample experiment for testing",
        metadata_path="/data/test/metadata.json",
    )
    test_session.add(exp)
    await test_session.commit()
    await test_session.refresh(exp)
    return exp


@pytest.fixture
async def sample_experiment_with_files(
    test_session: AsyncSession, test_user: User
) -> Experiment:
    """Create an experiment with files for snapshot tests."""
    exp = Experiment(
        user_id=test_user.id,
        name="Experiment With Files",
        description="Has two files",
        metadata_path="/data/test/metadata.json",
    )
    test_session.add(exp)
    await test_session.commit()
    await test_session.refresh(exp)

    f1 = ExperimentFile(
        experiment_id=exp.id,
        file_path="/data/test/spectrum1.csv",
        file_type="csv",
        stage="raw",
    )
    f2 = ExperimentFile(
        experiment_id=exp.id,
        file_path="/data/test/spectrum2.csv",
        file_type="csv",
        stage="processed",
    )
    test_session.add_all([f1, f2])
    await test_session.commit()
    return exp


@pytest.fixture
async def sample_workflow(
    test_session: AsyncSession, test_user: User
) -> Workflow:
    """Create a sample workflow for linking tests."""
    wf = Workflow(
        user_id=test_user.id,
        name="Test Workflow",
        description="Sample workflow for testing",
        status="draft",
    )
    test_session.add(wf)
    await test_session.commit()
    await test_session.refresh(wf)
    return wf


# ── CRUD Tests ────────────────────────────────────────────────────────


class TestProjectCRUD:
    """Project create, list, get, update, delete."""

    @pytest.mark.anyio
    async def test_create_project(self, auth_client: AsyncClient):
        resp = await auth_client.post(
            "/api/v1/projects",
            json={
                "name": "My FTIR Project",
                "description": "Analyzing polymer blends",
                "technique": "FTIR",
                "sample_type": "polymer blend",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My FTIR Project"
        assert data["description"] == "Analyzing polymer blends"
        assert data["technique"] == "FTIR"
        assert data["sample_type"] == "polymer blend"
        assert data["parent_id"] is None
        assert data["experiment_count"] == 0
        assert data["workflow_count"] == 0
        assert data["experiments"] == []
        assert data["workflows"] == []

    @pytest.mark.anyio
    async def test_create_project_minimal(self, auth_client: AsyncClient):
        resp = await auth_client.post(
            "/api/v1/projects",
            json={"name": "Minimal"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Minimal"
        assert data["technique"] is None
        assert data["sample_type"] is None

    @pytest.mark.anyio
    async def test_create_project_name_required(self, auth_client: AsyncClient):
        resp = await auth_client.post(
            "/api/v1/projects",
            json={"description": "No name given"},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_list_projects_empty(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/v1/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.anyio
    async def test_list_projects(self, auth_client: AsyncClient):
        await auth_client.post("/api/v1/projects", json={"name": "P1"})
        await auth_client.post("/api/v1/projects", json={"name": "P2"})

        resp = await auth_client.get("/api/v1/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {p["name"] for p in data}
        assert names == {"P1", "P2"}

    @pytest.mark.anyio
    async def test_get_project(self, auth_client: AsyncClient):
        create_resp = await auth_client.post(
            "/api/v1/projects",
            json={"name": "Detail Test", "technique": "Raman"},
        )
        project_id = create_resp.json()["id"]

        resp = await auth_client.get(f"/api/v1/projects/{project_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Detail Test"
        assert data["technique"] == "Raman"
        assert "experiments" in data
        assert "workflows" in data
        assert "children" in data
        assert "metadata" in data

    @pytest.mark.anyio
    async def test_get_project_not_found(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/v1/projects/9999")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_update_project(self, auth_client: AsyncClient):
        create_resp = await auth_client.post(
            "/api/v1/projects",
            json={"name": "Original", "technique": "FTIR"},
        )
        project_id = create_resp.json()["id"]

        resp = await auth_client.put(
            f"/api/v1/projects/{project_id}",
            json={"name": "Renamed", "technique": "Raman", "sample_type": "wine"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Renamed"
        assert data["technique"] == "Raman"
        assert data["sample_type"] == "wine"

    @pytest.mark.anyio
    async def test_update_project_partial(self, auth_client: AsyncClient):
        create_resp = await auth_client.post(
            "/api/v1/projects",
            json={"name": "Original", "technique": "FTIR", "sample_type": "oil"},
        )
        project_id = create_resp.json()["id"]

        resp = await auth_client.put(
            f"/api/v1/projects/{project_id}",
            json={"description": "Added description"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Original"  # unchanged
        assert data["technique"] == "FTIR"  # unchanged
        assert data["description"] == "Added description"

    @pytest.mark.anyio
    async def test_update_project_self_parent_rejected(self, auth_client: AsyncClient):
        create_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Self"}
        )
        project_id = create_resp.json()["id"]

        resp = await auth_client.put(
            f"/api/v1/projects/{project_id}",
            json={"parent_id": project_id},
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_delete_project(self, auth_client: AsyncClient):
        create_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "To Delete"}
        )
        project_id = create_resp.json()["id"]

        resp = await auth_client.delete(f"/api/v1/projects/{project_id}")
        assert resp.status_code == 204

        get_resp = await auth_client.get(f"/api/v1/projects/{project_id}")
        assert get_resp.status_code == 404

    @pytest.mark.anyio
    async def test_delete_project_not_found(self, auth_client: AsyncClient):
        resp = await auth_client.delete("/api/v1/projects/9999")
        assert resp.status_code == 404


# ── Sub-Project Hierarchy Tests ───────────────────────────────────────


class TestSubProjects:
    """Sub-project creation, listing, and cascade delete."""

    @pytest.mark.anyio
    async def test_create_sub_project(self, auth_client: AsyncClient):
        parent_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Parent"}
        )
        parent_id = parent_resp.json()["id"]

        child_resp = await auth_client.post(
            "/api/v1/projects",
            json={"name": "Child", "parent_id": parent_id},
        )
        assert child_resp.status_code == 201
        child_data = child_resp.json()
        assert child_data["parent_id"] == parent_id

    @pytest.mark.anyio
    async def test_children_in_parent_detail(self, auth_client: AsyncClient):
        parent_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Parent"}
        )
        parent_id = parent_resp.json()["id"]

        await auth_client.post(
            "/api/v1/projects",
            json={"name": "Child A", "parent_id": parent_id},
        )
        await auth_client.post(
            "/api/v1/projects",
            json={"name": "Child B", "parent_id": parent_id},
        )

        resp = await auth_client.get(f"/api/v1/projects/{parent_id}")
        data = resp.json()
        assert data["children_count"] == 2
        assert len(data["children"]) == 2
        child_names = {c["name"] for c in data["children"]}
        assert child_names == {"Child A", "Child B"}

    @pytest.mark.anyio
    async def test_sub_projects_not_in_top_level_list(self, auth_client: AsyncClient):
        parent_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Parent"}
        )
        parent_id = parent_resp.json()["id"]

        await auth_client.post(
            "/api/v1/projects",
            json={"name": "Child", "parent_id": parent_id},
        )

        resp = await auth_client.get("/api/v1/projects")
        data = resp.json()
        # Only the parent should appear in top-level list
        assert len(data) == 1
        assert data[0]["name"] == "Parent"

    @pytest.mark.anyio
    async def test_delete_parent_cascades_children(
        self, auth_client: AsyncClient, test_session: AsyncSession
    ):
        parent_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Parent"}
        )
        parent_id = parent_resp.json()["id"]

        child_resp = await auth_client.post(
            "/api/v1/projects",
            json={"name": "Child", "parent_id": parent_id},
        )
        child_id = child_resp.json()["id"]

        # Delete parent
        await auth_client.delete(f"/api/v1/projects/{parent_id}")

        # Child should be gone too
        get_resp = await auth_client.get(f"/api/v1/projects/{child_id}")
        assert get_resp.status_code == 404


# ── Link / Unlink Tests ──────────────────────────────────────────────


class TestLinkUnlink:
    """Linking and unlinking experiments and workflows."""

    @pytest.mark.anyio
    async def test_link_experiment(
        self, auth_client: AsyncClient, sample_experiment: Experiment
    ):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Link Test"}
        )
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/experiments/{sample_experiment.id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["experiment_count"] == 1
        assert len(data["experiments"]) == 1
        assert data["experiments"][0]["name"] == "Test Experiment"

    @pytest.mark.anyio
    async def test_unlink_experiment(
        self, auth_client: AsyncClient, sample_experiment: Experiment
    ):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Unlink Test"}
        )
        proj_id = proj_resp.json()["id"]

        # Link then unlink
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/experiments/{sample_experiment.id}"
        )
        resp = await auth_client.delete(
            f"/api/v1/projects/{proj_id}/experiments/{sample_experiment.id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["experiment_count"] == 0
        assert data["experiments"] == []

    @pytest.mark.anyio
    async def test_link_workflow(
        self, auth_client: AsyncClient, sample_workflow: Workflow
    ):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "WF Link Test"}
        )
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/workflows/{sample_workflow.id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_count"] == 1
        assert len(data["workflows"]) == 1
        assert data["workflows"][0]["name"] == "Test Workflow"

    @pytest.mark.anyio
    async def test_unlink_workflow(
        self, auth_client: AsyncClient, sample_workflow: Workflow
    ):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "WF Unlink Test"}
        )
        proj_id = proj_resp.json()["id"]

        # Link then unlink
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/workflows/{sample_workflow.id}"
        )
        resp = await auth_client.delete(
            f"/api/v1/projects/{proj_id}/workflows/{sample_workflow.id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_count"] == 0
        assert data["workflows"] == []

    @pytest.mark.anyio
    async def test_link_nonexistent_experiment(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Bad Link"}
        )
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/experiments/9999"
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_link_nonexistent_workflow(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Bad WF Link"}
        )
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/workflows/9999"
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_unlink_not_linked_experiment(
        self, auth_client: AsyncClient, sample_experiment: Experiment
    ):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Not Linked"}
        )
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.delete(
            f"/api/v1/projects/{proj_id}/experiments/{sample_experiment.id}"
        )
        assert resp.status_code == 404


# ── Delete Unlinks Tests ─────────────────────────────────────────────


class TestDeleteUnlinks:
    """Deleting project unlinks (SET NULL) experiments/workflows."""

    @pytest.mark.anyio
    async def test_delete_project_unlinks_experiment(
        self,
        auth_client: AsyncClient,
        sample_experiment: Experiment,
        test_session: AsyncSession,
    ):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "To Delete"}
        )
        proj_id = proj_resp.json()["id"]

        # Link experiment
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/experiments/{sample_experiment.id}"
        )

        # Delete project
        await auth_client.delete(f"/api/v1/projects/{proj_id}")

        # Experiment should still exist but project_id should be NULL
        await test_session.refresh(sample_experiment)
        assert sample_experiment.project_id is None

    @pytest.mark.anyio
    async def test_delete_project_unlinks_workflow(
        self,
        auth_client: AsyncClient,
        sample_workflow: Workflow,
        test_session: AsyncSession,
    ):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "To Delete WF"}
        )
        proj_id = proj_resp.json()["id"]

        # Link workflow
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/workflows/{sample_workflow.id}"
        )

        # Delete project
        await auth_client.delete(f"/api/v1/projects/{proj_id}")

        # Workflow should still exist but project_id should be NULL
        await test_session.refresh(sample_workflow)
        assert sample_workflow.project_id is None


# ── Versioning / Save All Tests ──────────────────────────────────────


class TestVersioning:
    """Save All snapshots, version listing, and version retrieval."""

    @pytest.mark.anyio
    async def test_save_project_creates_version(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post(
            "/api/v1/projects",
            json={"name": "Versioned", "technique": "NIR"},
        )
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/save",
            json={"change_description": "Initial save"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["version_number"] == 1
        assert data["change_description"] == "Initial save"
        assert data["include_raw_data"] is False

    @pytest.mark.anyio
    async def test_save_increments_version(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Multi-save"}
        )
        proj_id = proj_resp.json()["id"]

        v1 = await auth_client.post(
            f"/api/v1/projects/{proj_id}/save",
            json={"change_description": "v1"},
        )
        assert v1.json()["version_number"] == 1

        v2 = await auth_client.post(
            f"/api/v1/projects/{proj_id}/save",
            json={"change_description": "v2"},
        )
        assert v2.json()["version_number"] == 2

    @pytest.mark.anyio
    async def test_save_captures_snapshot_with_experiments(
        self,
        auth_client: AsyncClient,
        sample_experiment_with_files: Experiment,
    ):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Snapshot Test"}
        )
        proj_id = proj_resp.json()["id"]

        # Link experiment with files
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/experiments/{sample_experiment_with_files.id}"
        )

        save_resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/save",
            json={"change_description": "With data"},
        )
        version_id = save_resp.json()["id"]

        # Retrieve version detail to check snapshot
        ver_resp = await auth_client.get(
            f"/api/v1/projects/{proj_id}/versions/{version_id}"
        )
        assert ver_resp.status_code == 200
        snapshot = ver_resp.json()["snapshot"]
        assert snapshot["name"] == "Snapshot Test"
        assert len(snapshot["experiments"]) == 1
        assert snapshot["experiments"][0]["name"] == "Experiment With Files"
        assert len(snapshot["experiments"][0]["files"]) == 2

    @pytest.mark.anyio
    async def test_list_versions(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Version List"}
        )
        proj_id = proj_resp.json()["id"]

        await auth_client.post(
            f"/api/v1/projects/{proj_id}/save",
            json={"change_description": "First"},
        )
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/save",
            json={"change_description": "Second"},
        )

        resp = await auth_client.get(f"/api/v1/projects/{proj_id}/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["versions"]) == 2
        # Descending order: newest first
        assert data["versions"][0]["version_number"] == 2
        assert data["versions"][1]["version_number"] == 1

    @pytest.mark.anyio
    async def test_get_version_not_found(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "No Versions"}
        )
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.get(
            f"/api/v1/projects/{proj_id}/versions/9999"
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_version_count_in_summary(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Version Count"}
        )
        proj_id = proj_resp.json()["id"]

        await auth_client.post(
            f"/api/v1/projects/{proj_id}/save", json={}
        )
        await auth_client.post(
            f"/api/v1/projects/{proj_id}/save", json={}
        )

        resp = await auth_client.get(f"/api/v1/projects/{proj_id}")
        assert resp.json()["version_count"] == 2


# ── Export / Import Tests ────────────────────────────────────────────


class TestExportImport:
    """Export to .spectrapy archive and import back."""

    @pytest.mark.anyio
    async def test_export_project(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post(
            "/api/v1/projects",
            json={
                "name": "Export Me",
                "technique": "FTIR",
                "sample_type": "oil",
            },
        )
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.get(f"/api/v1/projects/{proj_id}/export")
        assert resp.status_code == 200
        assert "spectrapy" in resp.headers.get("content-disposition", "")

        # Verify ZIP contents
        buf = io.BytesIO(resp.content)
        with zipfile.ZipFile(buf, "r") as zf:
            assert "project.json" in zf.namelist()
            project_json = json.loads(zf.read("project.json"))
            assert project_json["name"] == "Export Me"
            assert project_json["technique"] == "FTIR"
            assert project_json["sample_type"] == "oil"

    @pytest.mark.anyio
    async def test_import_project(self, auth_client: AsyncClient):
        # Create a valid .spectrapy archive
        snapshot = {
            "name": "Imported Project",
            "description": "From archive",
            "metadata": {"lab": "Test Lab"},
            "technique": "Raman",
            "sample_type": "mineral",
            "experiments": [],
            "workflows": [],
            "children": [],
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(snapshot))
        buf.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("test.spectrapy", buf, "application/zip")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Imported Project"
        assert data["technique"] == "Raman"
        assert data["sample_type"] == "mineral"

    @pytest.mark.anyio
    async def test_import_creates_initial_version(self, auth_client: AsyncClient):
        snapshot = {
            "name": "Versioned Import",
            "experiments": [],
            "workflows": [],
            "children": [],
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(snapshot))
        buf.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("test.spectrapy", buf, "application/zip")},
        )
        proj_id = resp.json()["id"]

        # Check that version 1 was created
        ver_resp = await auth_client.get(
            f"/api/v1/projects/{proj_id}/versions"
        )
        data = ver_resp.json()
        assert data["total"] == 1
        assert data["versions"][0]["version_number"] == 1
        assert data["versions"][0]["change_description"] == "Imported from .spectrapy archive"

    @pytest.mark.anyio
    async def test_import_invalid_archive(self, auth_client: AsyncClient):
        # Not a valid ZIP
        buf = io.BytesIO(b"not a zip file")
        resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("bad.spectrapy", buf, "application/zip")},
        )
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_import_missing_project_json(self, auth_client: AsyncClient):
        # Valid ZIP but no project.json inside
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("other.txt", "hello")
        buf.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("bad.spectrapy", buf, "application/zip")},
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_export_roundtrip(self, auth_client: AsyncClient):
        """Create, export, then import and verify structure matches."""
        # Create project
        proj_resp = await auth_client.post(
            "/api/v1/projects",
            json={
                "name": "Roundtrip",
                "technique": "NMR",
                "description": "Test roundtrip",
            },
        )
        proj_id = proj_resp.json()["id"]

        # Export
        export_resp = await auth_client.get(
            f"/api/v1/projects/{proj_id}/export"
        )

        # Import
        buf = io.BytesIO(export_resp.content)
        import_resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("roundtrip.spectrapy", buf, "application/zip")},
        )
        assert import_resp.status_code == 201
        imported = import_resp.json()
        assert imported["name"] == "Roundtrip"
        assert imported["technique"] == "NMR"
        assert imported["description"] == "Test roundtrip"
        # IDs should differ (new project)
        assert imported["id"] != proj_id


# ── Ownership Tests ──────────────────────────────────────────────────


class TestOwnership:
    """Users can only access their own projects."""

    @pytest.mark.anyio
    async def test_user_cannot_see_other_users_projects(
        self,
        auth_client: AsyncClient,
        test_user: User,
        user2: User,
        swap_user,
    ):
        # User 1 creates a project
        resp = await auth_client.post(
            "/api/v1/projects", json={"name": "User1 Project"}
        )
        assert resp.status_code == 201

        # Swap to user2
        swap_user(user2)

        # User 2 should see empty list
        list_resp = await auth_client.get("/api/v1/projects")
        assert list_resp.status_code == 200
        assert list_resp.json() == []

        # Restore user1 for cleanup
        swap_user(test_user)

    @pytest.mark.anyio
    async def test_user_cannot_get_other_users_project(
        self,
        auth_client: AsyncClient,
        test_user: User,
        user2: User,
        swap_user,
    ):
        resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Private"}
        )
        proj_id = resp.json()["id"]

        # Swap to user2
        swap_user(user2)
        get_resp = await auth_client.get(f"/api/v1/projects/{proj_id}")
        assert get_resp.status_code == 404

        swap_user(test_user)

    @pytest.mark.anyio
    async def test_user_cannot_delete_other_users_project(
        self,
        auth_client: AsyncClient,
        test_user: User,
        user2: User,
        swap_user,
    ):
        resp = await auth_client.post(
            "/api/v1/projects", json={"name": "Not Yours"}
        )
        proj_id = resp.json()["id"]

        # Swap to user2
        swap_user(user2)
        del_resp = await auth_client.delete(f"/api/v1/projects/{proj_id}")
        assert del_resp.status_code == 404

        swap_user(test_user)


# ── Metadata Tests ───────────────────────────────────────────────────


class TestMetadata:
    """Project metadata JSON column."""

    @pytest.mark.anyio
    async def test_create_with_metadata(self, auth_client: AsyncClient):
        resp = await auth_client.post(
            "/api/v1/projects",
            json={
                "name": "Meta Project",
                "metadata": {"lab": "Spectra Lab", "instrument": "Bruker Alpha"},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["metadata"]["lab"] == "Spectra Lab"
        assert data["metadata"]["instrument"] == "Bruker Alpha"

    @pytest.mark.anyio
    async def test_update_metadata(self, auth_client: AsyncClient):
        resp = await auth_client.post(
            "/api/v1/projects",
            json={"name": "Meta Update", "metadata": {"key": "val"}},
        )
        proj_id = resp.json()["id"]

        update_resp = await auth_client.put(
            f"/api/v1/projects/{proj_id}",
            json={"metadata": {"key": "updated", "new_key": 42}},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["metadata"]["key"] == "updated"
        assert update_resp.json()["metadata"]["new_key"] == 42
