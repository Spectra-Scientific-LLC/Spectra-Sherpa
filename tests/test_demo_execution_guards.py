"""Regression coverage for demo-mode data execution guards."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.v1.routes import api_keys
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.main import app
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.services.dag import node_registry
from spectra_sherpa.app.services.workflow_access import TRIAL_SOURCE_NODE_TYPES
from tests.route_utils import iter_effective_api_routes


def _find_route(path: str, method: str = "POST") -> APIRoute:
    for effective_path, route in iter_effective_api_routes(app.routes):
        if effective_path == path and method in route.methods:
            return route
    raise AssertionError(f"Route not found: {method} {path}")


def _has_demo_guard(route: APIRoute) -> bool:
    for dep in route.dependant.dependencies:
        call = dep.call
        if (
            call
            and getattr(call, "__name__", None) == "_guard"
            and getattr(call, "__module__", "") == "spectra_sherpa.app.api.deps"
        ):
            return True
    return False


@pytest.fixture
def demo_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_config, "site_profile", "demo")


class TestDemoGuardCoverage:
    def test_trial_source_guard_matches_the_complete_live_source_census(self) -> None:
        """Every source-capable DAG operation must pass the starter grant."""

        registered_sources = {
            metadata.node_type
            for metadata in node_registry.list_nodes()
            if metadata.resolved_execution_contract().payload["lifecycle_kind"] == "data_source"
        }
        assert TRIAL_SOURCE_NODE_TYPES == registered_sources

    def test_file_upload_routes_have_demo_guard(self) -> None:
        """Every scientific-ingress route has a fail-closed demo guard."""
        guarded_paths = [
            ("/api/v1/experiments/{experiment_id}/files", "POST"),
            ("/api/v1/experiments/{experiment_id}/files/{file_id}", "DELETE"),
            ("/api/v1/experiments/{experiment_id}/import-reference", "POST"),
            ("/api/v1/experiments/{experiment_id}/collection-definition/preview", "POST"),
            ("/api/v1/experiments/{experiment_id}/collection-definition", "PUT"),
            ("/api/v1/experiments/{experiment_id}/collection-definition", "DELETE"),
            ("/api/v1/builder/file-metadata", "PATCH"),
            ("/api/v1/datasets/library/import", "POST"),
            ("/api/v1/datasets/library/{library_id}/spectrum", "GET"),
            ("/api/v1/models/import-canonical-full-refit", "POST"),
            ("/api/v1/projects/canonical-import", "POST"),
            ("/api/v1/projects/import", "POST"),
            ("/api/v1/projects/objects/inspect", "POST"),
            ("/api/v1/projects/objects/validate", "POST"),
            ("/api/v1/projects/{project_id}/data-sources", "POST"),
            ("/api/v1/projects/{project_id}/data-sources/{data_source_id}", "PUT"),
            ("/api/v1/projects/{project_id}/export", "GET"),
            ("/api/v1/projects/{project_id}/export/sherpa", "GET"),
            ("/api/v1/datasets/download/{file_id}", "GET"),
            ("/api/v1/runs/batch/folder", "POST"),
            ("/api/v1/experiments/{experiment_id}/files/{file_id}/scientific-assets", "GET"),
            ("/api/v1/datasets/{dataset_id}/preview", "GET"),
            ("/api/v1/datasets/{dataset_id}/axes", "GET"),
            ("/api/v1/datasets/{dataset_id}/sample-table", "GET"),
            ("/api/v1/datasets/{dataset_id}/provenance", "GET"),
            ("/api/v1/datasets/{dataset_id}/quality", "GET"),
            ("/api/v1/datasets/{dataset_id}/summary", "GET"),
            ("/api/v1/datasets/{dataset_id}/branch", "POST"),
            ("/api/v1/synthesis/spectrum", "GET"),
            ("/api/v1/synthesis/spectrum/load", "POST"),
            ("/api/v1/synthesis/preview", "POST"),
            ("/api/v1/synthesis/synthesize", "POST"),
            ("/api/v1/synthesis/save", "POST"),
        ]
        for path, method in guarded_paths:
            route = _find_route(path, method)
            assert _has_demo_guard(route), f"Expected demo_guard dependency on {method} {path}"

    def test_retired_placeholder_compute_route_is_absent(self) -> None:
        """A placeholder may never return fabricated scientific success."""

        with pytest.raises(AssertionError, match="Route not found"):
            _find_route("/api/v1/compute/execute", "POST")

    def test_unexposed_doe_prototype_routes_are_absent(self) -> None:
        """The retained DOE service must not advertise an unsupported product surface."""

        paths = {path for path, _route in iter_effective_api_routes(app.routes)}
        assert not any(path.startswith("/api/v1/experiments/{experiment_id}/doe") for path in paths)
        assert not any(path.startswith("/api/v1/doe-configs") for path in paths)

    def test_retired_builder_preprocessing_route_is_absent(self) -> None:
        """Preprocessing must enter through typed canonical DAG operations."""

        with pytest.raises(AssertionError, match="Route not found"):
            _find_route("/api/v1/builder/preprocess", "POST")

    @pytest.mark.parametrize("service", ["hitran", "openai"])
    def test_demo_blocks_all_user_managed_api_keys(
        self,
        demo_profile: None,
        service: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectra_sherpa.app.contracts import demo_policy

        monkeypatch.setattr(
            demo_policy,
            "_demo_policy_provider",
            lambda: demo_policy.DemoPolicy(
                disabled_capabilities=frozenset({"api_key_management", "hitran_api_key_management"})
            ),
        )
        with pytest.raises(Exception) as exc_info:
            api_keys._require_api_key_capability(service)

        assert getattr(exc_info.value, "status_code", None) == 403

    def test_hosted_pro_blocks_user_managed_llm_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectra_sherpa.app.core.config import app_config

        monkeypatch.setattr(app_config, "site_profile", "pro")
        with pytest.raises(Exception) as exc_info:
            api_keys._require_api_key_capability("openai")

        assert getattr(exc_info.value, "status_code", None) == 403

    def test_folder_watch_mutations_have_demo_guard(self) -> None:
        guarded_paths = [
            ("/api/v1/deploy/watches", "POST"),
            ("/api/v1/deploy/watches/{watch_id}", "PATCH"),
            ("/api/v1/deploy/watches/{watch_id}", "DELETE"),
            ("/api/v1/deploy/watches/{watch_id}/enable", "POST"),
            ("/api/v1/deploy/watches/{watch_id}/disable", "POST"),
        ]
        for path, method in guarded_paths:
            route = _find_route(path, method)
            assert _has_demo_guard(route), f"Expected demo_guard dependency on {method} {path}"

    @pytest.mark.anyio
    async def test_export_capability_guards_remain_fail_closed_when_explicitly_disabled(
        self,
        auth_client: AsyncClient,
        demo_profile: None,
    ) -> None:
        """An operator can still disable export without making that the demo default."""

        from spectra_sherpa.app.contracts import demo_policy

        previous = demo_policy._demo_policy_provider
        demo_policy.set_demo_policy_provider(
            lambda: demo_policy.DemoPolicy(
                disabled_capabilities=frozenset({"raw_data_export", "data_bearing_project_export"})
            )
        )
        try:
            responses = [
                await auth_client.get("/api/v1/datasets/download/1"),
                await auth_client.get("/api/v1/projects/1/export"),
                await auth_client.get("/api/v1/projects/1/export/sherpa"),
            ]
        finally:
            demo_policy._demo_policy_provider = previous

        assert [response.status_code for response in responses] == [403, 403, 403]
        assert all("not available in demo mode" in response.text for response in responses)

    @pytest.mark.anyio
    async def test_trial_builder_inspection_re_admits_the_exact_loaded_snapshot(
        self,
        auth_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = (await auth_client.post("/api/v1/projects", json={"name": "Starter"})).json()
        experiment = (
            await auth_client.post(
                "/api/v1/experiments",
                json={"name": "Issued starter", "metadata": {}, "project_id": project["id"]},
            )
        ).json()
        fixture = Path(__file__).parent / "fixtures" / "formats" / "jcamp" / "simple-spectrum.jdx"
        uploaded = await auth_client.post(
            f"/api/v1/experiments/{experiment['id']}/files",
            data={"stage": "raw", "data_role": "X_spectra"},
            files={"file": ("starter.jdx", fixture.read_bytes(), "chemical/x-jcamp-dx")},
        )
        assert uploaded.status_code == 201
        uploaded_second = await auth_client.post(
            f"/api/v1/experiments/{experiment['id']}/files",
            data={"stage": "raw", "data_role": "X_spectra"},
            files={"file": ("starter-second.jdx", fixture.read_bytes(), "chemical/x-jcamp-dx")},
        )
        assert uploaded_second.status_code == 201

        from spectra_sherpa.app.lib.collection_definition import COLLECTION_DEFINITION_SCHEMA
        from spectra_sherpa.app.lib.sherpa_dataset import DomainContext
        from spectra_sherpa.app.services.collection_definitions import write_collection_definition

        digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
        columns = ["sample_id", "specimen_id", "block"]
        rows = []
        for index, record in enumerate((uploaded.json(), uploaded_second.json()), start=1):
            sample_id = f"starter-{index}"
            rows.append(
                {
                    "file_name": record["file_path"],
                    "sha256": digest,
                    "asset_id": "spectrum",
                    "source_row_index": 0,
                    "sample_id": sample_id,
                    "annotations": {"sample_id": sample_id, "specimen_id": sample_id, "block": 1},
                }
            )
        write_collection_definition(
            experiment["id"],
            {
                "schema_version": COLLECTION_DEFINITION_SCHEMA,
                "columns": columns,
                "collection": {
                    "dataset_id": "trial-starter-test/1",
                    "title": "Issued starter",
                    "units": None,
                    "data_role": "X_spectra",
                    "domain": DomainContext().model_dump(mode="json", exclude_none=False),
                    "sample_axis": {"title": "Samples", "units": None, "values_policy": "omit"},
                },
                "rows": rows,
            },
        )

        from spectra_sherpa.app.contracts import demo_policy

        captured: list[dict] = []

        async def _capture_exact_loaded_dataset(**kwargs):
            captured.append(kwargs)
            from spectra_sherpa.app.services.model_application import load_project_dataset

            loaded = await load_project_dataset(
                kwargs["session"],
                user_id=kwargs["user_id"],
                experiment_id=kwargs["experiment_id"],
                stage=kwargs["stage"],
                file_id=kwargs["file_id"],
                file_ids=kwargs.get("file_ids"),
                asset_id=kwargs["asset_id"],
                strict_prepared_data=True,
            )
            return SimpleNamespace(
                grant=SimpleNamespace(dataset_key="avatar-lavender-essential-oils-v1"),
                loaded_dataset=loaded,
            )

        previous = demo_policy._trial_dataset_access_provider
        demo_policy.set_trial_dataset_access_provider(_capture_exact_loaded_dataset)
        monkeypatch.setattr(app_config, "site_profile", "demo")
        try:
            response = await auth_client.post(
                "/api/v1/builder/file-info",
                json={"experiment_id": experiment["id"]},
            )
            selected_response = await auth_client.post(
                "/api/v1/builder/file-info",
                json={
                    "experiment_id": experiment["id"],
                    "file_path": uploaded.json()["file_path"],
                },
            )
            batch_response = await auth_client.post(
                "/api/v1/builder/file-info",
                json={"experiment_id": experiment["id"], "file_ids": [uploaded_second.json()["id"]]},
            )
        finally:
            demo_policy.set_trial_dataset_access_provider(previous)

        assert response.status_code == 200
        assert selected_response.status_code == 200
        assert selected_response.json()["metadata"]["sample_labels"] == ["starter-1"]
        assert batch_response.status_code == 200
        assert batch_response.json()["metadata"]["sample_labels"] == ["starter-2"]
        assert len(captured) == 3
        assert captured[2]["file_ids"] == [uploaded_second.json()["id"]]
        assert captured[2]["file_id"] is None
        grant_input = captured[0]
        assert grant_input["workflow_project_id"] == project["id"]
        assert grant_input["experiment_id"] == experiment["id"]
        assert grant_input["file_id"] is None
        assert grant_input["loaded_dataset"] is None
        selected_grant_input = captured[1]
        assert selected_grant_input["workflow_project_id"] == project["id"]
        assert selected_grant_input["experiment_id"] == experiment["id"]
        assert selected_grant_input["file_id"] == uploaded.json()["id"]
        assert selected_grant_input["loaded_dataset"] is None

    @pytest.mark.anyio
    async def test_user_acquired_registered_reference_is_visible_for_analysis(
        self,
        auth_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Checksum admission must not prevent the scientist from seeing and analysing the data."""

        project = (await auth_client.post("/api/v1/projects", json={"name": "Corn starter"})).json()
        experiment = (
            await auth_client.post(
                "/api/v1/experiments",
                json={"name": "Corn", "metadata": {}, "project_id": project["id"]},
            )
        ).json()
        fixture = Path(__file__).parent / "fixtures" / "formats" / "jcamp" / "simple-spectrum.jdx"
        uploaded = await auth_client.post(
            f"/api/v1/experiments/{experiment['id']}/files",
            data={"stage": "raw", "data_role": "X_spectra"},
            files={"file": ("corn.jdx", fixture.read_bytes(), "chemical/x-jcamp-dx")},
        )
        assert uploaded.status_code == 201

        from spectra_sherpa.app.contracts import demo_policy

        async def _admit_corn(**kwargs):
            from spectra_sherpa.app.services.model_application import load_project_dataset

            loaded = await load_project_dataset(
                kwargs["session"],
                user_id=kwargs["user_id"],
                experiment_id=kwargs["experiment_id"],
                stage=kwargs["stage"],
                file_id=kwargs["file_id"],
                asset_id=kwargs["asset_id"],
                strict_prepared_data=True,
            )
            return SimpleNamespace(
                grant=SimpleNamespace(dataset_key="public-corn-m5-moisture-v1"),
                loaded_dataset=loaded,
            )

        previous = demo_policy._trial_dataset_access_provider
        demo_policy.set_trial_dataset_access_provider(_admit_corn)
        monkeypatch.setattr(app_config, "site_profile", "demo")
        try:
            response = await auth_client.post(
                "/api/v1/builder/file-info",
                json={"experiment_id": experiment["id"]},
            )
        finally:
            demo_policy.set_trial_dataset_access_provider(previous)

        assert response.status_code == 200
        body = response.json()
        assert body["type"] == "SherpaDataset"
        assert body["shape"] == [1, 3]
        assert body["data"] == [[0.1, 0.2, 0.3]]

    @pytest.mark.anyio
    async def test_trial_infers_synthetic_stage_for_inventory_and_inspection(
        self,
        auth_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = (await auth_client.post("/api/v1/projects", json={"name": "Synthetic"})).json()
        experiment = (
            await auth_client.post(
                "/api/v1/experiments",
                json={"name": "Synthetic reference", "metadata": {}, "project_id": project["id"]},
            )
        ).json()
        fixture = Path(__file__).parent / "fixtures" / "formats" / "jcamp" / "simple-spectrum.jdx"
        uploaded = await auth_client.post(
            f"/api/v1/experiments/{experiment['id']}/files",
            data={"stage": "synthetic", "data_role": "X_spectra"},
            files={"file": ("synthetic.jdx", fixture.read_bytes(), "chemical/x-jcamp-dx")},
        )
        assert uploaded.status_code == 201

        from spectra_sherpa.app.contracts import demo_policy
        from spectra_sherpa.app.services.model_application import load_project_dataset

        observed_stages: list[str] = []

        async def _admit_synthetic(**kwargs):
            observed_stages.append(str(kwargs["stage"]))
            loaded = await load_project_dataset(
                kwargs["session"],
                user_id=kwargs["user_id"],
                experiment_id=kwargs["experiment_id"],
                stage=kwargs["stage"],
                file_id=kwargs["file_id"],
                asset_id=kwargs["asset_id"],
                strict_prepared_data=True,
            )
            return SimpleNamespace(
                grant=SimpleNamespace(dataset_key="catalog:synthetic:fixture"),
                loaded_dataset=loaded,
            )

        previous = demo_policy._trial_dataset_access_provider
        demo_policy.set_trial_dataset_access_provider(_admit_synthetic)
        monkeypatch.setattr(app_config, "site_profile", "demo")
        try:
            files_response = await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files")
            inspection = await auth_client.post(
                "/api/v1/builder/file-info",
                json={"experiment_id": experiment["id"]},
            )
        finally:
            demo_policy.set_trial_dataset_access_provider(previous)

        assert files_response.status_code == 200
        assert [row["stage"] for row in files_response.json()] == ["synthetic"]
        assert inspection.status_code == 200
        assert inspection.json()["metadata"]["contents_stage"] == "synthetic"
        assert observed_stages == ["synthetic", "synthetic"]

    @pytest.mark.anyio
    async def test_trial_imports_label_identified_sklearn_feature_table(
        self,
        auth_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = (await auth_client.post("/api/v1/projects", json={"name": "Iris"})).json()
        experiment = (
            await auth_client.post(
                "/api/v1/experiments",
                json={"name": "Iris", "metadata": {}, "project_id": project["id"]},
            )
        ).json()

        from spectra_sherpa.app.contracts import demo_policy
        from spectra_sherpa.app.services.model_application import load_project_dataset

        admitted = []

        async def _issue_reference(**kwargs):
            loaded = await load_project_dataset(
                kwargs["session"],
                user_id=kwargs["user_id"],
                experiment_id=kwargs["experiment_id"],
                stage=kwargs["stage"],
                file_id=kwargs["file_id"],
                asset_id=kwargs["asset_id"],
                strict_prepared_data=True,
            )
            admitted.append(loaded)
            return SimpleNamespace(
                experiment_id=kwargs["experiment_id"],
                file_id=kwargs["file_id"],
            )

        previous = demo_policy._trial_reference_grant_provider
        demo_policy.set_trial_reference_grant_provider(_issue_reference)
        monkeypatch.setattr(app_config, "site_profile", "demo")
        try:
            response = await auth_client.post(
                f"/api/v1/experiments/{experiment['id']}/import-reference",
                json={"datasets": [{"source": "sklearn", "name": "iris"}]},
            )
        finally:
            demo_policy.set_trial_reference_grant_provider(previous)

        assert response.status_code == 201
        assert len(admitted) == 1
        assert admitted[0].dataset.data_role == "X_features"
        assert admitted[0].dataset.feature_axis.values is None
        assert admitted[0].dataset.feature_axis.labels == [
            "sepal length (cm)",
            "sepal width (cm)",
            "petal length (cm)",
            "petal width (cm)",
        ]
        assert admitted[0].dataset.target_context.target_type == "categorical"
        assert admitted[0].dataset.target_context.class_names == ["setosa", "versicolor", "virginica"]

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "node_type",
        [
            "custom.catmull_rom_curve",
            "custom.concentration_curve",
            "data.nist_library",
            "data.synthetic_curve",
            "deploy.input",
        ],
    )
    async def test_trial_rejects_every_ungranted_alternate_source(
        self,
        auth_client: AsyncClient,
        test_session: AsyncSession,
        test_user: User,
        demo_profile: None,
        node_type: str,
    ) -> None:
        """Initial-data overrides cannot bypass the two issued starter datasets."""
        workflow = Workflow(name="demo-ref-data", user_id=test_user.id)
        test_session.add(workflow)
        await test_session.flush()
        test_session.add(
            WorkflowNode(
                workflow_id=workflow.id,
                node_id="data_1",
                node_type=node_type,
                parameters={},
            )
        )
        await test_session.commit()
        await test_session.refresh(workflow)

        from spectra_sherpa.app.contracts import demo_policy

        async def _refuse_unissued_source(**kwargs) -> None:
            raise HTTPException(status_code=403, detail="dataset is not an active server-issued free-trial starter")

        previous = demo_policy._trial_dataset_access_provider
        demo_policy.set_trial_dataset_access_provider(_refuse_unissued_source)

        payload = {
            "initial_data": {
                "data_1": {
                    "source": "eigenvector",
                    "eigenvector_dataset": "diesel_nir",
                }
            }
        }
        try:
            resp = await auth_client.post(
                f"/api/v1/workflows/{workflow.id}/execute",
                json=payload,
            )
        finally:
            demo_policy.set_trial_dataset_access_provider(previous)
        assert resp.status_code == 403
        assert "server-issued" in resp.text

    @pytest.mark.anyio
    async def test_trial_parameter_override_is_authorized_before_executor_construction(
        self,
        auth_client: AsyncClient,
        demo_profile: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The target override cannot validate one tenant and execute another."""

        from spectra_sherpa.app.api.v1.routes.workflows import execute as execute_route
        from spectra_sherpa.app.contracts import demo_policy

        observed: list[int | None] = []

        async def _deny_effective_source(**kwargs):
            observed.append(kwargs["experiment_id"])
            raise HTTPException(status_code=403, detail="effective source is outside starter custody")

        previous_policy = demo_policy._demo_policy_provider
        previous_access = demo_policy._trial_dataset_access_provider
        demo_policy.set_demo_policy_provider(lambda: demo_policy.DemoPolicy())
        demo_policy.set_trial_dataset_access_provider(_deny_effective_source)
        monkeypatch.setattr(
            execute_route,
            "DAGExecutor",
            lambda *args, **kwargs: pytest.fail("unadmitted override reached DAG construction"),
        )
        try:
            response = await auth_client.post(
                "/api/v1/workflows/trial/execute",
                json={
                    "target_node_id": "source",
                    "trial_params": {"experiment_id": 999, "file_id": 1001, "stage": "raw"},
                    "nodes": [
                        {
                            "node_id": "source",
                            "node_type": "data.file_load",
                            "parameters": {"experiment_id": 1, "file_id": 2, "stage": "raw"},
                        }
                    ],
                    "edges": [],
                    "initial_data": None,
                    "project_id": 7,
                },
            )
        finally:
            demo_policy._demo_policy_provider = previous_policy
            demo_policy.set_trial_dataset_access_provider(previous_access)

        assert response.status_code == 403
        assert observed == [999]
