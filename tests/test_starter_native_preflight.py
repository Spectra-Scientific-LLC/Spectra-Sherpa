"""The HTTP starter gate checks native targets and automatic PLS populations."""

import hashlib

import pytest
from sqlalchemy import func, select

from spectra_sherpa.app.api.v1.routes import workflow_templates as routes
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.types import ensure_type_registry_loaded
from tests.test_canonical_template_project_corpus import _bound_source, _template_record


@pytest.mark.asyncio
@pytest.mark.parametrize("group_column", [None, "batch"])
@pytest.mark.parametrize(
    "slug,rows",
    [
        ("pls_calibration", 5),
        ("pls_calibration", 20),
        ("classification_plsda", 20),
        ("knn_classification", 20),
        ("simca_classification", 20),
    ],
)
async def test_native_starter_population_is_checked_before_any_sheet_is_saved(
    auth_client, test_session, test_user, monkeypatch, tmp_path, slug, rows, group_column
):
    ensure_type_registry_loaded()
    monkeypatch.setattr(routes, "experiment_dir", lambda eid: tmp_path / str(eid))
    project = Project(user_id=test_user.id, name="Native starter qualification")
    template = WorkflowTemplate(**_template_record(slug))
    test_session.add_all([project, template])
    await test_session.flush()
    experiment, source_file = await _bound_source(
        session=test_session, user=test_user, project=project, node_id="data_1"
    )
    path = routes.experiment_dir(experiment.id) / source_file.file_path
    path.write_text("\n".join(path.read_text().splitlines()[: rows + 1]) + "\n")
    source_file.file_size_bytes = path.stat().st_size
    regression = slug == "pls_calibration"
    binding = {
        "source": "experiment",
        "experiment_id": experiment.id,
        "file_id": source_file.id,
        "stage": "raw",
        "target_authority": {
            "schema_version": "spectrasherpa-target-authority/1",
            "column": "Moisture" if regression else "target",
            "target_type": "continuous" if regression else "categorical",
            "units": None,
            "source_digest": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    }
    if group_column:
        binding["group_column"] = group_column
    await test_session.commit()
    project_id = project.id
    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={"workflow_name": "Native preview", "project_id": project.id, "data_bindings": {"data_1": binding}},
    )
    if rows == 5 or group_column:
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert "partition" in detail or "Automatic PLS selection needs" in detail or "Data Portfolio" in detail
        assert (
            await test_session.scalar(
                select(func.count()).select_from(Workflow).where(Workflow.project_id == project_id)
            )
            == 0
        )
    else:
        assert response.status_code == 201, response.text
        assert (
            await test_session.scalar(
                select(func.count()).select_from(Workflow).where(Workflow.project_id == project_id)
            )
            > 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["classification_plsda", "knn_classification", "simca_classification"])
async def test_real_wine_example_starter_admits_fresh_and_cached_native_targets(
    auth_client, test_session, test_user, slug
):
    ensure_type_registry_loaded()
    template = WorkflowTemplate(**_template_record(slug))
    project = Project(user_id=test_user.id, name="Bundled Wine starter qualification")
    test_session.add_all([template, project])
    await test_session.commit()
    bindings = []
    for attempt in range(2):
        response = await auth_client.post(
            f"/api/v1/workflow-templates/{template.id}/instantiate",
            json={"workflow_name": f"Wine qualification {attempt}", "project_id": project.id, "launch_mode": "example"},
        )
        assert response.status_code == 201, response.text
        source = next(node for node in response.json()["nodes"] if node["node_id"] == "data_1")
        assert source["node_type"] == "data.file_load"
        assert source["parameters"]["target_authority"]["target_type"] == "categorical"
        bindings.append(source["parameters"])
    assert bindings[0] == bindings[1], "Cached examples must retain the exact native source binding"
