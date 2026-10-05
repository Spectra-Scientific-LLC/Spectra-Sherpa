"""End-to-end regression checks, optionally qualified with real Corn data.

Without CORN_MAT_PATH, generate an unrelated synthetic multi-asset MAT for CI.
Set CORN_MAT_PATH and optionally CORN_PROOF_DIR. CORN_AUDIT_BASELINE=1 records
the unmodified template failure and runs a clearly separate numerical control.
"""

import asyncio
import copy
import hashlib
import io
import json
import os
import runpy
import zipfile
from pathlib import Path

import numpy as np
import pytest

CASES = [
    ("m5-moisture", "m5spec", "Moisture", "pls", False),
    ("mp5-moisture", "mp5spec", "Moisture", "pls", False),
    ("mp6-moisture", "mp6spec", "Moisture", "pls", False),
    ("m5-protein", "m5spec", "Protein", "pls", False),
    ("m5-snv-moisture", "m5spec", "Moisture", "pls", True),
    ("m5-pcr-moisture", "m5spec", "Moisture", "pcr", False),
]


@pytest.fixture
def corn_source(tmp_path):
    if os.environ.get("CORN_MAT_PATH"):
        return Path(os.environ["CORN_MAT_PATH"])
    from scipy.io import savemat

    from tests.test_native_matlab_dso import _cell, _dso_struct

    rng = np.random.default_rng(419)
    x = rng.normal(size=(80, 12))
    y = x[:, :4] + rng.normal(scale=0.1, size=(80, 4))
    properties = _dso_struct(y, name="Synthetic properties")
    for field in (
        "axisscale",
        "axisscalename",
        "axisscaletype",
        "title",
        "titlename",
        "class",
        "classname",
        "classlookup",
    ):
        properties[field][0, 0] = _cell([[], []])
    properties["label"][0, 0] = _cell([[], [np.array(["Moisture", "Oil", "Protein", "Starch"], dtype=object)]])
    properties["labelname"][0, 0] = _cell([[], [np.array(["Responses"])]])
    properties["include"][0, 0] = _cell([[np.arange(1, 81)], [np.arange(1, 5)]])
    path = tmp_path / "synthetic-multiasset.mat"
    savemat(path, {"m5spec": x, "mp5spec": x * 1.02, "mp6spec": x + 0.03, "propvals": properties})
    return path


@pytest.mark.parametrize("name,asset,target,model,snv", CASES, ids=[c[0] for c in CASES])
@pytest.mark.asyncio
async def test_corn_journey(
    auth_client,
    test_session,
    test_user,
    test_engine,
    monkeypatch,
    tmp_path,
    name,
    asset,
    target,
    model,
    snv,
    corn_source,
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from spectra_sherpa.app.core.template_loader import TemplateLoader
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
    from spectra_sherpa.app.services import dataset_source_resolver
    from spectra_sherpa.app.types import type_registry
    from spectra_sherpa.io import ingest

    monkeypatch.setattr(
        dataset_source_resolver, "async_session", async_sessionmaker(test_engine, expire_on_commit=False)
    )
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")
    output = Path(os.environ.get("CORN_PROOF_DIR", str(tmp_path))) / name
    output.mkdir(parents=True, exist_ok=True)
    project = Project(user_id=test_user.id, name=name)
    template = WorkflowTemplate(**next(t for t in TemplateLoader().load_all() if t["slug"] == "pls_calibration"))
    graph = copy.deepcopy(template.template_data)
    test_session.add_all([project, template])
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=project.id, name=name, metadata_path="{}")
    test_session.add(experiment)
    await test_session.commit()
    project_id, experiment_id, template_id = project.id, experiment.id, template.id
    path = corn_source
    content = path.read_bytes()
    upload_data = {"stage": "raw", **({"data_role": "X_spectra"} if snv else {})}
    r = await auth_client.post(
        f"/api/v1/experiments/{experiment_id}/files",
        data=upload_data,
        files={"file": ("corn.mat", content, "application/octet-stream")},
    )
    assert r.status_code == 201, r.text
    file_id = r.json()["id"]
    target_file_id = file_id
    if snv:
        r = await auth_client.post(
            f"/api/v1/experiments/{experiment_id}/files",
            data={"stage": "raw"},
            files={"file": ("corn_targets.mat", content, "application/octet-stream")},
        )
        assert r.status_code == 201, r.text
        target_file_id = r.json()["id"]
    binding = {"source": "experiment", "experiment_id": experiment_id, "file_id": file_id, "stage": "raw"}
    authority = {
        "schema_version": "spectrasherpa-target-authority/1",
        "column": target,
        "target_type": "continuous",
        "units": None,
        "source_digest": hashlib.sha256(content).hexdigest(),
    }
    r = await auth_client.post(
        f"/api/v1/workflow-templates/{template_id}/instantiate",
        json={
            "workflow_name": name,
            "project_id": project_id,
            "data_bindings": {
                "data_1": {
                    **binding,
                    "asset_id": asset,
                    "target_binding": {
                        **binding,
                        "file_id": target_file_id,
                        "asset_id": "propvals",
                        "target_authority": authority,
                    },
                }
            },
        },
    )
    (output / "new-analysis.json").write_text(r.text)
    baseline = os.environ.get("CORN_AUDIT_BASELINE") == "1"
    if baseline:
        await test_session.refresh(test_user)
        nodes, edges = graph["nodes"], graph["edges"]
        for n in nodes:
            n.pop("example_binding", None)
            if n["node_id"] == "data_1":
                n["parameters"] = {
                    "experiment_id": experiment_id,
                    "file_id": file_id,
                    "stage": "raw",
                    "asset_id": asset,
                }
            if n["node_id"] == "eval_1":
                n["node_type"] = "diagnostics.regression_evaluator"
            if n["node_id"] in ("model_1", "eval_1"):
                n["parameters"]["target_names"] = [target]
        nodes.append(
            {
                "node_id": "target_source",
                "node_type": "data.file_load",
                "parameters": {
                    "experiment_id": experiment_id,
                    "file_id": target_file_id,
                    "stage": "raw",
                    "asset_id": "propvals",
                    "target_authority": authority,
                },
            }
        )
        edges = [e for e in edges if e.get("to_input") != "sample_context"]
        for e in edges:
            if e["from_node_id"] == "data_1" and e.get("from_output") == "target":
                e["from_node_id"] = "target_source"
        workflow_id = None
    else:
        assert r.status_code == 201, r.text
        workflow_id = r.json()["id"]
        nodes, edges = r.json()["nodes"], r.json()["edges"]
        nodes = [
            {k: n[k] for k in ("node_id", "node_type", "label", "parameters", "position_x", "position_y")}
            for n in nodes
        ]
        edges = [{k: e[k] for k in ("from_node_id", "to_node_id", "from_output", "to_input")} for e in edges]
    for n in nodes:
        if n["node_id"] == "model_1":
            n["node_type"] = "model.fitted_" + model
            if model == "pcr":
                n["parameters"].pop("target_names", None)
    if snv:
        nodes.append({"node_id": "snv", "node_type": "preprocess.normalize", "parameters": {"method": "snv"}})
        edge = next(e for e in edges if e["to_node_id"] == "partition_1" and e.get("to_input") == "X")
        edges.append({"from_node_id": edge["from_node_id"], "to_node_id": "snv"})
        edge["from_node_id"] = "snv"
    if workflow_id is None:
        r = await auth_client.post(
            "/api/v1/workflows",
            json={"name": name + " numerical control", "project_id": project_id, "nodes": nodes, "edges": edges},
        )
        assert r.status_code == 201, r.text
        workflow_id = r.json()["id"]
    else:
        r = await auth_client.put(f"/api/v1/workflows/{workflow_id}", json={"nodes": nodes, "edges": edges})
        assert r.status_code == 200, r.text
    r = await auth_client.post(f"/api/v1/workflows/{workflow_id}/execute", json={})
    (output / "execution.json").write_text(r.text)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["status"] == "completed", result["error"]
    assert all(s == "completed" for s in result["node_statuses"].values())
    values = result["results"]
    split = values["partition_1"]
    test, train = np.asarray(split["test_indices"]), np.asarray(split["train_indices"])
    assert len(test) == 20 and len(train) == 60 and not set(test) & set(train)
    y = np.asarray(split["y_test"]).reshape(-1)
    pred = np.asarray(values["predict_1"]["default"]).reshape(-1)
    raw = next(a.dataset for a in ingest(path).assets if a.asset_id == "propvals")
    np.testing.assert_allclose(y, raw.X[test, list(raw.feature_axis.labels).index(target)])
    metrics = values["eval_1"]["default"]
    np.testing.assert_allclose(metrics["rmse"], np.sqrt(np.mean((pred - y) ** 2)))
    np.testing.assert_allclose(metrics["r2"], 1 - np.sum((pred - y) ** 2) / np.sum((y - y.mean()) ** 2))
    assert metrics["population_authority"]["role"] == "held_out_test"
    if not baseline:
        source = next(a.dataset for a in ingest(path).assets if a.asset_id == asset)
        source_labels = source.sample_axis.labels if source.sample_axis is not None else None
        source_labels = source_labels or [f"Source row {i + 1}" for i in range(source.n_samples)]
        assert [row["sample"] for row in values["eval_1"]["comparison"]["data"]] == [source_labels[i] for i in test]
    assert values["viz_1"]["visualization"]["data"]
    assert values["table_1"]["visualization"]
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(name, metrics["rmse"], metrics["r2"])
    if not baseline:
        download = await auth_client.get(f"/api/v1/workflows/{workflow_id}/export/download", params={"format": "zip"})
        assert download.status_code == 200, download.text
        bundle_dir = tmp_path / "portable"
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            assert all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in archive.namelist())
            archive.extractall(bundle_dir)
        script = next(bundle_dir.glob("*/*_workflow.py"))
        monkeypatch.delenv("SHERPA_DATA_DIR", raising=False)
        monkeypatch.delenv("SPECTRA_REFERENCE_DIR", raising=False)
        exported = await asyncio.to_thread(lambda: runpy.run_path(str(script))["run_workflow"]())
        np.testing.assert_allclose(np.asarray(exported["predict_1"]["default"]).reshape(-1), pred, rtol=1e-12)
