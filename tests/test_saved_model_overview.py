"""Saved-model comparison never invents validation or qualification evidence."""

from types import SimpleNamespace

from spectra_sherpa.app.services.saved_model_overview import (
    heldout_evaluator_nodes,
    heldout_regression_evaluator_nodes,
    model_component_count,
    project_model_row,
    verified_heldout_classification,
    verified_heldout_regression,
    verified_run_definition,
)


def _model(**changes):
    return SimpleNamespace(
        **{
            "artifact_uid": "model-a",
            "display_name": "First fit",
            "name": "First fit",
            "model_type": "pls",
            "source_run_id": 7,
            "workflow_id": 3,
            "training_dataset_id": 11,
            "n_components": 2,
            "integrity_hash": "c" * 64,
            "is_deploy_ready": False,
            "training_scientific_digest": "d" * 64,
            **changes,
        }
    )


def _manifest(**changes):
    return {
        "response_identity": {"names": ["Protein"], "units": ["wt %"]},
        "preprocessing_chain": [{"op_id": "preprocess.snv"}],
        "metrics": {"rmse": 0.4, "r2": 0.9},
        "reference_value_evidence": {
            "method": {
                "method_id": "Kjeldahl",
                "version": "1",
                "measurement_basis": "single_measurement",
                "measurements_per_label": 1,
            }
        },
        **changes,
    }


def _curve(**changes):
    return {
        "schema_version": "spectrasherpa-pls-component-curve/1",
        "selected_components": 2,
        "n_calibration": 24,
        "response_names": ["Protein"],
        "response_units": ["wt %"],
        "calibration": [{"components": 2, "status": "available", "rmsec": [0.34], "r2y_cumulative": [0.92]}],
        "cross_validation": {
            "status": "available",
            "role": "development_tuning",
            "method": "group_kfold",
            "n_folds": 3,
            "split_digest": "a" * 64,
            "rows": [{"components": 2, "status": "available", "rmsecv": [0.51], "q2": [0.76]}],
        },
        **changes,
    }


def _source(**changes):
    return {"data_selection_revisions": [{"source_node_id": "input", "revision_number": 1}], **changes}


def test_exact_cv_projection_keeps_development_and_independent_results_separate():
    row = project_model_row(
        _model(), _manifest(), curve=_curve(), run_source=_source(), exclusions={"excluded": ["s3"]}
    )
    assert row["metrics"] == {
        "rmsec": 0.34,
        "rmsecv": 0.51,
        "rmsep": None,
        "r2_calibration": 0.92,
        "q2_cv": 0.76,
    }
    assert row["validation"]["role"] == "development_tuning"
    assert row["independent_test_count"] is None
    assert row["qualification"]["state"] == "unavailable"
    assert row["exclusions"] == ["s3"]
    assert row["comparison_key"] is not None


def test_graph_verified_starter_heldout_rmse_is_not_independent_rmsep():
    snapshot = {
        "nodes": [
            {"node_id": "split", "node_type": "data.train_test_split"},
            {"node_id": "fit", "node_type": "model.fitted_pls"},
            {"node_id": "predict", "node_type": "model.predict_regression"},
            {"node_id": "evaluate", "node_type": "diagnostics.labeled_regression_evaluator"},
            {"node_id": "unrelated", "node_type": "diagnostics.labeled_regression_evaluator"},
        ],
        "edges": [
            {"from_node_id": "split", "to_node_id": "fit", "from_output": "X_train", "to_input": "default"},
            {"from_node_id": "split", "to_node_id": "predict", "from_output": "X_test", "to_input": "default"},
            {"from_node_id": "fit", "to_node_id": "predict", "from_output": "fitted_state", "to_input": "fitted_state"},
            {"from_node_id": "predict", "to_node_id": "evaluate", "from_output": "default", "to_input": "default"},
            {"from_node_id": "split", "to_node_id": "evaluate", "from_output": "y_test", "to_input": "y_true"},
            {"from_node_id": "split", "to_node_id": "evaluate", "from_output": "X_test", "to_input": "sample_context"},
        ],
    }
    assert heldout_regression_evaluator_nodes(snapshot, "fit") == ["evaluate"]
    assert heldout_regression_evaluator_nodes(snapshot, "other_fit") == []
    response_edge = {"from_node_id": "split", "to_node_id": "fit", "from_output": "y_train", "to_input": "y"}
    snapshot["edges"].append(response_edge)
    assert heldout_regression_evaluator_nodes(snapshot, "fit") == ["evaluate"]
    response_edge["from_output"] = "y_test"
    assert heldout_regression_evaluator_nodes(snapshot, "fit") == []
    response_edge["from_output"] = "y_train"
    response_edge["from_node_id"] = "unrelated"
    assert heldout_regression_evaluator_nodes(snapshot, "fit") == []
    snapshot["edges"].append({**response_edge, "from_node_id": "split"})
    assert heldout_regression_evaluator_nodes(snapshot, "fit") == []
    snapshot["edges"] = snapshot["edges"][:-2]

    snapshot["edges"][-1]["from_output"] = "X_train"
    assert heldout_regression_evaluator_nodes(snapshot, "fit") == []
    evidence = {"task_type": "regression", "registry_version": "1", "n_samples": 9, "rmse": 0.42}
    assert verified_heldout_regression(evidence)
    assert not verified_heldout_regression({**evidence, "rmse": float("nan")})
    assert not verified_heldout_regression({**evidence, "n_samples": 0})
    row = project_model_row(
        _model(),
        _manifest(),
        curve=_curve(),
        run_source=_source(),
        heldout={**evidence, "graph_verified": True},
    )
    assert row["held_out_validation"] == {"role": "within_dataset_held_out_test", "count": 9, "rmse": 0.42}
    assert row["metrics"]["rmsep"] is None
    assert row["independent_test_count"] is None
    assert project_model_row(_model(), _manifest(), heldout=evidence)["held_out_validation"] is None


def test_comparison_requires_same_target_units_source_view_and_cv_split():
    exclusions = {"excluded": []}
    first = project_model_row(_model(), _manifest(), curve=_curve(), run_source=_source(), exclusions=exclusions)
    changed_units = project_model_row(
        _model(),
        _manifest(response_identity={"names": ["Protein"], "units": ["mg/g"]}),
        curve=_curve(),
        run_source=_source(),
        exclusions=exclusions,
    )
    changed_split = project_model_row(
        _model(),
        _manifest(),
        curve=_curve(cross_validation={**_curve()["cross_validation"], "split_digest": "b" * 64}),
        run_source=_source(),
        exclusions=exclusions,
    )
    changed_source = project_model_row(
        _model(),
        _manifest(),
        curve=_curve(),
        run_source=_source(data_selection_revisions=[{"source_node_id": "input", "revision_number": 2}]),
        exclusions=exclusions,
    )
    assert changed_units["comparison_key"] is None
    assert changed_units["metrics"]["rmsecv"] is None
    assert len({first["comparison_key"], changed_split["comparison_key"], changed_source["comparison_key"]}) == 3
    missing_view = project_model_row(_model(), _manifest(), curve=_curve(), run_source={}, exclusions=exclusions)
    assert missing_view["comparison_key"] is None


def test_comparison_refuses_changed_exclusion_or_training_science_with_same_index_split():
    first = project_model_row(
        _model(), _manifest(), curve=_curve(), run_source=_source(), exclusions={"excluded": ["s3"]}
    )
    changed_exclusion = project_model_row(
        _model(), _manifest(), curve=_curve(), run_source=_source(), exclusions={"excluded": ["s4"]}
    )
    changed_training = project_model_row(
        _model(training_scientific_digest="e" * 64),
        _manifest(),
        curve=_curve(),
        run_source=_source(),
        exclusions={"excluded": ["s3"]},
    )
    missing_decisions = project_model_row(_model(), _manifest(), curve=_curve(), run_source=_source())
    assert len({first["comparison_key"], changed_exclusion["comparison_key"], changed_training["comparison_key"]}) == 3
    assert missing_decisions["comparison_key"] is None


def test_missing_curve_and_multiresponse_never_invent_scalar_or_qualification():
    row = project_model_row(_model(), _manifest(), run_source=_source())
    assert row["metrics"]["rmsecv"] is None
    assert row["comparison_key"] is None
    assert row["validation"]["unavailable_reason"]
    multi = project_model_row(
        _model(),
        _manifest(response_identity={"names": ["Protein", "Oil"], "units": ["wt %", "wt %"]}),
        curve=_curve(),
        run_source=_source(),
        qualification={
            "state": "pending",
            "external_validation": {
                "count": 20,
                "responses": [{"rmse": 0.8}, {"rmse": 1.2}],
                "interval_coverage": [0.85, 0.55],
                "interval_available_rows": 17,
            },
        },
    )
    assert multi["metrics"]["rmsecv"] is None
    assert multi["comparison_key"] is None
    assert multi["coverage"] is None  # no unlabeled response-0 value beside multiple targets
    assert multi["coverage_denominator"] is None


def test_workflow_dossier_cannot_qualify_unrelated_model():
    row = project_model_row(
        _model(),
        _manifest(artifact_digest="a" * 64),
        curve=_curve(),
        run_source=_source(),
    )
    assert row["qualification"]["state"] == "unavailable"
    assert row["operational_deploy_ready"] is False
    assert row["evidence"]["source_run_id"] == 7
    assert row["evidence"]["component_curve_sha256"]


def test_plsda_projection_uses_target_and_exact_classification_evidence():
    curve = {
        "schema_version": "spectrasherpa-plsda-component-curve/1",
        "selected_components": 2,
        "n_calibration": 24,
        "calibration": [{"components": 2, "status": "available", "balanced_accuracy": 0.95}],
        "cross_validation": {
            "status": "available",
            "role": "development_tuning",
            "method": "stratified_group_kfold",
            "n_folds": 3,
            "rows": [{"components": 2, "status": "available", "balanced_accuracy": 0.8}],
        },
    }
    heldout = {
        "schema_version": "spectrasherpa.classification-evaluation/1",
        "task_type": "classification",
        "n_samples": 9,
        "accuracy": 0.89,
        "balanced_accuracy": 0.83,
        "population_authority": {
            "schema_version": "spectrasherpa-population-authority/1",
            "role": "held_out_test",
            "qualification": "graph_verified",
        },
    }
    assert verified_heldout_classification(heldout)
    assert not verified_heldout_classification({**heldout, "population_authority": {"role": "calibration"}})
    assert not verified_heldout_classification({**heldout, "n_samples": None})
    row = project_model_row(
        _model(model_type="plsda"),
        _manifest(
            response_identity=None,
            model_type="plsda",
            effective_n_components=2,
            preprocessing_chain=[
                {"op_id": "data.attach_target", "parameters": {"target_column": "claimed_botanical_group"}}
            ],
        ),
        curve=curve,
        heldout=heldout,
    )
    assert row["target_names"] == ["claimed_botanical_group"]
    assert row["classification_metrics"] == {
        "calibration_balanced_accuracy": 0.95,
        "cv_balanced_accuracy": 0.8,
        "held_out_balanced_accuracy": 0.83,
        "held_out_accuracy": 0.89,
    }
    assert row["held_out_validation"]["count"] == 9
    assert row["independent_test_count"] == 9
    assert row["metrics"]["rmsec"] is None
    assert row["comparison_key"] is None


def test_heldout_evaluator_must_be_downstream_of_this_model():
    snapshot = {
        "nodes": [
            {"node_id": "fit", "node_type": "classification.plsda"},
            {"node_id": "apply", "node_type": "classification.apply_plsda"},
            {"node_id": "test", "node_type": "diagnostics.classification_evaluator"},
            {"node_id": "other", "node_type": "diagnostics.classification_evaluator"},
        ],
        "edges": [
            {"source": "fit", "target": "apply", "from_output": "fitted_state", "to_input": "fitted_state"},
            {"source": "apply", "target": "test", "from_output": "y_pred", "to_input": "default"},
            {"source": "fit", "target": "other", "to_input": "y_true"},
        ],
    }
    assert heldout_evaluator_nodes(snapshot, "fit") == ["test"]
    assert heldout_evaluator_nodes(snapshot, "missing") == []


def test_heldout_evaluator_does_not_cross_into_another_classifier():
    snapshot = {
        "nodes": [
            {"node_id": "fit_a", "node_type": "classification.plsda"},
            {"node_id": "fit_b", "node_type": "classification.plsda"},
            {"node_id": "apply_b", "node_type": "classification.apply_plsda"},
            {"node_id": "eval_b", "node_type": "diagnostics.classification_evaluator"},
        ],
        "edges": [
            {"source": "fit_a", "target": "fit_b", "from_output": "scores", "to_input": "X"},
            {"source": "fit_b", "target": "apply_b", "from_output": "fitted_state", "to_input": "fitted_state"},
            {"source": "apply_b", "target": "eval_b", "from_output": "y_pred", "to_input": "default"},
        ],
    }
    assert heldout_evaluator_nodes(snapshot, "fit_a") == []
    assert heldout_evaluator_nodes(snapshot, "fit_b") == ["eval_b"]


def test_plsda_component_count_uses_sealed_effective_fit_for_older_rows():
    model = _model(model_type="plsda", n_components=None)
    manifest = _manifest(model_type="plsda", n_components=None, effective_n_components=2)
    assert model_component_count(model, manifest) == 2
    assert model_component_count(_model(model_type="plsda", n_components=3), manifest) is None
    assert model_component_count(model, {**manifest, "n_components": 3}) is None
    assert (
        project_model_row(
            model,
            manifest,
            curve={
                "schema_version": "spectrasherpa-plsda-component-curve/1",
                "selected_components": 2,
                "n_calibration": 24,
                "calibration": [{"components": 2, "status": "available", "balanced_accuracy": 0.9}],
                "cross_validation": {"status": "unavailable", "reason": "Too few independent groups"},
            },
        )["classification_metrics"]["calibration_balanced_accuracy"]
        == 0.9
    )


def test_retained_run_definition_requires_exact_graph_hash():
    from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash

    definition = {"nodes": [{"node_id": "fit", "node_type": "classification.plsda"}], "edges": []}
    digest = compute_workflow_hash(definition["nodes"], definition["edges"])
    exact = {**definition, "integrity_hash": digest}
    assert verified_run_definition(exact, digest) == exact
    assert verified_run_definition(exact, "0" * 64) is None
    assert verified_run_definition({**exact, "nodes": []}, digest) is None
