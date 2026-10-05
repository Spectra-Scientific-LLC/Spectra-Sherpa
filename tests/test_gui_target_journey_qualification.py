"""Release qualifications for supervised dataset-to-report journeys."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.v1.routes import workflow_export
from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.lib.target_authority import issue_target_authority
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.experiments import import_reference_dataset
from spectra_sherpa.app.services.model_application import load_project_dataset
from spectra_sherpa.app.services.run_params import build_saved_definition_snapshot
from spectra_sherpa.app.types import ensure_type_registry_loaded


def _production_template(slug: str, *, stored_slug: str | None = None) -> WorkflowTemplate:
    definition = {item["slug"]: item for item in TemplateLoader().load_all()}[slug]
    return WorkflowTemplate(
        slug=stored_slug or definition["slug"],
        name=definition["name"],
        description=definition["description"],
        category=definition["category"],
        template_data={**definition["template_data"], "status": "ready"},
        is_active=True,
    )


async def _project_with_experiment(
    session: AsyncSession,
    user: User,
    *,
    project_name: str,
    experiment_name: str,
) -> tuple[Project, Experiment]:
    project = Project(user_id=user.id, name=project_name, description="")
    session.add(project)
    await session.flush()
    experiment = Experiment(
        user_id=user.id,
        project_id=project.id,
        name=experiment_name,
        description="",
        metadata_path="{}",
    )
    session.add(experiment)
    await session.flush()
    return project, experiment


@pytest.mark.asyncio
async def test_breast_cancer_import_keeps_categorical_readiness_through_run_and_report(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One exact target identity must survive every scientist-facing surface."""

    from spectra_sherpa.app.core.config import app_config

    monkeypatch.setattr(app_config, "site_profile", "local")
    monkeypatch.setattr(workflow_export, "check_export_allowed", AsyncMock(return_value=True))
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    templates = [
        _production_template("classification_plsda"),
        _production_template("knn_classification"),
        _production_template("simca_classification"),
    ]
    project, experiment = await _project_with_experiment(
        test_session,
        test_user,
        project_name="Breast Cancer qualification",
        experiment_name="Breast Cancer",
    )
    test_session.add_all(templates)
    await test_session.commit()

    imported = await auth_client.post(
        f"/api/v1/experiments/{experiment.id}/import-reference",
        json={"datasets": [{"source": "sklearn", "name": "breast_cancer"}]},
    )
    assert imported.status_code == 201, imported.text
    source_file = imported.json()["files"][0]

    available = await auth_client.get(f"/api/v1/datasets/available?project_id={project.id}")
    assert available.status_code == 200, available.text
    dataset_summary = next(item for item in available.json()["experiments"] if item["id"] == experiment.id)
    assert dataset_summary["target_names"] == ["target"]
    assert dataset_summary["target_types"] == {"target": "categorical"}
    assert dataset_summary["selected_target"] == "target"
    assert dataset_summary["target_complete_rows"] == 569

    inspected = await auth_client.post(
        "/api/v1/builder/file-info",
        json={"experiment_id": experiment.id, "file_id": source_file["id"]},
    )
    assert inspected.status_code == 200, inspected.text
    target_context = inspected.json()["target_context"]
    assert target_context["target_name"] == "target"
    assert target_context["target_names"] == ["target"]
    assert target_context["target_type"] == "categorical"
    assert target_context["class_names"] == ["benign", "malignant"]

    readiness = await auth_client.post(
        "/api/v1/workflow-templates/binding-compatibility-preview",
        json={
            "project_id": project.id,
            "binding": {
                "experiment_id": experiment.id,
                "file_id": source_file["id"],
                "stage": "raw",
            },
        },
    )
    assert readiness.status_code == 200, readiness.text
    readiness_body = readiness.json()
    assert readiness_body["profile"]["target_type"] == "categorical"
    assert readiness_body["profile"]["target_fields"] == ["target"]
    decisions = {item["template_slug"]: item for item in readiness_body["decisions"]}
    assert {slug: decisions[slug]["display_status"] for slug in decisions} == {
        "classification_plsda": "compatible",
        "knn_classification": "compatible",
        "simca_classification": "compatible",
    }

    loaded = await load_project_dataset(
        test_session,
        user_id=test_user.id,
        experiment_id=experiment.id,
        stage="raw",
        file_ids=[source_file["id"]],
    )
    authority = issue_target_authority(loaded.dataset, column="target", target_type="categorical")
    authority_dict = authority.canonical_dict()
    ensure_type_registry_loaded()
    instantiated = await auth_client.post(
        f"/api/v1/workflow-templates/{templates[0].id}/instantiate",
        json={
            "workflow_name": "Breast Cancer PLS-DA",
            "project_id": project.id,
            "data_bindings": {
                "data_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "file_ids": [source_file["id"]],
                    "stage": "raw",
                    "target_authority": authority_dict,
                }
            },
        },
    )
    assert instantiated.status_code == 201, instantiated.text
    instantiated_source = next(node for node in instantiated.json()["nodes"] if node["node_id"] == "data_1")
    assert instantiated_source["parameters"]["target_authority"] == authority_dict

    workflow = await test_session.scalar(
        select(Workflow)
        .where(Workflow.id == instantiated.json()["id"])
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.primary_data_source),
        )
    )
    assert workflow is not None
    definition = build_saved_definition_snapshot(workflow)
    revision = {
        "revision_id": 1,
        "revision_number": 1,
        "source_node_id": "data_1",
        "created_by": test_user.id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "origin": "canvas",
        "reason": "Initial template data binding",
        "graph_digest": workflow.integrity_hash,
        "selection": {
            "dataset_name": "Breast Cancer",
            "experiment_id": experiment.id,
            "stage": "raw",
            "selected_file_ids": [source_file["id"]],
            "target_authority": authority_dict,
            "group_column": None,
        },
    }
    run = ExecutionRun(
        project_id=project.id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="Breast Cancer PLS-DA",
        status="completed",
        run_kind="training",
        params_snapshot={"data_1": {"target_authority": authority_dict}},
        results_summary={},
        source_metadata={"data_selection_revisions": [revision]},
        evidence_completeness=retention.retain_run_outputs(
            test_user.id,
            {"__workflow__": {"definition": definition}},
            {},
        ),
        executed_at=datetime.now(timezone.utc),
    )
    test_session.add(run)
    await test_session.commit()

    run_response = await auth_client.get(f"/api/v1/runs/{run.id}?project_id={project.id}")
    assert run_response.status_code == 200, run_response.text
    assert run_response.json()["params_snapshot"]["data_1"]["target_authority"] == authority_dict

    report = await workflow_export.get_report_data(
        workflow.id,
        run_ids=str(run.id),
        session=test_session,
        current_user=test_user,
    )
    saved_source = next(node for node in report["runs"][0]["saved_definition"]["nodes"] if node["node_id"] == "data_1")
    report_revision = report["runs"][0]["selection_provenance"]["revisions"][0]
    assert saved_source["parameters"]["target_authority"] == authority_dict
    assert report_revision["selection"]["target_authority"] == authority_dict

    stale_authority = {**authority_dict, "source_digest": "0" * 64}
    refused = await auth_client.post(
        f"/api/v1/workflow-templates/{templates[0].id}/instantiate",
        json={
            "workflow_name": "Stale Breast Cancer PLS-DA",
            "project_id": project.id,
            "data_bindings": {
                "data_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "file_ids": [source_file["id"]],
                    "stage": "raw",
                    "target_authority": stale_authority,
                }
            },
        },
    )
    assert refused.status_code == 400, refused.text
    stale_workflow = await test_session.scalar(select(Workflow).where(Workflow.name == "Stale Breast Cancer PLS-DA"))
    assert stale_workflow is None


@pytest.mark.asyncio
async def test_synthetic_atmospheric_exposes_six_targets_and_binds_selected_responses(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
) -> None:
    expected_targets = [
        "Carbon dioxide",
        "Carbon monoxide",
        "Water",
        "Methane",
        "Nitrous oxide",
        "Nitrogen dioxide",
    ]
    pls = _production_template("pls_calibration", stored_slug="qualified_pls_calibration")
    nested = _production_template("nested_cv_validation", stored_slug="qualified_nested_cv_validation")
    project, experiment = await _project_with_experiment(
        test_session,
        test_user,
        project_name="Synthetic target qualification",
        experiment_name="Synthetic_atmospheric-6",
    )
    test_session.add_all([pls, nested])
    files = await import_reference_dataset(
        test_session,
        experiment.id,
        "synthetic",
        "Synthetic_atmospheric-6",
    )
    await test_session.commit()

    available = await auth_client.get(f"/api/v1/datasets/available?project_id={project.id}")
    assert available.status_code == 200, available.text
    summary = next(item for item in available.json()["experiments"] if item["id"] == experiment.id)
    assert summary["target_names"] == expected_targets
    assert summary["target_types"] == {name: "continuous" for name in expected_targets}
    assert summary["target_complete_rows"] == 50
    assert summary["selected_target"] == expected_targets[0]

    loaded = await load_project_dataset(
        test_session,
        user_id=test_user.id,
        experiment_id=experiment.id,
        stage="synthetic",
        file_ids=[files[0].id],
    )
    assert loaded.dataset.target_context is not None
    assert loaded.dataset.target_context.target_names == expected_targets
    ensure_type_registry_loaded()

    for template, selected_target in ((pls, "Carbon dioxide"), (nested, "Nitrogen dioxide")):
        authority = issue_target_authority(
            loaded.dataset,
            column=selected_target,
            target_type="continuous",
        ).canonical_dict()
        response = await auth_client.post(
            f"/api/v1/workflow-templates/{template.id}/instantiate",
            json={
                "workflow_name": f"{selected_target} · {template.name}",
                "project_id": project.id,
                "data_bindings": {
                    "data_1": {
                        "source": "experiment",
                        "experiment_id": experiment.id,
                        "file_ids": [files[0].id],
                        "stage": "synthetic",
                        "target_authority": authority,
                    }
                },
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        source = next(node for node in body["nodes"] if node["node_id"] == "data_1")
        assert source["parameters"]["target_authority"] == authority
        if template is pls:
            nodes = {node["node_id"]: node for node in body["nodes"]}
            assert nodes["model_1"]["parameters"]["target_names"] == [selected_target]
            assert nodes["eval_1"]["parameters"]["target_names"] == [selected_target]
        else:
            target_edges = {
                (edge["from_node_id"], edge["to_node_id"], edge["from_output"], edge["to_input"])
                for edge in body["edges"]
                if edge.get("from_output") == "target"
            }
            assert target_edges == {
                ("data_1", "nested_cv_1", "target", "y"),
                ("data_1", "nested_cv_2", "target", "y"),
            }
