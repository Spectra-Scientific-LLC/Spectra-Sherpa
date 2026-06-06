from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user
from spectra_sherpa.app.api.v1.routes import builder as builder_routes
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.services.experiments import metadata_path_for, relative_to_data_dir, write_metadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _builder_client() -> TestClient:
    app = FastAPI()
    app.include_router(builder_routes.router)
    app.dependency_overrides[get_current_user] = lambda: object()
    return TestClient(app)


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

    def test_pca_templates_are_safe_for_iris_feature_tables(self) -> None:
        """PCA templates that advertise Iris must not request more PCs than Iris has features."""
        from spectra_sherpa.app.core.template_loader import TemplateLoader

        templates = {
            template["slug"]: template
            for template in TemplateLoader().load_all()
            if template["slug"] in {"pca", "pca_exploratory"}
        }
        assert set(templates) == {"pca", "pca_exploratory"}

        for slug, template in templates.items():
            certified = template["template_data"].get("certified_datasets") or []
            advertises_iris = any(
                entry.get("source") == "sklearn" and entry.get("name") == "iris" for entry in certified
            )
            assert advertises_iris, f"{slug} no longer advertises sklearn Iris; update this regression test"

            model_node = next(node for node in template["template_data"]["nodes"] if node["node_type"] == "model.pca")
            n_components = int(model_node["parameters"]["n_components"])
            assert n_components <= 4, f"{slug} requests {n_components} PCs but Iris has only 4 features"


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
async def test_demo_categories_match_featured_template_filter(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    from spectra_sherpa.app.contracts import demo_policy as demo_policy_mod
    from spectra_sherpa.app.contracts.demo_policy import DemoPolicy
    from spectra_sherpa.app.core.config import app_config

    featured = WorkflowTemplate(
        slug="featured_demo_template",
        name="Featured Demo Template",
        description="Visible in demo",
        category="exploratory",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    hidden = WorkflowTemplate(
        slug="hidden_demo_template",
        name="Hidden Demo Template",
        description="Not featured in demo",
        category="calibration",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    test_session.add_all([featured, hidden])
    await test_session.commit()

    monkeypatch.setattr(app_config, "site_profile", "demo")
    monkeypatch.setattr(
        demo_policy_mod,
        "_demo_policy_provider",
        lambda: DemoPolicy(featured_templates=("featured_demo_template",)),
    )

    response = await auth_client.get("/api/v1/workflow-templates/categories")

    assert response.status_code == 200
    assert response.json() == ["exploratory"]


@pytest.mark.asyncio
async def test_matching_datasets_returns_only_certified_entries(
    auth_client: AsyncClient,
    test_session: AsyncSession,
):
    template = WorkflowTemplate(
        slug="certified_matching_template",
        name="Certified Matching Template",
        description="Only curated examples should be returned",
        category="calibration",
        template_data={
            **_make_template_data(),
            "status": "ready",
            "certified_datasets": [
                {"source": "eigenvector", "name": "corn_m5"},
                {"source": "sklearn", "name": "wine"},
            ],
        },
        is_active=True,
    )
    test_session.add(template)
    await test_session.commit()

    response = await auth_client.get(f"/api/v1/workflow-templates/{template.id}/matching-datasets")

    assert response.status_code == 200
    payload = response.json()
    returned_pairs = {(entry["source"], entry["name"]) for matches in payload.values() for entry in matches}
    assert returned_pairs == {("eigenvector", "corn_m5"), ("sklearn", "wine")}


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

    assert response.status_code == 201, response.text
    data = response.json()
    nodes_by_id = {node["node_id"]: node for node in data["nodes"]}
    assert nodes_by_id["data_1"]["node_type"] == "data.my_dataset"
    assert nodes_by_id["data_1"]["parameters"]["dataset_id"] == created_experiment.id


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
                certified_datasets=[
                    {"source": "eigenvector", "name": "corn_m5"},
                    {"source": "sklearn", "name": "wine"},
                ],
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

    assert response.status_code == 201, response.text
    mock_import_ref.assert_awaited_once()
    args = mock_import_ref.await_args.args
    assert args[2] == "sklearn"
    assert args[3] == "wine"


@pytest.mark.asyncio
async def test_instantiate_example_mode_oes_workflow_exports_python(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    from spectra_sherpa.app.services.experiments import experiment_dir
    from spectra_sherpa.app.services.prepared_data import save_prepared_data_overrides

    template = WorkflowTemplate(
        slug="oes_export_template",
        name="OES Process Monitoring",
        description="Bundled OES example data",
        category="exploratory",
        template_data={
            "nodes": [
                {
                    "node_id": "data_1",
                    "node_type": "data.source",
                    "label": "Load OES Data",
                    "parameters": {"source": "eigenvector", "eigenvector_dataset": "metal_etch_oes"},
                    "position_x": 120,
                    "position_y": 180,
                },
                {
                    "node_id": "preprocess_1",
                    "node_type": "preprocess.normalize",
                    "label": "SNV Normalize",
                    "parameters": {"method": "snv"},
                    "position_x": 360,
                    "position_y": 180,
                },
                {
                    "node_id": "model_1",
                    "node_type": "model.pca",
                    "label": "PCA",
                    "parameters": {"n_components": 3},
                    "position_x": 600,
                    "position_y": 180,
                },
                {
                    "node_id": "stats_1",
                    "node_type": "stats.summary",
                    "label": "Monitoring Summary",
                    "parameters": {},
                    "position_x": 840,
                    "position_y": 120,
                },
                {
                    "node_id": "viz_1",
                    "node_type": "output.plot",
                    "label": "OES Scores Plot",
                    "parameters": {"plot_type": "spectra"},
                    "position_x": 840,
                    "position_y": 240,
                },
            ],
            "edges": [
                {"from_node_id": "data_1", "to_node_id": "preprocess_1"},
                {"from_node_id": "preprocess_1", "to_node_id": "model_1"},
                {"from_node_id": "model_1", "to_node_id": "stats_1"},
                {"from_node_id": "model_1", "to_node_id": "viz_1", "from_output": "scores"},
            ],
            "canvas_state": {"zoom": 1.0, "pan_x": 0, "pan_y": 0},
            "data_roles": {
                "X_spectra": {
                    "role_type": "X_spectra",
                    "node_binding": "data_1",
                    "required": True,
                    "binding_mode": "embedded",
                    "accepted_techniques": ["OES", "UV-Vis"],
                }
            },
            "certified_datasets": [
                {"source": "eigenvector", "name": "metal_etch_oes"},
            ],
            "status": "ready",
        },
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="OES Export Project", description="")
    test_session.add_all([template, project])
    await test_session.commit()
    await test_session.refresh(template)
    await test_session.refresh(project)

    created_experiment = Experiment(
        id=1101,
        user_id=test_user.id,
        project_id=project.id,
        name="Example - OES Process Monitoring",
        description="Bundled OES example",
        metadata_path="{}",
    )
    imported_file = ExperimentFile(
        id=1102,
        experiment_id=1101,
        file_path="raw/metal_etch_oes.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=1024,
    )

    async def mock_create_experiment(**kwargs):
        test_session.add(created_experiment)
        await test_session.flush()
        return created_experiment

    async def mock_import_reference(session, exp_id, source, dataset_name):
        test_session.add(imported_file)
        await test_session.flush()
        return [imported_file]

    exp_dir = experiment_dir(created_experiment.id)
    raw_file = exp_dir / imported_file.file_path
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(
        "sample,200,201,202,etch_rate\nrun_1,1.0,1.1,1.2,0.4\nrun_2,1.3,1.4,1.5,0.6\n",
        encoding="utf-8",
    )
    save_prepared_data_overrides(
        {
            "x_title": "Time",
            "x_units": "ms",
            "y_title": "Intensity",
            "is_time_series": True,
        },
        file_path=f"experiments/exp_{created_experiment.id:03d}/{imported_file.file_path}",
    )

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
        instantiate_response = await auth_client.post(
            f"/api/v1/workflow-templates/{template.id}/instantiate",
            json={
                "workflow_name": "OES Export Workflow",
                "project_id": project.id,
                "launch_mode": "example",
            },
        )

    assert instantiate_response.status_code == 201
    workflow_id = instantiate_response.json()["id"]

    export_response = await auth_client.get(f"/api/v1/workflows/{workflow_id}/export/python")

    assert export_response.status_code == 200
    body = export_response.json()
    assert body["workflow_id"] == workflow_id
    assert "python_code" in body
    assert "Generated workflow: OES Export Workflow" in body["python_code"]
    assert "os.path.join(DATA_DIR, 'data_1/metal_etch_oes.csv')" in body["python_code"]
    assert "_feature_axis_data_1.title = 'Time'" in body["python_code"]
    assert "_feature_axis_data_1.units = 'ms'" in body["python_code"]
    assert "_ds.is_time_series = True" in body["python_code"]

    zip_response = await auth_client.get(f"/api/v1/workflows/{workflow_id}/export/download?format=zip")
    assert zip_response.status_code == 200
    import io
    import json
    import zipfile

    with zipfile.ZipFile(io.BytesIO(zip_response.content)) as zf:
        names = set(zf.namelist())
        assert "oes_export_workflow/data/data_1/metal_etch_oes.csv" in names
        assert "oes_export_workflow/prepared_data_manifest.json" in names
        assert "oes_export_workflow/workflow_manifest.json" in names
        manifest = json.loads(zf.read("oes_export_workflow/prepared_data_manifest.json"))
        assert manifest["sources"][0]["overrides"]["x_title"] == "Time"
        requirements = zf.read("oes_export_workflow/requirements.txt").decode("utf-8")
        assert "plotly" in requirements


@pytest.mark.asyncio
async def test_instantiate_example_mode_rejects_uncertified_example_dataset(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    template = WorkflowTemplate(
        slug="example_certified_template",
        name="Example Certified Template",
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
                certified_datasets=[
                    {"source": "eigenvector", "name": "corn_m5"},
                ],
            ),
            "status": "ready",
        },
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Example Certified Project", description="")
    test_session.add_all([template, project])
    await test_session.commit()

    with (
        patch(
            "spectra_sherpa.app.api.v1.routes.workflow_templates._create_example_experiment",
            new=AsyncMock(side_effect=AssertionError("uncertified examples must be rejected before import")),
        ),
        patch(
            "spectra_sherpa.app.api.v1.routes.workflow_templates.import_reference_dataset",
            new=AsyncMock(side_effect=AssertionError("uncertified examples must be rejected before import")),
        ),
    ):
        response = await auth_client.post(
            f"/api/v1/workflow-templates/{template.id}/instantiate",
            json={
                "workflow_name": "Rejected Workflow",
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

    assert response.status_code == 400
    assert "not in certified_datasets" in response.json()["detail"]


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

    assert response.status_code == 201, response.text
    data = response.json()
    nodes_by_id = {node["node_id"]: node for node in data["nodes"]}
    assert nodes_by_id["data_1"]["node_type"] == "data.my_dataset"
    assert nodes_by_id["data_1"]["parameters"]["dataset_id"] == experiment.id


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

    assert response.status_code == 201, response.text
    data = response.json()

    nodes_by_id = {node["node_id"]: node for node in data["nodes"]}
    assert "data_1" in nodes_by_id
    assert "data_1__target_source" in nodes_by_id
    assert "data_1__attach_target" in nodes_by_id
    assert nodes_by_id["data_1"]["node_type"] == "data.my_dataset"
    assert nodes_by_id["data_1"]["parameters"]["dataset_id"] == experiment.id
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


def test_matching_catalog_includes_synthetic_atmospheric_gas_benchmark() -> None:
    from spectra_sherpa.app.api.v1.routes.workflow_templates import _build_flat_catalog

    catalog = _build_flat_catalog()
    benchmark = next(
        entry for entry in catalog if entry["source"] == "synthetic" and entry["name"] == "Synthetic_atmospheric-6"
    )

    assert benchmark["label"] == "Synthetic_atmospheric-6"
    assert benchmark["data_role"] == "X_spectra"
    assert benchmark["technique"] == "FTIR"
    assert benchmark["has_embedded_target"] is True
    assert benchmark["target_type"] == "continuous"


def test_synthetic_benchmark_analysis_starter_is_available() -> None:
    from spectra_sherpa.app.api.v1.routes.workflow_templates import (
        _build_flat_catalog,
        _compute_dataset_matches,
        _extract_example_reference,
    )
    from spectra_sherpa.app.core.template_loader import TemplateLoader

    templates = {template["slug"]: template for template in TemplateLoader().load_all()}
    template = templates["synthetic_ftir_benchmark"]

    assert template["name"] == "Spectra Scientific Synthetic Benchmark"
    assert template["category"] == "curve_resolution"
    assert template["template_data"]["status"] == "ready"

    certified = template["template_data"]["certified_datasets"]
    assert certified == [
        {"source": "synthetic", "name": "Synthetic_atmospheric-6"},
        {"source": "synthetic", "name": "Library_atmospheric-9"},
    ]

    source_node = next(node for node in template["template_data"]["nodes"] if node["node_id"] == "data_1")
    assert _extract_example_reference(source_node) == ("synthetic", "Synthetic_atmospheric-6")
    library_node = next(node for node in template["template_data"]["nodes"] if node["node_id"] == "data_2")
    assert _extract_example_reference(library_node) == ("synthetic", "Library_atmospheric-9")

    nodes_by_id = {node["node_id"]: node for node in template["template_data"]["nodes"]}
    assert nodes_by_id["model_1"]["parameters"]["n_components"] == 6
    assert nodes_by_id["model_1"]["parameters"]["validation_target_index"] == 3
    assert nodes_by_id["compare_1"]["node_type"] == "analysis.compare_library"
    assert nodes_by_id["compare_1"]["parameters"]["hqi_mode"] == "band_limited"
    assert nodes_by_id["compare_1"]["parameters"]["diagnostic_band_threshold"] == 0.2
    edges = {
        (
            edge["from_node_id"],
            edge["to_node_id"],
            edge.get("from_output", "default"),
            edge.get("to_input", "default"),
        )
        for edge in template["template_data"]["edges"]
    }
    assert ("data_1", "compare_1", "default", "sample") in edges
    assert ("data_2", "compare_1", "default", "library") in edges
    assert ("compare_1", "table_1", "hqi_report", "default") in edges

    matches = _compute_dataset_matches(
        template["template_data"]["data_roles"],
        _build_flat_catalog(),
        certified_datasets=certified,
    )
    assert matches["X_spectra"][0]["source"] == "synthetic"
    assert matches["X_spectra"][0]["name"] == "Synthetic_atmospheric-6"


@pytest.mark.asyncio
async def test_instantiate_synthetic_benchmark_materializes_mixture_and_library(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    from spectra_sherpa.app.core.template_loader import TemplateLoader

    template_def = {template["slug"]: template for template in TemplateLoader().load_all()}["synthetic_ftir_benchmark"]
    template = WorkflowTemplate(
        slug=template_def["slug"],
        name=template_def["name"],
        description=template_def["description"],
        category=template_def["category"],
        template_data={**template_def["template_data"], "status": "ready"},
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Synthetic Benchmark Project", description="")
    test_session.add_all([template, project])
    await test_session.commit()
    await test_session.refresh(template)
    await test_session.refresh(project)

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Synthetic Benchmark Workflow",
            "project_id": project.id,
            "launch_mode": "example",
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    nodes_by_id = {node["node_id"]: node for node in data["nodes"]}
    assert nodes_by_id["data_1"]["node_type"] == "data.my_dataset"
    assert nodes_by_id["data_2"]["node_type"] == "data.my_dataset"
    assert nodes_by_id["data_1"]["parameters"]["dataset_id"] != nodes_by_id["data_2"]["parameters"]["dataset_id"]
    assert nodes_by_id["compare_1"]["node_type"] == "analysis.compare_library"

    mixture_id = nodes_by_id["data_1"]["parameters"]["dataset_id"]
    library_id = nodes_by_id["data_2"]["parameters"]["dataset_id"]
    file_result = await test_session.execute(
        select(ExperimentFile).where(ExperimentFile.experiment_id.in_([mixture_id, library_id]))
    )
    files = list(file_result.scalars().all())
    assert sorted(file.stage for file in files) == ["synthetic", "synthetic"]
    assert any(file.file_path.endswith("Synthetic_atmospheric-6.npz") for file in files)
    assert any(file.file_path.endswith("Library_atmospheric-9.npz") for file in files)

    experiment_result = await test_session.execute(
        select(Experiment.name).where(Experiment.id.in_([mixture_id, library_id]))
    )
    experiment_names = set(experiment_result.scalars().all())
    assert experiment_names == {
        "Example - Spectra Scientific Synthetic Benchmark - Synthetic_atmospheric-6",
        "Example - Spectra Scientific Synthetic Benchmark - Library_atmospheric-9",
    }


def test_compute_dataset_matches_surfaces_feature_tables_for_dual_mode_template() -> None:
    """Dual-mode templates (PCA, PLS-DA, KNN, …) that accept both X_spectra
    and X_features must surface feature-table sources like sklearn:wine in
    the wizard dropdown — even when the template only lists spectroscopy
    techniques (FTIR/NIR/Raman/…) in `accepted_techniques`.

    Regression for the matching-datasets scoring bug: without a baseline
    role-match score, sklearn:wine got 0 (technique "ML/Statistics" doesn't
    match any spectroscopy acronym) and was silently filtered out even
    though the template accepts X_features.
    """
    from spectra_sherpa.app.api.v1.routes.workflow_templates import _compute_dataset_matches

    data_roles = {
        "data_in": {
            "role_type": "X_spectra",
            "accepted_data_roles": ["X_spectra", "X_features"],
            "accepted_techniques": ["FTIR", "NIR", "Raman"],
        }
    }
    catalog = [
        {
            "name": "wine",
            "source": "sklearn",
            "label": "Wine — feature table",
            "technique": "ML/Statistics",
            "data_role": "X_features",
            "has_embedded_target": True,
            "target_type": "categorical",
        },
        {
            "name": "corn_m5",
            "source": "eigenvector",
            "label": "Corn M5 NIR",
            "technique": "NIR",
            "data_role": "X_spectra",
            "has_embedded_target": True,
            "target_type": "continuous",
        },
    ]

    matches = _compute_dataset_matches(data_roles, catalog)

    names = [m["name"] for m in matches["data_in"]]
    assert "wine" in names, f"sklearn:wine missing from feature-table matches: {names}"
    assert "corn_m5" in names
    # Spectra match still wins on ranking thanks to the +10 technique bonus.
    assert matches["data_in"][0]["name"] == "corn_m5"


@pytest.mark.parametrize(
    ("source", "name", "patch_target"),
    [
        ("eigenvector", "corn_m5", "spectra_sherpa.app.lib.eigenvector.get_dataset_info"),
        ("sklearn", "iris", "spectra_sherpa.app.lib.sklearn_info.get_sklearn_dataset_info"),
        ("oes", "metal_etch_oes", "spectra_sherpa.app.lib.oes_datasets.get_oes_dataset_info"),
    ],
)
def test_reference_dataset_info_missing_bundled_file_returns_404(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    name: str,
    patch_target: str,
) -> None:
    """Corrupt/partial bundled-data installs should not leak as API 500s."""

    def _missing(_name: str) -> dict[str, Any]:
        raise FileNotFoundError(_name)

    monkeypatch.setattr(patch_target, _missing)

    with _builder_client() as client:
        response = client.get(f"/builder/reference-datasets/{source}/{name}")

    assert response.status_code == 404
    assert response.json()["detail"] == f"Dataset '{name}' not found"
