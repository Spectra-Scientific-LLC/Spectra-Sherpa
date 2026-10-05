"""Scientific workflow proofs and adversarial model-port interchange tests."""

import copy
import itertools

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.model_edge_contracts import model_edge_error
from spectra_sherpa.app.services.dag.node_base import NodeResult, node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.predict_regression_node import PredictRegressionNode
from tests.test_phase1c_consumer_projects import canonical_selection_source  # noqa: F401

TRAINERS = [
    "model.fitted_pls",
    "model.fitted_pcr",
    "model.fitted_svr",
    "model.fitted_linear_regression",
    "model.pcr",
    "model.svr",
    "model.linear_regression",
]


def outputs(result):
    return result.outputs if isinstance(result, NodeResult) else result


def dataset():
    rng = np.random.default_rng(1947)
    X = rng.normal(size=(60, 8))
    return SherpaDataset(
        X=X,
        target=2 * X[:, 0] - X[:, 3] + 0.5,
        feature_axis=SpectralAxis(values=np.arange(8.0) + 1000, units="nm", title="Wavelength"),
        sample_axis=SampleAxis(labels=[f"sample-{i}" for i in range(60)]),
        target_context=TargetContext(target_type="continuous", target_names=["Glucose"], target_units="wt %"),
    )


@pytest.mark.parametrize("trainer", TRAINERS)
async def test_split_train_predict_evaluate_and_export_without_refit(trainer, monkeypatch):
    split = outputs(
        await node_registry.create_node(
            "data.train_test_split",
            "split",
            {
                "split_method": "random",
                "test_size": 0.25,
                "random_seed": 42,
            },
        ).execute(X=dataset())
    )
    fit = node_registry.create_node(trainer, "fit", {})
    kwargs = {"input_data" if trainer.startswith("model.fitted_") else "X": split["X_train"], "y": split["y_train"]}
    trained = outputs(await fit.execute(**kwargs))
    state = copy.deepcopy(trained["fitted_state"])
    predictor = PredictRegressionNode("predict", {})
    # Any accidental fit on held-out rows must fail this whole workflow.
    from sklearn.linear_model import LinearRegression
    from sklearn.pipeline import Pipeline

    def forbidden(*args, **kwargs):
        raise AssertionError("Prediction must never fit")

    monkeypatch.setattr(Pipeline, "fit", forbidden)
    monkeypatch.setattr(LinearRegression, "fit", forbidden)
    result = outputs(await predictor.execute(default=split["X_test"], fitted_state=state))
    assert np.asarray(result["default"]).shape == (15, 1)
    assert np.isfinite(result["default"]).all()
    if trainer in {"model.pcr", "model.svr", "model.linear_regression"}:
        np.testing.assert_allclose(
            np.asarray(result["default"]).ravel(),
            np.asarray(trained["model"].predict(split["X_test"].X)).ravel(),
            rtol=1e-10,
            atol=1e-10,
        )
    receipt = result["prediction_identity"]
    assert receipt["sample_labels"] == split["X_test"].sample_axis.labels
    # Split currently returns raw y arrays: do not invent their identity from X.
    assert receipt["response_identity"] == {"names": None, "units": [None]}
    changed = split["X_test"].copy()
    changed.target = np.full(15, -1e12)
    np.testing.assert_allclose(
        outputs(await predictor.execute(default=changed, fitted_state=state))["default"], result["default"]
    )
    evaluated = outputs(
        await node_registry.create_node("diagnostics.labeled_regression_evaluator", "eval", {}).execute(
            input_data=result["default"],
            y_true=split["y_test"],
            sample_context=split["X_test"],
        )
    )
    assert evaluated
    scope = {"results": {}, "heldout": split["X_test"], "state": state}
    exec("\n".join(predictor.generate_python({"default": "heldout", "fitted_state": "state"}, indent="")), scope)
    np.testing.assert_allclose(scope["results"]["predict"]["default"], result["default"])
    assert "prediction_intervals" not in result  # no invented model-specific evidence


@pytest.mark.parametrize(
    "source,target",
    itertools.product(
        ["model.fitted_pls", "model.fitted_pcr", "model.fitted_svr", "model.fitted_linear_regression"],
        [
            "model.apply_fitted_pls",
            "model.apply_fitted_pcr",
            "model.apply_fitted_svr",
            "model.apply_fitted_linear_regression",
        ],
    ),
)
def test_regression_pair_matrix(source, target):
    reason = model_edge_error(
        node_registry.get_metadata(source), "fitted_state", node_registry.get_metadata(target), "fitted_state"
    )
    assert (reason is None) == (source == target.replace(".apply_fitted_", ".fitted_"))


@pytest.mark.parametrize(
    "source,target",
    itertools.product(
        ["classification.knn", "classification.plsda", "classification.simca"],
        ["classification.apply_knn", "classification.apply_plsda", "classification.apply_simca"],
    ),
)
def test_classifier_pair_matrix(source, target):
    reason = model_edge_error(
        node_registry.get_metadata(source), "fitted_state", node_registry.get_metadata(target), "fitted_state"
    )
    assert (reason is None) == (source == target.replace(".apply_", "."))


@pytest.mark.parametrize(
    "source,port,target,target_port,valid",
    [
        ("model.pca", "model", "model.pca_transform", "model", True),
        ("model.pca", "diagnostic_state", "model.pca_transform", "model", False),
        ("model.pca", "diagnostic_state", "diagnostics.outliers", "default", True),
        ("model.pca", "fitted_state", "diagnostics.outliers", "default", False),
        ("model.ica", "fitted_state", "model.pca_transform", "model", False),
        ("model.mcr_als", "fitted_state", "diagnostics.outliers", "default", False),
        ("model.parafac", "model", "model.pca_transform", "model", False),
        ("model.fitted_pls", "fitted_state", "selection.variable_select", "model", True),
        ("model.kmeans", "model", "selection.variable_select", "model", False),
        *[
            (name, "fitted_state", "transfer.apply_fitted", "fitted_state", True)
            for name in ("transfer.ds", "transfer.pds", "transfer.sws")
        ],
    ],
)
def test_other_model_consumers(source, port, target, target_port, valid):
    assert (
        model_edge_error(node_registry.get_metadata(source), port, node_registry.get_metadata(target), target_port)
        is None
    ) == valid


async def test_prediction_rejects_tampering_and_reordered_wavelengths():
    data = dataset()
    state = outputs(await node_registry.create_node("model.pcr", "fit", {}).execute(X=data))["fitted_state"]
    forged = copy.deepcopy(state)
    forged["arrays"]["pca_mean"][0] += 1
    with pytest.raises(ValueError, match="digest"):
        PredictRegressionNode("predict", {})._execute_sync(data, forged)
    with pytest.raises(ValueError, match="identity|feature|axis"):
        PredictRegressionNode("predict", {})._execute_sync(data[:, ::-1], state)


@pytest.mark.parametrize("trainer", ["model.pcr", "model.svr", "model.linear_regression"])
async def test_embedded_response_identity(trainer):
    data = dataset()
    state = outputs(await node_registry.create_node(trainer, "fit", {}).execute(X=data))["fitted_state"]
    result = PredictRegressionNode("predict", {})._execute_sync(data, state)
    assert result.outputs["prediction_identity"]["response_identity"] == {"names": ["Glucose"], "units": ["wt %"]}


def test_every_model_consuming_node_has_an_audited_disposition():
    consumers = {
        (meta.node_type, port.name)
        for meta in node_registry.list_nodes()
        for port in meta.input_ports or []
        if any(kind in port.type_ref for kind in ("Model/", "DecompositionResult/"))
    }
    assert consumers == {
        ("selection.variable_select", "model"),
        ("model.pca_transform", "model"),
        ("diagnostics.outliers", "default"),
        ("transfer.apply_fitted", "fitted_state"),
        ("model.predict_regression", "fitted_state"),
        *{(f"model.apply_fitted_{name}", "fitted_state") for name in ("pls", "pcr", "svr", "linear_regression")},
        *{(f"classification.apply_{name}", "fitted_state") for name in ("knn", "plsda", "simca")},
    }, "A new model consumer needs an explicit compatibility audit and cross-family tests"


def test_wrong_model_is_rejected_by_save_preflight_and_executor():
    from pathlib import Path

    from spectra_sherpa.app.types import type_registry

    type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")
    from spectra_sherpa.app.services.dag.executor import DAGExecutor
    from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
    from spectra_sherpa.app.services.dag.saved_graph_admission import admit_saved_workflow_graph
    from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow

    nodes = [WorkflowNode("train", "model.pcr", {}), WorkflowNode("predict", "model.apply_fitted_pls", {})]
    edge = WorkflowEdge("train", "predict", "model", "fitted_state")
    preflight = preflight_workflow(nodes, [edge], require_runtime_dependencies=False)
    assert preflight.edges[0].status == "invalid"
    assert "Predict Regression" in preflight.edges[0].reason
    executor = DAGExecutor()
    for node in nodes:
        executor.add_node(node)
    executor.add_edge(edge)
    assert any("incompatible fitted-model contract" in issue.message for issue in executor.validate_full().issues)
    with pytest.raises(ValueError, match="incompatible fitted-model contract"):
        admit_saved_workflow_graph(
            [{"node_id": n.node_id, "node_type": n.node_type, "parameters": {}} for n in nodes],
            [{"from_node_id": "train", "to_node_id": "predict", "from_output": "model", "to_input": "fitted_state"}],
        )


async def test_pls_coefficient_selection_accepts_canonical_state():
    data = dataset()
    fitted = outputs(
        await node_registry.create_node("model.fitted_pls", "fit", {"n_components": 3}).execute(input_data=data)
    )
    selected = outputs(
        await node_registry.create_node(
            "selection.variable_select",
            "select",
            {
                "method": "coef_abs",
                "threshold": 0.5,
            },
        ).execute(X=data, model=fitted["fitted_state"])
    )
    assert selected["default"].shape[0] == data.shape[0]
    assert selected["default"].shape[1] > 0


@pytest.mark.parametrize("trainer", ["model.fitted_pls", "model.pcr", "model.svr", "model.linear_regression"])
async def test_real_calibration_template_trainer_replacement(
    trainer, canonical_selection_source, monkeypatch  # noqa: F811
):
    from tests import consumer_project_harness as harness

    template = harness.load_consumer_project("pls_calibration")
    for node in template["nodes"]:
        if node["node_id"] == "model_1":
            node["node_type"] = trainer
            node["parameters"] = {}
    if trainer != "model.fitted_pls":
        for edge in template["edges"]:
            if edge["to_node_id"] == "model_1" and edge["to_input"] == "default":
                edge["to_input"] = "X"
    monkeypatch.setattr(harness, "load_consumer_project", lambda slug: template)
    run = await harness.execute_consumer_project(
        "pls_calibration",
        source_parameters={"data_1": canonical_selection_source},
    )
    predicted = np.asarray(run.results["predict_1"]["default"])
    references = np.asarray(run.results["partition_1"]["y_test"]).reshape(-1, 1)
    assert predicted.shape == references.shape == (12, 1)
    assert np.isfinite(predicted).all()
    assert run.results["eval_1"]["default"]["n_samples"] == 12
    assert run.results["table_1"]
    assert run.results["viz_1"]
    if trainer in {"model.pcr", "model.linear_regression"}:
        assert np.sqrt(np.mean((predicted - references) ** 2)) < 0.2
