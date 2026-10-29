"""Starter checks use the actual bundled specimen populations and split authority."""

import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset
from spectra_sherpa.app.services.dag.nodes.data.transforms import TrainTestSplitNode
from spectra_sherpa.app.services.starter_validation import preview_starter_validation


def lavender(target="claimed_botanical_group"):
    archive = Path(__file__).parents[1] / "src/spectra_sherpa/data/reference/lavender-essential-oil-v1.zip"
    with zipfile.ZipFile(archive) as z:
        definition = json.loads(
            z.read(next(name for name in z.namelist() if name.endswith("collection-definition.json")))
        )
    rows = [
        row["annotations"]
        for row in definition["rows"]
        if row["annotations"]["analysis_role"] == "oil" or target == "author_reported_authenticity_status"
    ]
    table = {key: [row.get(key) for row in rows] for key in definition["columns"]}
    ds = SherpaDataset(
        X=np.random.default_rng(24).normal(size=(len(rows), 4)),
        sample_axis=SampleAxis(labels=table["sample_id"], sample_table=table),
    )
    ds.meta["source_collection"] = {
        "manifest_digest": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "collection_definition_sha256": hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest(),
        "scientific_collection_sha256": hashlib.sha256(
            ds.X.tobytes() + json.dumps(table, sort_keys=True).encode()
        ).hexdigest(),
    }
    return attach_target_dataset(
        ds,
        None,
        target_type="categorical",
        target_source="sample_table_column",
        target_column=target,
        group_column="specimen_id",
        node_id="target",
    )


def graph(parameters=None):
    return (
        [
            {"node_id": "source", "node_type": "data.file_load", "parameters": {}},
            {
                "node_id": "split",
                "node_type": "data.train_test_split",
                "parameters": parameters or {"split_method": "stratified", "test_size": 0.25, "random_seed": 42},
            },
            {"node_id": "model", "node_type": "classification.plsda", "parameters": {}},
        ],
        [
            {"from_node_id": "source", "to_node_id": "split", "to_input": "X"},
            {"from_node_id": "split", "from_output": "X_train", "to_node_id": "model", "to_input": "X"},
        ],
    )


@pytest.mark.asyncio
async def test_real_lavender_botanical_holdout_valid_but_component_cv_unavailable():
    ds = lavender()
    nodes, edges = graph()
    preview = await preview_starter_validation(nodes, edges, {"source": ds})
    assert preview["status"] == "feasible"
    split = preview["splits"][0]
    assert split["component_cv"]["status"] == "unavailable"
    assert split["training_count"] + split["held_out_count"] == ds.n_samples
    executed = await TrainTestSplitNode("split", nodes[1]["parameters"]).execute(X=ds)
    assert executed["X_train"].provenance.to_list()[-1]["parameters"]["digest"] == split["split_digest"]


@pytest.mark.asyncio
async def test_real_lavender_singleton_authenticity_class_refused_before_workflow():
    nodes, edges = graph()
    preview = await preview_starter_validation(
        nodes, edges, {"source": lavender("author_reported_authenticity_status")}
    )
    assert preview["status"] == "refused"
    assert "partition" in preview["reason"]


@pytest.mark.asyncio
async def test_unknown_upstream_transform_is_not_claimed_as_checked():
    nodes, edges = graph()
    nodes.insert(1, {"node_id": "transform", "node_type": "preprocess.normalize", "parameters": {}})
    edges[0]["from_node_id"] = "transform"
    edges.append({"from_node_id": "source", "to_node_id": "transform"})
    assert (await preview_starter_validation(nodes, edges, {"source": lavender()}))["status"] == "not_checked"


@pytest.mark.asyncio
async def test_exclusions_and_actual_filter_are_applied_before_feasibility():
    ds = lavender()
    # Drop every specimen of one class except a single independent specimen.
    table = ds.sample_axis.sample_table
    minority = table["claimed_botanical_group"][1]
    specimen = next(
        table["specimen_id"][i] for i, value in enumerate(table["claimed_botanical_group"]) if value == minority
    )
    axis = ds.sample_axis
    axis.include_mask = [
        value != minority or table["specimen_id"][i] == specimen
        for i, value in enumerate(table["claimed_botanical_group"])
    ]
    ds.sample_axis = axis
    nodes, edges = graph()
    nodes.insert(
        1, {"node_id": "filter", "node_type": "data.filter_samples", "parameters": {"field": "source_inclusion"}}
    )
    edges[0]["from_node_id"] = "filter"
    edges.append({"from_node_id": "source", "to_node_id": "filter"})
    preview = await preview_starter_validation(nodes, edges, {"source": ds})
    assert preview["status"] == "refused"


def categorical_source(labels, mask=None):
    ids = [f"sample-{index}" for index in range(len(labels))]
    ds = SherpaDataset(
        np.random.default_rng(13).normal(size=(len(labels), 4)),
        sample_axis=SampleAxis(labels=ids, include_mask=mask, sample_table={"sample_id": ids, "class": labels}),
    )
    ds.meta["source_collection"] = {
        key: "c" * 64 for key in ("manifest_digest", "collection_definition_sha256", "scientific_collection_sha256")
    }
    return attach_target_dataset(
        ds,
        None,
        target_type="categorical",
        target_source="sample_table_column",
        target_column="class",
        node_id="target",
    )


@pytest.mark.asyncio
async def test_preview_matches_execution_when_source_inclusion_precedes_index_filter():
    from spectra_sherpa.app.lib.workflow_population import source_population_outputs
    from spectra_sherpa.app.services.dag.nodes.data.transforms import FilterSamplesNode

    ds = categorical_source(["A", "B"] * 6, [True, False] + [True] * 10)
    nodes, edges = graph()
    nodes.insert(
        1,
        {
            "node_id": "filter",
            "node_type": "data.filter_samples",
            "parameters": {"field": "sample_index", "pattern": "1-8"},
        },
    )
    edges[0]["from_node_id"] = "filter"
    edges.append({"from_node_id": "source", "to_node_id": "filter"})
    preview = await preview_starter_validation(nodes, edges, {"source": ds})
    assert preview["status"] == "feasible"
    source = source_population_outputs(ds, node_id="source", source_binding={})["default"]
    filtered = await FilterSamplesNode("filter", nodes[1]["parameters"]).execute(X=source)
    executed = await TrainTestSplitNode("split", nodes[2]["parameters"]).execute(X=filtered["default"])
    assert preview["splits"][0]["training_count"] == executed["X_train"].n_samples == 6
    assert preview["splits"][0]["held_out_count"] == executed["X_test"].n_samples == 2
    assert preview["splits"][0]["split_digest"] == executed["X_train"].provenance.to_list()[-1]["parameters"]["digest"]


@pytest.mark.asyncio
async def test_constructible_split_with_single_class_training_is_refused():
    ds = categorical_source(["A"] * 6 + ["B"] * 6)
    nodes, edges = graph({"split_method": "sequential", "test_size": 0.5})
    preview = await preview_starter_validation(nodes, edges, {"source": ds})
    assert preview["status"] == "refused"
    assert "at least two classes" in preview["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["all_files", "file_ids"])
@pytest.mark.parametrize("case", ["singleton", "filtered", "excluded"])
async def test_bound_preview_and_instantiation_agree_on_collection_population(
    auth_client,
    test_session,
    test_user,
    monkeypatch,
    scope,
    case,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sqlalchemy import func, select

    from spectra_sherpa.app.api.v1.routes import workflow_templates as routes
    from spectra_sherpa.app.core.template_loader import TemplateLoader
    from spectra_sherpa.app.lib.target_authority import issue_target_authority
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
    from spectra_sherpa.app.types import ensure_type_registry_loaded

    ensure_type_registry_loaded()

    ds = lavender("author_reported_authenticity_status") if case == "singleton" else categorical_source(["A", "B"] * 7)
    column = "author_reported_authenticity_status" if case == "singleton" else "class"
    group = "specimen_id" if case == "singleton" else None
    if case == "excluded":
        axis = ds.sample_axis
        axis.include_mask = [False] * ds.n_samples
        ds.sample_axis = axis
    if case == "filtered":
        axis = ds.sample_axis
        axis.sample_table["specimen_id"] = [f"specimen-{i}" for i in range(12)] + ["duplicate", "duplicate"]
        ds.sample_axis = axis
        ds = attach_target_dataset(
            ds,
            None,
            target_type="categorical",
            target_source="sample_table_column",
            target_column=column,
            node_id="target",
        )
    definition = next(t for t in TemplateLoader().load_all() if t["slug"] == "classification_plsda")
    if case == "excluded":
        graph_data = definition["template_data"]
        graph_data["nodes"].append(
            {
                "node_id": "normalize",
                "node_type": "preprocess.normalize",
                "parameters": {},
                "position_x": 100,
                "position_y": 100,
            }
        )
        for edge in graph_data["edges"]:
            if edge["from_node_id"] == "data_1" and edge["to_node_id"] == "partition_1":
                edge["from_node_id"] = "normalize"
        graph_data["edges"].append(
            {"from_node_id": "data_1", "to_node_id": "normalize", "from_output": "default", "to_input": "default"}
        )
    if case == "filtered":
        graph_data = definition["template_data"]
        graph_data["nodes"].append(
            {
                "node_id": "cohort",
                "node_type": "data.filter_samples",
                "label": "Select cohort",
                "parameters": {"field": "sample_index", "pattern": "1-12"},
                "position_x": 175,
                "position_y": 150,
            }
        )
        for edge in graph_data["edges"]:
            if edge["from_node_id"] == "data_1" and edge["to_node_id"] == "partition_1":
                edge["from_node_id"] = "cohort"
        graph_data["edges"].append(
            {"from_node_id": "data_1", "to_node_id": "cohort", "from_output": "default", "to_input": "X"}
        )
    template = WorkflowTemplate(
        **{key: definition[key] for key in ("slug", "name", "description", "category")},
        template_data={**definition["template_data"], "status": "ready"},
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Starter population audit")
    test_session.add_all([template, project])
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=project.id, name="Population fixture", metadata_path="{}")
    test_session.add(experiment)
    await test_session.commit()
    loaded = SimpleNamespace(
        dataset=ds,
        experiment_name=experiment.name,
        stage="raw",
        file_ids=[901],
        source_manifest_sha256=ds.meta["source_collection"]["manifest_digest"],
        collection_definition_sha256=ds.meta["source_collection"]["collection_definition_sha256"],
        scientific_collection_sha256=ds.meta["source_collection"]["scientific_collection_sha256"],
    )
    monkeypatch.setattr(routes, "load_project_dataset", AsyncMock(return_value=loaded))
    binding = {
        "source": "experiment",
        "experiment_id": experiment.id,
        "stage": "raw",
        scope: True if scope == "all_files" else [901],
        "target_authority": issue_target_authority(ds, column=column, target_type="categorical").canonical_dict(),
        "group_column": group,
    }
    preview = await auth_client.post(
        "/api/v1/workflow-templates/binding-compatibility-preview", json={"project_id": project.id, "binding": binding}
    )
    assert preview.status_code == 200, preview.text
    decision = next(d for d in preview.json()["decisions"] if d["template_slug"] == template.slug)
    assert (
        decision["validation_preview"]["status"]
        == {"singleton": "refused", "filtered": "feasible", "excluded": "not_checked"}[case]
    )
    before = await test_session.scalar(select(func.count()).select_from(Workflow))
    instantiated = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Must not persist",
            "project_id": project.id,
            "launch_mode": "user",
            "data_bindings": {"data_1": binding},
        },
    )
    if case in {"singleton", "excluded"}:
        assert instantiated.status_code == 409, instantiated.text
        if case == "singleton":
            assert instantiated.json()["detail"] == decision["validation_preview"]["reason"]
        else:
            assert "active workflow observation" in instantiated.json()["detail"]
        assert await test_session.scalar(select(func.count()).select_from(Workflow)) == before
    else:
        assert instantiated.status_code == 201, instantiated.text
        assert await test_session.scalar(select(func.count()).select_from(Workflow)) == before + 1


@pytest.mark.asyncio
async def test_unchecked_branch_does_not_recheck_filtered_out_specimens_on_other_branch():
    from spectra_sherpa.app.api.v1.routes.workflow_templates import DataBindingSpec, _require_starter_validation
    from spectra_sherpa.app.lib.target_authority import issue_target_authority

    curated = categorical_source(["A", "B"] * 7)
    axis = curated.sample_axis
    axis.sample_table["specimen_id"] = [f"s{i}" for i in range(12)] + ["repeat", "repeat"]
    curated.sample_axis = axis
    other = categorical_source(["A", "B"] * 6)
    nodes, edges = graph()
    nodes.insert(
        1,
        {
            "node_id": "filter",
            "node_type": "data.filter_samples",
            "parameters": {"field": "sample_index", "pattern": "1-12"},
        },
    )
    edges[0]["from_node_id"] = "filter"
    edges.append({"from_node_id": "source", "to_node_id": "filter"})
    nodes.extend(
        [
            {"node_id": "other", "node_type": "data.file_load", "parameters": {}},
            {"node_id": "normalize", "node_type": "preprocess.normalize", "parameters": {}},
            {"node_id": "other_split", "node_type": "data.train_test_split", "parameters": {}},
        ]
    )
    edges.extend(
        [
            {"from_node_id": "other", "to_node_id": "normalize"},
            {"from_node_id": "normalize", "to_node_id": "other_split"},
        ]
    )
    sources = {"source": curated, "other": other}
    bindings = {
        key: DataBindingSpec(
            source="experiment",
            experiment_id=index + 1,
            all_files=True,
            target_authority=issue_target_authority(ds, column="class", target_type="categorical"),
        )
        for index, (key, ds) in enumerate(sources.items())
    }
    await _require_starter_validation(
        nodes, edges, sources, bindings, validation_goal="unseen_specimens", held_out_groups=None
    )
    # A shared source also feeding the unchecked branch must still be guarded.
    edges[-2]["from_node_id"] = "source"
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        await _require_starter_validation(
            nodes, edges, sources, bindings, validation_goal="unseen_specimens", held_out_groups=None
        )
    assert error.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("sample_count,expected", [(60, "feasible"), (5, "refused")])
async def test_automatic_pls_preflight_checks_inner_training_population(sample_count, expected):
    from spectra_sherpa.app.lib.sherpa_dataset import TargetContext

    rng = np.random.default_rng(165)
    source = SherpaDataset(
        X=rng.normal(size=(sample_count, 4)),
        target=rng.normal(size=sample_count),
        target_context=TargetContext(target_type="continuous", target_name="moisture", target_units="ppm"),
    )
    nodes = [
        {"node_id": "source", "node_type": "data.file_load", "parameters": {}},
        {"node_id": "split", "node_type": "data.train_test_split", "parameters": {"test_size": 0.25}},
        {
            "node_id": "pls",
            "node_type": "model.fitted_pls",
            "parameters": {"component_fit_mode": "one_standard_error", "component_cv_folds": 5},
        },
    ]
    edges = [
        {"from_node_id": "source", "to_node_id": "split", "from_output": "default"},
        {"from_node_id": "split", "to_node_id": "pls", "from_output": "X_train"},
    ]
    preview = await preview_starter_validation(nodes, edges, {"source": source})
    assert preview["status"] == expected
    if expected == "feasible":
        assert preview["splits"][0]["component_cv"]["status"] == "population_feasible"
    else:
        assert "independent training samples" in preview["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("repeats", ["training", "held_out", "none"])
async def test_automatic_pls_preflight_checks_independence_of_training_rows_only(repeats):
    from spectra_sherpa.app.lib.sherpa_dataset import TargetContext
    from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node

    X = np.random.default_rng(88).normal(size=(40, 8))
    specimens = [f"s{i}" for i in range(40)]
    if repeats == "training":
        specimens[:30] = [f"train{i // 2}" for i in range(30)]
    elif repeats == "held_out":
        specimens[30:] = [f"test{i // 2}" for i in range(10)]
    source = SherpaDataset(
        X=X,
        target=X[:, 0] + 0.2 * X[:, 1],
        target_context=TargetContext(target_type="continuous", target_name="y", target_names=["y"]),
        sample_axis=SampleAxis(
            labels=[f"r{i}" for i in range(40)],
            sample_table={
                "assignment": ["Training"] * 30 + ["Test"] * 10,
                "specimen_id": specimens,
            },
        ),
    )
    source.meta["csv.assignment_column"] = "assignment"
    split_params = {"split_method": "group_holdout", "held_out_groups": ["Test"]}
    model_params = {"component_fit_mode": "one_standard_error", "component_cv_folds": 5, "component_curve_max": 4}
    nodes = [
        {"node_id": "source", "node_type": "data.file_load", "parameters": {}},
        {"node_id": "split", "node_type": "data.train_test_split", "parameters": split_params},
        {"node_id": "model", "node_type": "model.fitted_pls", "parameters": model_params},
    ]
    edges = [
        {"from_node_id": "source", "to_node_id": "split", "from_output": "default"},
        {"from_node_id": "split", "to_node_id": "model", "from_output": "X_train"},
    ]
    preview = await preview_starter_validation(nodes, edges, {"source": source})
    split = await TrainTestSplitNode("split", split_params).execute(X=source)
    if repeats == "training":
        assert preview["status"] == "refused"
        assert "Repeated specimen_id" in preview["reason"]
        with pytest.raises(ValueError, match="Repeated specimen_id"):
            await FittedPLSV2Node("model", model_params).execute(input_data=split["X_train"])
    else:
        assert preview["status"] == "feasible"
        assert preview["splits"][0]["training_count"] == 30
        await FittedPLSV2Node("model", model_params).execute(input_data=split["X_train"])
