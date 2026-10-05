"""Persistence proof for the complete ready New Analysis corpus."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.v1.routes import workflow_templates as workflow_template_routes
from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.services.dag import node_catalog_contract
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow
from spectra_sherpa.app.types import type_registry

_READY_TEMPLATE_SLUGS = tuple(
    sorted(
        template["slug"]
        for template in TemplateLoader().load_all()
        if template["template_data"].get("status") == "ready"
    )
)


def _template_record(slug: str) -> dict[str, object]:
    return next(template for template in TemplateLoader().load_all() if template["slug"] == slug)


async def _bound_source(
    *,
    session: AsyncSession,
    user: User,
    project: Project,
    node_id: str,
) -> tuple[Experiment, ExperimentFile]:
    experiment = Experiment(
        user_id=user.id,
        project_id=project.id,
        name=f"Corpus source {node_id}",
        description="",
        metadata_path="{}",
    )
    session.add(experiment)
    await session.flush()
    source_file = ExperimentFile(
        experiment_id=experiment.id,
        file_path=f"raw/{node_id}.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=64,
    )
    session.add(source_file)
    await session.flush()

    # Binding preflight admits immutable source bytes before workflow
    # persistence.  Keep this corpus test honest by materializing a small
    # native CSV with every target name used by the ready template catalog,
    # rather than relying on the retired database-only file stub.
    source_path = workflow_template_routes.experiment_dir(experiment.id) / source_file.file_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        "sample_id,100,200,300,Moisture,target,response,coefficient_matrix\n"
        "sample-1,1.0,2.0,3.0,10.0,class-a,0.1,0.25\n"
        "sample-2,1.5,2.5,3.5,11.0,class-b,0.2,0.75\n",
        encoding="utf-8",
    )
    source_file.file_size_bytes = source_path.stat().st_size
    return experiment, source_file


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", _READY_TEMPLATE_SLUGS)
async def test_ready_template_persists_its_exact_preflighted_analysis_dag(
    slug: str,
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Every advertised starter creates a real project sheet fit for Run."""

    # Persistence does not execute optional scientific dependencies. Exercise
    # every ready template independent of which extras happen to be installed
    # in this test environment; runtime rejection has a dedicated route test.
    monkeypatch.setattr(
        node_catalog_contract,
        "distribution_is_installed",
        lambda _distribution: True,
    )
    data_root = tmp_path / "data"
    monkeypatch.setattr(
        workflow_template_routes,
        "experiment_dir",
        lambda experiment_id: data_root / "experiments" / f"exp_{experiment_id:03d}",
    )

    async def _ordinary_separate_source(*_args: object, **_kwargs: object) -> bool:
        # Corpus bindings are generic native CSVs, not portable sample tables.
        # Exercise the ordinary separate-target path unless this case
        # explicitly represents the sample-table template below.
        return False

    monkeypatch.setattr(
        workflow_template_routes,
        "_is_portable_sample_table_binding",
        _ordinary_separate_source,
    )

    record = _template_record(slug)
    original_analysis_profile = workflow_template_routes.analysis_profile_from_dataset

    def _compatible_analysis_profile(dataset: object) -> dict[str, object]:
        profile = dict(original_analysis_profile(dataset))
        roles = record["template_data"].get("data_roles", {})
        if any(isinstance(role, dict) and role.get("is_time_series") is True for role in roles.values()):
            profile["ordered_samples"] = True
        if slug == "parafac_multiway":
            profile.update(primary_role="X_hsi", modality="hsi")
        if slug == "raman_processing":
            profile["technique"] = "Raman"
        return profile

    monkeypatch.setattr(
        workflow_template_routes,
        "analysis_profile_from_dataset",
        _compatible_analysis_profile,
    )
    template = WorkflowTemplate(**record)
    project = Project(user_id=test_user.id, name=f"Corpus {slug}", description="")
    test_session.add_all([template, project])
    await test_session.flush()

    template_data = template.template_data
    declared_nodes = {str(node["node_id"]): node for node in template_data["nodes"] if isinstance(node, dict)}
    roles = template_data.get("data_roles", {})
    required_source_ids = {
        str(role["node_binding"]) for role in roles.values() if isinstance(role, dict) and role.get("required", True)
    }
    separate_target_source_ids = {
        str(role["node_binding"])
        for role in roles.values()
        if isinstance(role, dict) and role.get("required", True) and role.get("binding_mode") == "separate_source"
    }
    data_bindings: dict[str, dict[str, object]] = {}
    for source_id in sorted(required_source_ids):
        source_node = declared_nodes[source_id]
        assert source_node["node_type"] == "data.file_load", f"{slug} role binds to non-source node {source_id}"
        experiment, source_file = await _bound_source(
            session=test_session,
            user=test_user,
            project=project,
            node_id=source_id,
        )
        binding: dict[str, object] = {
            "source": "experiment",
            "experiment_id": experiment.id,
            "file_id": source_file.id,
            "stage": "raw",
        }
        example = source_node.get("example_binding")
        if isinstance(example, dict) and example.get("selected_target"):
            source_path = workflow_template_routes.experiment_dir(experiment.id) / source_file.file_path
            binding["target_authority"] = {
                "schema_version": "spectrasherpa-target-authority/1",
                "column": example["selected_target"],
                "target_type": example["target_type"],
                "units": None,
                "source_digest": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            }
        if source_id in separate_target_source_ids:
            target_experiment, target_file = await _bound_source(
                session=test_session,
                user=test_user,
                project=project,
                node_id=f"{source_id}-target",
            )
            target_path = workflow_template_routes.experiment_dir(target_experiment.id) / target_file.file_path
            binding["target_binding"] = {
                "source": "experiment",
                "experiment_id": target_experiment.id,
                "file_id": target_file.id,
                "stage": "raw",
                "target_authority": {
                    "schema_version": "spectrasherpa-target-authority/1",
                    "column": "target",
                    "target_type": "continuous",
                    "units": None,
                    "source_digest": hashlib.sha256(target_path.read_bytes()).hexdigest(),
                },
            }
        data_bindings[source_id] = binding

    if slug == "supervised_data_preparation":

        async def _portable_sample_table(*_args: object, **_kwargs: object) -> bool:
            return True

        monkeypatch.setattr(
            workflow_template_routes,
            "_is_portable_sample_table_binding",
            _portable_sample_table,
        )

    await test_session.commit()
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": f"Canonical {slug}",
            "project_id": project.id,
            "data_bindings": data_bindings,
        },
    )
    assert response.status_code == 201, f"{slug}: {response.text}"

    workflows = tuple(
        (
            await test_session.scalars(
                select(Workflow)
                .where(Workflow.project_id == project.id)
                .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
                .order_by(Workflow.sheet_order)
            )
        ).all()
    )
    expected_sheet_count = 2 if template_data.get("canonical_project") else 1
    assert len(workflows) == expected_sheet_count

    analysis = workflows[0]
    assert analysis.purpose == "analysis"
    assert analysis.created_from_template_id == template.id
    assert analysis.created_from_template_version == "1"
    expected_node_types = {node_id: str(node["node_type"]) for node_id, node in declared_nodes.items()}
    expected_edges = {
        (
            str(edge["from_node_id"]),
            str(edge["to_node_id"]),
            str(edge.get("from_output", "default")),
            str(edge.get("to_input", "default")),
        )
        for edge in template_data["edges"]
    }
    portable_sample_table_sources = separate_target_source_ids if slug == "supervised_data_preparation" else set()
    for source_id in sorted(separate_target_source_ids):
        target_source_id = f"{source_id}__target_source"
        attach_target_id = f"{source_id}__attach_target"
        filter_samples_id = f"{source_id}__filter_samples"
        expected_node_types.update(
            {
                target_source_id: "data.file_load",
                attach_target_id: "data.attach_target",
            }
        )
        downstream_source_id = attach_target_id
        if source_id in portable_sample_table_sources:
            expected_node_types[filter_samples_id] = "data.filter_samples"
            downstream_source_id = filter_samples_id

        expected_edges = {
            (
                downstream_source_id if from_node_id == source_id and from_output == "default" else from_node_id,
                to_node_id,
                from_output,
                to_input,
            )
            for from_node_id, to_node_id, from_output, to_input in expected_edges
        }
        target_port = next(
            (
                str(role.get("connects_to_port") or "y")
                for role in roles.values()
                if isinstance(role, dict)
                and role.get("node_binding") == source_id
                and role.get("role_type") in {"Y_reference", "class_labels"}
            ),
            "y",
        )
        expected_edges.update(
            {
                (source_id, attach_target_id, "default", "X"),
                (target_source_id, attach_target_id, "target", target_port),
            }
        )
        if source_id in portable_sample_table_sources:
            expected_edges.add((target_source_id, attach_target_id, "sample_table", "sample_table"))
            expected_edges.add((attach_target_id, filter_samples_id, "default", "default"))
    assert {node.node_id: node.node_type for node in analysis.nodes} == expected_node_types
    assert {(edge.from_node_id, edge.to_node_id, edge.from_output, edge.to_input) for edge in analysis.edges} == (
        expected_edges
    )

    node_payload = [
        {
            "node_id": node.node_id,
            "node_type": node.node_type,
            "parameters": node.parameters,
        }
        for node in analysis.nodes
    ]
    edge_payload = [
        {
            "from_node_id": edge.from_node_id,
            "to_node_id": edge.to_node_id,
            "from_output": edge.from_output,
            "to_input": edge.to_input,
        }
        for edge in analysis.edges
    ]
    assert analysis.integrity_hash == compute_workflow_hash(node_payload, edge_payload)

    preflight = preflight_workflow(
        (
            WorkflowNode(
                node_id=node.node_id,
                node_type=node.node_type,
                parameters=dict(node.parameters),
            )
            for node in analysis.nodes
        ),
        (
            WorkflowEdge(
                from_node=edge.from_node_id,
                to_node=edge.to_node_id,
                from_output=edge.from_output,
                to_input=edge.to_input,
            )
            for edge in analysis.edges
        ),
        require_runtime_dependencies=False,
    )
    assert preflight.is_valid, (
        slug,
        [(issue.code, issue.message) for issue in preflight.issues if issue.level == "error"],
    )

    if expected_sheet_count == 2:
        assert workflows[1].purpose == "managed_candidate_authority"
