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
import uuid
import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.project import Project, ProjectVersion
from spectra_sherpa.app.models.project_data_source import ProjectDataSource, WorkflowDataSource
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.services.experiments import (
    ensure_experiment_dirs,
    experiment_dir,
    metadata_path_for,
    relative_to_data_dir,
    write_metadata,
)

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
async def sample_experiment(test_session: AsyncSession, test_user: User) -> Experiment:
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
async def sample_experiment_with_files(test_session: AsyncSession, test_user: User) -> Experiment:
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
async def sample_workflow(test_session: AsyncSession, test_user: User) -> Workflow:
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
        create_resp = await auth_client.post("/api/v1/projects", json={"name": "Self"})
        project_id = create_resp.json()["id"]

        resp = await auth_client.put(
            f"/api/v1/projects/{project_id}",
            json={"parent_id": project_id},
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_delete_project(self, auth_client: AsyncClient):
        create_resp = await auth_client.post("/api/v1/projects", json={"name": "To Delete"})
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
        parent_resp = await auth_client.post("/api/v1/projects", json={"name": "Parent"})
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
        parent_resp = await auth_client.post("/api/v1/projects", json={"name": "Parent"})
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
        parent_resp = await auth_client.post("/api/v1/projects", json={"name": "Parent"})
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
    async def test_delete_parent_cascades_children(self, auth_client: AsyncClient, test_session: AsyncSession):
        parent_resp = await auth_client.post("/api/v1/projects", json={"name": "Parent"})
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
    async def test_link_experiment(self, auth_client: AsyncClient, sample_experiment: Experiment):
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "Link Test"})
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.post(f"/api/v1/projects/{proj_id}/experiments/{sample_experiment.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["experiment_count"] == 1
        assert len(data["experiments"]) == 1
        assert data["experiments"][0]["name"] == "Test Experiment"

    @pytest.mark.anyio
    async def test_template_example_experiment_summary_uses_dataset_content(
        self,
        auth_client: AsyncClient,
        test_session: AsyncSession,
        test_user: User,
    ):
        exp = Experiment(
            user_id=test_user.id,
            name="Example - PLS Regression Calibration",
            description="Bundled example data materialized from template 'PLS Regression Calibration'",
            metadata_path="",
        )
        test_session.add(exp)
        await test_session.flush()

        metadata_file = metadata_path_for(exp.id)
        write_metadata(
            metadata_file,
            {
                "template_slug": "pls_calibration",
                "launch_mode": "example",
                "example_source": "eigenvector",
                "example_dataset": "corn_m5",
            },
        )
        exp.metadata_path = relative_to_data_dir(metadata_file)
        await test_session.commit()
        await test_session.refresh(exp)

        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "Template Data Summary"})
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.post(f"/api/v1/projects/{proj_id}/experiments/{exp.id}")
        assert resp.status_code == 200
        experiment = resp.json()["experiments"][0]
        assert experiment["name"] == "Example - PLS Regression Calibration"
        assert experiment["description"].startswith("Corn M5 NIR")
        assert "80 samples of corn" in experiment["description"]
        assert experiment["facts"] == ["NIR", "80 samples", "700 channels", "4 targets"]

    @pytest.mark.anyio
    async def test_unlink_experiment(self, auth_client: AsyncClient, sample_experiment: Experiment):
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "Unlink Test"})
        proj_id = proj_resp.json()["id"]

        # Link then unlink
        await auth_client.post(f"/api/v1/projects/{proj_id}/experiments/{sample_experiment.id}")
        resp = await auth_client.delete(f"/api/v1/projects/{proj_id}/experiments/{sample_experiment.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["experiment_count"] == 0
        assert data["experiments"] == []

    @pytest.mark.anyio
    async def test_link_workflow(self, auth_client: AsyncClient, sample_workflow: Workflow):
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "WF Link Test"})
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.post(f"/api/v1/projects/{proj_id}/workflows/{sample_workflow.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_count"] == 1
        assert len(data["workflows"]) == 1
        assert data["workflows"][0]["name"] == "Test Workflow"

    @pytest.mark.anyio
    async def test_unlink_workflow(self, auth_client: AsyncClient, sample_workflow: Workflow):
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "WF Unlink Test"})
        proj_id = proj_resp.json()["id"]

        # Link then unlink
        await auth_client.post(f"/api/v1/projects/{proj_id}/workflows/{sample_workflow.id}")
        resp = await auth_client.delete(f"/api/v1/projects/{proj_id}/workflows/{sample_workflow.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_count"] == 0
        assert data["workflows"] == []

    @pytest.mark.anyio
    async def test_link_nonexistent_experiment(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "Bad Link"})
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.post(f"/api/v1/projects/{proj_id}/experiments/9999")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_link_nonexistent_workflow(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "Bad WF Link"})
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.post(f"/api/v1/projects/{proj_id}/workflows/9999")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_unlink_not_linked_experiment(self, auth_client: AsyncClient, sample_experiment: Experiment):
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "Not Linked"})
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.delete(f"/api/v1/projects/{proj_id}/experiments/{sample_experiment.id}")
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
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "To Delete"})
        proj_id = proj_resp.json()["id"]

        # Link experiment
        await auth_client.post(f"/api/v1/projects/{proj_id}/experiments/{sample_experiment.id}")

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
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "To Delete WF"})
        proj_id = proj_resp.json()["id"]

        # Link workflow
        await auth_client.post(f"/api/v1/projects/{proj_id}/workflows/{sample_workflow.id}")

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
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "Multi-save"})
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
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "Snapshot Test"})
        proj_id = proj_resp.json()["id"]

        # Link experiment with files
        await auth_client.post(f"/api/v1/projects/{proj_id}/experiments/{sample_experiment_with_files.id}")

        save_resp = await auth_client.post(
            f"/api/v1/projects/{proj_id}/save",
            json={"change_description": "With data"},
        )
        version_id = save_resp.json()["id"]

        # Retrieve version detail to check snapshot
        ver_resp = await auth_client.get(f"/api/v1/projects/{proj_id}/versions/{version_id}")
        assert ver_resp.status_code == 200
        snapshot = ver_resp.json()["snapshot"]
        assert snapshot["name"] == "Snapshot Test"
        assert len(snapshot["experiments"]) == 1
        assert snapshot["experiments"][0]["name"] == "Experiment With Files"
        assert len(snapshot["experiments"][0]["files"]) == 2

    @pytest.mark.anyio
    async def test_list_versions(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "Version List"})
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
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "No Versions"})
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.get(f"/api/v1/projects/{proj_id}/versions/9999")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_version_count_in_summary(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "Version Count"})
        proj_id = proj_resp.json()["id"]

        await auth_client.post(f"/api/v1/projects/{proj_id}/save", json={})
        await auth_client.post(f"/api/v1/projects/{proj_id}/save", json={})

        resp = await auth_client.get(f"/api/v1/projects/{proj_id}")
        assert resp.json()["version_count"] == 2


# ── Export / Import Tests ────────────────────────────────────────────


class TestExportImport:
    """Export to .spectrapy archive and import back."""

    @staticmethod
    def _project_payload_from_archive(payload: bytes) -> dict:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as zf:
            return json.loads(zf.read("project.json"))

    @staticmethod
    def _stable_roundtrip_summary(payload: dict) -> dict:
        source_id_to_name = {source.get("id"): source.get("display_name") for source in payload.get("data_sources", [])}

        def normalize_ids(value):
            if isinstance(value, dict):
                normalized = {key: normalize_ids(item) for key, item in value.items()}
                for key in ("data_source_id", "primary_data_source_id"):
                    if normalized.get(key) in source_id_to_name:
                        normalized[key] = source_id_to_name[normalized[key]]
                return normalized
            if isinstance(value, list):
                return [source_id_to_name.get(item, normalize_ids(item)) for item in value]
            return value

        return {
            "name": payload.get("name"),
            "technique": payload.get("technique"),
            "sample_type": payload.get("sample_type"),
            "data_sources": [
                {
                    "display_name": source.get("display_name"),
                    "source_type": source.get("source_type"),
                    "source_ref": source.get("source_ref"),
                    "fingerprint": source.get("fingerprint"),
                    "color": source.get("color"),
                    "metadata": source.get("metadata"),
                    "sort_order": source.get("sort_order"),
                }
                for source in sorted(payload.get("data_sources", []), key=lambda item: item.get("display_name") or "")
            ],
            "workflows": [
                {
                    "name": workflow.get("name"),
                    "status": workflow.get("status"),
                    "technique": workflow.get("technique"),
                    "sample_type": workflow.get("sample_type"),
                    "primary_data_source": source_id_to_name.get(workflow.get("primary_data_source_id")),
                    "data_sources": [source_id_to_name.get(item) for item in workflow.get("data_source_ids", [])],
                    "nodes": [
                        {
                            "node_id": node.get("node_id"),
                            "node_type": node.get("node_type"),
                            "label": node.get("label"),
                            "parameters": normalize_ids(node.get("parameters") or {}),
                        }
                        for node in sorted(workflow.get("nodes", []), key=lambda item: item.get("node_id") or "")
                    ],
                    "edges": [
                        {
                            "from_node_id": edge.get("from_node_id"),
                            "to_node_id": edge.get("to_node_id"),
                            "from_output": edge.get("from_output"),
                            "to_input": edge.get("to_input"),
                        }
                        for edge in sorted(
                            workflow.get("edges", []),
                            key=lambda item: (item.get("from_node_id") or "", item.get("to_node_id") or ""),
                        )
                    ],
                }
                for workflow in sorted(payload.get("workflows", []), key=lambda item: item.get("name") or "")
            ],
        }

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
    async def test_export_project_sherpa_object(self, auth_client: AsyncClient):
        proj_resp = await auth_client.post(
            "/api/v1/projects",
            json={
                "name": "Portable Object",
                "technique": "FTIR",
                "sample_type": "polymer",
            },
        )
        proj_id = proj_resp.json()["id"]

        resp = await auth_client.get(f"/api/v1/projects/{proj_id}/export/sherpa")
        assert resp.status_code == 200
        assert "Portable_Object.sherpa" in resp.headers.get("content-disposition", "")

        with zipfile.ZipFile(io.BytesIO(resp.content), "r") as zf:
            assert "project.json" in zf.namelist()
            assert "sherpa-object.json" in zf.namelist()
            manifest = json.loads(zf.read("sherpa-object.json"))
            assert manifest["schema"] == "spectra_sherpa_object"
            assert manifest["object_type"] == "project"
            assert manifest["package_mode"] == "full"
            assert manifest["payloads"]["members"]["project.json"]["sha256"]

        validate_resp = await auth_client.post(
            "/api/v1/projects/objects/validate",
            files={"file": ("portable.sherpa", io.BytesIO(resp.content), "application/zip")},
        )
        assert validate_resp.status_code == 200
        assert validate_resp.json()["valid"] is True

    @pytest.mark.anyio
    async def test_project_archive_exports_respect_export_policy(self, auth_client: AsyncClient, monkeypatch):
        from spectra_sherpa.app.api.v1.routes import projects as project_routes

        async def deny_export(_user, _session=None):
            return False

        proj_resp = await auth_client.post("/api/v1/projects", json={"name": "No Export"})
        proj_id = proj_resp.json()["id"]
        monkeypatch.setattr(project_routes, "check_export_allowed", deny_export)

        spectrapy_resp = await auth_client.get(f"/api/v1/projects/{proj_id}/export")
        sherpa_resp = await auth_client.get(f"/api/v1/projects/{proj_id}/export/sherpa")

        assert spectrapy_resp.status_code == 403
        assert sherpa_resp.status_code == 403

    @pytest.mark.anyio
    async def test_sherpa_object_endpoints_declare_auth_dependency(self):
        import inspect

        from spectra_sherpa.app.api.v1.routes import projects as project_routes

        for endpoint in (project_routes.inspect_sherpa_object, project_routes.validate_sherpa_object):
            signature = inspect.signature(endpoint)
            assert "current_user" in signature.parameters

    @pytest.mark.anyio
    async def test_validate_sherpa_object_rejects_uncompressed_zip_bomb_guard(self, auth_client: AsyncClient):
        original_max_size = settings.max_file_size_mb
        object.__setattr__(settings, "max_file_size_mb", 1)
        try:
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("project.json", b"0" * ((1024 * 1024) + 1))
                zf.writestr(
                    "sherpa-object.json",
                    json.dumps(
                        {
                            "schema": "spectra_sherpa_object",
                            "object_version": "0.1",
                            "object_type": "project",
                            "package_mode": "full",
                            "payloads": {"project": "project.json", "members": {}},
                            "content_hash": "unused",
                        }
                    ),
                )
            archive.seek(0)

            resp = await auth_client.post(
                "/api/v1/projects/objects/validate",
                files={"file": ("bomb.sherpa", archive, "application/zip")},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is False
            assert "Archive uncompressed payload exceeds the configured upload limit." in data["errors"]
        finally:
            object.__setattr__(settings, "max_file_size_mb", original_max_size)

    @pytest.mark.anyio
    async def test_validate_sherpa_object_rejects_unsupported_version(self, auth_client: AsyncClient):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps({"name": "Future Object"}))
            zf.writestr(
                "sherpa-object.json",
                json.dumps(
                    {
                        "schema": "spectra_sherpa_object",
                        "object_version": "9.9",
                        "object_type": "project",
                        "package_mode": "full",
                        "payloads": {
                            "project": "project.json",
                            "members": {"project.json": {"sha256": "unused", "size": 1}},
                        },
                        "content_hash": "unused",
                    }
                ),
            )
        archive.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/objects/validate",
            files={"file": ("future.sherpa", archive, "application/zip")},
        )
        assert resp.status_code == 200
        assert "Unsupported .sherpa object version." in resp.json()["errors"]

    @pytest.mark.anyio
    async def test_validate_sherpa_object_rejects_parent_directory_member(self, auth_client: AsyncClient):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("..", b"unsafe")
            zf.writestr("project.json", json.dumps({"name": "Unsafe"}))
            zf.writestr("sherpa-object.json", json.dumps({}))
        archive.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/objects/validate",
            files={"file": ("unsafe.sherpa", archive, "application/zip")},
        )
        assert resp.status_code == 200
        assert "Archive contains an unsafe member path." in resp.json()["errors"]

    @pytest.mark.anyio
    async def test_validate_sherpa_object_sanitizes_parser_details(self, auth_client: AsyncClient):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", "{not-json")
            zf.writestr("sherpa-object.json", "{also-not-json")
        archive.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/objects/validate",
            files={"file": ("invalid.sherpa", archive, "application/zip")},
        )

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["valid"] is False
        assert payload["errors"]
        assert "error_details" in payload
        assert {detail["code"] for detail in payload["error_details"]} == {"invalid_archive_json"}
        response_text = resp.text.lower()
        assert "line " not in response_text
        assert "column " not in response_text
        assert "expecting property name" not in response_text

    @pytest.mark.anyio
    async def test_inspect_sherpa_object_sanitizes_parser_details(self, auth_client: AsyncClient):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", "{not-json")
            zf.writestr("sherpa-object.json", "{also-not-json")
        archive.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/objects/inspect",
            files={"file": ("invalid.sherpa", archive, "application/zip")},
        )

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["errors"]
        assert "error_details" in payload
        assert {detail["code"] for detail in payload["error_details"]} == {"invalid_archive_json"}
        response_text = resp.text.lower()
        assert "line " not in response_text
        assert "column " not in response_text
        assert "expecting property name" not in response_text

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
    async def test_import_legacy_spectrapy_recreates_expected_workflow_count(self, auth_client: AsyncClient):
        snapshot = {
            "name": "Legacy Workflow Project",
            "experiments": [],
            "workflows": [
                {
                    "id": 10,
                    "name": "Legacy Sheet",
                    "status": "draft",
                    "nodes": [
                        {
                            "node_id": "source",
                            "node_type": "data.source",
                            "parameters": {},
                        }
                    ],
                    "edges": [],
                }
            ],
            "children": [],
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(snapshot))
        buf.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("legacy.spectrapy", buf, "application/zip")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["workflows"]) == 1
        assert data["workflows"][0]["name"] == "Legacy Sheet"

    @pytest.mark.anyio
    async def test_sherpa_object_export_import_reexport_preserves_stable_workflow_payload(
        self,
        auth_client: AsyncClient,
        test_session: AsyncSession,
        test_user: User,
    ):
        project = Project(
            user_id=test_user.id,
            name="Roundtrip Project",
            technique="FTIR",
            sample_type="polymer",
            metadata_={"purpose": "roundtrip"},
        )
        test_session.add(project)
        await test_session.flush()

        data_source = ProjectDataSource(
            project_id=project.id,
            display_name="Calibration File",
            source_type="upload",
            source_ref="calibration.csv",
            fingerprint=f"roundtrip-{uuid.uuid4()}",
            color="#3b82f6",
            metadata_={"extension": ".csv"},
            sort_order=0,
        )
        test_session.add(data_source)
        await test_session.flush()

        workflow = Workflow(
            user_id=test_user.id,
            project_id=project.id,
            name="Roundtrip PCA",
            status="draft",
            technique="FTIR",
            sample_type="polymer",
            primary_data_source_id=data_source.id,
            color_source="blank",
            sheet_order=0,
        )
        test_session.add(workflow)
        await test_session.flush()
        test_session.add(WorkflowDataSource(workflow_id=workflow.id, data_source_id=data_source.id, role="primary"))
        test_session.add_all(
            [
                WorkflowNode(
                    workflow_id=workflow.id,
                    node_id="source_1",
                    node_type="data.source",
                    label="Source",
                    parameters={"data_source_id": data_source.id},
                    position_x=0,
                    position_y=0,
                ),
                WorkflowNode(
                    workflow_id=workflow.id,
                    node_id="pca_1",
                    node_type="model.pca",
                    label="PCA",
                    parameters={"n_components": 2},
                    position_x=240,
                    position_y=0,
                ),
                WorkflowEdge(
                    workflow_id=workflow.id,
                    from_node_id="source_1",
                    to_node_id="pca_1",
                    from_output="dataset",
                    to_input="X",
                ),
            ]
        )
        await test_session.commit()

        export_resp = await auth_client.get(f"/api/v1/projects/{project.id}/export/sherpa")
        assert export_resp.status_code == 200
        original_summary = self._stable_roundtrip_summary(self._project_payload_from_archive(export_resp.content))

        import_resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("roundtrip.sherpa", io.BytesIO(export_resp.content), "application/zip")},
        )
        assert import_resp.status_code == 201
        imported_id = import_resp.json()["id"]

        reexport_resp = await auth_client.get(f"/api/v1/projects/{imported_id}/export/sherpa")
        assert reexport_resp.status_code == 200
        reexported_summary = self._stable_roundtrip_summary(self._project_payload_from_archive(reexport_resp.content))
        assert reexported_summary == original_summary

    @pytest.mark.anyio
    async def test_sherpa_object_roundtrip_restores_uploaded_data_and_executes_imported_workflow(
        self,
        auth_client: AsyncClient,
        test_session: AsyncSession,
        test_engine,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import spectra_sherpa.app.db.session as db_session

        test_sessionmaker = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(db_session, "async_session", test_sessionmaker)

        project = Project(
            user_id=test_user.id,
            name="Portable Data Project",
            technique="FTIR",
            sample_type="polymer",
        )
        test_session.add(project)
        await test_session.flush()

        experiment = Experiment(
            user_id=test_user.id,
            project_id=project.id,
            name="Uploaded Calibration Set",
            description="A tiny uploaded CSV used to prove project archive portability",
            metadata_path="",
        )
        test_session.add(experiment)
        await test_session.flush()
        ensure_experiment_dirs(experiment.id)
        metadata_file = metadata_path_for(experiment.id)
        write_metadata(metadata_file, {"instrument": "unit-test FTIR", "source": "uploaded"})
        experiment.metadata_path = relative_to_data_dir(metadata_file)

        data_path = experiment_dir(experiment.id) / "raw" / "portable.csv"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text("Wavenumber (cm-1),sample_a,sample_b,sample_c\n1000,1,4,7\n1001,2,5,8\n1002,3,6,9\n")
        file_row = ExperimentFile(
            experiment_id=experiment.id,
            file_path="raw/portable.csv",
            file_type="csv",
            stage="raw",
            file_size_bytes=data_path.stat().st_size,
        )
        test_session.add(file_row)
        await test_session.flush()

        source_ref = f"dataset:{experiment.id}"
        data_source = ProjectDataSource(
            project_id=project.id,
            display_name="Uploaded Calibration Set",
            source_type="upload",
            source_ref=source_ref,
            fingerprint=source_ref,
            color="#3b82f6",
            metadata_={"dataset_id": experiment.id, "stage": "raw"},
            sort_order=0,
        )
        test_session.add(data_source)
        await test_session.flush()

        workflow = Workflow(
            user_id=test_user.id,
            project_id=project.id,
            name="Imported Data Workflow",
            status="draft",
            technique="FTIR",
            sample_type="polymer",
            primary_data_source_id=data_source.id,
            color_source="data",
            sheet_order=0,
        )
        test_session.add(workflow)
        await test_session.flush()
        test_session.add(WorkflowDataSource(workflow_id=workflow.id, data_source_id=data_source.id, role="primary"))
        test_session.add_all(
            [
                WorkflowNode(
                    workflow_id=workflow.id,
                    node_id="source_1",
                    node_type="data.my_dataset",
                    label="My Dataset",
                    parameters={"dataset_id": experiment.id, "stage": "raw"},
                    position_x=0,
                    position_y=0,
                ),
                WorkflowNode(
                    workflow_id=workflow.id,
                    node_id="scale_1",
                    node_type="preprocess.scale",
                    label="Mean Center",
                    parameters={"method": "mean_center"},
                    position_x=240,
                    position_y=0,
                ),
                WorkflowEdge(
                    workflow_id=workflow.id,
                    from_node_id="source_1",
                    to_node_id="scale_1",
                    from_output="default",
                    to_input="default",
                ),
            ]
        )
        await test_session.commit()

        export_resp = await auth_client.get(f"/api/v1/projects/{project.id}/export/sherpa")
        assert export_resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(export_resp.content), "r") as zf:
            names = set(zf.namelist())
            assert f"data/experiments/{experiment.id}/raw/portable.csv" in names
            project_json = json.loads(zf.read("project.json"))
            archived_file = project_json["experiments"][0]["files"][0]
            assert archived_file["archive_status"] == "included"
            assert archived_file["sha256"]

        import_resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("portable-data.sherpa", io.BytesIO(export_resp.content), "application/zip")},
        )
        assert import_resp.status_code == 201, import_resp.text
        imported_project = import_resp.json()
        assert imported_project["experiments"][0]["name"] == "Uploaded Calibration Set"
        imported_experiment_id = imported_project["experiments"][0]["id"]
        imported_workflow_id = imported_project["workflows"][0]["id"]
        assert imported_experiment_id != experiment.id

        imported_file_path = experiment_dir(imported_experiment_id) / "raw" / "portable.csv"
        assert imported_file_path.read_text() == data_path.read_text()

        data_sources_resp = await auth_client.get(f"/api/v1/projects/{imported_project['id']}/data-sources")
        assert data_sources_resp.status_code == 200
        imported_data_sources = data_sources_resp.json()
        assert len(imported_data_sources) == 1
        imported_data_source = imported_data_sources[0]
        assert imported_data_source["display_name"] == "Uploaded Calibration Set"
        assert imported_data_source["source_type"] == "upload"
        assert imported_data_source["source_ref"] == f"dataset:{imported_experiment_id}"
        assert imported_data_source["metadata"]["dataset_id"] == imported_experiment_id
        assert imported_data_source["metadata"]["stage"] == "raw"

        workflow_resp = await auth_client.get(f"/api/v1/workflows/{imported_workflow_id}")
        assert workflow_resp.status_code == 200
        workflow_detail = workflow_resp.json()
        imported_source_node = next(node for node in workflow_detail["nodes"] if node["node_id"] == "source_1")
        assert imported_source_node["parameters"]["dataset_id"] == imported_experiment_id

        execute_resp = await auth_client.post(f"/api/v1/workflows/{imported_workflow_id}/execute", json={})
        assert execute_resp.status_code == 200, execute_resp.text
        executed = execute_resp.json()
        assert executed["status"] == "completed", executed
        assert executed["node_statuses"]["source_1"] == "completed"
        assert executed["node_statuses"]["scale_1"] == "completed"
        assert executed["results"]["source_1"]["default"]["shape"] == [3, 3]

    @pytest.mark.anyio
    async def test_sherpa_object_roundtrip_restores_child_project_tree_and_executes_child_workflow(
        self,
        auth_client: AsyncClient,
        test_session: AsyncSession,
        test_engine,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import spectra_sherpa.app.db.session as db_session

        test_sessionmaker = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(db_session, "async_session", test_sessionmaker)

        root_project = Project(
            user_id=test_user.id,
            name="Parent Portable Project",
            technique="FTIR",
            sample_type="polymer",
        )
        test_session.add(root_project)
        await test_session.flush()
        child_project = Project(
            user_id=test_user.id,
            parent_id=root_project.id,
            name="Child Calibration Project",
            technique="FTIR",
            sample_type="polymer",
        )
        test_session.add(child_project)
        await test_session.flush()

        experiment = Experiment(
            user_id=test_user.id,
            project_id=child_project.id,
            name="Child Uploaded Data",
            metadata_path="",
        )
        test_session.add(experiment)
        await test_session.flush()
        ensure_experiment_dirs(experiment.id)
        metadata_file = metadata_path_for(experiment.id)
        write_metadata(metadata_file, {"source": "child-project"})
        experiment.metadata_path = relative_to_data_dir(metadata_file)

        data_path = experiment_dir(experiment.id) / "raw" / "child.csv"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text("Wavenumber (cm-1),sample_a,sample_b\n1000,1,3\n1001,2,4\n")
        test_session.add(
            ExperimentFile(
                experiment_id=experiment.id,
                file_path="raw/child.csv",
                file_type="csv",
                stage="raw",
                file_size_bytes=data_path.stat().st_size,
            )
        )
        await test_session.flush()

        source_ref = f"dataset:{experiment.id}"
        data_source = ProjectDataSource(
            project_id=child_project.id,
            display_name="Child Uploaded Data",
            source_type="upload",
            source_ref=source_ref,
            fingerprint=source_ref,
            color="#3b82f6",
            metadata_={"dataset_id": experiment.id, "stage": "raw"},
            sort_order=0,
        )
        test_session.add(data_source)
        await test_session.flush()

        workflow = Workflow(
            user_id=test_user.id,
            project_id=child_project.id,
            name="Child Workflow",
            status="draft",
            technique="FTIR",
            sample_type="polymer",
            primary_data_source_id=data_source.id,
            color_source="data",
            sheet_order=0,
        )
        test_session.add(workflow)
        await test_session.flush()
        test_session.add(WorkflowDataSource(workflow_id=workflow.id, data_source_id=data_source.id, role="primary"))
        test_session.add_all(
            [
                WorkflowNode(
                    workflow_id=workflow.id,
                    node_id="source_1",
                    node_type="data.my_dataset",
                    label="My Dataset",
                    parameters={"dataset_id": experiment.id},
                    position_x=0,
                    position_y=0,
                ),
                WorkflowNode(
                    workflow_id=workflow.id,
                    node_id="scale_1",
                    node_type="preprocess.scale",
                    label="Mean Center",
                    parameters={"method": "mean_center"},
                    position_x=240,
                    position_y=0,
                ),
                WorkflowEdge(
                    workflow_id=workflow.id,
                    from_node_id="source_1",
                    to_node_id="scale_1",
                    from_output="default",
                    to_input="default",
                ),
            ]
        )
        await test_session.commit()

        export_resp = await auth_client.get(f"/api/v1/projects/{root_project.id}/export/sherpa")
        assert export_resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(export_resp.content), "r") as zf:
            names = set(zf.namelist())
            assert f"data/experiments/{experiment.id}/raw/child.csv" in names
            project_json = json.loads(zf.read("project.json"))
            assert project_json["children"][0]["name"] == "Child Calibration Project"
            assert project_json["children"][0]["experiments"][0]["files"][0]["archive_status"] == "included"

        import_resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("child-tree.sherpa", io.BytesIO(export_resp.content), "application/zip")},
        )
        assert import_resp.status_code == 201, import_resp.text
        imported_root = import_resp.json()
        assert imported_root["name"] == "Parent Portable Project"
        assert len(imported_root["children"]) == 1

        imported_child_id = imported_root["children"][0]["id"]
        child_resp = await auth_client.get(f"/api/v1/projects/{imported_child_id}")
        assert child_resp.status_code == 200
        imported_child = child_resp.json()
        assert imported_child["name"] == "Child Calibration Project"
        assert imported_child["experiments"][0]["name"] == "Child Uploaded Data"
        imported_experiment_id = imported_child["experiments"][0]["id"]
        imported_workflow_id = imported_child["workflows"][0]["id"]

        imported_file_path = experiment_dir(imported_experiment_id) / "raw" / "child.csv"
        assert imported_file_path.read_text() == data_path.read_text()

        workflow_resp = await auth_client.get(f"/api/v1/workflows/{imported_workflow_id}")
        assert workflow_resp.status_code == 200
        imported_source_node = next(node for node in workflow_resp.json()["nodes"] if node["node_id"] == "source_1")
        assert imported_source_node["parameters"]["dataset_id"] == imported_experiment_id

        execute_resp = await auth_client.post(f"/api/v1/workflows/{imported_workflow_id}/execute", json={})
        assert execute_resp.status_code == 200, execute_resp.text
        executed = execute_resp.json()
        assert executed["status"] == "completed", executed
        assert executed["node_statuses"]["source_1"] == "completed"
        assert executed["node_statuses"]["scale_1"] == "completed"
        assert executed["results"]["source_1"]["default"]["shape"] == [2, 2]

    @pytest.mark.anyio
    async def test_import_bundled_project_data_requires_sha_and_cleans_partial_experiment(
        self,
        auth_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from spectra_sherpa.app.api.v1.routes import projects as project_routes

        deleted_experiment_ids: list[int] = []
        original_delete_experiment_files = project_routes.delete_experiment_files

        def record_delete_experiment_files(experiment_id: int) -> None:
            deleted_experiment_ids.append(experiment_id)
            original_delete_experiment_files(experiment_id)

        monkeypatch.setattr(project_routes, "delete_experiment_files", record_delete_experiment_files)

        snapshot = {
            "name": "Missing Data Hash",
            "experiments": [
                {
                    "id": 42,
                    "name": "Uploaded CSV",
                    "metadata": {},
                    "files": [
                        {
                            "id": 7,
                            "stage": "raw",
                            "file_path": "raw/portable.csv",
                            "file_type": "csv",
                            "archive_member": "data/experiments/42/raw/portable.csv",
                        }
                    ],
                }
            ],
            "data_sources": [],
            "workflows": [],
            "scripts": [],
            "models": [],
            "children": [],
        }
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(snapshot))
            zf.writestr("data/experiments/42/raw/portable.csv", "Wavenumber,sample\n1000,1\n")
        archive.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("missing-hash.spectrapy", archive, "application/zip")},
        )

        assert resp.status_code == 400
        assert "missing integrity hash" in resp.text
        assert deleted_experiment_ids
        assert not experiment_dir(deleted_experiment_ids[0]).exists()

    @pytest.mark.anyio
    async def test_import_bundled_project_data_rejects_archive_member_redirection(self, auth_client: AsyncClient):
        from spectra_sherpa.app.services.sherpa_object import sha256_bytes

        payload = b"Wavenumber,sample\n1000,9\n"
        snapshot = {
            "name": "Redirected Data Member",
            "experiments": [
                {
                    "id": 43,
                    "name": "Uploaded CSV",
                    "metadata": {},
                    "files": [
                        {
                            "id": 8,
                            "stage": "raw",
                            "file_path": "raw/portable.csv",
                            "file_type": "csv",
                            "archive_member": "data/experiments/43/raw/other.csv",
                            "sha256": sha256_bytes(payload),
                        }
                    ],
                }
            ],
            "data_sources": [],
            "workflows": [],
            "scripts": [],
            "models": [],
            "children": [],
        }
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(snapshot))
            zf.writestr("data/experiments/43/raw/other.csv", payload)
        archive.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("redirected-member.spectrapy", archive, "application/zip")},
        )

        assert resp.status_code == 400
        assert "archive member does not match" in resp.text

    @pytest.mark.anyio
    async def test_sherpa_export_deduplicates_duplicate_experiment_file_rows(
        self,
        auth_client: AsyncClient,
        test_session: AsyncSession,
        test_user: User,
    ):
        project = Project(user_id=test_user.id, name="Duplicate Files")
        test_session.add(project)
        await test_session.flush()

        experiment = Experiment(user_id=test_user.id, project_id=project.id, name="Uploaded Data", metadata_path="")
        test_session.add(experiment)
        await test_session.flush()
        ensure_experiment_dirs(experiment.id)
        metadata_file = metadata_path_for(experiment.id)
        write_metadata(metadata_file, {})
        experiment.metadata_path = relative_to_data_dir(metadata_file)

        data_path = experiment_dir(experiment.id) / "raw" / "same.csv"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text("Wavenumber,sample\n1000,1\n")
        test_session.add_all(
            [
                ExperimentFile(
                    experiment_id=experiment.id,
                    file_path="raw/same.csv",
                    file_type="csv",
                    stage="raw",
                    file_size_bytes=data_path.stat().st_size,
                ),
                ExperimentFile(
                    experiment_id=experiment.id,
                    file_path="raw/same.csv",
                    file_type="csv",
                    stage="raw",
                    file_size_bytes=data_path.stat().st_size,
                ),
            ]
        )
        await test_session.commit()

        resp = await auth_client.get(f"/api/v1/projects/{project.id}/export/sherpa")
        assert resp.status_code == 200

        with zipfile.ZipFile(io.BytesIO(resp.content), "r") as zf:
            names = zf.namelist()
            assert names.count(f"data/experiments/{experiment.id}/raw/same.csv") == 1
            project_json = json.loads(zf.read("project.json"))
            statuses = [file_data.get("archive_status") for file_data in project_json["experiments"][0]["files"]]
            assert statuses.count("included") == 1
            assert statuses.count("duplicate") == 1

    @pytest.mark.anyio
    async def test_versioned_sherpa_export_bundles_only_project_owned_experiment_files(
        self,
        auth_client: AsyncClient,
        test_session: AsyncSession,
        test_user: User,
        user2: User,
    ):
        project = Project(user_id=test_user.id, name="Versioned Portable Data")
        other_project = Project(user_id=user2.id, name="Other Project")
        test_session.add_all([project, other_project])
        await test_session.flush()

        owned_experiment = Experiment(
            user_id=test_user.id,
            project_id=project.id,
            name="Owned Upload",
            metadata_path="",
        )
        other_experiment = Experiment(
            user_id=user2.id,
            project_id=other_project.id,
            name="Other Upload",
            metadata_path="",
        )
        test_session.add_all([owned_experiment, other_experiment])
        await test_session.flush()

        file_rows: dict[int, ExperimentFile] = {}
        for experiment, filename, value in (
            (owned_experiment, "owned.csv", "1"),
            (other_experiment, "other.csv", "9"),
        ):
            ensure_experiment_dirs(experiment.id)
            metadata_file = metadata_path_for(experiment.id)
            write_metadata(metadata_file, {})
            experiment.metadata_path = relative_to_data_dir(metadata_file)
            data_path = experiment_dir(experiment.id) / "raw" / filename
            data_path.parent.mkdir(parents=True, exist_ok=True)
            data_path.write_text(f"Wavenumber,sample\n1000,{value}\n")
            file_row = ExperimentFile(
                experiment_id=experiment.id,
                file_path=f"raw/{filename}",
                file_type="csv",
                stage="raw",
                file_size_bytes=data_path.stat().st_size,
            )
            test_session.add(file_row)
            file_rows[experiment.id] = file_row
        await test_session.flush()

        snapshot = {
            "name": project.name,
            "experiments": [
                {
                    "id": owned_experiment.id,
                    "name": owned_experiment.name,
                    "metadata": {},
                    "files": [
                        {
                            "id": file_rows[owned_experiment.id].id,
                            "file_path": "raw/owned.csv",
                            "stage": "raw",
                            "file_type": "csv",
                            "file_size_bytes": file_rows[owned_experiment.id].file_size_bytes,
                        }
                    ],
                },
                {
                    "id": other_experiment.id,
                    "name": other_experiment.name,
                    "metadata": {},
                    "files": [
                        {
                            "id": file_rows[other_experiment.id].id,
                            "file_path": "raw/other.csv",
                            "stage": "raw",
                            "file_type": "csv",
                            "file_size_bytes": file_rows[other_experiment.id].file_size_bytes,
                        }
                    ],
                },
            ],
            "data_sources": [],
            "workflows": [],
            "scripts": [],
            "models": [],
            "children": [],
        }
        version = ProjectVersion(
            project_id=project.id,
            version_number=1,
            created_by=test_user.id,
            change_description="Version snapshot",
            snapshot=snapshot,
            include_raw_data=True,
        )
        test_session.add(version)
        await test_session.commit()

        resp = await auth_client.get(f"/api/v1/projects/{project.id}/export/sherpa?version_id={version.id}")
        assert resp.status_code == 200

        with zipfile.ZipFile(io.BytesIO(resp.content), "r") as zf:
            names = set(zf.namelist())
            assert f"data/experiments/{owned_experiment.id}/raw/owned.csv" in names
            assert f"data/experiments/{other_experiment.id}/raw/other.csv" not in names
            project_json = json.loads(zf.read("project.json"))
            assert project_json["archive_format"]["version"] == "0.2"
            assert project_json["experiments"][0]["files"][0]["archive_status"] == "included"
            assert project_json["experiments"][1]["files"][0]["archive_status"] == "not_project_owned"
            manifest = json.loads(zf.read("sherpa-object.json"))
            assert manifest["project_payload_version"] == "0.2"

    @pytest.mark.anyio
    async def test_import_sherpa_object_recreates_workflow_rows(self, auth_client: AsyncClient):
        from spectra_sherpa.app.services.sherpa_object import build_archive

        snapshot = {
            "name": "Imported Sherpa Object",
            "description": "Portable archive",
            "metadata": {"lab": "Test Lab"},
            "technique": "FTIR",
            "sample_type": "polymer",
            "data_sources": [
                {
                    "id": 12,
                    "display_name": "Calibration spectra",
                    "source_type": "experiment",
                    "source_ref": "exp_001",
                    "fingerprint": "abc123",
                    "color": "#3b82f6",
                    "metadata": {"role": "calibration"},
                    "sort_order": 0,
                }
            ],
            "experiments": [],
            "workflows": [
                {
                    "id": 77,
                    "name": "PCA sheet",
                    "description": "Imported workflow",
                    "status": "draft",
                    "technique": "FTIR",
                    "sample_type": "polymer",
                    "primary_data_source_id": 12,
                    "data_source_ids": [12],
                    "sheet_order": 0,
                    "nodes": [
                        {
                            "node_id": "source_1",
                            "node_type": "data.source",
                            "label": "Source",
                            "parameters": {"data_source_id": 12},
                            "position_x": 10,
                            "position_y": 20,
                        },
                        {
                            "node_id": "pca_1",
                            "node_type": "model.pca",
                            "label": "PCA",
                            "parameters": {"n_components": 2},
                            "position_x": 280,
                            "position_y": 20,
                        },
                    ],
                    "edges": [
                        {
                            "from_node_id": "source_1",
                            "to_node_id": "pca_1",
                            "from_output": "dataset",
                            "to_input": "X",
                        }
                    ],
                }
            ],
            "scripts": [],
            "models": [],
            "children": [],
        }
        archive = build_archive(project_payload=snapshot)

        resp = await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("roundtrip.sherpa", io.BytesIO(archive), "application/zip")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Imported Sherpa Object"
        assert len(data["data_sources"]) == 1
        assert len(data["workflows"]) == 1
        workflow = data["workflows"][0]
        assert workflow["name"] == "PCA sheet"
        assert workflow["primary_data_source_id"] == data["data_sources"][0]["id"]
        assert workflow["data_source_ids"] == [data["data_sources"][0]["id"]]

        ver_resp = await auth_client.get(f"/api/v1/projects/{data['id']}/versions")
        assert ver_resp.json()["versions"][0]["change_description"] == "Imported from .sherpa object"

    @pytest.mark.anyio
    async def test_validate_sherpa_object_rejects_hash_mismatch(self, auth_client: AsyncClient):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps({"name": "Tampered"}))
            zf.writestr(
                "sherpa-object.json",
                json.dumps(
                    {
                        "schema": "spectra_sherpa_object",
                        "object_version": "0.1",
                        "object_type": "project",
                        "package_mode": "full",
                        "payloads": {
                            "project": "project.json",
                            "members": {"project.json": {"sha256": "bad", "size": 1}},
                        },
                        "content_hash": "bad",
                    }
                ),
            )
        archive.seek(0)

        resp = await auth_client.post(
            "/api/v1/projects/objects/validate",
            files={"file": ("tampered.sherpa", archive, "application/zip")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "Archive member hash does not match the manifest." in data["errors"]

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
        ver_resp = await auth_client.get(f"/api/v1/projects/{proj_id}/versions")
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
        assert resp.json()["detail"]["message"] == "Invalid project archive."

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
    async def test_import_rejects_oversized_archive_before_zip_parse(
        self,
        auth_client: AsyncClient,
    ):
        original_max_size = settings.max_file_size_mb
        object.__setattr__(settings, "max_file_size_mb", 1)
        try:
            oversized_payload = io.BytesIO(b"x" * ((1024 * 1024) + 1))

            resp = await auth_client.post(
                "/api/v1/projects/import",
                files={"file": ("too-large.spectrapy", oversized_payload, "application/zip")},
            )
            assert resp.status_code == 413
            assert "Archive too large" in resp.json()["detail"]
        finally:
            object.__setattr__(settings, "max_file_size_mb", original_max_size)

    @pytest.mark.anyio
    async def test_import_fail_fast_total_model_budget_is_atomic(
        self,
        auth_client: AsyncClient,
        test_session: AsyncSession,
    ):
        import numpy as np

        original_max_size = settings.max_file_size_mb
        object.__setattr__(settings, "max_file_size_mb", 1)

        try:
            # 6 models * ~0.9 MB arrays > 5 MB total budget, with each member < 1 MB.
            # Uses a repeating 1KB random-ish block to keep compression ratio below 200:1.
            block = np.random.default_rng(0).integers(0, 256, size=1024, dtype=np.uint8)
            arr = np.tile(block, (900_000 // block.size) + 1)[:900_000]
            arrays_buf = io.BytesIO()
            np.savez(arrays_buf, arr=arr)
            arrays_payload = arrays_buf.getvalue()

            models = []
            for i in range(6):
                models.append(
                    {
                        "artifact_uid": str(uuid.uuid4()),
                        "node_id": f"node_{i}",
                        "model_type": "pca",
                        "name": f"Model {i}",
                    }
                )

            rollback_name = f"Should Roll Back {uuid.uuid4()}"
            snapshot = {
                "name": rollback_name,
                "description": "Validation should fail before commit",
                "metadata": {},
                "technique": "IR",
                "sample_type": "powder",
                "experiments": [],
                "workflows": [],
                "scripts": [],
                "models": models,
                "children": [],
            }

            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("project.json", json.dumps(snapshot))
                for model in models:
                    uid = model["artifact_uid"]
                    zf.writestr(f"models/{uid}/manifest.json", json.dumps({"model_type": "pca"}))
                    zf.writestr(f"models/{uid}/arrays.npz", arrays_payload)
            payload.seek(0)

            before_count = await test_session.scalar(
                select(func.count(Project.id)).where(Project.name == rollback_name)
            )

            resp = await auth_client.post(
                "/api/v1/projects/import",
                files={"file": ("too-many-models.spectrapy", payload, "application/zip")},
            )
            assert resp.status_code == 413
            assert "Total model data too large" in resp.json()["detail"]

            after_count = await test_session.scalar(select(func.count(Project.id)).where(Project.name == rollback_name))
            assert (before_count or 0) == (after_count or 0) == 0
        finally:
            object.__setattr__(settings, "max_file_size_mb", original_max_size)

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
        export_resp = await auth_client.get(f"/api/v1/projects/{proj_id}/export")

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
        resp = await auth_client.post("/api/v1/projects", json={"name": "User1 Project"})
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
        resp = await auth_client.post("/api/v1/projects", json={"name": "Private"})
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
        resp = await auth_client.post("/api/v1/projects", json={"name": "Not Yours"})
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
