"""Durable project-custody tests for the canonical package importer."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from spectra_sherpa.app.api.v1.routes import projects as projects_route
from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.canonical_project_custody import (
    CanonicalProjectCustodyError,
    resolve_canonical_application_plan_provenance,
    resolve_canonical_artifact_read_grant,
)
from spectra_sherpa.app.services.canonical_project_dependencies import CanonicalProjectDependencyReadiness
from spectra_sherpa.app.services.canonical_project_import import (
    CanonicalProjectImportError,
    import_canonical_project,
)
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.sherpa_object import ArchiveMember, build_archive
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifactError

# Keep the fixture package shared with the offline package-contract suite.  It
# is generated from a real first-party PLS refit rather than a hand-written
# JSON approximation, which means this importer test exercises all three
# package identities exactly as users will receive them.
from tests.test_canonical_project_package import _package, _review_package

# ``_package`` constructs the evidence fixture with ``asyncio.run``.  Build it
# at module import, before pytest-asyncio owns a test event loop, then use its
# sealed bytes in each async database test.
if not type_registry.is_loaded:
    type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")
_PACKAGE = _package()
_REVIEW_PACKAGE, _REVIEW_ANCHORS = _review_package(_PACKAGE)


@pytest.fixture(autouse=True)
def _canonical_project_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Make custody's server-owned root match this isolated test import."""

    import spectra_sherpa.app.services.canonical_project_custody as custody

    anchors = tmp_path / "campaign-review-trust-anchors.json"
    anchors.write_text(json.dumps(_REVIEW_ANCHORS.as_dict()), encoding="utf-8")
    monkeypatch.setattr(custody, "settings", replace(custody.settings, data_dir=tmp_path))
    monkeypatch.setattr(
        projects_route,
        "settings",
        replace(
            projects_route.settings,
            data_dir=tmp_path,
            campaign_review_publisher_trust_anchors_path=str(anchors),
        ),
    )


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _factory(test_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


@pytest.mark.asyncio
async def test_import_creates_visible_application_workflow_and_private_custody(
    test_engine,
    test_session: AsyncSession,
    test_user: User,
    tmp_path: Path,
) -> None:
    package = _PACKAGE
    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=package.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )

    project = await test_session.get(Project, imported.project_id)
    workflow = await test_session.get(Workflow, imported.workflow_id)
    custody = await test_session.scalar(
        select(CanonicalProjectArtifact).where(CanonicalProjectArtifact.workflow_id == imported.workflow_id)
    )
    assert project is not None
    assert workflow is not None
    assert custody is not None
    assert project.user_id == test_user.id
    assert workflow.project_id == project.id
    assert workflow.user_id == test_user.id
    assert project.metadata_["canonical_project"]["application_workflow_id"] == workflow.id
    assert custody.user_id == test_user.id
    assert custody.project_id == project.id
    assert custody.artifact_digest == package.artifact.artifact_digest
    assert custody.capsule_digest == package.capsule.capsule_digest
    assert custody.application_plan_digest == package.application_plan.application_plan_digest
    assert custody.application_plan_payload == package.application_plan.as_dict()
    assert custody.application_integrity_hash == workflow.integrity_hash
    assert custody.package_sha256 == package.archive_sha256

    await test_session.refresh(workflow, attribute_names=["nodes", "edges"])
    persisted_nodes = [
        {"node_id": node.node_id, "node_type": node.node_type, "parameters": node.parameters} for node in workflow.nodes
    ]
    persisted_edges = [
        {
            "from_node_id": edge.from_node_id,
            "from_output": edge.from_output,
            "to_node_id": edge.to_node_id,
            "to_input": edge.to_input,
        }
        for edge in workflow.edges
    ]
    assert workflow.integrity_hash == compute_workflow_hash(persisted_nodes, persisted_edges)
    assert {node["node_id"] for node in persisted_nodes} == {
        node["node_id"] for node in package.application_plan.payload["nodes"]
    }
    expected_apply_bindings = {
        node["node_id"]: node["artifact_binding"]
        for node in package.application_plan.payload["nodes"]
        if "artifact_binding" in node
    }
    assert {
        node["node_id"]: node["parameters"] for node in persisted_nodes if node["node_id"] in expected_apply_bindings
    } == expected_apply_bindings
    assert Path(custody.artifact_dir).is_dir()
    assert Path(custody.artifact_dir).parent.name == f"project-{project.id}"
    assert Path(custody.artifact_dir).parent.parent.name == f"user-{test_user.id}"

    # Reload through a fresh session to prove that provenance is durable and
    # remains distinct from the closed worker-facing apply-node parameters.
    async with _factory(test_engine)() as reload_session:
        provenance = await resolve_canonical_application_plan_provenance(
            reload_session,
            user_id=test_user.id,
            workflow_id=imported.workflow_id,
        )
    assert provenance.application_plan.application_plan_digest == custody.application_plan_digest
    assert provenance.application_plan.as_dict() == package.application_plan.as_dict()
    original_fitted_nodes = [
        node for node in provenance.application_plan.payload["nodes"] if "artifact_binding" in node
    ]
    assert original_fitted_nodes
    assert all("parameters" in node for node in original_fitted_nodes)


@pytest.mark.asyncio
async def test_import_keeps_an_unpinned_runtime_project_inspectable_but_dependency_blocked(
    test_engine,
    test_session: AsyncSession,
    test_user: User,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime absence changes availability, never the sealed imported graph."""

    import spectra_sherpa.app.services.canonical_project_import as canonical_import

    blocked = CanonicalProjectDependencyReadiness(
        ready=False,
        source_operation_ids=("baseline.rubberband",),
        blockers=("canonical_runtime_unavailable_or_unpinned",),
        remediation=("Install the exact certified runtime, then restart and revalidate.",),
    )
    monkeypatch.setattr(canonical_import, "canonical_project_dependency_readiness", lambda _plan: blocked)

    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=_PACKAGE.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    workflow = await test_session.get(Workflow, imported.workflow_id)
    project = await test_session.get(Project, imported.project_id)

    assert imported.status == "dependency_blocked"
    assert imported.dependency_readiness == blocked
    assert workflow is not None and workflow.status == "dependency_blocked"
    assert project is not None
    canonical_metadata = project.metadata_["canonical_project"]
    assert canonical_metadata["package_status"] == "dependency_blocked"
    assert canonical_metadata["dependency_readiness"] == {
        "ready": False,
        "blockers": ["canonical_runtime_unavailable_or_unpinned"],
        "remediation": ["Install the exact certified runtime, then restart and revalidate."],
    }


@pytest.mark.asyncio
async def test_custody_resolver_denies_another_user_even_when_digest_is_known(
    test_engine,
    test_session: AsyncSession,
    test_user: User,
    tmp_path: Path,
) -> None:
    package = _PACKAGE
    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=package.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    other = User(username="canonical-import-other-user")
    test_session.add(other)
    await test_session.commit()

    owner_grant = await resolve_canonical_artifact_read_grant(
        test_session,
        user_id=test_user.id,
        workflow_id=imported.workflow_id,
    )
    assert owner_grant.artifact_digest == package.artifact.artifact_digest
    assert owner_grant.artifact_dir.name == package.artifact.artifact_digest
    with pytest.raises(CanonicalProjectCustodyError, match="custody is unavailable"):
        await resolve_canonical_artifact_read_grant(
            test_session,
            user_id=other.id,
            workflow_id=imported.workflow_id,
        )


@pytest.mark.asyncio
async def test_invalid_or_failed_import_leaves_no_record_or_durable_artifact(
    test_engine,
    test_session: AsyncSession,
    test_user: User,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(CanonicalProjectImportError, match="package is invalid"):
        await import_canonical_project(
            _factory(test_engine),
            user_id=test_user.id,
            archive=b"not a canonical package",
            data_dir=tmp_path,
            max_uncompressed_bytes=1024 * 1024,
        )
    assert (await test_session.execute(select(Project))).scalars().all() == []
    assert not (tmp_path / "canonical_project_artifacts").exists()

    package = _PACKAGE

    def _fail_write(self, directory: Path, **_kwargs: object) -> Path:
        del self, directory
        raise CanonicalFittedArtifactError("simulated storage failure")

    monkeypatch.setattr(type(package.artifact), "write_new", _fail_write)
    with pytest.raises(CanonicalProjectImportError, match="cannot be installed"):
        await import_canonical_project(
            _factory(test_engine),
            user_id=test_user.id,
            archive=package.archive,
            data_dir=tmp_path,
            max_uncompressed_bytes=1024 * 1024,
        )
    assert (await test_session.execute(select(Project))).scalars().all() == []
    assert (await test_session.execute(select(CanonicalProjectArtifact))).scalars().all() == []
    root = tmp_path / "canonical_project_artifacts" / f"user-{test_user.id}"
    if root.exists():
        assert not any(root.rglob(package.artifact.artifact_digest))


@pytest.mark.asyncio
async def test_canonical_import_route_uses_the_separate_sealed_importer(
    auth_client,
    test_engine,
    test_session: AsyncSession,
    test_user: User,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user-facing route cannot accidentally route to legacy snapshot restore."""

    monkeypatch.setattr(projects_route, "async_session", _factory(test_engine))
    monkeypatch.setattr(projects_route, "settings", replace(projects_route.settings, data_dir=tmp_path))
    response = await auth_client.post(
        "/api/v1/projects/canonical-import",
        files={"file": ("campaign-review.sherpa", _REVIEW_PACKAGE.archive, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "awaiting_local_data_binding"
    assert payload["artifact_digest"] == _PACKAGE.artifact.artifact_digest
    assert payload["application_handle"].startswith("app_")
    assert payload["application"]["handle"] == payload["application_handle"]
    assert payload["application"]["workflow_id"] == payload["workflow_id"]
    assert payload["campaign_review_sha256"] == _REVIEW_PACKAGE.archive_sha256
    assert payload["publisher_attestation_digest"] == _REVIEW_PACKAGE.publisher_attestation.digest
    assert payload["publisher_authenticated"] is True
    assert payload["publisher_authentication_digest"] == _REVIEW_PACKAGE.publisher_attestation.digest
    project = await test_session.get(Project, payload["project_id"])
    workflow = await test_session.get(Workflow, payload["workflow_id"])
    assert project is not None and project.user_id == test_user.id
    assert workflow is not None and workflow.project_id == project.id
    provenance = await auth_client.get(f"/api/v1/workflows/{payload['workflow_id']}/canonical-provenance")
    assert provenance.status_code == 200, provenance.text
    provenance_payload = provenance.json()
    assert provenance_payload["application_plan_digest"] == _PACKAGE.application_plan.application_plan_digest
    assert provenance_payload["application_plan"] == _PACKAGE.application_plan.as_dict()


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["campaign-review.sherpa", "managed-result.sherpa", "renamed.sherpa"])
async def test_unified_project_import_detects_campaign_review_identity_from_bytes(
    auth_client,
    test_engine,
    test_session: AsyncSession,
    test_user: User,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    monkeypatch.setattr(projects_route, "async_session", _factory(test_engine))
    test_user_id = test_user.id
    response = await auth_client.post(
        "/api/v1/projects/import",
        files={"file": (filename, _REVIEW_PACKAGE.archive, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["id"] > 0
    assert payload["application_handle"].startswith("app_")
    assert payload["application"]["handle"] == payload["application_handle"]
    assert payload["application"]["project_id"] == payload["id"]
    project = await test_session.get(Project, payload["id"])
    assert project is not None and project.user_id == test_user_id


@pytest.mark.asyncio
async def test_unified_canonical_import_consumes_quota_after_its_independent_commit(
    auth_client,
    test_engine,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(projects_route, "async_session", _factory(test_engine))
    events: list[str] = []

    monkeypatch.setattr(
        projects_route,
        "reserve_demo_upload_quota_or_429",
        lambda _user_id: events.append("reserve") or True,
    )
    monkeypatch.setattr(
        projects_route,
        "consume_reserved_demo_upload_quota_if_needed",
        lambda _user_id, _reserved: events.append("consume"),
    )
    monkeypatch.setattr(
        projects_route,
        "release_demo_upload_quota_reservation_if_needed",
        lambda _user_id, _reserved: events.append("release"),
    )

    async def _projection_failure(*_args, **_kwargs):
        raise RuntimeError("projection failed after canonical commit")

    monkeypatch.setattr(projects_route, "_project_to_detail", _projection_failure)

    with pytest.raises(RuntimeError, match="projection failed after canonical commit"):
        await auth_client.post(
            "/api/v1/projects/import",
            files={"file": ("renamed.sherpa", _REVIEW_PACKAGE.archive, "application/octet-stream")},
        )

    assert events == ["reserve", "consume"]


@pytest.mark.asyncio
async def test_canonical_plan_provenance_fails_closed_when_durable_payload_is_tampered(
    test_engine,
    test_session: AsyncSession,
    test_user: User,
    tmp_path: Path,
) -> None:
    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=_PACKAGE.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    custody = await test_session.scalar(
        select(CanonicalProjectArtifact).where(CanonicalProjectArtifact.workflow_id == imported.workflow_id)
    )
    assert custody is not None
    custody.application_plan_payload = {"forged": "application plan"}
    await test_session.commit()

    with pytest.raises(CanonicalProjectCustodyError, match="provenance is unavailable"):
        await resolve_canonical_application_plan_provenance(
            test_session,
            user_id=test_user.id,
            workflow_id=imported.workflow_id,
        )


@pytest.mark.asyncio
async def test_canonical_import_enforces_the_route_uncompressed_budget(
    test_engine,
    test_session: AsyncSession,
    test_user: User,
    tmp_path: Path,
) -> None:
    # This is deliberately not a normal canonical fixture: it isolates the
    # compressed-upload/expanded-member boundary before canonical identity
    # parsing can obscure it.  The generic archive inventory is otherwise
    # valid, its transferred bytes fit below the service budget, and the one
    # member expands far beyond it.
    compressed_expansion = build_archive(
        project_payload={"name": "Compressed expansion probe"},
        members=[ArchiveMember("canonical/expansion.bin", b"x" * (64 * 1024))],
    )
    assert len(compressed_expansion) < 1024

    with pytest.raises(CanonicalProjectImportError, match="package is invalid"):
        await import_canonical_project(
            _factory(test_engine),
            user_id=test_user.id,
            archive=compressed_expansion,
            data_dir=tmp_path,
            max_uncompressed_bytes=1024,
        )

    assert (await test_session.execute(select(Project))).scalars().all() == []
    assert not (tmp_path / "canonical_project_artifacts").exists()
