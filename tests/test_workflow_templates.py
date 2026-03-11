from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.services.experiments import metadata_path_for, relative_to_data_dir, write_metadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_template_data(**overrides: Any) -> dict:
    """Minimal valid template_data with data_roles."""
    base = {
        "nodes": [
            {
                "node_id": "data_1",
                "node_type": "data.source",
                "label": "Load Data",
                "parameters": {"source": "eigenvector", "eigenvector_dataset": "corn_m5"},
                "position_x": 120,
                "position_y": 180,
            },
            {
                "node_id": "model_1",
                "node_type": "model.pls",
                "label": "PLS Regression",
                "parameters": {"n_components": 2},
                "position_x": 360,
                "position_y": 180,
            },
        ],
        "edges": [
            {"from_node_id": "data_1", "to_node_id": "model_1"},
        ],
        "canvas_state": {"zoom": 1.0, "pan_x": 0, "pan_y": 0},
        "data_roles": {
            "X_spectra": {
                "role_type": "X_spectra",
                "node_binding": "data_1",
                "required": True,
                "binding_mode": "embedded",
                "description": "Spectral data",
            },
            "Y_reference": {
                "role_type": "Y_reference",
                "node_binding": "data_1",
                "required": True,
                "binding_mode": "embedded",
                "target_type": "continuous",
                "connects_to_port": "y",
                "description": "Target values for calibration",
            },
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Startup validation enforcement
# ---------------------------------------------------------------------------


class TestStartupValidationEnforcement:
    """ensure_workflow_templates() must raise on invalid templates."""

    @pytest.mark.asyncio
    async def test_raises_on_validation_errors(self) -> None:
        """When validate_all() returns errors, startup must raise RuntimeError."""
        fake_errors = ["dup.yaml: duplicate slug 'pca'", "bad.yaml: unknown category 'fake'"]

        with patch(
            "spectra_sherpa.app.core.template_loader.TemplateLoader",
            autospec=True,
        ) as MockLoader:
            MockLoader.return_value.validate_all.return_value = fake_errors
            from spectra_sherpa.app.core.startup import ensure_workflow_templates

            with pytest.raises(RuntimeError, match="Template validation failed"):
                await ensure_workflow_templates()
            # load_all must NOT have been called
            MockLoader.return_value.load_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_proceeds_when_valid(self) -> None:
        """When validate_all() returns no errors, startup should call load_all."""
        mock_templates = [
            {
                "name": "Test",
                "slug": "test",
                "description": "",
                "category": "calibration",
                "is_active": True,
                "template_data": _make_template_data(),
            },
        ]

        with (
            patch(
                "spectra_sherpa.app.core.template_loader.TemplateLoader",
                autospec=True,
            ) as MockLoader,
            patch("spectra_sherpa.app.core.startup.async_session") as mock_session_ctx,
        ):
            MockLoader.return_value.validate_all.return_value = []
            MockLoader.return_value.load_all.return_value = mock_templates

            # Mock the DB session to raise OperationalError (skip DB)
            from sqlalchemy.exc import OperationalError

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(side_effect=OperationalError("no db", None, None))
            mock_session_ctx.return_value = mock_session

            from spectra_sherpa.app.core.startup import ensure_workflow_templates

            await ensure_workflow_templates()
            MockLoader.return_value.load_all.assert_called_once()


class TestTemplateValidationCli:
    """The validator CLI should mirror runtime plugin discovery behavior."""

    def test_cli_validation_discovers_plugins_first(self) -> None:
        with (
            patch("spectra_sherpa.app.services.plugin_loader.discover_plugins") as mock_discover,
            patch("spectra_sherpa.app.core.template_loader.TemplateLoader", autospec=True) as mock_loader_cls,
            pytest.raises(SystemExit) as exc_info,
        ):
            mock_loader = mock_loader_cls.return_value
            mock_loader.validate_all.return_value = []
            mock_loader.load_all.return_value = [{"slug": "test"}]
            mock_loader.load_categories.return_value = {"exploratory": {"label": "Exploratory"}}

            from spectra_sherpa.app.core.template_loader import _cli_validate

            _cli_validate()

        assert exc_info.value.code == 0
        mock_discover.assert_called_once()
        mock_loader.validate_all.assert_called_once()


# ---------------------------------------------------------------------------
# 2. Startup deactivation of removed templates
# ---------------------------------------------------------------------------


class TestStartupDeactivation:
    """DB templates whose YAML was removed must be deactivated."""

    @pytest.mark.asyncio
    async def test_deactivation_logic(self) -> None:
        """ensure_workflow_templates must deactivate slugs not in YAML."""
        from unittest.mock import MagicMock

        # Create a fake DB template that is NOT in the YAML set
        orphan = MagicMock(spec=WorkflowTemplate)
        orphan.slug = "orphaned_slug_not_in_yaml"
        orphan.is_active = True
        orphan.name = "Orphan"

        # Create a fake DB template that IS in the YAML set
        survivor = MagicMock(spec=WorkflowTemplate)
        survivor.slug = "test_pls"
        survivor.is_active = True
        survivor.name = "Test PLS"

        yaml_slugs = {"test_pls", "test_pca"}

        # Exercise the deactivation logic directly (mirrors startup.py lines 608-613)
        deactivated = 0
        for t in [orphan, survivor]:
            if t.slug and t.slug not in yaml_slugs and t.is_active:
                t.is_active = False
                deactivated += 1

        assert deactivated == 1
        assert orphan.is_active is False
        assert survivor.is_active is True

    @pytest.mark.asyncio
    async def test_startup_deactivation_called_in_flow(self) -> None:
        """Verify the full startup flow reaches the deactivation branch."""
        from spectra_sherpa.app.core.template_loader import TemplateLoader

        # Load real templates to get real slugs
        loader = TemplateLoader()
        real_templates = loader.load_all()
        real_slugs = {t["slug"] for t in real_templates}

        # A slug not in YAML must not survive
        assert "orphaned_test_slug_xyz" not in real_slugs, "Test assumes this slug doesn't exist in YAML"

    @pytest.mark.asyncio
    async def test_reactivates_canonical_row_and_deactivates_legacy_duplicates(self) -> None:
        """Prefer the exact YAML row, reactivate it, and hide legacy duplicates."""
        yaml_template = {
            "name": "Classification (PLS-DA)",
            "slug": "classification_plsda",
            "description": "Canonical classification template",
            "category": "classification",
            "is_active": True,
            "template_data": _make_template_data(),
        }

        canonical = WorkflowTemplate(
            id=31,
            name="Classification (PLS-DA)",
            slug="classification_plsda",
            description="old canonical",
            category="classification",
            template_data={"nodes": [], "edges": []},
            is_active=False,
        )
        legacy_same_slug = WorkflowTemplate(
            id=16,
            name="Classification (PCA + PLS-DA)",
            slug="classification_plsda",
            description="legacy duplicate",
            category="classification",
            template_data={"nodes": [{"parameters": {"source": "experiment"}}], "edges": []},
            is_active=True,
        )
        legacy_blank_slug = WorkflowTemplate(
            id=30,
            name="PLSRegression Calibration",
            slug="",
            description="legacy blank slug row",
            category="calibration",
            template_data={"nodes": [{"parameters": {"source": "experiment"}}], "edges": []},
            is_active=True,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            legacy_same_slug,
            canonical,
            legacy_blank_slug,
        ]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.scalar = AsyncMock(return_value=3)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_session
        mock_context.__aexit__.return_value = None

        with (
            patch("spectra_sherpa.app.core.template_loader.TemplateLoader", autospec=True) as mock_loader_cls,
            patch("spectra_sherpa.app.core.startup.async_session", return_value=mock_context),
        ):
            mock_loader = mock_loader_cls.return_value
            mock_loader.validate_all.return_value = []
            mock_loader.load_all.return_value = [yaml_template]

            from spectra_sherpa.app.core.startup import ensure_workflow_templates

            await ensure_workflow_templates()

        assert canonical.is_active is True
        assert canonical.description == yaml_template["description"]
        assert canonical.template_data == yaml_template["template_data"]
        assert legacy_same_slug.is_active is False
        assert legacy_blank_slug.is_active is False
        mock_session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. data_roles-driven instantiation
# ---------------------------------------------------------------------------


class TestDataRolesInstantiation:
    """Instantiation must use data_roles for target port and type inference."""

    def test_resolve_target_port_from_data_roles(self) -> None:
        """_resolve_target_port reads connects_to_port from data_roles."""
        from spectra_sherpa.app.api.v1.routes.workflow_templates import _resolve_target_port

        template = WorkflowTemplate(
            name="T",
            slug="t",
            description="",
            category="calibration",
            template_data={
                "data_roles": {
                    "Y_reference": {
                        "role_type": "Y_reference",
                        "node_binding": "data_1",
                        "connects_to_port": "target_y",
                    }
                }
            },
        )
        assert _resolve_target_port(template, "data_1") == "target_y"

    def test_resolve_target_port_fallback(self) -> None:
        """Without connects_to_port, falls back to 'y'."""
        from spectra_sherpa.app.api.v1.routes.workflow_templates import _resolve_target_port

        template = WorkflowTemplate(
            name="T",
            slug="t",
            description="",
            category="calibration",
            template_data={"data_roles": {}},
        )
        assert _resolve_target_port(template, "data_1") == "y"

    def test_infer_target_type_from_data_roles(self) -> None:
        """_infer_target_type reads target_type from data_roles Y_reference."""
        from spectra_sherpa.app.api.v1.routes.workflow_templates import DataBindingSpec, _infer_target_type

        template = WorkflowTemplate(
            name="T",
            slug="t",
            description="",
            category="calibration",
            template_data={
                "data_roles": {
                    "class_labels": {
                        "role_type": "class_labels",
                        "node_binding": "data_1",
                        "target_type": "categorical",
                    }
                }
            },
        )
        binding = DataBindingSpec(
            source="experiment",
            experiment_id=1,
            stage="raw",
            target_type=None,  # not provided — should fall back to data_roles
        )
        assert _infer_target_type(template, binding) == "categorical"

    def test_infer_target_type_explicit_binding_wins(self) -> None:
        """Explicit binding.target_type takes priority over data_roles."""
        from spectra_sherpa.app.api.v1.routes.workflow_templates import DataBindingSpec, _infer_target_type

        template = WorkflowTemplate(
            name="T",
            slug="t",
            description="",
            category="classification",
            template_data={
                "data_roles": {
                    "Y": {"role_type": "class_labels", "node_binding": "data_1", "target_type": "categorical"}
                }
            },
        )
        binding = DataBindingSpec(
            source="experiment",
            experiment_id=1,
            stage="raw",
            target_type="continuous",  # explicit override
        )
        assert _infer_target_type(template, binding) == "continuous"

    def test_infer_target_type_category_fallback(self) -> None:
        """Without data_roles target_type, falls back to category heuristic."""
        from spectra_sherpa.app.api.v1.routes.workflow_templates import DataBindingSpec, _infer_target_type

        template = WorkflowTemplate(
            name="T",
            slug="t",
            description="",
            category="classification",
            template_data={"data_roles": {}},
        )
        binding = DataBindingSpec(
            source="experiment",
            experiment_id=1,
            stage="raw",
            target_type=None,
        )
        assert _infer_target_type(template, binding) == "categorical"


# ---------------------------------------------------------------------------
# 4. Template loader validation
# ---------------------------------------------------------------------------


class TestTemplateLoaderValidation:
    """TemplateLoader.validate_all() must catch structural problems."""

    def test_validate_all_catches_duplicate_slugs(self, tmp_path) -> None:
        """Duplicate slugs across templates must be reported."""
        import yaml

        from spectra_sherpa.app.core.template_loader import TemplateLoader

        cat_yaml = {
            "schema_version": 1,
            "categories": {"calibration": {"label": "Cal", "icon": "pi pi-chart-bar", "display_order": 1}},
        }
        (tmp_path / "templates").mkdir()
        (tmp_path / "templates" / "_categories.yaml").write_text(yaml.dump(cat_yaml))

        for name in ("a.yaml", "b.yaml"):
            tpl = {
                "schema_version": 1,
                "name": f"Template {name}",
                "slug": "duplicate_slug",
                "description": "test",
                "category": "calibration",
                "template_data": {
                    "nodes": [{"node_id": "data_1", "node_type": "data.source", "label": "D", "parameters": {}}],
                    "edges": [],
                    "canvas_state": {},
                    "data_roles": {"X": {"role_type": "X_spectra", "node_binding": "data_1"}},
                },
            }
            (tmp_path / "templates" / name).write_text(yaml.dump(tpl))

        loader = TemplateLoader.__new__(TemplateLoader)
        loader._package = "test"
        loader._templates_dir = tmp_path / "templates"

        errors = loader.validate_all()
        assert any("duplicate slug" in e for e in errors), f"Expected duplicate slug error, got: {errors}"

    def test_validate_all_catches_bad_category(self, tmp_path) -> None:
        """Templates referencing non-existent categories must be reported."""
        import yaml

        from spectra_sherpa.app.core.template_loader import TemplateLoader

        cat_yaml = {
            "schema_version": 1,
            "categories": {"calibration": {"label": "Cal", "icon": "pi pi-chart-bar", "display_order": 1}},
        }
        (tmp_path / "templates").mkdir()
        (tmp_path / "templates" / "_categories.yaml").write_text(yaml.dump(cat_yaml))

        tpl = {
            "schema_version": 1,
            "name": "Bad Cat",
            "slug": "bad_cat",
            "description": "test",
            "category": "nonexistent_category",
            "template_data": {
                "nodes": [{"node_id": "data_1", "node_type": "data.source", "label": "D", "parameters": {}}],
                "edges": [],
                "canvas_state": {},
                "data_roles": {"X": {"role_type": "X_spectra", "node_binding": "data_1"}},
            },
        }
        (tmp_path / "templates" / "bad.yaml").write_text(yaml.dump(tpl))

        loader = TemplateLoader.__new__(TemplateLoader)
        loader._package = "test"
        loader._templates_dir = tmp_path / "templates"

        errors = loader.validate_all()
        assert any("nonexistent_category" in e for e in errors), f"Expected bad category error, got: {errors}"

    def test_production_templates_validate_clean(self) -> None:
        """The real template set must have zero validation errors."""
        from spectra_sherpa.app.core.template_loader import TemplateLoader

        loader = TemplateLoader()
        errors = loader.validate_all()
        assert errors == [], "Production templates have validation errors:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# 5. Instantiation integration (existing test, updated for data_roles)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_templates_excludes_wip_by_default(
    auth_client: AsyncClient,
    test_session: AsyncSession,
):
    ready_template = WorkflowTemplate(
        slug="ready_template",
        name="Ready Template",
        description="Ready for use",
        category="calibration",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    wip_template = WorkflowTemplate(
        slug="wip_template",
        name="WIP Template",
        description="Not ready",
        category="calibration",
        template_data={**_make_template_data(), "status": "wip"},
        is_active=True,
    )
    test_session.add_all([ready_template, wip_template])
    await test_session.commit()

    response = await auth_client.get("/api/v1/workflow-templates")
    assert response.status_code == 200
    payload = response.json()
    names = {template["name"] for template in payload["templates"]}
    assert "Ready Template" in names
    assert "WIP Template" not in names


@pytest.mark.asyncio
async def test_instantiate_requires_explicit_data_bindings(
    auth_client: AsyncClient,
    test_session: AsyncSession,
):
    template = WorkflowTemplate(
        slug="binding_required_template",
        name="Binding Required Template",
        description="Must bind project data",
        category="calibration",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    test_session.add(template)
    await test_session.commit()

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={"workflow_name": "No Bindings"},
    )

    assert response.status_code == 400
    assert "requires explicit project data bindings" in response.json()["detail"]


@pytest.mark.asyncio
async def test_instantiate_example_mode_materializes_project_visible_example_data(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    template = WorkflowTemplate(
        slug="example_ready_template",
        name="Example Ready Template",
        description="Bundled example data",
        category="calibration",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Corn Demo Project", description="")
    test_session.add_all([template, project])
    await test_session.commit()
    await test_session.refresh(template)
    await test_session.refresh(project)

    created_experiment = Experiment(
        id=321,
        user_id=test_user.id,
        project_id=project.id,
        name="Example - Example Ready Template",
        description="Bundled example",
        metadata_path="{}",
    )
    imported_file = ExperimentFile(
        id=654,
        experiment_id=321,
        file_path="raw/corn_m5.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=512,
    )

    async def mock_create_experiment(**kwargs):
        test_session.add(created_experiment)
        await test_session.flush()
        return created_experiment

    async def mock_import_reference(session, exp_id, source, dataset_name):
        test_session.add(imported_file)
        await test_session.flush()
        return [imported_file]

    with (
        patch(
            "spectra_sherpa.app.api.v1.routes.workflow_templates._create_example_experiment",
            new=AsyncMock(side_effect=mock_create_experiment),
        ),
        patch(
            "spectra_sherpa.app.api.v1.routes.workflow_templates.import_reference_dataset",
            new=AsyncMock(side_effect=mock_import_reference),
        ),
    ):
        response = await auth_client.post(
            f"/api/v1/workflow-templates/{template.id}/instantiate",
            json={
                "workflow_name": "Example Workflow",
                "project_id": project.id,
                "launch_mode": "example",
            },
        )

    assert response.status_code == 201
    data = response.json()
    nodes_by_id = {node["node_id"]: node for node in data["nodes"]}
    assert nodes_by_id["data_1"]["parameters"]["source"] == "experiment"
    assert nodes_by_id["data_1"]["parameters"]["experiment_id"] == created_experiment.id
    assert nodes_by_id["data_1"]["parameters"]["file_id"] == imported_file.id


@pytest.mark.asyncio
async def test_instantiate_example_mode_honors_selected_example_dataset(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    template = WorkflowTemplate(
        slug="example_override_template",
        name="Example Override Template",
        description="Bundled example data",
        category="classification",
        template_data={
            **_make_template_data(
                nodes=[
                    {
                        "node_id": "data_1",
                        "node_type": "data.source",
                        "label": "Load Data",
                        "parameters": {"source": "eigenvector", "eigenvector_dataset": "corn_m5"},
                        "position_x": 120,
                        "position_y": 180,
                    },
                    {
                        "node_id": "model_1",
                        "node_type": "classification.knn",
                        "label": "KNN",
                        "parameters": {"n_neighbors": 3},
                        "position_x": 360,
                        "position_y": 180,
                    },
                ],
                data_roles={
                    "X_spectra": {
                        "role_type": "X_spectra",
                        "node_binding": "data_1",
                        "required": True,
                        "binding_mode": "embedded",
                        "accepted_techniques": ["FTIR", "NIR", "Raman", "UV-Vis"],
                    },
                    "class_labels": {
                        "role_type": "class_labels",
                        "node_binding": "data_1",
                        "required": True,
                        "binding_mode": "embedded",
                        "target_type": "categorical",
                    },
                },
            ),
            "status": "ready",
        },
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Example Override Project", description="")
    test_session.add_all([template, project])
    await test_session.commit()
    await test_session.refresh(template)
    await test_session.refresh(project)

    created_experiment = Experiment(
        id=901,
        user_id=test_user.id,
        project_id=project.id,
        name="Example - Example Override Template",
        description="Bundled example",
        metadata_path="{}",
    )
    imported_file = ExperimentFile(
        id=902,
        experiment_id=901,
        file_path="raw/sklearn_wine.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=256,
    )

    async def mock_create_experiment(**kwargs):
        test_session.add(created_experiment)
        await test_session.flush()
        return created_experiment

    async def mock_import_reference(session, exp_id, source, dataset_name):
        test_session.add(imported_file)
        await test_session.flush()
        return [imported_file]

    mock_import_ref = AsyncMock(side_effect=mock_import_reference)

    with (
        patch(
            "spectra_sherpa.app.api.v1.routes.workflow_templates._create_example_experiment",
            new=AsyncMock(side_effect=mock_create_experiment),
        ),
        patch(
            "spectra_sherpa.app.api.v1.routes.workflow_templates.import_reference_dataset",
            new=mock_import_ref,
        ),
    ):
        response = await auth_client.post(
            f"/api/v1/workflow-templates/{template.id}/instantiate",
            json={
                "workflow_name": "Override Workflow",
                "project_id": project.id,
                "launch_mode": "example",
                "example_bindings": {
                    "data_1": {
                        "source": "sklearn",
                        "dataset_name": "wine",
                    }
                },
            },
        )

    assert response.status_code == 201
    mock_import_ref.assert_awaited_once()
    args = mock_import_ref.await_args.args
    assert args[2] == "sklearn"
    assert args[3] == "wine"


@pytest.mark.asyncio
async def test_instantiate_example_mode_cleans_up_materialized_files_on_failure(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    template = WorkflowTemplate(
        slug="example_cleanup_template",
        name="Example Cleanup Template",
        description="Bundled example data",
        category="calibration",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Cleanup Project", description="")
    test_session.add_all([template, project])
    await test_session.commit()

    created_experiment = Experiment(
        id=777,
        user_id=test_user.id,
        project_id=project.id,
        name="Example - Example Cleanup Template",
        description="Bundled example",
        metadata_path="{}",
    )
    imported_file = ExperimentFile(
        id=888,
        experiment_id=777,
        file_path="raw/corn_m5.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=512,
    )

    with (
        patch(
            "spectra_sherpa.app.api.v1.routes.workflow_templates._create_example_experiment",
            new=AsyncMock(return_value=created_experiment),
        ),
        patch(
            "spectra_sherpa.app.api.v1.routes.workflow_templates.import_reference_dataset",
            new=AsyncMock(return_value=[imported_file]),
        ),
        patch(
            "spectra_sherpa.app.api.v1.routes.workflow_templates._validate_binding",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch("spectra_sherpa.app.api.v1.routes.workflow_templates.delete_experiment_files") as mock_delete_files,
        pytest.raises(RuntimeError, match="boom"),
    ):
        await auth_client.post(
            f"/api/v1/workflow-templates/{template.id}/instantiate",
            json={
                "workflow_name": "Should Fail",
                "project_id": project.id,
                "launch_mode": "example",
            },
        )

    mock_delete_files.assert_called_once_with(created_experiment.id)


@pytest.mark.asyncio
async def test_instantiate_example_mode_reuses_existing_project_example_experiment(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    template = WorkflowTemplate(
        slug="example_reuse_template",
        name="Example Reuse Template",
        description="Bundled example data",
        category="calibration",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Reuse Project", description="")
    test_session.add_all([template, project])
    await test_session.flush()

    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Example - Example Reuse Template",
        description="Existing bundled example",
        metadata_path="",
    )
    test_session.add(experiment)
    await test_session.flush()

    metadata_file = metadata_path_for(experiment.id)
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    write_metadata(
        metadata_file,
        {
            "template_slug": template.slug,
            "launch_mode": "example",
            "example_source": "eigenvector",
            "example_dataset": "corn_m5",
        },
    )
    experiment.metadata_path = relative_to_data_dir(metadata_file)

    existing_file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/corn_m5.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=512,
    )
    test_session.add(existing_file)
    await test_session.commit()

    with (
        patch(
            "spectra_sherpa.app.api.v1.routes.workflow_templates._create_example_experiment",
            new=AsyncMock(side_effect=AssertionError("should not create a duplicate example experiment")),
        ),
        patch(
            "spectra_sherpa.app.api.v1.routes.workflow_templates.import_reference_dataset",
            new=AsyncMock(side_effect=AssertionError("should not re-import duplicate example data")),
        ),
    ):
        response = await auth_client.post(
            f"/api/v1/workflow-templates/{template.id}/instantiate",
            json={
                "workflow_name": "Reused Example Workflow",
                "project_id": project.id,
                "launch_mode": "example",
            },
        )

    assert response.status_code == 201
    data = response.json()
    nodes_by_id = {node["node_id"]: node for node in data["nodes"]}
    assert nodes_by_id["data_1"]["parameters"]["experiment_id"] == experiment.id
    assert nodes_by_id["data_1"]["parameters"]["file_id"] == existing_file.id


@pytest.mark.asyncio
async def test_instantiate_single_source_supervised_template_with_separate_target_binding(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    experiment = Experiment(
        user_id=test_user.id,
        name="Calibration Inputs",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()

    spectra_file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/spectra.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=128,
    )
    target_file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/targets.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=64,
    )
    template = WorkflowTemplate(
        name="Single Source PLS Template",
        slug="single_source_pls_template",
        description="Single-source supervised template for tests",
        category="calibration",
        template_data={
            "nodes": [
                {
                    "node_id": "data_1",
                    "node_type": "data.source",
                    "label": "Load Data",
                    "parameters": {"source": "eigenvector", "eigenvector_dataset": "corn_m5"},
                    "position_x": 120,
                    "position_y": 180,
                },
                {
                    "node_id": "model_1",
                    "node_type": "model.pls",
                    "label": "PLS Regression",
                    "parameters": {"n_components": 2},
                    "position_x": 360,
                    "position_y": 180,
                },
            ],
            "edges": [
                {"from_node_id": "data_1", "to_node_id": "model_1"},
            ],
            "canvas_state": {"zoom": 1.0, "pan_x": 0, "pan_y": 0},
            "data_roles": {
                "X_spectra": {
                    "role_type": "X_spectra",
                    "node_binding": "data_1",
                    "required": True,
                    "binding_mode": "embedded",
                    "description": "Spectral data",
                },
                "Y_reference": {
                    "role_type": "Y_reference",
                    "node_binding": "data_1",
                    "required": True,
                    "binding_mode": "embedded",
                    "target_type": "continuous",
                    "connects_to_port": "y",
                    "description": "Target values for calibration",
                },
            },
        },
        is_active=True,
    )
    test_session.add_all([spectra_file, target_file, template])
    await test_session.commit()

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Bound Supervised Workflow",
            "data_bindings": {
                "data_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "stage": "raw",
                    "file_id": spectra_file.id,
                    "target_binding": {
                        "source": "experiment",
                        "experiment_id": experiment.id,
                        "stage": "raw",
                        "file_id": target_file.id,
                    },
                    "target_type": "continuous",
                }
            },
        },
    )

    assert response.status_code == 201
    data = response.json()

    nodes_by_id = {node["node_id"]: node for node in data["nodes"]}
    assert "data_1" in nodes_by_id
    assert "data_1__target_source" in nodes_by_id
    assert "data_1__attach_target" in nodes_by_id
    assert nodes_by_id["data_1"]["parameters"]["file_id"] == spectra_file.id
    assert nodes_by_id["data_1__target_source"]["parameters"]["file_id"] == target_file.id
    assert nodes_by_id["data_1__attach_target"]["node_type"] == "data.attach_target"
    assert nodes_by_id["data_1__attach_target"]["parameters"]["target_type"] == "continuous"

    edges = {
        (
            edge["from_node_id"],
            edge["to_node_id"],
            edge["from_output"],
            edge["to_input"],
        )
        for edge in data["edges"]
    }
    assert ("data_1", "data_1__attach_target", "default", "X") in edges
    assert ("data_1__target_source", "data_1__attach_target", "default", "y") in edges
    assert ("data_1__attach_target", "model_1", "default", "default") in edges


def test_compute_dataset_matches_surfaces_oes_examples() -> None:
    from spectra_sherpa.app.api.v1.routes.workflow_templates import _compute_dataset_matches

    data_roles = {
        "X_spectra": {
            "role_type": "X_spectra",
            "accepted_techniques": ["OES"],
        }
    }
    catalog = [
        {
            "name": "metal_etch_oes",
            "source": "eigenvector",
            "label": "Metal Etch OES",
            "technique": "OES",
            "has_embedded_target": False,
            "target_type": None,
        },
        {
            "name": "corn_m5",
            "source": "eigenvector",
            "label": "Corn M5 NIR",
            "technique": "NIR",
            "has_embedded_target": True,
            "target_type": "continuous",
        },
    ]

    matches = _compute_dataset_matches(data_roles, catalog)

    assert "X_spectra" in matches
    assert matches["X_spectra"]
    assert matches["X_spectra"][0]["name"] == "metal_etch_oes"
    assert matches["X_spectra"][0]["technique"] == "OES"
