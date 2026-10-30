"""PLS review preserves the actual calibration and independent test populations."""

from copy import deepcopy

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression

from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset


def dataset():
    x = np.random.default_rng(6242).normal(size=(40, 8)) @ np.diag(np.arange(1, 9))
    x[-2:] += 40
    ds = SherpaDataset(
        X=x,
        sample_axis=SampleAxis(
            labels=[f"s{i:02}" for i in range(40)],
            sample_table={"sample_id": [f"s{i:02}" for i in range(40)]},
        ),
        feature_axis=SpectralAxis(values=np.arange(8.0), units="cm^-1"),
        data_role="X_spectra",
    )
    ds.meta["source_collection"] = {"files": [{"sha256": "a" * 64}], "manifest_digest": "b" * 64}
    return ds


from spectra_sherpa.app.services.dag.nodes.data.transforms import FilterSamplesNode, TrainTestSplitNode
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.modeling.predict_regression_node import PredictRegressionNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node import NormalizeNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.shared_reference_scale_node import SharedReferenceScaleNode
from spectra_sherpa.app.services.pca_review_evidence import filter_id
from spectra_sherpa.app.services.pls_review_evidence import build_review_receipt, review_path


def definition(excluded=()):
    nodes = [
        {"node_id": "source", "node_type": "data.collection_load", "parameters": {}},
        {
            "node_id": "split",
            "node_type": "data.train_test_split",
            "parameters": {"split_method": "random", "random_seed": 21, "test_size": 0.25},
        },
        {"node_id": "pls", "node_type": "model.fitted_pls", "parameters": {"n_components": 2, "scale": False}},
        {"node_id": "predict", "node_type": "model.predict_regression", "parameters": {}},
    ]

    def e(a, b, output="default", input="default"):
        return {"from_node_id": a, "to_node_id": b, "from_output": output, "to_input": input}

    edges = [
        e("source", "split", input="X"),
        e("split", "pls", "X_train"),
        e("split", "predict", "X_test"),
        e("pls", "predict", "fitted_state", "fitted_state"),
    ]
    if excluded:
        nodes.append(
            {
                "node_id": filter_id("pls"),
                "node_type": "data.filter_samples",
                "parameters": {
                    "field": "sample_table",
                    "sample_table_column": "sample_id",
                    "filter_values": list(excluded),
                    "invert": True,
                },
            }
        )
        edges.remove(e("split", "pls", "X_train"))
        edges.extend([e("split", filter_id("pls"), "X_train", "X"), e(filter_id("pls"), "pls")])
    return {"nodes": nodes, "edges": edges}


async def run(excluded=(), corrupt=None, responses=1, scale=False):
    ds = dataset()
    ds.target = ds.X[:, 0] * 2 + ds.X[:, 1] * 0.4 + np.random.default_rng(20).normal(size=40)
    if responses == 2:
        ds.target = np.column_stack((ds.target, ds.X[:, 2] * 3))
    graph = definition(excluded)
    graph["nodes"][2]["parameters"]["scale"] = scale
    result = {"source": ds}
    split = await TrainTestSplitNode("split", graph["nodes"][1]["parameters"]).execute(X=ds)
    result["split"] = split.outputs if hasattr(split, "outputs") else split
    train = result["split"]["X_train"]
    if excluded:
        filtered = await FilterSamplesNode(filter_id("pls"), graph["nodes"][-1]["parameters"]).execute(X=train)
        train = filtered["default"]
        result[filter_id("pls")] = train
    result["pls"] = (await FittedPLSV2Node("pls", graph["nodes"][2]["parameters"]).execute(input_data=train)).outputs
    result["predict"] = (
        await PredictRegressionNode("predict", {}).execute(
            default=result["split"]["X_test"], fitted_state=result["pls"]["fitted_state"]
        )
    ).outputs
    if corrupt:
        corrupt(result)
    return await build_review_receipt(graph, result, "pls"), ds, result


@pytest.mark.asyncio
async def test_pls_review_and_explanations_follow_ids_after_display_relabel(monkeypatch):
    original_factory = dataset

    def relabeled():
        value = original_factory()
        axis = value.sample_axis
        axis.labels = [f"Display specimen {index}" for index in range(40)]
        value.sample_axis = axis
        return value

    monkeypatch.setitem(globals(), "dataset", relabeled)
    original, _, _ = await run()
    selected = original["calibration_ids"][-1]
    reviewed, _, _ = await run([selected])
    assert reviewed["identity_field"] == "sample_id"
    assert reviewed["heldout_ids"] == original["heldout_ids"]
    assert selected in reviewed["pls_explanations"]["rows"]
    assert {row["id"] for row in reviewed["rows"]} == {f"s{i:02}" for i in range(40)}


@pytest.mark.asyncio
@pytest.mark.parametrize("labels", ["duplicate", "absent"])
async def test_pls_review_refuses_genuine_predictions_for_reversed_ids_even_without_unique_labels(monkeypatch, labels):
    original_factory = dataset

    def relabeled():
        value = original_factory()
        axis = value.sample_axis
        axis.labels = ["Same display label"] * value.n_samples if labels == "duplicate" else None
        value.sample_axis = axis
        return value

    monkeypatch.setitem(globals(), "dataset", relabeled)
    receipt, _, results = await run()
    original = results["predict"]["default"].copy()
    heldout = results["split"]["X_test"]
    reversed_result = (
        PredictRegressionNode("predict", {})._execute_sync(heldout[::-1], results["pls"]["fitted_state"]).outputs
    )
    assert reversed_result["prediction_identity"]["sample_ids"] == list(reversed(receipt["heldout_ids"]))
    assert not np.array_equal(reversed_result["default"], original)
    results["predict"] = reversed_result
    with pytest.raises(ValueError, match="prediction identity/state custody"):
        await build_review_receipt(definition(), results, "pls")


@pytest.mark.asyncio
async def test_new_pls_review_refuses_legacy_prediction_receipt_without_typed_ids():
    _, _, results = await run()
    results["predict"]["prediction_identity"].pop("sample_ids")
    with pytest.raises(ValueError, match="prediction identity/state custody"):
        await build_review_receipt(definition(), results, "pls")


def preprocessed_definition(excluded=(), *, group_holdout=False, extra_samplewise=False):
    def edge(a, b, output="default", input="default"):
        return {"from_node_id": a, "to_node_id": b, "from_output": output, "to_input": input}

    nodes = [
        {"node_id": "source", "node_type": "data.collection_load", "parameters": {}},
        {
            "node_id": "split",
            "node_type": "data.train_test_split",
            "parameters": {"split_method": "random", "random_seed": 21, "test_size": 0.25},
        },
        {"node_id": "train_snv", "node_type": "preprocess.normalize", "parameters": {"method": "snv"}},
        {"node_id": "test_snv", "node_type": "preprocess.normalize", "parameters": {"method": "snv"}},
        {
            "node_id": "scale",
            "node_type": "preprocess.shared_reference_scale",
            "parameters": {"method": "autoscale", "center": True},
        },
        {"node_id": "pls", "node_type": "model.fitted_pls", "parameters": {"n_components": 2, "scale": False}},
        {"node_id": "predict", "node_type": "model.predict_regression", "parameters": {}},
    ]
    if extra_samplewise:
        nodes[4:4] = [
            {
                "node_id": "train_smooth",
                "node_type": "preprocess.smooth",
                "parameters": {"method": "gaussian", "sigma": 1.1},
            },
            {
                "node_id": "test_smooth",
                "node_type": "preprocess.smooth",
                "parameters": {"method": "gaussian", "sigma": 1.1},
            },
            {
                "node_id": "train_deriv",
                "node_type": "preprocess.derivative",
                "parameters": {"method": "savitzky_golay", "deriv": "1", "size": 7, "order": 2},
            },
            {
                "node_id": "test_deriv",
                "node_type": "preprocess.derivative",
                "parameters": {"method": "savitzky_golay", "deriv": "1", "size": 7, "order": 2},
            },
        ]
    if group_holdout:
        nodes[1]["parameters"] = {"split_method": "group_holdout", "held_out_groups": ["batch-D"]}
    train_source = "split"
    train_port = "X_train"
    if excluded:
        nodes.append(
            {
                "node_id": filter_id("pls"),
                "node_type": "data.filter_samples",
                "parameters": {
                    "field": "sample_table",
                    "sample_table_column": "sample_id",
                    "filter_values": list(excluded),
                    "invert": True,
                },
            }
        )
        train_source = filter_id("pls")
        train_port = "default"
    edges = [edge("source", "split", input="X")]
    if excluded:
        edges.append(edge("split", filter_id("pls"), "X_train", "X"))
    edges += [
        edge(train_source, "train_snv", train_port),
        edge("split", "test_snv", "X_test"),
        edge("scale", "pls", "reference_scaled"),
        edge("scale", "predict"),
        edge("pls", "predict", "fitted_state", "fitted_state"),
    ]
    if extra_samplewise:
        edges += [
            edge("train_snv", "train_smooth"),
            edge("train_smooth", "train_deriv"),
            edge("train_deriv", "scale", input="reference"),
            edge("test_snv", "test_smooth"),
            edge("test_smooth", "test_deriv"),
            edge("test_deriv", "scale"),
        ]
    else:
        edges += [edge("train_snv", "scale", input="reference"), edge("test_snv", "scale")]
    return {"nodes": nodes, "edges": edges}


async def run_preprocessed(
    excluded=(), *, heldout_shift=0, corrupt=None, group_holdout=False, multi_file=False, extra_samplewise=False
):
    ds = dataset()
    ds.target = ds.X[:, 0] * 2 + ds.X[:, 1] * 0.4 + np.random.default_rng(20).normal(size=40)
    if multi_file:
        files = [
            {
                "file_name": f"raw/part-{part}.csv",
                "sha256": str(part + 1) * 64,
                "prepared_data_sha256": str(part + 3) * 64,
                "asset_id": f"asset-{part}",
            }
            for part in range(2)
        ]
        ds.meta["source_collection"]["files"] = files
        ds.meta["source_observations"] = [
            {"sample_id": identity, **files[index // 20], "source_row": index % 20}
            for index, identity in enumerate(ds.sample_axis.labels)
        ]
    if group_holdout:
        from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset

        ds.meta["source_collection"].update(
            {
                "collection_definition_sha256": "c" * 64,
                "scientific_collection_sha256": "d" * 64,
            }
        )
        labels = list(ds.sample_axis.labels)
        ds.sample_axis = SampleAxis(
            labels=labels,
            sample_table={
                "sample_id": labels,
                "response": ds.target.tolist(),
                "batch": [f"batch-{chr(65 + i // 10)}" for i in range(40)],
            },
        )
        ds = attach_target_dataset(
            ds,
            None,
            target_type="continuous",
            target_source="sample_table_column",
            target_column="response",
            group_column="batch",
            node_id="attach-target",
        )
    graph = preprocessed_definition(excluded, group_holdout=group_holdout, extra_samplewise=extra_samplewise)
    split_node = TrainTestSplitNode("split", graph["nodes"][1]["parameters"])
    original_split = await split_node.execute(X=ds)
    if heldout_shift:
        ds.X[original_split["test_indices"]] += heldout_shift
    split = await split_node.execute(X=ds)
    train, test = split["X_train"], split["X_test"]
    results = {"source": ds, "split": split}
    if excluded:
        filtered = await FilterSamplesNode(filter_id("pls"), graph["nodes"][-1]["parameters"]).execute(X=train)
        train = filtered["default"]
        results[filter_id("pls")] = train
    train = (await NormalizeNode("train_snv", {"method": "snv"}).execute(input_data=train)).outputs["default"]
    test = (await NormalizeNode("test_snv", {"method": "snv"}).execute(input_data=test)).outputs["default"]
    results["train_snv"], results["test_snv"] = train, test
    if extra_samplewise:
        from spectra_sherpa.app.services.dag.nodes.preprocessing.derivative_node import DerivativeNode
        from spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_node import SmoothNode

        for node_id, source in (("train_smooth", train), ("test_smooth", test)):
            results[node_id] = (
                await SmoothNode(node_id, {"method": "gaussian", "sigma": 1.1}).execute(input_data=source)
            ).outputs["default"]
        for node_id, source_id in (("train_deriv", "train_smooth"), ("test_deriv", "test_smooth")):
            results[node_id] = (
                await DerivativeNode(
                    node_id, {"method": "savitzky_golay", "deriv": "1", "size": 7, "order": 2}
                ).execute(input_data=results[source_id])
            ).outputs["default"]
        train, test = results["train_deriv"], results["test_deriv"]
    results["scale"] = (
        await SharedReferenceScaleNode("scale", {"method": "autoscale", "center": True}).execute(
            default=test, reference=train
        )
    ).outputs
    results["pls"] = (
        await FittedPLSV2Node("pls", next(n["parameters"] for n in graph["nodes"] if n["node_id"] == "pls")).execute(
            input_data=results["scale"]["reference_scaled"]
        )
    ).outputs
    results["predict"] = (
        await PredictRegressionNode("predict", {}).execute(
            default=results["scale"]["default"], fitted_state=results["pls"]["fitted_state"]
        )
    ).outputs
    if corrupt:
        corrupt(results)
    return await build_review_receipt(graph, results, "pls"), ds, results


@pytest.mark.asyncio
async def test_preprocessed_fixed_split_uses_one_fit_for_train_and_full_test():
    original, _, _ = await run_preprocessed()
    excluded = [original["calibration_ids"][-1]]
    reviewed, _, results = await run_preprocessed(excluded)
    assert reviewed["heldout_ids"] == original["heldout_ids"]
    assert reviewed["calibration_ids"] == original["calibration_ids"]
    assert [step["operation"] for step in reviewed["preprocessing"]] == [
        "preprocess.normalize",
        "preprocess.shared_reference_scale",
    ]
    assert reviewed["preprocessing"][0]["parameters"]["method"] == "snv"
    assert reviewed["preprocessing"][1]["parameters"] == {"method": "autoscale", "center": True}
    assert reviewed["executed_split"]["method"] == "random"
    assert reviewed["executed_split"]["n_test"] == len(reviewed["heldout_ids"])
    assert reviewed["preprocessing"][-1]["fitting_count"] == reviewed["n_calibration"]
    assert reviewed["model_input_spectra"]["missing_ids"] == []
    assert set(reviewed["model_input_spectra"]["rows"]) == {row["id"] for row in reviewed["rows"]}
    assert reviewed["source_spectral_space"].startswith("Saved workflow input")
    assert (
        reviewed["model_input_spectra"]["rows"][reviewed["calibration_ids"][0]]
        != reviewed["spectra"]["rows"][reviewed["calibration_ids"][0]]
    )
    train = results["scale"]["reference_scaled"]
    test = results["scale"]["default"]
    state = [
        step["parameters"]["transform_state"] for step in train.provenance.to_list() if step.get("node_id") == "scale"
    ][-1]
    exact = ScaleNode("scale", {"method": "autoscale", "center": True}).apply_fitted_state(results["test_snv"], state)
    np.testing.assert_array_equal(test.X, exact.X)
    independent = PLSRegression(n_components=2, scale=False).fit(train.X, train.target)
    heldout = [row for row in reviewed["rows"] if row["role"] == "held_out_test"]
    np.testing.assert_allclose(
        [row["predicted"] for row in heldout], independent.predict(test.X).reshape(-1, 1), atol=1e-8
    )
    assert len(heldout) == len(reviewed["heldout_ids"])
    restored, _, _ = await run_preprocessed()
    assert restored["rows"] == original["rows"]


@pytest.mark.asyncio
async def test_heldout_perturbation_cannot_change_calibration_fit_or_scale():
    first, _, original = await run_preprocessed()
    shifted, _, perturbed = await run_preprocessed(heldout_shift=1000)
    assert first["calibration_ids"] == shifted["calibration_ids"]
    assert first["heldout_ids"] == shifted["heldout_ids"]
    assert first["preprocessing"] == shifted["preprocessing"]
    np.testing.assert_array_equal(original["scale"]["reference_scaled"].X, perturbed["scale"]["reference_scaled"].X)
    np.testing.assert_array_equal(original["pls"]["default"], perturbed["pls"]["default"])


@pytest.mark.asyncio
async def test_mirrored_smoothing_and_derivative_keep_saved_settings_and_units():
    original, _, _ = await run_preprocessed(extra_samplewise=True)
    reviewed, _, results = await run_preprocessed([original["calibration_ids"][0]], extra_samplewise=True)
    assert reviewed["heldout_ids"] == original["heldout_ids"]
    assert [step["operation"] for step in reviewed["preprocessing"]] == [
        "preprocess.normalize",
        "preprocess.smooth",
        "preprocess.derivative",
        "preprocess.shared_reference_scale",
    ]
    assert reviewed["preprocessing"][1]["parameters"]["sigma"] == 1.1
    assert reviewed["preprocessing"][2]["parameters"]["deriv"] == "1"
    assert reviewed["preprocessing"][2]["parameters"]["delta"] > 0
    assert reviewed["model_input_spectra"]["signal_units"] == results["scale"]["reference_scaled"].units
    assert reviewed["preprocessing"][-1]["fitting_count"] == reviewed["n_calibration"]


@pytest.mark.asyncio
async def test_grouped_holdout_preprocessing_preserves_original_group_membership_after_exclusion():
    from spectra_sherpa.app.services.dag.supervision_binding import admit_attached_sample_table_supervision

    initial, _, _ = await run_preprocessed(group_holdout=True)
    removed = initial["calibration_ids"][0]
    reviewed, _, results = await run_preprocessed([removed], group_holdout=True)
    filtered = results[filter_id("pls")]
    binding = admit_attached_sample_table_supervision(filtered)
    assert binding is not None and binding.groups is not None
    assert len(binding.groups) == reviewed["n_calibration"]
    assert reviewed["executed_split"]["method"] == "group_holdout"
    assert reviewed["executed_split"]["n_groups"] == 4
    assert len(reviewed["executed_split"]["groups_content_digest"]) == 64
    assert initial["heldout_ids"] == reviewed["heldout_ids"]
    assert len(reviewed["heldout_ids"]) == 10
    assert {row["group"] for row in reviewed["rows"] if row["role"] == "held_out_test"} == {"batch-D"}
    assert {row["group"] for row in reviewed["rows"] if row["role"] == "calibration"}.isdisjoint({"batch-D"})
    assert reviewed["preprocessing"][-1]["fitting_count"] == len(reviewed["calibration_ids"]) - 1
    assert reviewed["full_test_statistics"]["targets"][0]["metrics"]["n_samples"] == 10


@pytest.mark.asyncio
async def test_multifile_preprocessed_review_keeps_source_row_custody():
    original, _, _ = await run_preprocessed(multi_file=True)
    assert len(original["rows"]) == 40
    reviewed, _, _ = await run_preprocessed([original["calibration_ids"][0]], multi_file=True)
    assert original["heldout_ids"] == reviewed["heldout_ids"]
    assert reviewed["n_calibration"] == original["n_calibration"] - 1
    assert reviewed["source_manifest_sha256"] == original["source_manifest_sha256"]

    def mutate_source_row(results):
        results["source"].meta["source_observations"][0]["sha256"] = "f" * 64

    with pytest.raises(ValueError, match="Source observation identity"):
        await run_preprocessed(multi_file=True, corrupt=mutate_source_row)


@pytest.mark.asyncio
async def test_preprocessed_review_refuses_tampered_test_scale_application():
    def corrupt(results):
        results["scale"]["default"].X[0, 0] += 1

    with pytest.raises(ValueError, match="exact fitted scale application"):
        await run_preprocessed(corrupt=corrupt)


@pytest.mark.asyncio
async def test_preprocessed_review_refuses_changed_executed_split_plan():
    from spectra_sherpa.app.lib.sherpa_dataset import Provenance

    def corrupt(results):
        history = results["split"]["X_test"].provenance.to_list()
        next(step for step in history if step.get("op_id") == "data.train_test_split")["parameters"][
            "method"
        ] = "sequential"
        results["split"]["X_test"].provenance = Provenance.from_list(history)

    with pytest.raises(ValueError, match="executed split plans|split-plan digest"):
        await run_preprocessed(corrupt=corrupt)


@pytest.mark.asyncio
async def test_preprocessed_review_refuses_out_of_range_executed_split_index():
    import hashlib
    import json

    from spectra_sherpa.app.lib.sherpa_dataset import Provenance

    def corrupt(results):
        for port in ("X_train", "X_test"):
            output = results["split"][port]
            history = output.provenance.to_list()
            params = next(step for step in history if step.get("op_id") == "data.train_test_split")["parameters"]
            params["train_indices"][0] = 10_000
            payload = {key: value for key, value in params.items() if key not in {"split", "digest"}}
            params["digest"] = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
            ).hexdigest()
            output.provenance = Provenance.from_list(history)

    with pytest.raises(ValueError, match="split-plan indices"):
        await run_preprocessed(corrupt=corrupt)


@pytest.mark.asyncio
async def test_pls_exclusion_prediction_full_test_and_restore_against_sklearn():
    original, ds, _ = await run()
    excluded = [original["calibration_ids"][-1]]
    reviewed, _, results = await run(excluded)
    assert reviewed["heldout_ids"] == original["heldout_ids"]
    assert reviewed["calibration_ids"] == original["calibration_ids"]
    assert reviewed["source_digest"] == original["source_digest"]
    assert reviewed["n_calibration"] == 29
    train = results[filter_id("pls")]
    independent = PLSRegression(n_components=2, scale=False).fit(train.X, train.target)
    position = {x: i for i, x in enumerate(ds.sample_axis.labels)}
    pred = np.asarray([row["predicted"] for row in reviewed["rows"]])
    np.testing.assert_allclose(
        pred, independent.predict(ds.X[[position[row["id"]] for row in reviewed["rows"]]]).reshape(-1, 1), atol=1e-8
    )
    test = [row for row in reviewed["rows"] if row["role"] == "held_out_test"]
    assert reviewed["full_test_statistics"]["targets"][0]["metrics"]["n_samples"] == 10
    assert reviewed["full_test_statistics"]["targets"][0]["metrics"]["rmse"] == pytest.approx(
        np.sqrt(np.mean([row["residual"][0] ** 2 for row in test]))
    )
    restored, _, _ = await run()
    assert restored["rows"] == original["rows"]
    assert restored["full_test_statistics"] == original["full_test_statistics"]


@pytest.mark.asyncio
async def test_pls2_response_identity_and_spectral_rows():
    review, ds, _ = await run(responses=2)
    assert len(review["target_names"]) == 2
    assert len(review["rows"][0]["reference"]) == 2
    assert review["spectra"]["rows"]["s00"] == ds.X[0].tolist()


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["labels", "digest", "state", "response", "partition"])
async def test_pls_refuses_untrusted_prediction_or_partition(damage):
    def corrupt(results):
        identity = results["predict"]["prediction_identity"]
        if damage == "labels":
            identity["sample_labels"] = list(reversed(identity["sample_labels"]))
        if damage == "digest":
            results["predict"]["default"][0, 0] += 1
        if damage == "state":
            identity["fitted_state_custody"]["state_content_digest"] = "a" * 64
        if damage == "response":
            identity["response_identity"] = {"names": ["wrong"], "units": [None]}
        if damage == "partition":
            results["split"]["X_test"].sample_axis = SampleAxis(
                labels=[
                    results["split"]["X_train"].sample_axis.labels[0],
                    *results["split"]["X_test"].sample_axis.labels[1:],
                ]
            )

    with pytest.raises(ValueError):
        await run(corrupt=corrupt)


@pytest.mark.parametrize(
    "damage", ["target_side_input", "wrong_state", "pre_split_filter", "test_filter", "external_preprocess"]
)
def test_pls_graph_refusals(damage):
    graph = definition()
    if damage == "target_side_input":
        graph["edges"].append({"from_node_id": "split", "to_node_id": "pls", "from_output": "y_train", "to_input": "y"})
    if damage == "wrong_state":
        graph["edges"][-1]["from_node_id"] = "source"
    if damage == "pre_split_filter":
        graph["nodes"][1]["node_type"] = "data.filter_samples"
    if damage == "test_filter":
        graph["edges"][2]["from_output"] = "X_train"
    if damage == "external_preprocess":
        graph["nodes"].append({"node_id": "scale", "node_type": "preprocess.scale", "parameters": {}})
        graph["edges"][1]["to_node_id"] = "scale"
        graph["edges"].append(
            {"from_node_id": "scale", "to_node_id": "pls", "from_output": "default", "to_input": "default"}
        )
    with pytest.raises(ValueError):
        review_path(graph, "pls")


@pytest.mark.asyncio
async def test_projection_never_refits_and_failure_does_not_strand_restore(monkeypatch):
    import spectra_sherpa.app.services.pls_review_evidence as evidence

    original, _, _ = await run()
    excluded = [original["calibration_ids"][0]]

    def deny_fit(results):
        def denied(*args, **kwargs):
            raise AssertionError("Review must never fit")

        monkeypatch.setattr(FittedPLSV2Node, "_fit_model_and_state", denied)

    projected, _, _ = await run(excluded, corrupt=deny_fit)
    assert next(r for r in projected["rows"] if r["id"] == excluded[0])["predicted"] is not None
    monkeypatch.undo()

    async def failed(*args, **kwargs):
        raise ValueError("Exact projection state unavailable")

    monkeypatch.setattr(evidence, "project_excluded", failed)
    refused, _, _ = await run(excluded)
    row = next(r for r in refused["rows"] if r["id"] == excluded[0])
    assert row["predicted"] is None and "unavailable" in row["projection_error"]
    assert refused["n_calibration"] == 29 and refused["full_test_statistics"]


@pytest.mark.asyncio
@pytest.mark.parametrize("preprocessed", [False, True], ids=["plain", "preprocessed"])
async def test_real_http_pls_review_cohort_mask_refit_restore(
    auth_client, test_session, test_user, monkeypatch, preprocessed
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from spectra_sherpa.app.db import session as db_session
    from spectra_sherpa.app.lib.export_artifact import build_export_artifact
    from spectra_sherpa.app.lib.sherpa_dataset import TargetContext
    from spectra_sherpa.app.schemas.workflow_data_selection import WorkflowSourceSelection
    from spectra_sherpa.app.services.model_application import load_project_dataset
    from spectra_sherpa.app.services.workflow_data_selections import source_parameters

    monkeypatch.setattr(db_session, "async_session", async_sessionmaker(test_session.bind, expire_on_commit=False))
    project = await auth_client.post("/api/v1/projects", json={"name": "PLS review qualification"})
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    experiment = await auth_client.post("/api/v1/experiments", json={"name": "PLS synthetic", "project_id": pid})
    assert experiment.status_code == 201, experiment.text
    eid = experiment.json()["id"]
    ds = dataset()
    ds.target = ds.X[:, 0] * 2 + ds.X[:, 1] * 0.4
    ds.target_context = TargetContext(target_type="continuous", target_name="Concentration")
    artifact = build_export_artifact(ds, filename="spectra.csv", format="portable_csv")
    uploaded = await auth_client.post(
        f"/api/v1/experiments/{eid}/files",
        data={"stage": "raw"},
        files={"file": ("spectra.csv", artifact["content"].encode(), "text/csv")},
    )
    assert uploaded.status_code == 201, uploaded.text
    loaded = await load_project_dataset(test_session, user_id=test_user.id, experiment_id=eid)
    graph = preprocessed_definition() if preprocessed else definition()
    graph["nodes"][0]["parameters"] = source_parameters(
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
    created = await auth_client.post(
        "/api/v1/workflows", json={"name": "PLS review journey", "project_id": pid, **graph}
    )
    assert created.status_code == 201, created.text
    endpoint = f'/api/v1/workflows/{created.json()["id"]}'
    path = endpoint + "/sample-review/pls"

    async def read():
        response = await auth_client.get(path)
        assert response.status_code == 200, response.text
        return response.json()

    async def execute():
        result = await auth_client.post(endpoint + "/execute", json={})
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "completed", result.text
        return await read()

    async def decide(ctx, kind, ids, ack=True, status=200):
        payload = {
            "run_id": ctx["run_id"],
            "expected_latest_run_id": ctx["latest_run_id"],
            "expected_revision": ctx["revision"],
            "expected_graph_digest": ctx["graph_digest"],
            "source_digest": ctx["source_digest"],
            "action": kind,
            "sample_ids": ids,
            "reason": "Inspect acquisition anomaly",
            "acknowledge_post_review": ack,
        }
        result = await auth_client.post(path, json=payload)
        assert result.status_code == status, result.text
        return result

    original = await execute()
    if preprocessed:
        assert [step["operation"] for step in original["preprocessing"]] == [
            "preprocess.normalize",
            "preprocess.shared_reference_scale",
        ]
        assert len(original["model_input_spectra"]["rows"]) == 40
    assert len(original["pls_explanations"]["rows"]) == 40
    applicability = original["pls_applicability"]
    assert applicability["reference_count"] == 30
    assert applicability["score_covariance_rank"] == 2
    assert len(applicability["rows"]) == 40
    assert all(len(row["scores"]) == 2 and row["t2"] is not None and row["q"] is not None for row in original["rows"])
    assert applicability["application_t2_limit"] > applicability["calibration_t2_limit"]
    test_id = original["heldout_ids"][0]
    train_id = original["calibration_ids"][0]
    await decide(original, "exclude_test", [test_id], ack=False, status=400)
    await decide(original, "exclude", [test_id], status=400)
    await decide(original, "exclude_test", [test_id, train_id], status=400)
    await decide(original, "exclude_test", original["heldout_ids"], status=400)
    await decide(original, "exclude_test", [test_id])
    masked = await read()
    assert masked["graph_digest"] == original["graph_digest"] and masked["run_id"] == original["run_id"]
    assert masked["pls_explanations"] == original["pls_explanations"]
    assert masked["pls_applicability"] == applicability
    assert masked["rows"] == original["rows"]  # A report mask cannot change screening or the fit.
    assert masked["full_test_statistics"] == original["full_test_statistics"]
    assert masked["review_subset_statistics"]["targets"][0]["metrics"]["n_samples"] == 9
    assert masked["state"]["post_review"]
    assert masked["state"]["test_baseline"]["statistics"] == original["full_test_statistics"]
    proposed = deepcopy(graph)
    proposed["nodes"][1]["parameters"]["random_seed"] = 22
    changed = await auth_client.put(endpoint, json=proposed)
    assert changed.status_code == 409 and "separate analysis" in changed.text, changed.text
    override = await auth_client.post(endpoint + "/execute", json={"initial_data": {"split": {"random_seed": 22}}})
    assert override.status_code == 422, override.text
    await decide(masked, "exclude", [train_id])
    refit = await execute()
    assert refit["heldout_ids"] == original["heldout_ids"] and refit["calibration_ids"] == original["calibration_ids"]
    assert refit["n_calibration"] == 29 and refit["full_test_statistics"]["targets"][0]["metrics"]["n_samples"] == 10
    assert refit["state"]["heldout_excluded"] == [test_id]
    assert refit["pls_explanations"]["reference_count"] == 29
    assert train_id in refit["pls_explanations"]["rows"]
    assert refit["pls_applicability"]["reference_count"] == 29
    assert refit["pls_applicability"]["reference_digest"] != applicability["reference_digest"]
    projected = next(row for row in refit["rows"] if row["id"] == train_id)
    assert projected["role"] == "excluded_projected" and projected["scores"] is not None
    assert projected["outside_t2"] == (projected["t2"] > refit["pls_applicability"]["application_t2_limit"])
    await decide(refit, "restore", [train_id])
    restored = await execute()
    assert restored["rows"] == original["rows"]
    # The new execution has new input provenance; restored numerical evidence
    # and fitted reference identity must nevertheless match exactly.
    assert {k: v for k, v in restored["pls_applicability"].items() if k != "input_digests"} == {
        k: v for k, v in applicability.items() if k != "input_digests"
    }
    assert len(restored["pls_applicability"]["input_digests"]) == len(applicability["input_digests"])
    assert restored["full_test_statistics"] == original["full_test_statistics"]
    await decide(restored, "restore_test", [test_id])
    final = await read()
    assert final["state"]["post_review"] and not final["state"]["heldout_excluded"]
    assert final["review_subset_statistics"] == original["full_test_statistics"]
    assert final["state"]["test_baseline"]["run_id"] == original["run_id"]
    changed = await auth_client.put(endpoint, json=proposed)
    assert changed.status_code == 409, changed.text
    model_swap = deepcopy(graph)
    next(node for node in model_swap["nodes"] if node["node_id"] == "pls")["node_type"] = "model.pca"
    assert (await auth_client.put(endpoint, json=model_swap)).status_code == 409
    from spectra_sherpa.app.models.execution_run import ExecutionRun

    saved = await test_session.get(ExecutionRun, restored["run_id"])
    assert saved.source_metadata["sample_review"]["pls"]["post_review"] is True
    assert saved.source_metadata["sample_review"]["pls"]["baseline_run_id"] == original["run_id"]
    # A different tab commits a held-out decision after execution admission but
    # before run persistence. The run must retain the revision it actually saw.
    from spectra_sherpa.app.api.v1.routes.workflows import execute as execute_route

    persist = execute_route._auto_persist_run
    admitted = final["revision"]

    async def advance_review_before_persist(*args, **kwargs):
        await decide(final, "exclude_test", [test_id])
        return await persist(*args, **kwargs)

    monkeypatch.setattr(execute_route, "_auto_persist_run", advance_review_before_persist)
    concurrent = await execute()
    assert concurrent["revision"] == admitted + 1
    saved = await test_session.get(ExecutionRun, concurrent["run_id"])
    provenance = saved.source_metadata["sample_review"]["pls"]
    assert provenance["revision"] == admitted
    assert provenance["heldout_review_omitted_count"] == 0
    assert concurrent["state"]["heldout_excluded"] == [test_id]
    unchanged = await load_project_dataset(test_session, user_id=test_user.id, experiment_id=eid)
    assert unchanged.scientific_collection_sha256 == loaded.scientific_collection_sha256


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,params", [("preprocess.scale", {"method": "autoscale"}), ("preprocess.normalize", {"method": "snv"})]
)
async def test_calibration_only_preprocessing_applies_exact_state(kind, params):
    from spectra_sherpa.app.services.dag.node_base import node_registry

    ds = dataset()
    ds.target = ds.X[:, 0] * 2 + ds.X[:, 1]
    excluded = ["s39"]
    graph = {
        "nodes": [
            {"node_id": "source", "node_type": "data.collection_load", "parameters": {}},
            {
                "node_id": filter_id("pls"),
                "node_type": "data.filter_samples",
                "parameters": {
                    "field": "sample_table",
                    "sample_table_column": "sample_id",
                    "filter_values": excluded,
                    "invert": True,
                },
            },
            {"node_id": "pre", "node_type": kind, "parameters": params},
            {"node_id": "pls", "node_type": "model.fitted_pls", "parameters": {"n_components": 2}},
        ],
        "edges": [],
    }
    for a, b in zip(graph["nodes"], graph["nodes"][1:]):
        graph["edges"].append(
            {
                "from_node_id": a["node_id"],
                "to_node_id": b["node_id"],
                "from_output": "default",
                "to_input": "X" if b["node_type"] == "data.filter_samples" else "default",
            }
        )
    train = (await FilterSamplesNode(filter_id("pls"), graph["nodes"][1]["parameters"]).execute(X=ds))["default"]
    pre = await node_registry.create_node(kind, "pre", params).execute(input_data=train)
    transformed = pre.outputs["default"] if hasattr(pre, "outputs") else pre
    if isinstance(transformed, dict):
        transformed = transformed["default"]
    outputs = (await FittedPLSV2Node("pls", {"n_components": 2}).execute(input_data=transformed)).outputs
    review = await build_review_receipt(
        graph, {"source": ds, filter_id("pls"): train, "pre": transformed, "pls": outputs}, "pls"
    )
    assert review["n_calibration"] == 39
    assert review["rows"][-1]["role"] == "excluded_projected" and review["rows"][-1]["predicted"] is not None, review[
        "rows"
    ][-1]
    assert not review["heldout_ids"] and review["full_test_statistics"] is None
    assert len(review["pls_explanations"]["rows"]) == 40
    assert review["pls_explanations"]["preprocessing"] == [kind]
    assert review["pls_explanations"]["rows"]["s39"][0]["prediction"] == review["rows"][-1]["predicted"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("evaluator", ["diagnostics.regression_evaluator", "diagnostics.labeled_regression_evaluator"])
async def test_saved_review_allows_read_only_evaluation_sidecar_but_not_a_changed_test_branch(evaluator):
    expected, _, results = await run()
    graph = definition()
    graph["nodes"].append({"node_id": "eval", "node_type": evaluator, "parameters": {}})
    graph["edges"].extend(
        [
            {"from_node_id": "predict", "to_node_id": "eval", "from_output": "default", "to_input": "default"},
            {"from_node_id": "split", "to_node_id": "eval", "from_output": "y_test", "to_input": "y_true"},
        ]
    )
    if evaluator == "diagnostics.labeled_regression_evaluator":
        graph["edges"].append(
            {"from_node_id": "split", "to_node_id": "eval", "from_output": "X_test", "to_input": "sample_context"}
        )
    actual = await build_review_receipt(graph, results, "pls")
    assert actual["rows"] == expected["rows"]
    assert actual["full_test_statistics"] == expected["full_test_statistics"]
    # Evaluators cannot replace or feed back into the actual application path.
    changed = deepcopy(graph)
    next(edge for edge in changed["edges"] if edge["to_node_id"] == "predict" and edge["to_input"] == "default")[
        "from_node_id"
    ] = "eval"
    with pytest.raises(ValueError, match="test branch|exact calibration/test"):
        review_path(changed, "pls")
