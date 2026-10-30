"""Group loss is refused per validation consumer, not per source binding."""

from copy import deepcopy

import pytest

from spectra_sherpa.app.api.v1.routes import workflow_templates as routes
from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.types import ensure_type_registry_loaded


def binding():
    return routes.DataBindingSpec(
        source="experiment",
        experiment_id=1,
        file_id=2,
        stage="raw",
        group_column="specimen_id",
        target_authority={
            "schema_version": "spectrasherpa-target-authority/1",
            "column": "Response",
            "target_type": "continuous",
            "units": None,
            "source_digest": "a" * 64,
        },
    )


@pytest.mark.parametrize(
    "slug,refused",
    [
        ("pca", False),
        ("preprocessing", False),
        ("pls_calibration", True),
        ("classification_plsda", True),
        ("nested_cv_validation", True),
    ],
)
def test_group_refusal_follows_each_starter_graph(slug, refused):
    ensure_type_registry_loaded()
    template = next(t for t in TemplateLoader().load_all() if t["slug"] == slug)
    graph = template["template_data"]
    b = binding()
    assert routes._binding_to_file_load_params(b)["file_id"] == 2
    reason = routes._starter_group_binding_refusal(graph["nodes"], graph["edges"], {"data_1": b})
    assert bool(reason) == refused
    if reason:
        assert "Data Portfolio" in reason
    collection = b.model_copy(update={"file_id": None, "file_ids": [2]})
    assert routes._starter_group_binding_refusal(graph["nodes"], graph["edges"], {"data_1": collection}) is None


def test_group_refusal_does_not_leak_between_unconnected_sources():
    ensure_type_registry_loaded()
    nodes = [
        {"node_id": "a", "node_type": "data.file_load"},
        {"node_id": "b", "node_type": "data.file_load"},
        {"node_id": "pca", "node_type": "model.pca"},
        {"node_id": "split", "node_type": "data.train_test_split"},
    ]
    edges = [{"from_node_id": "a", "to_node_id": "pca"}, {"from_node_id": "b", "to_node_id": "split"}]
    assert routes._starter_group_binding_refusal(nodes, edges, {"a": binding()}) is None


@pytest.mark.parametrize(
    "slug",
    [
        "pls_calibration",
        "classification_plsda",
        "knn_classification",
        "simca_classification",
        "representative_calibration",
    ],
)
def test_all_starters_preserve_explicit_partition(slug):
    template = next(t for t in TemplateLoader().load_all() if t["slug"] == slug)
    graph = deepcopy(template["template_data"])
    routes._adapt_starter_to_source_assignment(
        analysis_profile={"source_assignment": {"validation_label": "Validation"}},
        nodes=graph["nodes"],
        edges=graph["edges"],
        source_node_id="data_1",
    )
    splits = [n for n in graph["nodes"] if n["node_type"] == "data.train_test_split"]
    assert splits and all(n["parameters"]["split_method"] == "group_holdout" for n in splits)
    assert all(n["parameters"]["held_out_groups"] == ["Validation"] for n in splits)


def test_source_assignment_does_not_change_other_source_or_inner_split():
    nodes = [
        {"node_id": n, "node_type": "data.train_test_split", "parameters": {"split_method": "random"}}
        for n in ("outer", "inner", "other")
    ]
    edges = [
        {"from_node_id": "a", "to_node_id": "outer"},
        {"from_node_id": "outer", "to_node_id": "inner"},
        {"from_node_id": "b", "to_node_id": "other"},
    ]
    routes._adapt_starter_to_source_assignment(
        analysis_profile={"source_assignment": {"validation_label": "Validation"}},
        nodes=nodes,
        edges=edges,
        source_node_id="a",
    )
    assert nodes[0]["parameters"]["split_method"] == "group_holdout"
    assert nodes[1]["parameters"]["split_method"] == nodes[2]["parameters"]["split_method"] == "random"


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["classification_plsda", "knn_classification", "simca_classification"])
async def test_classifier_http_starter_uses_declared_training_validation_rows(
    auth_client, test_session, test_user, slug
):
    import hashlib

    from spectra_sherpa.app.lib.io import load_csv_as_sherpa
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
    from spectra_sherpa.app.services.dag.nodes.data.transforms import TrainTestSplitNode
    from spectra_sherpa.app.services.experiments import relative_to_data_dir
    from spectra_sherpa.app.services.prepared_data import save_prepared_data_overrides
    from spectra_sherpa.core.prepared_data import apply_dataset_prepared_data_overrides
    from tests.test_canonical_template_project_corpus import _bound_source, _template_record

    ensure_type_registry_loaded()
    project = Project(user_id=test_user.id, name="Explicit classifier partition")
    template = WorkflowTemplate(**_template_record(slug))
    test_session.add_all([project, template])
    await test_session.flush()
    experiment, source_file = await _bound_source(
        session=test_session, user=test_user, project=project, node_id="data_1"
    )
    path = routes.experiment_dir(experiment.id) / source_file.file_path
    path.write_text(
        "Class,f1,f2,Assignment\n"
        + "".join(f"{'A' if i % 2 else 'B'},{i},{i*i},{'Training' if i < 18 else 'Validation'}\n" for i in range(24))
    )
    overrides = {"target_column": "Class", "target_type": "categorical", "assignment_column": "Assignment"}
    save_prepared_data_overrides(overrides, file_path=relative_to_data_dir(path))
    binding = {
        "source": "experiment",
        "experiment_id": experiment.id,
        "file_id": source_file.id,
        "stage": "raw",
        "target_authority": {
            "schema_version": "spectrasherpa-target-authority/1",
            "column": "Class",
            "target_type": "categorical",
            "units": None,
            "source_digest": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    }
    await test_session.commit()
    preview = await auth_client.post(
        "/api/v1/workflow-templates/binding-compatibility-preview", json={"project_id": project.id, "binding": binding}
    )
    assert preview.status_code == 200, preview.text
    decision = next(d for d in preview.json()["decisions"] if d["template_slug"] == slug)
    assert decision["validation_preview"]["status"] == "feasible", decision
    split_preview = decision["validation_preview"]["splits"][0]
    assert (split_preview["training_count"], split_preview["held_out_count"]) == (18, 6)
    if slug == "classification_plsda":
        assert split_preview["component_cv"]["status"] == "population_feasible"
    created = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={"workflow_name": "Source partition", "project_id": project.id, "data_bindings": {"data_1": binding}},
    )
    assert created.status_code == 201, created.text
    split = next(n for n in created.json()["nodes"] if n["node_type"] == "data.train_test_split")
    source = apply_dataset_prepared_data_overrides(load_csv_as_sherpa(path, _infer_implicit_target=False), overrides)
    result = await TrainTestSplitNode(split["node_id"], split["parameters"]).execute(X=source)
    assert result["X_train"].n_samples == 18
    assert result["X_test"].n_samples == 6
    assert set(result["X_train"].sample_axis.sample_table["Assignment"]) == {"Training"}
    assert set(result["X_test"].sample_axis.sample_table["Assignment"]) == {"Validation"}


def test_response_source_cannot_overwrite_predictor_partition():
    nodes = [{"node_id": "split", "node_type": "data.train_test_split", "parameters": {}}]
    edges = [
        {"from_node_id": "x", "to_node_id": "split", "to_input": "X"},
        {"from_node_id": "y", "from_output": "target", "to_node_id": "split", "to_input": "y"},
    ]
    for source in ("x", "y"):
        routes._adapt_starter_to_source_assignment(
            analysis_profile={"source_assignment": {"validation_label": f"{source}-validation"}},
            nodes=nodes,
            edges=edges,
            source_node_id=source,
        )
    assert nodes[0]["parameters"]["held_out_groups"] == ["x-validation"]
