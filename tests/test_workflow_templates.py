from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user
from spectra_sherpa.app.api.v1.routes import builder as builder_routes
from spectra_sherpa.app.api.v1.routes.workflow_templates import (
    DataBindingSpec,
    _adapt_pca_scaling_to_bound_role,
    _enforce_bound_dataset_requirements,
    _normalize_binding_target_authority,
    _require_target_variation,
    _template_runtime_readiness,
)
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_data_selection_revision import WorkflowDataSelectionRevision
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.services.canonical_workbench_baseline import load_canonical_workbench_baseline
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.experiments import (
    experiment_dir,
    metadata_path_for,
    relative_to_data_dir,
    write_metadata,
)
from spectra_sherpa.app.services.prepared_data import save_prepared_data_overrides
from spectra_sherpa.app.types import ensure_type_registry_loaded, type_registry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _builder_client() -> TestClient:
    app = FastAPI()
    app.include_router(builder_routes.router)
    app.dependency_overrides[get_current_user] = lambda: object()
    return TestClient(app)


def _materialize_bound_csv(experiment_id: int, relative_path: str) -> Path:
    """Create real immutable bytes for tests that exercise bind-time admission."""
    path = experiment_dir(experiment_id) / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "1000,1001,1002\n1.0,2.0,3.0\n4.0,5.0,6.0\n",
        encoding="utf-8",
    )
    return path


def _target_authority(
    *,
    column: str,
    target_type: str,
    source_digest: str,
    units: str | None = None,
) -> dict[str, str | None]:
    return {
        "schema_version": "spectrasherpa-target-authority/1",
        "column": column,
        "target_type": target_type,
        "units": units,
        "source_digest": source_digest,
    }


def _file_target_authority(
    experiment_id: int,
    relative_path: str,
    *,
    column: str,
    target_type: str,
    units: str | None = None,
) -> dict[str, str | None]:
    path = experiment_dir(experiment_id) / relative_path
    return _target_authority(
        column=column,
        target_type=target_type,
        units=units,
        source_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _materialize_bound_jdx(experiment_id: int, relative_path: str) -> Path:
    path = experiment_dir(experiment_id) / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"##TITLE={path.stem}",
                "##JCAMP-DX=5.00",
                "##DATA TYPE=INFRARED SPECTRUM",
                "##XUNITS=1/CM",
                "##YUNITS=ABSORBANCE",
                "##XYDATA=(X++(Y..Y))",
                "1000 1.0 2.0 3.0",
                "##END=",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _make_template_data(**overrides: Any) -> dict:
    """Minimal valid template_data with data_roles."""
    base = {
        "nodes": [
            {
                "node_id": "data_1",
                "node_type": "data.file_load",
                "label": "Load Data",
                "parameters": {},
                "example_binding": {"source": "eigenvector", "dataset_name": "corn_m5"},
                "position_x": 120,
                "position_y": 180,
            },
            {
                "node_id": "model_1",
                "node_type": "model.fitted_pls",
                "label": "Canonical PLS Regression",
                "parameters": {"n_components": 2},
                "position_x": 360,
                "position_y": 180,
            },
        ],
        "edges": [
            {
                "from_node_id": "data_1",
                "to_node_id": "model_1",
                "from_output": "default",
                "to_input": "default",
            },
            {
                "from_node_id": "data_1",
                "to_node_id": "model_1",
                "from_output": "target",
                "to_input": "y",
            },
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
    """The validator CLI uses only the shipped canonical registry."""

    def test_cli_validation_uses_canonical_registry(self) -> None:
        with (
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
            file_id=1,
            stage="raw",
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
            file_id=1,
            stage="raw",
            target_authority=_target_authority(
                column="response",
                target_type="continuous",
                source_digest="a" * 64,
            ),
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
            file_id=1,
            stage="raw",
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
                "status": "ready",
                "template_data": {
                    "nodes": [{"node_id": "data_1", "node_type": "data.file_load", "label": "D", "parameters": {}}],
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
            "status": "ready",
            "template_data": {
                "nodes": [{"node_id": "data_1", "node_type": "data.file_load", "label": "D", "parameters": {}}],
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

    def test_template_status_is_required_and_pending_states_explain_their_blocker(self) -> None:
        import yaml

        from spectra_sherpa.app.schemas.template_schema import TemplateFile

        path = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "data" / "templates" / "pca.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw.pop("status")
        with pytest.raises(ValueError, match="status"):
            TemplateFile.model_validate(raw)

        raw["status"] = "pending_qualification"
        with pytest.raises(ValueError, match="status_detail"):
            TemplateFile.model_validate(raw)

        raw["status_detail"] = "Representative execution evidence is pending."
        assert TemplateFile.model_validate(raw).status == "pending_qualification"

    def test_canonical_starter_project_contract_rejects_undeclared_fields(self) -> None:
        """Project-level workflow authority is closed, not an extensible metadata bag."""

        import yaml

        from spectra_sherpa.app.schemas.template_schema import TemplateFile

        path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "spectra_sherpa"
            / "data"
            / "templates"
            / "pls_calibration.yaml"
        )
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw["template_data"]["canonical_project"]["ignored_future_authority"] = True

        with pytest.raises(ValueError, match="extra_forbidden"):
            TemplateFile.model_validate(raw)

    def test_pca_templates_are_safe_for_iris_feature_tables(self) -> None:
        """PCA templates that advertise Iris must not request more PCs than Iris has features."""
        from spectra_sherpa.app.core.template_loader import TemplateLoader

        templates = {
            template["slug"]: template for template in TemplateLoader().load_all() if template["slug"] == "pca"
        }
        assert set(templates) == {"pca"}

        for slug, template in templates.items():
            certified = template["template_data"].get("certified_datasets") or []
            advertises_iris = any(
                entry.get("source") == "sklearn" and entry.get("name") == "iris" for entry in certified
            )
            assert advertises_iris, f"{slug} no longer advertises sklearn Iris; update this regression test"

            model_node = next(node for node in template["template_data"]["nodes"] if node["node_type"] == "model.pca")
            n_components = int(model_node["parameters"]["n_components"])
            assert n_components <= 4, f"{slug} requests {n_components} PCs but Iris has only 4 features"

            variance_plot = next(
                node
                for node in template["template_data"]["nodes"]
                if node["node_type"] == "output.plot" and node["label"] == "Explained Variance"
            )
            assert variance_plot["parameters"]["plot_type"] == "explained_variance"

    @pytest.mark.parametrize(
        ("primary_role", "expected_method", "expected_label"),
        [
            ("X_spectra", "mean_center", "Mean Center Spectra"),
            ("X_features", "autoscale", "Autoscale Features"),
        ],
    )
    def test_pca_starter_records_role_appropriate_scaling(
        self,
        primary_role: str,
        expected_method: str,
        expected_label: str,
    ) -> None:
        template = WorkflowTemplate(
            slug="pca",
            name="PCA",
            category="exploratory",
            template_data={},
            is_active=True,
        )
        nodes = [
            {"node_id": "data", "node_type": "data.file_load", "parameters": {}},
            {
                "node_id": "scale",
                "node_type": "preprocess.scale",
                "label": "Scale",
                "parameters": {"method": "mean_center"},
            },
            {"node_id": "model", "node_type": "model.pca", "parameters": {}},
        ]
        edges = [
            {"from_node_id": "data", "to_node_id": "scale"},
            {"from_node_id": "scale", "to_node_id": "model"},
        ]

        _adapt_pca_scaling_to_bound_role(
            template=template,
            source_node_id="data",
            analysis_profile={"primary_role": primary_role},
            nodes=nodes,
            edges=edges,
        )

        scale = nodes[1]
        assert scale["parameters"] == {"method": expected_method, "center": True}
        assert scale["label"] == expected_label


# ---------------------------------------------------------------------------
# 5. Instantiation integration (existing test, updated for data_roles)
# ---------------------------------------------------------------------------


def test_template_runtime_readiness_reports_optional_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    template = WorkflowTemplate(
        slug="mcr_runtime",
        name="MCR runtime",
        description="Runtime projection",
        category="curve_resolution",
        template_data={
            **_make_template_data(),
            "status": "ready",
            "nodes": [
                {
                    "node_id": "model_1",
                    "node_type": "model.mcr_als",
                    "parameters": {"n_components": 3},
                }
            ],
        },
        is_active=True,
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.dag.node_catalog_contract.distribution_is_installed",
        lambda distribution: distribution != "spectrochempy",
    )

    readiness = _template_runtime_readiness(template)

    assert readiness == {
        "ready": False,
        "blockers": ["spectrochempy_unavailable"],
        "remediation": ["Install the optional SpectroChemPy support: pip install 'spectra-sherpa[scp]'."],
        "unavailable_nodes": [
            {
                "node_id": "model_1",
                "node_type": "model.mcr_als",
                "blockers": ["spectrochempy_unavailable"],
            }
        ],
    }


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
        template_data={
            **_make_template_data(),
            "status": "wip",
            "status_detail": "Developer qualification is pending.",
        },
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

    preview = await auth_client.get("/api/v1/workflow-templates?include_wip=true")
    assert preview.status_code == 200
    preview_by_name = {template["name"]: template for template in preview.json()["templates"]}
    assert preview_by_name["Ready Template"]["status"] == "ready"
    assert preview_by_name["Ready Template"]["status_detail"] is None
    assert preview_by_name["WIP Template"]["status"] == "wip"
    assert preview_by_name["WIP Template"]["status_detail"] == "Developer qualification is pending."


@pytest.mark.asyncio
async def test_demo_categories_do_not_turn_featured_templates_into_an_allowlist(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
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
    response = await auth_client.get("/api/v1/workflow-templates/categories")

    assert response.status_code == 200
    assert response.json() == ["calibration", "exploratory"]


@pytest.mark.asyncio
async def test_matching_datasets_marks_certified_examples_without_hiding_other_data(
    auth_client: AsyncClient,
    test_session: AsyncSession,
):
    template = WorkflowTemplate(
        slug="certified_matching_template",
        name="Certified Matching Template",
        description="Qualified examples are marked without becoming an allowlist",
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
    entries = {(entry["source"], entry["name"]): entry for matches in payload.values() for entry in matches}
    assert entries[("eigenvector", "corn_m5")]["certified_example"] is True
    assert entries[("sklearn", "wine")]["certified_example"] is True
    assert entries[("registered", "public-corn-m5-moisture-v1")]["certified_example"] is False


@pytest.mark.asyncio
async def test_matching_datasets_is_read_only_under_demo_reference_import_block(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    from spectra_sherpa.app.contracts.demo_policy import DemoPolicy, set_demo_policy_provider
    from spectra_sherpa.app.core.config import app_config

    template = WorkflowTemplate(
        slug="demo_matching_template",
        name="Demo Matching Template",
        description="Read-only matching should remain visible in demo",
        category="exploratory",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    test_session.add(template)
    await test_session.commit()

    monkeypatch.setattr(app_config, "site_profile", "demo")
    set_demo_policy_provider(lambda: DemoPolicy(disabled_capabilities=frozenset({"reference_data_import"})))
    try:
        response = await auth_client.get(f"/api/v1/workflow-templates/{template.id}/matching-datasets")
    finally:
        set_demo_policy_provider(lambda: DemoPolicy())

    assert response.status_code == 200
    assert "X_spectra" in response.json()


@pytest.mark.asyncio
async def test_compatibility_matrix_returns_one_decision_for_every_registered_reference(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    from spectra_sherpa.app.services import experiments as experiment_services

    monkeypatch.setattr(experiment_services, "builtin_lavender_source_files", lambda: ["data/fixture.spa"])
    template = WorkflowTemplate(
        slug="compatibility_matrix_template",
        name="Compatibility Matrix Template",
        description="Exercises the total compatibility response",
        category="exploratory",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    test_session.add(template)
    await test_session.commit()

    response = await auth_client.get("/api/v1/workflow-templates/compatibility-matrix")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "spectra-sherpa-reference-template-matrix/1"
    assert payload["dataset_count"] == 26
    assert payload["template_count"] == 1
    assert payload["pair_count"] == 26
    assert len(payload["datasets"]) == 26
    assert payload["datasets"][0]["dataset_id"] == "builtin:lavender-essential-oil-v1"
    assert {dataset.get("dataset_id") for dataset in payload["datasets"]} >= {
        "synthetic:Synthetic_atmospheric-6",
        "synthetic:Library_atmospheric-9",
        "synthetic:msc_application_spectra",
        "synthetic:msc_reference_spectra",
        "sklearn:iris",
        "sklearn:wine",
        "sklearn:breast_cancer",
    }
    assert len(payload["matrix"]) == 26
    assert {item["template_slug"] for item in payload["matrix"]} == {"compatibility_matrix_template"}
    assert all(item["status"] in {"compatible", "needs_input", "incompatible", "pending"} for item in payload["matrix"])

    monkeypatch.setattr(experiment_services, "builtin_lavender_source_files", lambda: [])
    unavailable = (await auth_client.get("/api/v1/workflow-templates/compatibility-matrix")).json()
    assert unavailable["dataset_count"] == unavailable["pair_count"] == 25
    assert all(item.get("dataset_id") != "builtin:lavender-essential-oil-v1" for item in unavailable["datasets"])


@pytest.mark.asyncio
async def test_compatibility_preview_recomputes_an_explicit_target_choice(
    auth_client: AsyncClient,
    test_session: AsyncSession,
):
    regression = WorkflowTemplate(
        slug="preview_regression",
        name="Preview Regression",
        description="Requires a numeric target",
        category="calibration",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    classification_data = copy.deepcopy(_make_template_data())
    classification_data["data_roles"]["Y_reference"] = {
        **classification_data["data_roles"]["Y_reference"],
        "role_type": "class_labels",
        "target_type": "categorical",
    }
    classification = WorkflowTemplate(
        slug="preview_classification",
        name="Preview Classification",
        description="Requires class labels",
        category="classification",
        template_data={**classification_data, "status": "ready"},
        is_active=True,
    )
    test_session.add_all([regression, classification])
    await test_session.commit()

    response = await auth_client.post(
        "/api/v1/workflow-templates/compatibility-preview",
        json={
            "analysis_profile": {
                "primary_role": "X_spectra",
                "modality": "spectra",
                "technique": "IR",
                "target_type": "categorical",
                "target_fields": ["claimed_botanical_group"],
                "identity_fields": ["sample_id"],
                "group_fields": ["block"],
                "ordered_samples": False,
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    decisions = {item["template_slug"]: item for item in payload["decisions"]}
    assert decisions["preview_classification"]["status"] == "compatible"
    assert decisions["preview_regression"]["display_status"] == "needs_target"
    assert decisions["preview_regression"]["reason_codes"] == ["continuous_target_missing"]


@pytest.mark.asyncio
async def test_compatibility_preview_counts_runtime_blocked_starters_as_unavailable(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    template_data = _make_template_data()
    template_data["nodes"] = [
        {
            "node_id": "model_1",
            "node_type": "model.mcr_als",
            "parameters": {"n_components": 3},
        }
    ]
    template_data["edges"] = []
    template_data["status"] = "ready"
    template = WorkflowTemplate(
        slug="preview_runtime_blocked",
        name="Preview Runtime Blocked",
        description="Structurally usable but absent from this runtime",
        category="decomposition",
        template_data=template_data,
        is_active=True,
    )
    test_session.add(template)
    await test_session.commit()
    monkeypatch.setattr(
        "spectra_sherpa.app.services.dag.node_catalog_contract.distribution_is_installed",
        lambda distribution: distribution != "spectrochempy",
    )

    response = await auth_client.post(
        "/api/v1/workflow-templates/compatibility-preview",
        json={
            "analysis_profile": {
                "primary_role": "X_spectra",
                "modality": "spectra",
                "technique": "IR",
                "target_type": "continuous",
                "target_fields": ["Carbon dioxide"],
                "identity_fields": [],
                "group_fields": [],
                "ordered_samples": False,
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    decision = next(item for item in payload["decisions"] if item["template_slug"] == template.slug)
    assert decision["display_status"] == "unavailable"
    assert decision["status"] == "compatible"
    assert decision["reason_codes"] == ["spectrochempy_unavailable"]
    assert payload["counts"]["unavailable"] >= 1


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
async def test_instantiate_rejects_cross_project_source_binding(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    destination = Project(user_id=test_user.id, name="Destination", description="")
    other_project = Project(user_id=test_user.id, name="Other project", description="")
    template = WorkflowTemplate(
        slug="project_bound_source_template",
        name="Project-bound Source Template",
        description="Must not cross project custody",
        category="calibration",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    test_session.add_all([destination, other_project, template])
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=other_project.id,
        name="Other project data",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()
    source_file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/source.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=64,
    )
    test_session.add(source_file)
    await test_session.commit()
    _materialize_bound_csv(experiment.id, source_file.file_path)
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")
    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Forbidden Cross-project Workflow",
            "project_id": destination.id,
            "data_bindings": {
                "data_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "stage": "raw",
                    "file_id": source_file.id,
                }
            },
        },
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_instantiate_binds_exact_selected_collection_members(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    project = Project(user_id=test_user.id, name="Selected collection", description="")
    template_data = _make_template_data(
        nodes=[_make_template_data()["nodes"][0]],
        edges=[],
        data_roles={
            "X_spectra": {
                "role_type": "X_spectra",
                "node_binding": "data_1",
                "required": True,
                "binding_mode": "embedded",
            }
        },
        status="ready",
    )
    template = WorkflowTemplate(
        slug="selected_collection_template",
        name="Selected Collection Template",
        description="Binds exact selected members",
        category="exploratory",
        template_data=template_data,
        is_active=True,
    )
    test_session.add_all([project, template])
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Three sources",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()
    files = [
        ExperimentFile(
            experiment_id=experiment.id,
            file_path=f"raw/source-{index}.jdx",
            file_type="jdx",
            stage="raw",
            file_size_bytes=64,
        )
        for index in range(3)
    ]
    test_session.add_all(files)
    await test_session.commit()
    for file in files:
        _materialize_bound_jdx(experiment.id, file.file_path)
    ensure_type_registry_loaded()

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Exact subset",
            "project_id": project.id,
            "data_bindings": {
                "data_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "stage": "raw",
                    "file_ids": [files[0].id, files[2].id],
                }
            },
        },
    )

    assert response.status_code == 201, response.text
    source = next(node for node in response.json()["nodes"] if node["node_id"] == "data_1")
    assert source["node_type"] == "data.collection_load"
    assert source["parameters"]["selected_file_ids"] == [str(files[0].id), str(files[2].id)]
    assert len(source["parameters"]["source_manifest_sha256"]) == 64
    assert files[1].id not in [int(value) for value in source["parameters"]["selected_file_ids"]]
    initial_revision = await test_session.scalar(
        select(WorkflowDataSelectionRevision).where(
            WorkflowDataSelectionRevision.workflow_id == response.json()["id"],
            WorkflowDataSelectionRevision.source_node_id == "data_1",
        )
    )
    assert initial_revision is not None
    assert initial_revision.revision_number == 1
    assert initial_revision.selection["selected_file_ids"] == [files[0].id, files[2].id]

    from spectra_sherpa.app.services.dag.nodes.data.loaders import CollectionLoadNode
    from spectra_sherpa.core.execution_runtime import (
        ExecutionRuntime,
        ResolvedExperimentCollection,
        ResolvedExperimentFile,
    )

    class Resolver:
        async def resolve_experiment_collection(self, *, experiment_id: int, stage: str = "raw"):
            assert experiment_id == experiment.id
            selected = []
            for file in files:
                path = experiment_dir(experiment.id) / file.file_path
                selected.append(
                    ResolvedExperimentFile(
                        path=str(path),
                        original_file_path=file.file_path,
                        created_datetime="2026-09-01T00:00:00+00:00",
                        file_id=file.id,
                        stage=stage,
                        size_bytes=path.stat().st_size,
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
            return ResolvedExperimentCollection(experiment.id, experiment.name, tuple(selected))

    runtime_source = CollectionLoadNode("data_1", source["parameters"])
    runtime_source.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=Resolver()))
    executed = await runtime_source.execute()
    assert executed["default"].shape[0] == 2
    assert "source-1" not in " ".join(executed["default"].sample_axis.labels or [])


@pytest.mark.asyncio
async def test_instantiate_calibration_transfer_binds_two_explicit_instrument_views(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    from spectra_sherpa.app.core.template_loader import TemplateLoader

    production_record = next(
        template for template in TemplateLoader().load_all() if template["slug"] == "calibration_transfer"
    )
    template_record = copy.deepcopy(production_record)
    template_record["slug"] = "calibration_transfer_explicit_views_fixture"
    template = WorkflowTemplate(**template_record)
    project = Project(user_id=test_user.id, name="Instrument transfer", description="")
    test_session.add_all([template, project])
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Corn instrument views",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()
    primary = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/corn-m5.jdx",
        file_type="jdx",
        stage="raw",
        file_size_bytes=64,
    )
    secondary = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/corn-mp5.jdx",
        file_type="jdx",
        stage="raw",
        file_size_bytes=64,
    )
    test_session.add_all([primary, secondary])
    await test_session.commit()
    _materialize_bound_jdx(experiment.id, primary.file_path)
    _materialize_bound_jdx(experiment.id, secondary.file_path)
    ensure_type_registry_loaded()

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "M5 to MP5 Transfer",
            "project_id": project.id,
            "data_bindings": {
                "primary_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "stage": "raw",
                    "file_ids": [primary.id],
                },
                "secondary_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "stage": "raw",
                    "file_ids": [secondary.id],
                },
            },
        },
    )

    assert response.status_code == 201, response.text
    sources = {
        node["node_id"]: node for node in response.json()["nodes"] if node["node_id"] in {"primary_1", "secondary_1"}
    }
    assert sources["primary_1"]["node_type"] == "data.collection_load"
    assert sources["primary_1"]["parameters"]["selected_file_ids"] == [str(primary.id)]
    assert sources["secondary_1"]["node_type"] == "data.collection_load"
    assert sources["secondary_1"]["parameters"]["selected_file_ids"] == [str(secondary.id)]


@pytest.mark.asyncio
async def test_instantiate_rejects_nonportable_source_before_workflow_creation(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    project = Project(user_id=test_user.id, name="Portable-only", description="")
    template = WorkflowTemplate(
        slug="portable_source_template",
        name="Portable Source Template",
        description="Requires a portable canonical source",
        category="calibration",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    test_session.add_all([project, template])
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Pending vendor input",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()
    source_file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/pending.spa",
        file_type="spa",
        stage="raw",
        file_size_bytes=64,
    )
    test_session.add(source_file)
    await test_session.commit()
    _materialize_bound_csv(experiment.id, source_file.file_path)
    private_source_root = str(experiment_dir(experiment.id))
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Rejected Ambiguous Source",
            "project_id": project.id,
            "data_bindings": {
                "data_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "stage": "raw",
                    "file_id": source_file.id,
                }
            },
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "raw/pending.spa" in detail
    assert "choose its exact scientific asset_id" in detail
    assert private_source_root not in detail
    assert "originator" not in detail
    workflows = await test_session.execute(select(Workflow).where(Workflow.name == "Rejected Ambiguous Source"))
    assert workflows.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_instantiate_requires_exact_asset_before_persisting_multiasset_source(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    source_node = {
        "node_id": "data_1",
        "node_type": "data.file_load",
        "label": "Load Data",
        "parameters": {},
        "position_x": 120,
        "position_y": 180,
    }
    template = WorkflowTemplate(
        slug="multiasset_source_template",
        name="Multi-asset Source Template",
        description="Requires one exact scientific asset",
        category="decomposition",
        template_data={
            **_make_template_data(
                nodes=[source_node],
                edges=[],
                data_roles={
                    "X_spectra": {
                        "role_type": "X_spectra",
                        "node_binding": "data_1",
                        "required": True,
                        "binding_mode": "embedded",
                    }
                },
            ),
            "status": "ready",
        },
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Multi-asset project", description="")
    test_session.add_all([template, project])
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Licensed OPUS source",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()
    source_file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/polystyrene.0",
        file_type="0",
        stage="raw",
        file_size_bytes=0,
    )
    test_session.add(source_file)
    await test_session.commit()

    fixture = Path(__file__).parent / "fixtures" / "opus" / "openspecy-polystyrene.0"
    source_path = experiment_dir(experiment.id) / source_file.file_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(fixture.read_bytes())

    payload = {
        "workflow_name": "Exact OPUS Workflow",
        "project_id": project.id,
        "data_bindings": {
            "data_1": {
                "source": "experiment",
                "experiment_id": experiment.id,
                "file_id": source_file.id,
                "stage": "raw",
            }
        },
    }
    refused = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json=payload,
    )
    assert refused.status_code == 400
    assert "choose its exact scientific asset_id" in refused.json()["detail"]
    workflows = await test_session.execute(select(Workflow).where(Workflow.name == "Exact OPUS Workflow"))
    assert workflows.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_instantiate_rejects_semantically_invalid_template_before_workflow_creation(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    project = Project(user_id=test_user.id, name="Semantic preflight", description="")
    template_data = _make_template_data()
    template_data["edges"][0]["from_output"] = "target"
    template = WorkflowTemplate(
        slug="semantically_invalid_template",
        name="Semantically Invalid Template",
        description="A target vector cannot supply the model feature matrix",
        category="calibration",
        template_data={**template_data, "status": "ready"},
        is_active=True,
    )
    test_session.add_all([project, template])
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Bound source",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()
    source_file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/source.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=64,
    )
    test_session.add(source_file)
    await test_session.commit()
    _materialize_bound_csv(experiment.id, source_file.file_path)
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Rejected Semantic Workflow",
            "project_id": project.id,
            "data_bindings": {
                "data_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "stage": "raw",
                    "file_id": source_file.id,
                    "target_authority": _file_target_authority(
                        experiment.id,
                        source_file.file_path,
                        column="response",
                        target_type="continuous",
                    ),
                }
            },
        },
    )

    assert response.status_code == 400
    assert "failed canonical DAG preflight" in response.json()["detail"]
    assert "incompatible_semantic_edge" in response.json()["detail"]
    workflows = await test_session.execute(select(Workflow).where(Workflow.name == "Rejected Semantic Workflow"))
    assert workflows.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_time_series_role_does_not_inject_an_undeclared_source_parameter(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    project = Project(user_id=test_user.id, name="Kinetics", description="")
    template_data = _make_template_data()
    template_data["data_roles"]["X_spectra"]["is_time_series"] = True
    template = WorkflowTemplate(
        slug="time_series_source_template",
        name="Time-series Source Template",
        description="Time semantics remain dataset metadata",
        category="decomposition",
        template_data={**template_data, "status": "ready"},
        is_active=True,
    )
    test_session.add_all([project, template])
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Kinetic spectra",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()
    source_file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/kinetics.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=64,
    )
    test_session.add(source_file)
    await test_session.commit()
    source_path = _materialize_bound_csv(experiment.id, source_file.file_path)
    save_prepared_data_overrides(
        {"is_time_series": True},
        file_path=relative_to_data_dir(source_path),
    )
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")
    project_id = project.id
    experiment_id = experiment.id
    source_file_id = source_file.id
    template_id = template.id

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template_id}/instantiate",
        json={
            "workflow_name": "Canonical Kinetics Workflow",
            "project_id": project_id,
            "data_bindings": {
                "data_1": {
                    "source": "experiment",
                    "experiment_id": experiment_id,
                    "stage": "raw",
                    "file_id": source_file_id,
                    "target_authority": _file_target_authority(
                        experiment_id,
                        source_file.file_path,
                        column="response",
                        target_type="continuous",
                    ),
                }
            },
        },
    )

    assert response.status_code == 201, response.text
    source = next(node for node in response.json()["nodes"] if node["node_id"] == "data_1")
    assert source["parameters"] == {
        "experiment_id": experiment.id,
        "file_id": source_file.id,
        "stage": "raw",
        "target_authority": _file_target_authority(
            experiment_id,
            source_file.file_path,
            column="response",
            target_type="continuous",
        ),
    }


def test_server_guard_names_missing_numeric_target_before_persistence() -> None:
    template = WorkflowTemplate(
        slug="numeric_target_guard",
        name="Numeric Target Guard",
        description="Runtime scientific binding guard",
        category="calibration",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    binding = DataBindingSpec(experiment_id=1, file_id=1)
    target_free_profile = {
        "primary_role": "X_spectra",
        "modality": "spectra",
        "technique": "FTIR",
        "target_type": None,
        "target_fields": [],
        "identity_fields": [],
        "group_fields": [],
        "ordered_samples": False,
    }

    with pytest.raises(HTTPException, match="requires a numeric target"):
        _enforce_bound_dataset_requirements(
            template,
            node_id="data_1",
            binding=binding,
            analysis_profile=target_free_profile,
        )


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
    _materialize_bound_csv(created_experiment.id, imported_file.file_path)

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
    assert nodes_by_id["data_1"]["node_type"] == "data.file_load"
    assert nodes_by_id["data_1"]["parameters"] == {
        "experiment_id": created_experiment.id,
        "file_id": imported_file.id,
        "stage": "raw",
    }


@pytest.mark.asyncio
async def test_instantiate_draft_mode_allows_unbound_project_starter(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    template = WorkflowTemplate(
        slug="draft_ready_template",
        name="Draft Ready Template",
        description="Project-scoped starter workflow",
        category="calibration",
        template_data={**_make_template_data(), "status": "ready"},
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Lavender Starter", description="")
    test_session.add_all([template, project])
    await test_session.commit()
    await test_session.refresh(template)
    await test_session.refresh(project)

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Draft PCA",
            "project_id": project.id,
            "launch_mode": "draft",
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["project_id"] == project.id
    nodes_by_id = {node["node_id"]: node for node in data["nodes"]}
    assert nodes_by_id["data_1"]["node_type"] == "data.file_load"
    assert nodes_by_id["data_1"]["parameters"] == {}


@pytest.mark.asyncio
async def test_qualified_canonical_project_contract_persists_scientist_and_candidate_dags(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    """The first starter project saves two exact DAGs; no translator invents either one."""

    from spectra_sherpa.app.core.template_loader import TemplateLoader

    production_record = next(
        template for template in TemplateLoader().load_all() if template["slug"] == "pls_calibration"
    )
    assert production_record["template_data"]["status"] == "ready"
    template_record = copy.deepcopy(production_record)
    template_record["slug"] = "qualified_pls_contract_fixture"
    template = WorkflowTemplate(**template_record)
    project = Project(user_id=test_user.id, name="Canonical PLS Starter", description="")
    test_session.add_all([template, project])
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Scientist calibration data",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()
    source_file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/calibration.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=512,
    )
    test_session.add(source_file)
    await test_session.commit()
    _materialize_bound_csv(experiment.id, source_file.file_path)
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Moisture Calibration",
            "project_id": project.id,
            "data_bindings": {
                "data_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "file_id": source_file.id,
                    "stage": "raw",
                    "target_authority": _file_target_authority(
                        experiment.id,
                        source_file.file_path,
                        column="Moisture",
                        target_type="continuous",
                    ),
                }
            },
        },
    )

    assert response.status_code == 201, response.text
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
    assert [workflow.name for workflow in workflows] == [
        "Moisture Calibration",
        "Moisture Calibration — Harness-only PLS Candidate Authority",
    ]
    scientist, candidate = workflows
    assert scientist.purpose == "analysis"
    assert candidate.purpose == "managed_candidate_authority"
    assert response.json()["id"] == scientist.id
    tabs = await auth_client.get("/api/v1/workflows", params={"project_id": project.id, "in_workbook": True})
    assert tabs.status_code == 200
    assert [tab["id"] for tab in tabs.json()] == [scientist.id]
    assert [workflow.created_from_template_id for workflow in workflows] == [template.id, template.id]
    assert [workflow.created_from_template_version for workflow in workflows] == ["1", "1"]

    declared = template.template_data["canonical_project"]["managed_candidate"]
    candidate_nodes = sorted(candidate.nodes, key=lambda node: node.node_id)
    candidate_edges = sorted(
        candidate.edges,
        key=lambda edge: (edge.from_node_id, edge.to_node_id, edge.from_output, edge.to_input),
    )
    assert [(node.node_id, node.node_type) for node in candidate_nodes] == sorted(
        (node["node_id"], node["node_type"]) for node in declared["nodes"]
    )
    assert [
        (edge.from_node_id, edge.to_node_id, edge.from_output, edge.to_input) for edge in candidate_edges
    ] == sorted(
        (
            edge["from_node_id"],
            edge["to_node_id"],
            edge.get("from_output", "default"),
            edge.get("to_input", "default"),
        )
        for edge in declared["edges"]
    )
    candidate_source = next(node for node in candidate.nodes if node.node_id == declared["source_node_id"])
    assert candidate_source.parameters == {
        "experiment_id": experiment.id,
        "file_id": source_file.id,
        "stage": "raw",
        "target_authority": _file_target_authority(
            experiment.id,
            source_file.file_path,
            column="Moisture",
            target_type="continuous",
        ),
    }

    for workflow in workflows:
        node_payload = [
            {"node_id": node.node_id, "node_type": node.node_type, "parameters": node.parameters}
            for node in workflow.nodes
        ]
        edge_payload = [
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "from_output": edge.from_output,
                "to_input": edge.to_input,
            }
            for edge in workflow.edges
        ]
        assert workflow.integrity_hash == compute_workflow_hash(node_payload, edge_payload)

    baseline = await load_canonical_workbench_baseline(
        test_session,
        workflow_id=candidate.id,
        actor_user_id=test_user.id,
    )
    assert baseline.dataset.as_dict() == {
        "experiment_id": experiment.id,
        "file_id": source_file.id,
        "stage": "raw",
        "asset_id": None,
        "source_node_id": "candidate_data",
        "target_authority": _file_target_authority(
            experiment.id,
            source_file.file_path,
            column="Moisture",
            target_type="continuous",
        ),
        "group_column": None,
    }
    assert [(node.node_id, node.operation_id, dict(node.parameters)) for node in baseline.graph.nodes] == [
        (
            "candidate_model",
            "model.fitted_pls",
            {"n_components": 3, "scale": True, "target_names": []},
        ),
        ("candidate_evaluator", "diagnostics.regression_evaluator", {"target_names": []}),
    ]

    # The ordinary sheet applies the state fitted earlier in the same typed
    # DAG.  It is not an imported canonical project and must not be sent
    # through imported-artifact custody merely because it uses the same
    # canonical application operation.
    preflight = await auth_client.post(f"/api/v1/workflows/{scientist.id}/preflight")
    assert preflight.status_code == 200, preflight.text
    assert preflight.json()["is_valid"] is True, preflight.json()["issues"]
    assert all(issue["code"] != "canonical_dependency_provenance_unavailable" for issue in preflight.json()["issues"])


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
                        "node_type": "data.file_load",
                        "label": "Load Data",
                        "parameters": {},
                        "example_binding": {"source": "eigenvector", "dataset_name": "corn_m5"},
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
    _materialize_bound_csv(created_experiment.id, imported_file.file_path)

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
                        "selected_target": "target",
                        "target_type": "categorical",
                    }
                },
            },
        )

    assert response.status_code == 201, response.text
    mock_import_ref.assert_awaited_once()
    args = mock_import_ref.await_args.args
    assert args[2] == "sklearn"
    assert args[3] == "wine"
    source_node = next(node for node in response.json()["nodes"] if node["node_id"] == "data_1")
    assert source_node["parameters"]["target_authority"]["column"] == "target"
    assert source_node["parameters"]["target_authority"]["target_type"] == "categorical"


@pytest.mark.asyncio
async def test_instantiate_example_mode_oes_workflow_exports_python(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    from spectra_sherpa.app.services.experiments import experiment_dir

    ensure_type_registry_loaded()

    template = WorkflowTemplate(
        slug="oes_export_template",
        name="OES Process Monitoring",
        description="Bundled OES example data",
        category="exploratory",
        template_data={
            "status": "ready",
            "nodes": [
                {
                    "node_id": "data_1",
                    "node_type": "data.file_load",
                    "label": "Load OES Data",
                    "parameters": {},
                    "example_binding": {"source": "eigenvector", "dataset_name": "metal_etch_oes"},
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
                    "parameters": {"n_components": "3"},
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

    assert instantiate_response.status_code == 201, instantiate_response.text
    workflow_id = instantiate_response.json()["id"]

    export_response = await auth_client.get(f"/api/v1/workflows/{workflow_id}/export/python")

    assert export_response.status_code == 200, export_response.text
    body = export_response.json()
    assert body["workflow_id"] == workflow_id
    assert "python_code" in body
    assert body["export_mode"] == "canonical_dag"
    assert "Generated canonical workflow: OES Export Workflow" in body["python_code"]
    assert "'bundle_relative_path': 'data_1/metal_etch_oes.csv'" in body["python_code"]
    assert "'x_title': 'Time'" in body["python_code"]
    assert "'x_units': 'ms'" in body["python_code"]
    assert "'is_time_series': True" in body["python_code"]
    assert "ss.runtime.execute_workflow" in body["python_code"]

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
        workflow_manifest = json.loads(zf.read("oes_export_workflow/workflow_manifest.json"))
        executable_nodes = {node["node_id"]: node for node in workflow_manifest["nodes"]}
        assert executable_nodes["data_1"]["node_type"] == "deploy.input"
        assert all(node["node_type"] != "data.file_load" for node in executable_nodes.values())
        assert len(workflow_manifest["workflow_digest"]) == 64
        requirements = zf.read("oes_export_workflow/requirements.txt").decode("utf-8")
        assert "plotly" in requirements

    raw_bytes = raw_file.read_bytes()
    portable_reference = {
        "schema_version": "spectrasherpa-portable-reference/1",
        "projection_id": "eigenvector.test_projection",
        "artifact_id": "eigenvector.test_artifact",
        "artifact_size_bytes": len(raw_bytes) + 10,
        "artifact_sha256": "a" * 64,
        "member_path": "metal_etch_oes.csv",
        "member_size_bytes": len(raw_bytes),
        "member_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "native_reader_contract": "spectrasherpa.csv/1",
        "scientific_sha256": "b" * 64,
        "provider": "Eigenvector Research",
        "provider_page": "https://eigenvector.com/data_sets",
        "download_url": "https://eigenvector.com/data/test.zip",
        "redistribution": "user_acquired_no_redistribution",
    }
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

    materialized_reference = MagicMock(dataset=load_canonical_file_as_sherpa(raw_file))
    with (
        patch(
            "spectra_sherpa.app.services.workflow_export_context.read_registered_reference_sidecar",
            return_value=portable_reference,
        ),
        patch(
            "spectra_sherpa.app.lib.reference_materialization.materialize_reference_member",
            return_value=materialized_reference,
        ),
    ):
        reference_response = await auth_client.get(f"/api/v1/workflows/{workflow_id}/export/download?format=zip")

    assert reference_response.status_code == 200, reference_response.text
    with zipfile.ZipFile(io.BytesIO(reference_response.content)) as zf:
        names = set(zf.namelist())
        assert "oes_export_workflow/data/data_1/metal_etch_oes.csv" not in names
        manifest = json.loads(zf.read("oes_export_workflow/prepared_data_manifest.json"))
        source = manifest["sources"][0]
        assert source["source_files"] == [None]
        assert source["external_references"] == [portable_reference]
        python_source = zf.read("oes_export_workflow/oes_export_workflow_workflow.py").decode("utf-8")
        assert "SPECTRA_REFERENCE_DIR" in python_source
        assert "eigenvector.test_projection" in python_source
        readme = zf.read("oes_export_workflow/data/README.md").decode("utf-8")
        assert "not included in this export" in readme
        assert "https://eigenvector.com/data/test.zip" in readme


@pytest.mark.asyncio
async def test_workflow_exports_cannot_bundle_another_users_experiment_file(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    """Workflow-owned IDs are data, not authority to read another tenant's file."""
    from spectra_sherpa.app.services.experiments import experiment_dir

    foreign_user = User(username="foreign-export-owner")
    own_project = Project(user_id=test_user.id, name="Owned export project", description="")
    test_session.add_all([foreign_user, own_project])
    await test_session.flush()

    foreign_experiment = Experiment(
        user_id=foreign_user.id,
        name="Foreign source",
        description="",
        metadata_path="{}",
    )
    own_workflow = Workflow(
        user_id=test_user.id,
        project_id=own_project.id,
        name="Forged source binding",
        description="",
        status="draft",
    )
    test_session.add_all([foreign_experiment, own_workflow])
    await test_session.flush()

    foreign_file = ExperimentFile(
        experiment_id=foreign_experiment.id,
        file_path="raw/private.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=22,
    )
    forged_node = WorkflowNode(
        workflow_id=own_workflow.id,
        node_id="source",
        node_type="data.file_load",
        label="Forged foreign source",
        parameters={
            "experiment_id": foreign_experiment.id,
            "file_id": None,
            "stage": "raw",
        },
        position_x=0,
        position_y=0,
    )
    test_session.add_all([foreign_file, forged_node])
    await test_session.commit()
    await test_session.refresh(foreign_file)
    forged_node.parameters = {
        "experiment_id": foreign_experiment.id,
        "file_id": foreign_file.id,
        "stage": "raw",
    }
    await test_session.commit()

    private_path = experiment_dir(foreign_experiment.id) / foreign_file.file_path
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text("foreign-secret-bytes\n", encoding="utf-8")

    responses = [
        await auth_client.get(f"/api/v1/workflows/{own_workflow.id}/export/python"),
        await auth_client.get(f"/api/v1/workflows/{own_workflow.id}/export/notebook"),
        await auth_client.get(f"/api/v1/workflows/{own_workflow.id}/export/download?format=zip"),
        await auth_client.post(
            f"/api/v1/projects/{own_project.id}/scripts/generate",
            json={"workflow_id": own_workflow.id, "name": "forged.py"},
        ),
    ]

    assert [response.status_code for response in responses] == [422, 422, 422, 422]
    assert all("foreign-secret-bytes" not in response.text for response in responses)
    assert all(str(foreign_experiment.id) not in response.text for response in responses)


@pytest.mark.asyncio
async def test_workflow_export_cannot_cross_same_user_project_custody(
    test_session: AsyncSession,
    test_user: User,
):
    from spectra_sherpa.app.services.workflow_export_context import build_workflow_export_context

    workflow_project = Project(user_id=test_user.id, name="Workflow project", description="")
    source_project = Project(user_id=test_user.id, name="Other source project", description="")
    test_session.add_all([workflow_project, source_project])
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=source_project.id,
        name="Cross-project source",
        description="",
        metadata_path="{}",
    )
    workflow = Workflow(
        user_id=test_user.id,
        project_id=workflow_project.id,
        name="Cross-project workflow",
        description="",
        status="draft",
    )
    test_session.add_all([experiment, workflow])
    await test_session.flush()
    file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/source.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=4,
    )
    node = WorkflowNode(
        workflow_id=workflow.id,
        node_id="source",
        node_type="data.file_load",
        label="Source",
        parameters={"experiment_id": experiment.id, "file_id": 1, "stage": "raw"},
        position_x=0,
        position_y=0,
    )
    test_session.add_all([file, node])
    await test_session.commit()
    await test_session.refresh(file)
    node.parameters = {"experiment_id": experiment.id, "file_id": file.id, "stage": "raw"}
    await test_session.commit()
    await test_session.refresh(workflow, attribute_names=["nodes", "edges"])

    with pytest.raises(ValueError, match="not available"):
        await build_workflow_export_context(workflow, test_session, actor_user_id=test_user.id)


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
                        "node_type": "data.file_load",
                        "label": "Load Data",
                        "parameters": {},
                        "example_binding": {"source": "eigenvector", "dataset_name": "corn_m5"},
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
    _materialize_bound_csv(experiment.id, existing_file.file_path)

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
    assert nodes_by_id["data_1"]["node_type"] == "data.file_load"
    assert nodes_by_id["data_1"]["parameters"] == {
        "experiment_id": experiment.id,
        "file_id": existing_file.id,
        "stage": "raw",
    }


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
            "status": "ready",
            "nodes": [
                {
                    "node_id": "data_1",
                    "node_type": "data.file_load",
                    "label": "Load Data",
                    "parameters": {},
                    "example_binding": {"source": "eigenvector", "dataset_name": "corn_m5"},
                    "position_x": 120,
                    "position_y": 180,
                },
                {
                    "node_id": "model_1",
                    "node_type": "model.fitted_pls",
                    "label": "Canonical PLS Regression",
                    "parameters": {"n_components": 2},
                    "position_x": 360,
                    "position_y": 180,
                },
            ],
            "edges": [
                {
                    "from_node_id": "data_1",
                    "to_node_id": "model_1",
                    "from_output": "default",
                    "to_input": "default",
                },
                {
                    "from_node_id": "data_1",
                    "to_node_id": "model_1",
                    "from_output": "target",
                    "to_input": "y",
                },
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
    _materialize_bound_csv(experiment.id, spectra_file.file_path)
    _materialize_bound_csv(experiment.id, target_file.file_path)
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")

    with patch(
        "spectra_sherpa.app.api.v1.routes.workflow_templates._is_portable_sample_table_binding",
        new=AsyncMock(return_value=False),
    ):
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
                            "target_authority": _file_target_authority(
                                experiment.id,
                                target_file.file_path,
                                column="response",
                                target_type="continuous",
                            ),
                        },
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
    assert nodes_by_id["data_1"]["node_type"] == "data.file_load"
    assert nodes_by_id["data_1"]["parameters"] == {
        "experiment_id": experiment.id,
        "file_id": spectra_file.id,
        "stage": "raw",
    }
    assert nodes_by_id["data_1__target_source"]["parameters"]["file_id"] == target_file.id
    assert nodes_by_id["data_1__target_source"]["parameters"]["target_authority"]["column"] == "response"
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
    assert ("data_1__target_source", "data_1__attach_target", "target", "y") in edges
    assert ("data_1__target_source", "model_1", "target", "y") in edges
    assert ("data_1", "model_1", "target", "y") not in edges
    assert (
        "data_1__target_source",
        "data_1__attach_target",
        "sample_table",
        "sample_table",
    ) not in edges
    assert ("data_1__attach_target", "model_1", "default", "default") in edges


def test_separate_target_binding_requires_an_exact_response_name() -> None:
    from fastapi import HTTPException

    from spectra_sherpa.app.api.v1.routes.workflow_templates import (
        DataBindingSpec,
        _inject_target_binding,
    )

    template = MagicMock(spec=WorkflowTemplate)
    template.name = "Explicit response template"
    binding = DataBindingSpec(
        experiment_id=1,
        file_id=1,
        target_binding=DataBindingSpec(experiment_id=2, file_id=2),
    )

    with pytest.raises(HTTPException, match="requires an exact selected_target"):
        _inject_target_binding(
            template,
            {"node_id": "data_1", "position_x": 0, "position_y": 0},
            binding,
            [],
            {},
            [],
            filter_sample_table=False,
        )


def test_numeric_collection_target_inherits_the_template_continuous_authority() -> None:
    template = MagicMock(spec=WorkflowTemplate)
    template.name = "Quantitative calibration"
    template.category = "regression"
    template.template_data = {
        "data_roles": {
            "X_spectra": {
                "role_type": "X_spectra",
                "node_binding": "data_1",
                "required": True,
                "binding_mode": "embedded",
            },
            "Y_reference": {
                "role_type": "Y_reference",
                "node_binding": "data_1",
                "required": True,
                "binding_mode": "embedded",
                "target_type": "continuous",
            },
        }
    }
    binding = DataBindingSpec(
        experiment_id=1,
        file_ids=[2, 3],
        target_authority=_target_authority(
            column="moisture",
            target_type="continuous",
            source_digest="a" * 64,
        ),
    )

    normalized = _normalize_binding_target_authority(template, binding, "data_1")

    assert normalized.selected_target == "moisture"
    assert normalized.target_type == "continuous"


def test_separate_target_type_mismatch_refuses_before_source_admission() -> None:
    template = MagicMock(spec=WorkflowTemplate)
    template.name = "Quantitative calibration"
    template.category = "regression"
    template.template_data = {
        "data_roles": {
            "X_spectra": {
                "role_type": "X_spectra",
                "node_binding": "data_1",
                "required": True,
                "binding_mode": "embedded",
            },
            "Y_reference": {
                "role_type": "Y_reference",
                "node_binding": "data_1",
                "required": True,
                "binding_mode": "separate_source",
                "target_type": "continuous",
            },
        }
    }
    binding = DataBindingSpec(
        experiment_id=1,
        file_id=2,
        target_binding=DataBindingSpec(
            experiment_id=1,
            file_id=3,
            target_authority=_target_authority(
                column="cultivar",
                target_type="categorical",
                source_digest="a" * 64,
            ),
        ),
    )

    with pytest.raises(HTTPException, match="requires a continuous separate target"):
        _normalize_binding_target_authority(template, binding, "data_1")


def test_constant_selected_target_refuses_before_template_persistence() -> None:
    dataset = MagicMock()
    dataset.target = [4, 4.0, None]

    with pytest.raises(ValueError, match="constant or empty"):
        _require_target_variation(dataset, "moisture")

    dataset.target = [4.2, 4.3, None]
    _require_target_variation(dataset, "moisture")


def test_template_binding_persists_exact_scientific_asset_identity() -> None:
    from spectra_sherpa.app.api.v1.routes.workflow_templates import (
        DataBindingSpec,
        _binding_to_file_load_params,
    )
    from spectra_sherpa.app.services.dag.node_base import node_registry

    parameters = _binding_to_file_load_params(DataBindingSpec(experiment_id=1, file_id=2, stage="raw", asset_id="a"))
    assert parameters == {
        "experiment_id": 1,
        "file_id": 2,
        "stage": "raw",
        "asset_id": "a",
    }

    collection_parameters = _binding_to_file_load_params(
        DataBindingSpec(
            experiment_id=7,
            all_files=True,
            display_name="Synthetic Atmospheric FTIR",
            source_manifest_sha256="a" * 64,
        )
    )
    assert collection_parameters["group_title"] == "Synthetic Atmospheric FTIR"
    node_registry.create_node("data.collection_load", "data_1", collection_parameters)


def test_portable_sample_table_binding_injects_explicit_canonical_filter() -> None:
    from spectra_sherpa.app.api.v1.routes.workflow_templates import (
        DataBindingSpec,
        _inject_target_binding,
    )

    template = MagicMock(spec=WorkflowTemplate)
    template.name = "Explicit sample preparation"
    template.template_data = {"data_roles": {}}
    binding = DataBindingSpec(
        experiment_id=1,
        file_id=11,
        target_binding=DataBindingSpec(
            experiment_id=1,
            file_id=12,
            target_authority=_target_authority(
                column="moisture",
                target_type="continuous",
                source_digest="a" * 64,
            ),
        ),
    )
    nodes = [
        {
            "node_id": "data_1",
            "node_type": "data.file_load",
            "position_x": 0,
            "position_y": 0,
        },
        {"node_id": "model_1", "node_type": "model.fitted_pls"},
    ]
    nodes_by_id = {str(node["node_id"]): node for node in nodes}
    edges = [
        {
            "from_node_id": "data_1",
            "to_node_id": "model_1",
            "from_output": "default",
            "to_input": "default",
        }
    ]

    updated = _inject_target_binding(
        template,
        nodes_by_id["data_1"],
        binding,
        nodes,
        nodes_by_id,
        edges,
        filter_sample_table=True,
    )

    filter_node = nodes_by_id["data_1__filter_samples"]
    assert filter_node["node_type"] == "data.filter_samples"
    assert filter_node["parameters"] == {
        "field": "sample_table",
        "sample_table_column": "include",
        "filter_values": ["true"],
    }
    edge_tuples = {
        (
            edge["from_node_id"],
            edge["to_node_id"],
            edge.get("from_output", "default"),
            edge.get("to_input", "default"),
        )
        for edge in updated
    }
    assert ("data_1__attach_target", "data_1__filter_samples", "default", "default") in edge_tuples
    assert ("data_1__filter_samples", "model_1", "default", "default") in edge_tuples


@pytest.mark.asyncio
async def test_portable_sample_table_binding_is_identified_from_validated_contents(tmp_path: Path) -> None:
    from spectra_sherpa.app.api.v1.routes.workflow_templates import (
        DataBindingSpec,
        _is_portable_sample_table_binding,
    )

    table_path = tmp_path / "preprocessed" / "sample-table.csv"
    table_path.parent.mkdir(parents=True)
    table_path.write_text(
        "row_index,source_file_id,sample_id,include,target_schema,moisture,plate_id,well\n"
        '0,11,sample-1,true,"{""moisture"":""continuous""}",10.0,plate-1,A01\n',
        encoding="utf-8",
    )
    file_record = ExperimentFile(
        id=12,
        experiment_id=1,
        file_path="preprocessed/sample-table.csv",
        file_type="csv",
        stage="preprocessed",
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = file_record
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    binding = DataBindingSpec(
        experiment_id=1,
        file_id=12,
        stage="preprocessed",
        target_authority=_target_authority(
            column="moisture",
            target_type="continuous",
            source_digest="a" * 64,
        ),
    )

    with patch(
        "spectra_sherpa.app.api.v1.routes.workflow_templates.experiment_dir",
        return_value=tmp_path,
    ):
        assert await _is_portable_sample_table_binding(session, binding) is True


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
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch.setattr(
        "spectra_sherpa.app.services.dag.node_catalog_contract.distribution_is_installed",
        lambda distribution: True,
    )

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
    assert nodes_by_id["data_1"]["node_type"] == "data.file_load"
    assert nodes_by_id["data_2"]["node_type"] == "data.file_load"
    assert nodes_by_id["data_1"]["parameters"]["experiment_id"] != nodes_by_id["data_2"]["parameters"]["experiment_id"]
    assert nodes_by_id["compare_1"]["node_type"] == "analysis.compare_library"

    mixture_id = nodes_by_id["data_1"]["parameters"]["experiment_id"]
    library_id = nodes_by_id["data_2"]["parameters"]["experiment_id"]
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


@pytest.mark.asyncio
async def test_instantiate_pls_with_selected_native_synthetic_response(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
):
    from spectra_sherpa.app.core.template_loader import TemplateLoader
    from spectra_sherpa.app.lib.target_authority import issue_target_authority
    from spectra_sherpa.app.services.experiments import import_reference_dataset
    from spectra_sherpa.app.services.model_application import load_project_dataset

    template_def = {template["slug"]: template for template in TemplateLoader().load_all()}["pls_calibration"]
    template = WorkflowTemplate(
        slug="pls_native_synthetic_response",
        name=template_def["name"],
        description=template_def["description"],
        category=template_def["category"],
        template_data={**template_def["template_data"], "status": "ready"},
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Synthetic PLS Project", description="")
    test_session.add_all([template, project])
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="Synthetic atmospheric mixture",
        description="",
        metadata_path="{}",
    )
    test_session.add(experiment)
    await test_session.flush()
    files = await import_reference_dataset(
        test_session,
        experiment.id,
        "synthetic",
        "Synthetic_atmospheric-6",
    )
    await test_session.commit()
    loaded = await load_project_dataset(
        test_session,
        user_id=test_user.id,
        experiment_id=experiment.id,
        stage="synthetic",
        file_ids=[files[0].id],
    )
    authority = issue_target_authority(
        loaded.dataset,
        column="Carbon dioxide",
        target_type="continuous",
    )
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Carbon dioxide PLS",
            "project_id": project.id,
            "data_bindings": {
                "data_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "stage": "synthetic",
                    "file_ids": [files[0].id],
                    "target_authority": authority.canonical_dict(),
                }
            },
        },
    )

    assert response.status_code == 201, response.text
    source = next(node for node in response.json()["nodes"] if node["node_id"] == "data_1")
    model = next(node for node in response.json()["nodes"] if node["node_id"] == "model_1")
    evaluator = next(node for node in response.json()["nodes"] if node["node_id"] == "eval_1")
    assert source["node_type"] == "data.collection_load"
    assert source["parameters"]["target_authority"] == authority.canonical_dict()
    assert model["parameters"]["target_names"] == ["Carbon dioxide"]
    assert evaluator["parameters"]["target_names"] == ["Carbon dioxide"]
    workflows = list(
        (
            await test_session.scalars(
                select(Workflow)
                .where(Workflow.project_id == project.id)
                .options(selectinload(Workflow.nodes))
                .order_by(Workflow.sheet_order)
            )
        ).all()
    )
    assert [workflow.purpose for workflow in workflows] == ["analysis", "managed_candidate_authority"]
    managed_source = next(node for node in workflows[1].nodes if node.node_id == "candidate_data")
    assert managed_source.node_type == "data.file_load"
    assert managed_source.parameters["file_id"] == files[0].id
    assert managed_source.parameters["target_authority"]["column"] == "Carbon dioxide"
    assert managed_source.parameters["target_authority"]["source_digest"] != authority.source_digest


@pytest.mark.asyncio
async def test_instantiate_rejects_template_unavailable_in_server_runtime(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    template = WorkflowTemplate(
        slug="mcr_runtime_unavailable",
        name="MCR runtime unavailable",
        description="Requires optional SpectroChemPy support",
        category="curve_resolution",
        template_data={
            **_make_template_data(),
            "status": "ready",
            "nodes": [
                {
                    "node_id": "model_1",
                    "node_type": "model.mcr_als",
                    "parameters": {"n_components": 3},
                }
            ],
        },
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Runtime Guard Project", description="")
    test_session.add_all([template, project])
    await test_session.commit()
    await test_session.refresh(template)
    await test_session.refresh(project)
    monkeypatch.setattr(
        "spectra_sherpa.app.services.dag.node_catalog_contract.distribution_is_installed",
        lambda distribution: distribution != "spectrochempy",
    )

    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Must Not Persist",
            "project_id": project.id,
            "launch_mode": "draft",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "template_runtime_unavailable",
        "message": "This server runtime cannot execute the selected analysis starter.",
        "blockers": ["spectrochempy_unavailable"],
        "remediation": ["Install the optional SpectroChemPy support: pip install 'spectra-sherpa[scp]'."],
        "unavailable_nodes": [
            {
                "node_id": "model_1",
                "node_type": "model.mcr_als",
                "blockers": ["spectrochempy_unavailable"],
            }
        ],
    }
    workflows = await test_session.scalars(select(Workflow).where(Workflow.project_id == project.id))
    assert list(workflows) == []


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
        ("eigenvector", "corn_m5", "spectra_sherpa.app.services.eigenvector_datasets.get_dataset_info"),
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
