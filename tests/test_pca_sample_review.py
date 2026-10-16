"""PCA review is an observation-preserving workflow edit, never a second fit."""

import numpy as np
import pytest
from scipy.stats import f, norm
from sklearn.decomposition import PCA

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset
from spectra_sherpa.app.services.dag.nodes.data.transforms import FilterSamplesNode
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode
from spectra_sherpa.app.services.pca_review_evidence import build_review_receipt, filter_id, review_path, sample_ids


def dataset():
    rng = np.random.default_rng(6242)
    x = rng.normal(size=(40, 8)) @ np.diag(np.arange(1, 9))
    x[-2:] += 40
    ds = SherpaDataset(
        X=x,
        sample_axis=SampleAxis(labels=[f"s{i:02}" for i in range(40)]),
        feature_axis=SpectralAxis(values=np.arange(8.0), units="cm^-1"),
        data_role="X_spectra",
    )
    ds.meta["source_collection"] = {"files": [{"sha256": "a" * 64}], "manifest_digest": "b" * 64}
    return ds


def definition(excluded=()):
    nodes = [
        {"node_id": "source", "node_type": "data.collection_load", "parameters": {}},
        {"node_id": "scale", "node_type": "preprocess.scale", "parameters": {"method": "autoscale"}},
        {"node_id": "pca", "node_type": "model.pca", "parameters": {"n_components": "2"}},
    ]
    if excluded:
        nodes.insert(
            1,
            {
                "node_id": filter_id("pca"),
                "node_type": "data.filter_samples",
                "parameters": {"field": "sample_label", "filter_values": list(excluded), "invert": True},
            },
        )
    edges = [
        {"from_node_id": a["node_id"], "to_node_id": b["node_id"], "from_output": "default", "to_input": "default"}
        for a, b in zip(nodes, nodes[1:])
    ]
    return {"nodes": nodes, "edges": edges}


async def run(ds, excluded=(), before_receipt=None):
    graph = definition(excluded)
    results = {"source": ds}
    current = ds
    if excluded:
        node = graph["nodes"][1]
        current = await FilterSamplesNode(node["node_id"], node["parameters"]).execute(X=current)
        current = current["default"]
        results[node["node_id"]] = current
    scaled = await ScaleNode("scale", {"method": "autoscale"}).execute(input_data=current)
    current = scaled.outputs["default"]
    results["scale"] = current
    results["pca"] = (await PCANode("pca", {"n_components": "2"}).execute(input_data=current)).outputs
    if before_receipt:
        before_receipt(results)
    return await build_review_receipt(graph, results, "pca")


@pytest.mark.asyncio
async def test_exclusion_fit_projection_limits_and_exact_restore():
    ds = dataset()
    original = await run(ds)
    receipt = await run(ds, ["s38", "s39"])
    training = ds.X[:-2]
    mean, scale = training.mean(axis=0), training.std(axis=0)
    ref = PCA(n_components=2, svd_solver="full").fit((training - mean) / scale)
    all_scores = ref.transform((ds.X - mean) / scale)
    actual_scores = np.asarray([r["scores"] for r in receipt["rows"]])
    signs = np.sign((actual_scores[:38] * all_scores[:38]).sum(axis=0))
    np.testing.assert_allclose(actual_scores, all_scores * signs, atol=1e-10)
    residuals = (ds.X - mean) / scale - ref.inverse_transform(all_scores)
    np.testing.assert_allclose([r["q"] for r in receipt["rows"]], (residuals**2).sum(axis=1), atol=1e-10)
    np.testing.assert_allclose(
        [r["t2"] for r in receipt["rows"]], (all_scores**2 / ref.explained_variance_).sum(axis=1), atol=1e-10
    )
    limit = 2 * 37 / 36 * f.ppf(0.95, 2, 36)
    assert receipt["calibration_t2_limit"] == pytest.approx(limit)
    assert receipt["application_t2_limit"] == pytest.approx(limit * 39 / 38)
    spectrum = PCA(svd_solver="full").fit((training - mean) / scale).explained_variance_[2:]
    theta1, theta2, theta3 = [np.sum(spectrum**power) for power in (1, 2, 3)]
    h0 = 1 - 2 * theta1 * theta3 / (3 * theta2**2)
    qlimit = theta1 * (
        1 + norm.ppf(0.95) * np.sqrt(2 * theta2) * h0 / theta1 + theta2 * h0 * (h0 - 1) / theta1**2
    ) ** (1 / h0)
    assert receipt["q_limit"] == pytest.approx(qlimit)
    assert receipt["n_calibration"] == 38
    assert [r["role"] for r in receipt["rows"]][-2:] == ["excluded_projected"] * 2
    assert receipt["source_digest"] == original["source_digest"]
    restored = await run(ds)
    assert restored["rows"] == original["rows"]
    assert restored["q_limit"] == original["q_limit"]


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["missing", "invalid_scale"])
async def test_excluded_projection_refuses_missing_or_incompatible_state_without_refitting(monkeypatch, corruption):
    from spectra_sherpa.app.lib.sherpa_dataset import Provenance

    def corrupt_and_block_fit(results):
        history = results["scale"].provenance.to_list()
        if corruption == "missing":
            history = []
        else:
            history[-1]["parameters"]["transform_state"]["scale"] = [1.0]
        results["scale"].provenance = Provenance.from_list(history)

        def forbidden_fit(*args, **kwargs):
            raise AssertionError("Excluded projection must never fit")

        monkeypatch.setattr(ScaleNode, "fit_fitted_state", forbidden_fit)

    receipt = await run(dataset(), ["s39"], before_receipt=corrupt_and_block_fit)
    assert receipt["n_calibration"] == 39
    excluded = receipt["rows"][-1]
    assert excluded["role"] == "excluded_projected"
    assert excluded["scores"] is None and excluded["q"] is None and excluded["t2"] is None
    assert excluded["projection_error"]
    assert all(row["scores"] is not None for row in receipt["rows"][:-1])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,params",
    [
        ("preprocess.normalize", {"method": "snv"}),
        ("preprocess.smooth", {"size": 5, "order": 2}),
        ("preprocess.derivative", {"size": 5, "order": 2}),
    ],
)
async def test_source_inclusion_and_samplewise_projection_preserve_identity(kind, params):
    from spectra_sherpa.app.services.dag.node_base import node_registry

    ds = dataset()
    ds.sample_axis = SampleAxis(
        labels=ds.sample_axis.labels,
        classes=np.asarray([f"class{i % 2}" for i in range(40)]),
        include_mask=np.asarray([False] + [True] * 39),
    )
    ds.target = np.arange(40.0)
    inclusion = {
        "node_id": "inclusion",
        "node_type": "data.filter_samples",
        "parameters": {"field": "source_inclusion"},
    }
    graph = definition(["s39"])
    graph["nodes"].insert(1, inclusion)
    graph["nodes"].insert(-1, {"node_id": "local", "node_type": kind, "parameters": params})
    graph["edges"] = [
        {"from_node_id": a["node_id"], "to_node_id": b["node_id"], "from_output": "default", "to_input": "default"}
        for a, b in zip(graph["nodes"], graph["nodes"][1:])
    ]
    current, results = ds, {"source": ds}
    for n in graph["nodes"][1:]:
        node = node_registry.create_node(n["node_type"], n["node_id"], n["parameters"])
        result = await node.execute(
            **({"X": current} if n["node_type"] == "data.filter_samples" else {"input_data": current})
        )
        outputs = result if isinstance(result, dict) else result.outputs
        results[n["node_id"]] = outputs
        if n["node_id"] != "pca":
            current = outputs["default"]
    np.testing.assert_array_equal(current.target, np.arange(1.0, 39.0))
    np.testing.assert_array_equal(current.sample_axis.classes, ds.sample_axis.classes[1:39])
    receipt = await build_review_receipt(graph, results, "pca")
    assert [r["id"] for r in receipt["rows"]] == [f"s{i:02}" for i in range(1, 40)]
    assert [r["group"] for r in receipt["rows"]] == list(ds.sample_axis.classes[1:])
    projected = receipt["rows"][-1]
    assert projected["role"] == "excluded_projected"
    assert projected["scores"] is not None
    assert np.isfinite(projected["q"]) and np.isfinite(projected["t2"])
    assert receipt["n_calibration"] == 38


@pytest.mark.parametrize("mutation", ["split", "branch", "folds", "unknown", "multiple_pca"])
def test_refuses_unsafe_graphs(mutation):
    graph = definition()
    if mutation == "split":
        graph["nodes"][1]["node_type"] = "data.train_test_split"
    if mutation == "unknown":
        graph["nodes"][1]["node_type"] = "preprocess.osc"
    if mutation == "branch":
        graph["edges"].append({**graph["edges"][0], "to_node_id": "pca"})
    if mutation == "folds":
        graph["fold_validation_plan"] = {"folds": [1, 2]}
    if mutation == "multiple_pca":
        graph["nodes"].append({"node_id": "other", "node_type": "model.pca"})
    with pytest.raises(ValueError):
        review_path(graph, "pca")


def test_never_guesses_duplicate_or_missing_ids():
    ds = dataset()
    ds.sample_axis = SampleAxis(labels=["duplicate"] * 40)
    with pytest.raises(ValueError, match="unique exact"):
        sample_ids(ds)
    ds.sample_axis = SampleAxis(values=np.arange(40.0))
    with pytest.raises(ValueError, match="unique exact"):
        sample_ids(ds)


@pytest.mark.asyncio
async def test_source_reload_event_time_does_not_change_identity():
    from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

    first, second = dataset(), dataset()
    add_processing_step(first, "data.collection_load", {"file": "same.csv"}, node_id="source")
    add_processing_step(second, "data.collection_load", {"file": "same.csv"}, node_id="source")
    a, b = await run(first), await run(second, ["s39"])
    assert a["source_digest"] == b["source_digest"]
    changed = dataset()
    changed.X[0, 0] += 1
    assert (await run(changed))["source_digest"] != a["source_digest"]


@pytest.mark.asyncio
async def test_http_review_loop_conflicts_restore_failure_and_rank_change(
    auth_client, test_session, test_user, monkeypatch, swap_user
):
    import importlib
    from datetime import datetime, timezone

    from sqlalchemy import select

    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.models.sample_review_revision import SampleReviewRevision
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
    from spectra_sherpa.app.models.workflow_node import WorkflowNode
    from spectra_sherpa.app.services.run_output_retention import retain_run_outputs
    from spectra_sherpa.app.services.workflow_data_selections import workflow_graph_digest

    routes = importlib.import_module("spectra_sherpa.app.api.v1.routes.workflows.sample_review")

    async def admitted(*args, **kwargs):
        pass

    monkeypatch.setattr(routes, "validate_selection", admitted)
    graph = definition()
    graph["nodes"][0]["parameters"] = {
        "experiment_id": 1,
        "source_manifest_sha256": "a" * 64,
        "scientific_collection_sha256": "b" * 64,
        "selected_file_ids": ["1"],
    }
    workflow = Workflow(
        user_id=test_user.id,
        name="Review",
        purpose="analysis",
        nodes=[
            WorkflowNode(node_id=n["node_id"], node_type=n["node_type"], parameters=n["parameters"])
            for n in graph["nodes"]
        ],
        edges=[WorkflowEdge(**e) for e in graph["edges"]],
    )
    test_session.add(workflow)
    await test_session.commit()
    original_graph = workflow_graph_digest(workflow)

    async def save_run(excluded=(), failed=False):
        receipt = await run(dataset(), excluded)
        receipt["graph_digest"] = workflow_graph_digest(workflow)
        record = ExecutionRun(
            user_id=test_user.id,
            workflow_id=workflow.id,
            name="PCA",
            status="failed" if failed else "completed",
            params_snapshot={},
            results_summary={},
            executed_at=datetime.now(timezone.utc),
            integrity_hash=receipt["graph_digest"],
            evidence_completeness=retain_run_outputs(
                test_user.id, {"__workflow__": {"pca_review": {} if failed else {"pca": receipt}}}, {}
            ),
        )
        test_session.add(record)
        await test_session.commit()
        return record

    original_run = await save_run()
    path = f"/api/v1/workflows/{workflow.id}/sample-review/pca"

    async def context():
        response = await auth_client.get(path)
        assert response.status_code == 200, response.text
        return response.json()

    def action(ctx, kind, ids):
        return {
            "run_id": ctx["run_id"],
            "expected_latest_run_id": ctx["latest_run_id"],
            "expected_revision": ctx["revision"],
            "expected_graph_digest": ctx["graph_digest"],
            "source_digest": ctx["source_digest"],
            "action": kind,
            "sample_ids": ids,
            "reason": "Inspect high Q acquisition",
        }

    ctx = await context()
    from spectra_sherpa.app.models.user import User

    other = User(username="other-reviewer")
    test_session.add(other)
    await test_session.commit()
    swap_user(other)
    assert (await auth_client.get(path)).status_code == 404
    assert (await auth_client.post(path, json=action(ctx, "mark", ["s39"]))).status_code == 404
    swap_user(test_user)
    assert (await auth_client.post(path, json=action(ctx, "mark", ["foreign-id"]))).status_code == 400
    assert (await auth_client.post(path, json={**action(ctx, "mark", ["s39"]), "reason": " "})).status_code == 422
    assert (
        await auth_client.post(path, json={**action(ctx, "mark", ["s39"]), "source_digest": "f" * 64})
    ).status_code == 409
    marked = await auth_client.post(path, json=action(ctx, "mark", ["s39"]))
    assert marked.status_code == 200, marked.text
    stale = await auth_client.post(path, json=action(ctx, "mark", ["s38"]))
    assert stale.status_code == 409
    ctx = await context()
    assert ctx["state"]["marked"] == ["s39"]
    excluded = await auth_client.post(path, json=action(ctx, "exclude", ["s39"]))
    assert excluded.status_code == 200, excluded.text
    await test_session.refresh(workflow, attribute_names=["nodes", "edges"])
    assert next(n for n in workflow.nodes if n.node_id == filter_id("pca")).parameters["filter_values"] == ["s39"]
    assert any(e.to_node_id == filter_id("pca") and e.to_input == "X" for e in workflow.edges)
    stale_save = await auth_client.put(f"/api/v1/workflows/{workflow.id}", json=graph)
    assert stale_save.status_code == 409, stale_save.text
    assert "Restore" in stale_save.text or "restore" in stale_save.text
    proposed = {
        "nodes": [{"node_id": n.node_id, "node_type": n.node_type, "parameters": n.parameters} for n in workflow.nodes],
        "edges": [
            {k: getattr(e, k) for k in ("from_node_id", "to_node_id", "from_output", "to_input")}
            for e in workflow.edges
        ],
    }
    proposed["nodes"][0]["parameters"] = {**proposed["nodes"][0]["parameters"], "experiment_id": 99}
    replaced = await auth_client.put(f"/api/v1/workflows/{workflow.id}", json=proposed)
    assert replaced.status_code == 409, replaced.text
    assert "source" in replaced.text
    selection_routes = importlib.import_module("spectra_sherpa.app.api.v1.routes.workflows.data_selections")
    monkeypatch.setattr(selection_routes, "validate_selection", admitted)
    source_edit = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/data-selections/source",
        json={
            "expected_revision": None,
            "idempotency_key": "review-source-rebind-0001",
            "origin": "data_page",
            "reason": "different source",
            "selection": {
                "experiment_id": 99,
                "dataset_name": "Other",
                "stage": "raw",
                "source_manifest_sha256": "a" * 64,
                "scientific_collection_sha256": "b" * 64,
                "selected_file_ids": ["1"],
            },
        },
    )
    assert source_edit.status_code == 409, source_edit.text
    deletion = await auth_client.delete(f"/api/v1/workflows/{workflow.id}/runs/{original_run.id}")
    assert deletion.status_code == 409, deletion.text
    await save_run(["s39"])
    ctx = await context()
    assert ctx["state"]["excluded"] == ["s39"] and not ctx["stale"]
    # A new PCA setting and fresh evidence must not permanently strand the review.
    pca_node = next(n for n in workflow.nodes if n.node_id == "pca")
    pca_node.parameters = {"n_components": "2", "standardized": True}
    await test_session.commit()
    await save_run(["s39"])
    ctx = await context()
    assert (await auth_client.post(path, json=action(ctx, "unmark", ["s39"]))).status_code == 200
    # Failed refit has no PCA receipt, but the exact owned edit remains reversible.
    await save_run(["s39"], failed=True)
    ctx = await context()
    assert ctx["stale"]
    restored = await auth_client.post(path, json=action(ctx, "restore", ["s39"]))
    assert restored.status_code == 200, restored.text
    await test_session.refresh(workflow, attribute_names=["nodes", "edges"])
    assert len(workflow.nodes) == 3
    assert pca_node.parameters["standardized"] is True  # preserve unrelated authored settings
    pca_node.parameters = {"n_components": "2"}
    assert workflow_graph_digest(workflow) == original_graph
    history = list((await test_session.scalars(select(SampleReviewRevision))).all())
    assert len(history) == 4 and history[0].run_id == original_run.id
    # Copied generated filter must not gain authority from its reserved name.
    workflow.nodes.append(WorkflowNode(node_id=filter_id("pca"), node_type="data.filter_samples", parameters={}))
    await test_session.commit()
    refused = await auth_client.get(path)
    assert refused.status_code == 409


@pytest.mark.asyncio
async def test_real_http_execute_exclude_project_and_restore(auth_client, test_session, test_user, monkeypatch):
    """Real upload, source custody, executor, retention and review API: no patched science."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from spectra_sherpa.app.db import session as db_session
    from spectra_sherpa.app.lib.export_artifact import build_export_artifact

    monkeypatch.setattr(db_session, "async_session", async_sessionmaker(test_session.bind, expire_on_commit=False))
    from spectra_sherpa.app.schemas.workflow_data_selection import WorkflowSourceSelection
    from spectra_sherpa.app.services.model_application import load_project_dataset
    from spectra_sherpa.app.services.workflow_data_selections import source_parameters

    project = await auth_client.post("/api/v1/projects", json={"name": "PCA diagnostic qualification"})
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    experiment = await auth_client.post(
        "/api/v1/experiments", json={"name": "Synthetic calibration", "project_id": pid}
    )
    assert experiment.status_code == 201, experiment.text
    eid = experiment.json()["id"]
    artifact = build_export_artifact(dataset(), filename="spectra.csv", format="csv")
    upload = await auth_client.post(
        f"/api/v1/experiments/{eid}/files",
        data={"stage": "raw"},
        files={"file": ("spectra.csv", artifact["content"].encode(), "text/csv")},
    )
    assert upload.status_code == 201, upload.text
    loaded = await load_project_dataset(test_session, user_id=test_user.id, experiment_id=eid)
    source = source_parameters(
        WorkflowSourceSelection(
            experiment_id=eid,
            dataset_name="Calibration",
            stage="raw",
            selected_file_ids=loaded.file_ids,
            source_manifest_sha256=loaded.source_manifest_sha256,
            collection_definition_sha256=loaded.collection_definition_sha256,
            scientific_collection_sha256=loaded.scientific_collection_sha256,
            asset_id=loaded.asset_id,
        )
    )
    graph = definition()
    graph["nodes"][0]["parameters"] = source
    created = await auth_client.post(
        "/api/v1/workflows", json={"name": "PCA review journey", "project_id": pid, **graph}
    )
    assert created.status_code == 201, created.text
    wid = created.json()["id"]
    endpoint = f"/api/v1/workflows/{wid}"
    assert (await auth_client.get(endpoint + "/sample-review/pca")).status_code == 409

    async def execute():
        result = await auth_client.post(endpoint + "/execute", json={})
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "completed", result.text
        review = await auth_client.get(endpoint + "/sample-review/pca")
        assert review.status_code == 200, review.text
        assert not review.json()["stale"]
        explanation = review.json()["explanations"]
        assert "unavailable_reason" not in explanation, explanation
        assert explanation["reference_count"] == review.json()["n_calibration"]
        assert len(explanation["rows"]) == len(review.json()["rows"])
        return review.json()

    temporary = await auth_client.post(endpoint + "/execute", json={"initial_data": {"pca": {"n_components": "3"}}})
    assert temporary.status_code == 200 and temporary.json()["status"] == "completed", temporary.text
    unavailable = await auth_client.get(endpoint + "/sample-review/pca")
    assert unavailable.status_code == 409 and "temporary" in unavailable.text, unavailable.text
    original = await execute()
    assert original["n_calibration"] == 40
    chosen = original["rows"][-1]["id"]

    async def decide(ctx, action):
        response = await auth_client.post(
            endpoint + "/sample-review/pca",
            json={
                "run_id": ctx["run_id"],
                "expected_latest_run_id": ctx["latest_run_id"],
                "expected_revision": ctx["revision"],
                "expected_graph_digest": ctx["graph_digest"],
                "source_digest": ctx["source_digest"],
                "action": action,
                "sample_ids": [chosen],
                "reason": "Inspect synthetic acquisition outlier",
            },
        )
        assert response.status_code == 200, response.text

    await decide(original, "exclude")
    override = await auth_client.post(
        endpoint + "/execute", json={"initial_data": {filter_id("pca"): {"invert": False}}}
    )
    assert override.status_code == 422, override.text
    excluded = await execute()
    assert excluded["n_calibration"] == 39
    assert excluded["rows"][-1]["role"] == "excluded_projected"
    assert excluded["rows"][-1]["scores"] is not None, excluded["rows"][-1]
    assert excluded["source_digest"] == original["source_digest"]
    await decide(excluded, "restore")
    restored = await execute()
    assert restored["rows"] == original["rows"]
    assert restored["calibration_t2_limit"] == original["calibration_t2_limit"]
    assert restored["q_limit"] == original["q_limit"]
    assert restored["graph_digest"] == original["graph_digest"]
    unchanged = await load_project_dataset(test_session, user_id=test_user.id, experiment_id=eid)
    assert unchanged.scientific_collection_sha256 == loaded.scientific_collection_sha256


def test_review_migration_upgrade_idempotence_and_downgrade(tmp_path):
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).parents[1] / "src/spectra_sherpa/alembic/versions/k0l2m4n6o658_sample_review.py"
    spec = importlib.util.spec_from_file_location("review_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as conn:
        for table in ("workflow", "execution_run", "user"):
            conn.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()
            assert sa.inspect(conn).has_table("sample_review_revision")
            keys = sa.inspect(conn).get_foreign_keys("sample_review_revision")
            assert next(k for k in keys if k["referred_table"] == "execution_run")["options"]["ondelete"] == "RESTRICT"
            migration.downgrade()
            assert not sa.inspect(conn).has_table("sample_review_revision")
    engine.dispose()
