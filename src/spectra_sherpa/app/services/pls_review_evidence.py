"""Exact PLS review: calibration edits never change the held-out input population."""

from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy

import numpy as np

from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import verify_fitted_pls_state_envelope
from spectra_sherpa.app.services.dag.regression_comparison import build_regression_statistics
from spectra_sherpa.app.services.dag.retained_holdout import source_replay_digest
from spectra_sherpa.app.services.pca_review_evidence import (
    PREPROCESSORS,
    SAMPLEWISE,
    SCHEMA,
    TERMINALS,
    _dataset,
    filter_id,
    sample_ids,
)
from spectra_sherpa.sdk.runtime import execute_workflow_async, operation_workflow

SHARED_SCALE = "preprocess.shared_reference_scale"
PLS_PREPROCESSORS = PREPROCESSORS | {SHARED_SCALE}
# Evaluators consume predictions and reference/context data; they do not
# transform the held-out branch used to apply the fitted model. Their outputs
# may feed presentation nodes, but any edge back into computation is still
# rejected by the exact calibration/test graph comparison below.
PLS_REVIEW_TERMINALS = TERMINALS | {
    "diagnostics.regression_evaluator",
    "diagnostics.labeled_regression_evaluator",
}


def _split_preprocessing(definition, path, split, model_id, predictor):
    """Admit one mirrored sample-local branch and one shared fitted scale.

    The scale node fits once on filtered calibration rows. Its two outputs
    apply that same state to the reference and every original test row.
    """
    nodes = {node["node_id"]: node for node in definition["nodes"]}
    edges = definition["edges"]
    split_index = next(i for i, node in enumerate(path) if node["node_id"] == split["node_id"])
    training = path[split_index + 1 : -1]
    if training and training[0]["node_id"] == filter_id(model_id):
        training = training[1:]
    scale = training[-1] if training and training[-1]["node_type"] == SHARED_SCALE else None
    samplewise = training[:-1] if scale else training
    if any(node["node_type"] not in SAMPLEWISE for node in samplewise):
        raise ValueError("Held-out preprocessing supports sample-wise operations followed by one fitted scale.")
    expected = {
        (edge["from_node_id"], edge.get("from_output", "default"), edge["to_node_id"], edge.get("to_input", "default"))
        for edge in edges
        if edge["to_node_id"] in {node["node_id"] for node in path[1 : split_index + 1]}
    }
    # Validate the entire calibration chain, including the owned review filter.
    for before, after in zip(path[split_index:-1], path[split_index + 1 :]):
        from_port = "X_train" if before is split else "reference_scaled" if before is scale else "default"
        to_port = "reference" if after is scale else "X" if after["node_type"] == "data.filter_samples" else "default"
        expected.add((before["node_id"], from_port, after["node_id"], to_port))

    current, output = split["node_id"], "X_test"
    test_nodes = []
    while True:
        outgoing = [
            edge
            for edge in edges
            if edge["from_node_id"] == current
            and edge.get("from_output", "default") == output
            and nodes[edge["to_node_id"]]["node_type"] not in PLS_REVIEW_TERMINALS
        ]
        if len(outgoing) != 1:
            raise ValueError("Held-out preprocessing needs one unchanged test branch.")
        edge = outgoing[0]
        successor = nodes[edge["to_node_id"]]
        input_port = edge.get("to_input", "default")
        if successor is scale or successor is predictor:
            if input_port != "default" or (successor is scale) != bool(scale):
                raise ValueError("Held-out branch must apply the calibration-fitted scale before prediction.")
            expected.add((current, output, successor["node_id"], input_port))
            break
        if successor["node_type"] not in SAMPLEWISE or input_port != "default":
            raise ValueError("Held-out branch must mirror calibration sample-wise preprocessing.")
        test_nodes.append(successor)
        expected.add((current, output, successor["node_id"], input_port))
        current, output = successor["node_id"], "default"
        if len(test_nodes) > len(samplewise):
            raise ValueError("Held-out preprocessing has extra transformations.")
    if len(test_nodes) != len(samplewise) or any(
        a["node_type"] != b["node_type"] or (a.get("parameters") or {}) != (b.get("parameters") or {})
        for a, b in zip(samplewise, test_nodes)
    ):
        raise ValueError("Held-out sample-wise preprocessing must match calibration exactly.")
    if scale:
        expected.add((scale["node_id"], "default", predictor["node_id"], "default"))
    expected.add((model_id, "fitted_state", predictor["node_id"], "fitted_state"))
    actual = {
        (edge["from_node_id"], edge.get("from_output", "default"), edge["to_node_id"], edge.get("to_input", "default"))
        for edge in edges
        if nodes[edge["to_node_id"]]["node_type"] not in PLS_REVIEW_TERMINALS
    }
    if actual != expected or len(actual) != len(
        [edge for edge in edges if nodes[edge["to_node_id"]]["node_type"] not in PLS_REVIEW_TERMINALS]
    ):
        raise ValueError("Held-out PLS review requires the exact calibration/test application graph.")


def review_path(definition: dict, model_id: str):
    nodes = {n["node_id"]: n for n in definition["nodes"]}
    edges = definition["edges"]
    if definition.get("fold_validation_plan") or nodes[model_id]["node_type"] != "model.fitted_pls":
        raise ValueError("PLS review requires one Sherpa PLS Regression analysis, without campaign folds.")
    path, seen, current = [], set(), model_id
    while True:
        if current in seen:
            raise ValueError("Cyclic review path.")
        seen.add(current)
        path.insert(0, nodes[current])
        incoming = [e for e in edges if e["to_node_id"] == current]
        if not incoming:
            break
        if nodes[current]["node_type"] == SHARED_SCALE and len(incoming) == 2:
            reference = [e for e in incoming if e.get("to_input", "default") == "reference"]
            if len(reference) != 1 or sum(e.get("to_input", "default") == "default" for e in incoming) != 1:
                raise ValueError("Fitted scaling requires one calibration reference and one held-out input.")
            edge = reference[0]
        elif len(incoming) == 1:
            edge = incoming[0]
        else:
            raise ValueError("PLS review requires embedded targets and a single calibration data chain.")
        if edge.get("to_input", "default") not in {"default", "X", "reference"}:
            raise ValueError("Review requires the canonical dataset input.")
        if edge.get("from_output", "default") not in {"default", "X_train", "reference_scaled"}:
            raise ValueError("Only the training split output can fit a reviewed model.")
        current = edge["from_node_id"]
    if path[0]["node_type"] != "data.collection_load":
        raise ValueError("PLS review requires a single-file My Dataset source.")
    insertion = 0
    if len(path) > 2 and path[1]["node_type"] == "data.filter_samples":
        params = path[1].get("parameters") or {}
        if params.get("field") == "source_inclusion" and not params.get("invert"):
            insertion = 1
    split = None
    if len(path) > insertion + 2 and path[insertion + 1]["node_type"] == "data.train_test_split":
        insertion += 1
        split = path[insertion]
    middle = path[insertion + 1 : -1]
    if middle and middle[0]["node_id"] == filter_id(model_id):
        if middle[0]["node_type"] != "data.filter_samples":
            raise ValueError("Review filter was replaced.")
        middle = middle[1:]
    if any(n["node_type"] not in PLS_PREPROCESSORS for n in middle):
        raise ValueError(
            "Held-out review uses PLS internal centering/scaling; "
            "external preprocessing needs a fitted application path. "
            "Calibration-only review supports scale, normalize, smooth and derivative."
        )
    extras = [n for key, n in nodes.items() if key not in seen and n["node_type"] not in PLS_REVIEW_TERMINALS]
    if split:
        predictions = [n for n in extras if n["node_type"] in {"model.predict_regression", "model.apply_fitted_pls"}]
        if len(predictions) != 1:
            raise ValueError("Connect the unchanged test split and trainer Fitted State to one PLS prediction node.")
        prediction = predictions[0]
        if prediction.get("parameters"):
            raise ValueError("PLS review does not admit external saved-model bindings.")
        _split_preprocessing(definition, path, split, model_id, prediction)
    elif extras:
        raise ValueError("PLS review requires one model, one source, and presentation-only downstream nodes.")
    for n in ([] if split else path[:-1]):
        outgoing = [e for e in edges if e["from_node_id"] == n["node_id"]]
        if n is split:
            if len(outgoing) != 2 or {e.get("from_output") for e in outgoing} != {"X_train", "X_test"}:
                raise ValueError("Reviewed split must have exactly one training and one full-test branch.")
        elif len(outgoing) != 1 or outgoing[0].get("from_output", "default") != "default":
            raise ValueError("PLS review requires an unbranched canonical source path.")
    a, b = path[insertion : insertion + 2]
    edge = next(e for e in edges if e["from_node_id"] == a["node_id"] and e["to_node_id"] == b["node_id"])
    if edge.get("from_output", "default") != ("X_train" if split else "default"):
        raise ValueError("Exclusions must be inserted on the calibration branch.")
    return path, dict(edge)


def spectral_display(dataset):
    """Bound display payload; indices refer to actual variables, never invented samples."""
    count = min(dataset.shape[1], 256, max(2, 250000 // dataset.shape[0]))
    indices = np.unique(np.linspace(0, dataset.shape[1] - 1, count, dtype=int))
    axis = dataset.feature_axis
    values = axis.values if axis is not None and axis.values is not None else np.arange(dataset.shape[1])
    matrix = dataset.X[:, indices]
    return {
        "x": np.asarray(values)[indices].tolist(),
        "units": str(axis.units or "") if axis is not None else "Variable index",
        "signal_units": str(dataset.units or ""),
        "variable_count": dataset.shape[1],
        "display_count": len(indices),
        "rows": {
            identity: [float(v) if np.isfinite(v) else None for v in row]
            for identity, row in zip(sample_ids(dataset), matrix)
        },
    }


def model_input_spectral_display(datasets, source_ids):
    """Bound linked rows from the exact executed model/application inputs."""
    if not datasets:
        raise ValueError("Executed model-input spectra are unavailable.")
    first = datasets[0]
    axis = first.feature_axis
    values = axis.values if axis is not None and axis.values is not None else np.arange(first.shape[1])
    total = sum(len(sample_ids(dataset)) for dataset in datasets)
    count = min(first.shape[1], 256, max(1, 100000 // max(total, 1)))
    indices = np.unique(np.linspace(0, first.shape[1] - 1, count, dtype=int))
    rows = {}
    for dataset in datasets:
        other = dataset.feature_axis
        other_values = other.values if other is not None and other.values is not None else np.arange(dataset.shape[1])
        if dataset.shape[1] != first.shape[1] or not np.array_equal(values, other_values):
            raise ValueError("Executed model-input feature axes disagree.")
        if dataset.units != first.units:
            raise ValueError("Executed model-input signal units disagree.")
        for identity, row in zip(sample_ids(dataset), dataset.X[:, indices]):
            if identity in rows:
                raise ValueError("Model-input spectral row identity is duplicated.")
            rows[identity] = [float(value) if np.isfinite(value) else None for value in row]
    if not set(rows).issubset(source_ids):
        raise ValueError("Model-input spectral rows differ from the original source cohort.")
    return {
        "x": np.asarray(values)[indices].tolist(),
        "units": str(axis.units or "") if axis is not None else "Variable index",
        "signal_units": str(first.units or ""),
        "variable_count": first.shape[1],
        "display_count": len(indices),
        "rows": rows,
        "missing_ids": [identity for identity in source_ids if identity not in rows],
        "space": "Executed model input after saved preprocessing",
        "downsampled": len(indices) < first.shape[1],
    }


async def apply_operation(operation, inputs, parameters=None):
    spec, payloads, expected = operation_workflow(operation, parameters=parameters or {}, inputs=inputs)
    execution = await execute_workflow_async(spec, deployment_inputs=payloads)
    if dict(execution.dataset_content_digests) != dict(expected):
        raise ValueError("Review application input changed during admission.")
    return execution.output()


def statistics(rows, names):
    if not rows:
        return None
    return build_regression_statistics(
        [r["reference"] for r in rows], [r["predicted"] for r in rows], target_names=names
    )


MAX_RECEIPT_BYTES = 15 * 1024 * 1024


def _executed_split(split, results, full_source, train_ids, test_ids, supervision):
    """Retain only a digest-bound projection of the executed partition plan."""
    if split is None:
        return None
    from spectra_sherpa.app.services.dag.nodes.data.split_planner import SPLIT_METHODS, _array_content_digest

    records = []
    for port, role in (("X_train", "train"), ("X_test", "test")):
        output = _dataset(results, split["node_id"], port)
        matches = [
            item["parameters"]
            for item in output.provenance.to_list()
            if item.get("op_id") == "data.train_test_split"
            and item.get("node_id") == split["node_id"]
            and isinstance(item.get("parameters"), dict)
        ]
        if len(matches) != 1 or matches[0].get("split") != role:
            raise ValueError("Exact executed train/test split provenance is unavailable.")
        records.append(matches[0])
    train_record, test_record = records
    plan = {key: value for key, value in train_record.items() if key != "split"}
    if plan != {key: value for key, value in test_record.items() if key != "split"}:
        raise ValueError("Train/test branches have different executed split plans.")
    digest = plan.pop("digest", None)
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        != digest
    ):
        raise ValueError("Executed split-plan digest does not match its exact payload.")
    source_ids = sample_ids(full_source)
    partitions = (plan.get("train_indices"), plan.get("test_indices"))
    if any(
        not isinstance(indices, list)
        or any(type(index) is not int or index < 0 or index >= len(source_ids) for index in indices)
        for indices in partitions
    ):
        raise ValueError("Executed split-plan indices are invalid for the retained source.")
    if (
        plan.get("method") not in SPLIT_METHODS
        or plan.get("n_samples") != len(source_ids)
        or [source_ids[index] for index in partitions[0]] != train_ids
        or [source_ids[index] for index in partitions[1]] != test_ids
    ):
        raise ValueError("Executed split-plan membership differs from the retained source.")
    groups_digest = plan.get("groups_content_digest")
    if groups_digest != (
        None if supervision is None or supervision.groups is None else _array_content_digest(supervision.groups)
    ):
        raise ValueError("Executed split grouping differs from bound sample-table authority.")
    return {
        "method": plan["method"],
        "test_size": plan["test_size"],
        "random_seed": plan["random_seed"],
        "plan_digest": digest,
        "groups_content_digest": groups_digest,
        "n_groups": plan.get("n_groups"),
        "n_train": len(train_ids),
        "n_test": len(test_ids),
    }


def _executed_preprocessing(path, results, model_id, retained_ids):
    """Describe only the executed calibration chain and its exact fitted state."""
    from spectra_sherpa.app.services.dag.node_base import node_registry

    steps = []
    state = None
    for node in path:
        kind = node["node_type"]
        if kind not in PLS_PREPROCESSORS:
            continue
        output_port = (
            "reference_scaled"
            if kind == SHARED_SCALE and any(n["node_type"] == "data.train_test_split" for n in path)
            else "default"
        )
        output = _dataset(results, node["node_id"], output_port)
        records = [
            item
            for item in output.provenance.to_list()
            if item.get("op_id") == ("preprocess.scale" if kind == SHARED_SCALE else kind)
            and item.get("node_id") == node["node_id"]
        ]
        if len(records) != 1 or not isinstance(records[0].get("parameters"), dict):
            raise ValueError("Exact executed preprocessing parameters are unavailable.")
        executed = records[0]["parameters"]
        resolved = node_registry.create_node(kind, node["node_id"], node.get("parameters") or {})._resolve_params()
        if any(executed.get(key) != value for key, value in resolved.items()):
            raise ValueError("Executed preprocessing parameters differ from the saved workflow.")
        parameters = {key: executed[key] for key in (*resolved, "delta") if key in executed}
        if any(
            isinstance(value, (dict, list)) or isinstance(value, float) and not np.isfinite(value)
            for value in parameters.values()
        ):
            raise ValueError("Executed preprocessing parameters are not bounded scalar values.")
        entry = {
            "node_id": node["node_id"],
            "operation": kind,
            "parameters": parameters,
            "fitting_population": (
                "retained_calibration" if kind in {"preprocess.scale", SHARED_SCALE} else "sample_local"
            ),
        }
        if kind in {"preprocess.scale", SHARED_SCALE}:
            states = [
                item["parameters"]["transform_state"]
                for item in output.provenance.to_list()
                if item.get("op_id") == "preprocess.scale"
                and item.get("node_id") == node["node_id"]
                and isinstance(item.get("parameters", {}).get("transform_state"), dict)
            ]
            if len(states) != 1:
                raise ValueError("Exact calibration-fitted scaling state is unavailable.")
            state = states[0]
            entry["fitted_state_sha256"] = hashlib.sha256(
                json.dumps(state, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
            ).hexdigest()
            entry["fitting_ids_sha256"] = hashlib.sha256(
                json.dumps(retained_ids, separators=(",", ":")).encode()
            ).hexdigest()
            entry["fitting_count"] = len(retained_ids)
        steps.append(entry)
    return steps, state


def _verify_executed_scale(definition, path, results, model_input, scale_state):
    """Prove both saved scale outputs use the one calibration-fitted state."""
    from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode

    scale_node = next(node for node in path if node["node_type"] == SHARED_SCALE)
    scale_test = _dataset(results, scale_node["node_id"])
    test_states = [
        item["parameters"]["transform_state"]
        for item in scale_test.provenance.to_list()
        if item.get("op_id") == "preprocess.scale"
        and item.get("node_id") == scale_node["node_id"]
        and isinstance(item.get("parameters", {}).get("transform_state"), dict)
    ]
    if len(test_states) != 1 or test_states[0] != scale_state:
        raise ValueError("Held-out spectra did not use the exact calibration-fitted scale state.")
    scale_application = ScaleNode(scale_node["node_id"], scale_node.get("parameters") or {})
    for input_port, output in (("reference", model_input), ("default", scale_test)):
        source_edge = next(
            e
            for e in definition["edges"]
            if e["to_node_id"] == scale_node["node_id"] and e.get("to_input", "default") == input_port
        )
        input_dataset = _dataset(results, source_edge["from_node_id"], source_edge.get("from_output", "default"))
        replay = scale_application.apply_fitted_state(input_dataset, scale_state)
        if sample_ids(output) != sample_ids(replay) or not np.array_equal(output.X, replay.X, equal_nan=True):
            raise ValueError("Held-out or calibration spectra differ from the exact fitted scale application.")


async def build_review_receipt(definition, results, model_id):
    path, edge = review_path(definition, model_id)
    source = _dataset(results, path[0]["node_id"])
    collection = source.meta.get("source_collection", {})
    sha = collection.get("source_manifest_sha256") or collection.get("manifest_digest")
    if not isinstance(sha, str) or len(sha) != 64:
        raise ValueError("PLS review needs exact retained source identity.")
    if len(collection.get("files", [])) != 1:
        from spectra_sherpa.app.lib.collection_assembly import verified_source_observations

        verified_source_observations(source)
    split = next((n for n in path if n["node_type"] == "data.train_test_split"), None)
    baseline = _dataset(results, edge["from_node_id"], edge.get("from_output", "default"))
    train_ids = sample_ids(baseline)
    if split:
        src_edge = next(e for e in definition["edges"] if e["to_node_id"] == split["node_id"])
        full_source = _dataset(results, src_edge["from_node_id"])
        test = _dataset(results, split["node_id"], "X_test")
        test_ids = sample_ids(test)
        if set(train_ids) & set(test_ids) or set(train_ids) | set(test_ids) != set(sample_ids(full_source)):
            raise ValueError("Train/test IDs are not an exact disjoint source partition.")
        source_positions = {identity: i for i, identity in enumerate(sample_ids(full_source))}
        for dataset in (baseline, test):
            indices = [source_positions[x] for x in sample_ids(dataset)]
            if not np.array_equal(dataset.X, full_source.X[indices], equal_nan=True) or not np.array_equal(
                np.asarray(dataset.target), np.asarray(full_source.target)[indices], equal_nan=True
            ):
                raise ValueError("Split values/targets differ from the retained source.")
    else:
        full_source, test_ids = baseline, []
    from spectra_sherpa.app.services.dag.supervision_binding import admit_attached_sample_table_supervision

    supervision = admit_attached_sample_table_supervision(full_source)
    grouped = (
        dict(zip(sample_ids(full_source), (str(value) for value in supervision.groups)))
        if supervision is not None and supervision.groups is not None
        else {}
    )
    executed_split = _executed_split(split, results, full_source, train_ids, test_ids, supervision)
    incoming = next(e for e in definition["edges"] if e["to_node_id"] == model_id)
    model_input = _dataset(results, incoming["from_node_id"], incoming.get("from_output", "default"))
    retained = sample_ids(model_input)
    excluded = [x for x in train_ids if x not in set(retained)]
    if retained != [x for x in train_ids if x in set(retained)]:
        raise ValueError("PLS input changed calibration identity/order.")
    owned = next((n for n in path if n["node_id"] == filter_id(model_id)), None)
    review_parameters = owned.get("parameters", {}) if owned else {}
    if excluded and (
        review_parameters.get("field") != "sample_table"
        or review_parameters.get("sample_table_column") != "sample_id"
        or review_parameters.get("invert") is not True
        or set(review_parameters.get("filter_values", [])) != set(excluded)
    ):
        raise ValueError("Calibration cohort does not match its review filter.")
    preprocessing, scale_state = _executed_preprocessing(path, results, model_id, retained)
    if split and scale_state is not None:
        _verify_executed_scale(definition, path, results, model_input, scale_state)
    envelope = results[model_id]["fitted_state"]
    state = verify_fitted_pls_state_envelope(envelope)
    names = state["response_identity"]["names"] or [f"Target {i+1}" for i in range(state["targets"])]
    actual_predictions = np.asarray(results[model_id]["default"], dtype=float)
    reference = np.asarray(baseline.target, dtype=float).reshape(len(train_ids), -1)
    positions = {x: i for i, x in enumerate(train_ids)}
    if (
        actual_predictions.shape != (len(retained), len(names))
        or reference.shape[1] != len(names)
        or not np.isfinite(actual_predictions).all()
        or not np.isfinite(reference).all()
    ):
        raise ValueError("Exact finite calibration references/predictions are unavailable.")
    if not np.array_equal(
        np.asarray(model_input.target).reshape(len(retained), -1), reference[[positions[x] for x in retained]]
    ):
        raise ValueError("Calibration preprocessing changed embedded target identity.")
    predictions = {identity: actual_predictions[i] for i, identity in enumerate(retained)}
    explanation_inputs = [model_input]
    projection_error = None
    if excluded:
        try:
            projected_input, projected = await project_excluded(
                path, edge, results, baseline, excluded, model_id, envelope
            )
            if projected.shape != (len(excluded), len(names)) or not np.isfinite(projected).all():
                raise ValueError("Excluded projection is not finite or aligned.")
            predictions.update({identity: projected[i] for i, identity in enumerate(excluded)})
            explanation_inputs.append(projected_input)
        except (ValueError, TypeError, KeyError) as exc:
            projection_error = str(exc)
    rows = []
    for i, identity in enumerate(train_ids):
        predicted = predictions.get(identity)
        rows.append(
            {
                "id": identity,
                "role": "excluded_projected" if identity in excluded else "calibration",
                "group": grouped.get(
                    identity,
                    str(baseline.sample_axis.classes[i]) if baseline.sample_axis.classes is not None else "Calibration",
                ),
                "reference": reference[i].tolist(),
                "predicted": predicted.tolist() if predicted is not None else None,
                "residual": (reference[i] - predicted).tolist() if predicted is not None else None,
                "scores": None,
                "t2": None,
                "q": None,
                **({"projection_error": projection_error} if predicted is None else {}),
            }
        )
    if split:
        predictor = next(
            n for n in definition["nodes"] if n["node_type"] in {"model.predict_regression", "model.apply_fitted_pls"}
        )
        output = results[predictor["node_id"]]
        prediction_edge = next(
            e
            for e in definition["edges"]
            if e["to_node_id"] == predictor["node_id"] and e.get("to_input", "default") == "default"
        )
        test_model_input = _dataset(
            results, prediction_edge["from_node_id"], prediction_edge.get("from_output", "default")
        )
        if sample_ids(test_model_input) != test_ids or not np.array_equal(
            np.asarray(test_model_input.target), np.asarray(test.target), equal_nan=True
        ):
            raise ValueError("Held-out preprocessing changed original test observation or response identity.")
        predicted = np.asarray(output["default"], dtype=float)
        identity = output["prediction_identity"]
        if (
            identity.get("sample_ids") != test_ids
            or identity.get("sample_labels")
            != (list(test_model_input.sample_axis.labels) if test_model_input.sample_axis.labels is not None else None)
            or identity.get("prediction_sha256")
            != hashlib.sha256(np.asarray(predicted, dtype="<f8").tobytes(order="C")).hexdigest()
            or identity.get("fitted_state_custody", {}).get("state_content_digest") != envelope["state_content_digest"]
            or identity.get("response_identity") != state["response_identity"]
        ):
            raise ValueError("Held-out prediction identity/state custody failed.")
        reference = np.asarray(test.target, dtype=float).reshape(len(test_ids), -1)
        if reference.shape != predicted.shape or not np.isfinite(reference).all() or not np.isfinite(predicted).all():
            raise ValueError("Held-out references and predictions are not aligned and finite.")
        explanation_inputs.append(test_model_input)
        for i, identity in enumerate(test_ids):
            rows.append(
                {
                    "id": identity,
                    "role": "held_out_test",
                    "group": grouped.get(
                        identity,
                        str(test.sample_axis.classes[i]) if test.sample_axis.classes is not None else "Test",
                    ),
                    "reference": reference[i].tolist(),
                    "predicted": predicted[i].tolist(),
                    "residual": (reference[i] - predicted[i]).tolist(),
                    "scores": None,
                    "t2": None,
                    "q": None,
                }
            )
    from .dataset_views import review_curation_binding

    receipt = {
        "dataset_curation_source": review_curation_binding(source, path[0]["parameters"]),
        "schema_version": SCHEMA,
        "identity_field": "sample_id",
        "model_kind": "pls",
        "pca_node_id": model_id,
        "graph_digest": compute_workflow_hash(definition["nodes"], definition["edges"]),
        "source_digest": source_replay_digest(full_source),
        "source_execution_digest": full_source.scientific_digest,
        "source_manifest_sha256": sha,
        "insertion_edge": edge,
        "filter_id": filter_id(model_id),
        "rows": rows,
        "n_calibration": len(retained),
        "n_components": state["effective_n_components"],
        "target_names": names,
        "target_units": state["response_identity"]["units"],
        "preprocessing": preprocessing,
        "executed_split": executed_split,
        "calibration_ids": train_ids,
        "heldout_ids": test_ids,
        "spectra": spectral_display(full_source),
        "source_spectral_space": "Saved workflow input after source curation, before preprocessing",
        "full_test_statistics": statistics([r for r in rows if r["role"] == "held_out_test"], names),
        "calibration_statistics": statistics([r for r in rows if r["role"] == "calibration"], names),
        "interpretation": (
            "Residual = reference − predicted. Calibration review is adaptive development. "
            "Full-test metrics always retain every original test observation."
        ),
    }
    from spectra_sherpa.app.lib.reference_value_evidence import bound_reference_value_evidence

    reference_evidence = bound_reference_value_evidence(
        model_input,
        response_names=names,
        response_units=state["response_identity"]["units"],
        target_type="continuous",
    )
    if reference_evidence is not None:
        receipt["reference_value_evidence"] = reference_evidence

    from .pls_review_applicability import build_applicability, without_decomposition

    try:
        applicability, updates = await asyncio.to_thread(
            build_applicability,
            state,
            envelope["state_content_digest"],
            envelope["source_contract_digest"],
            explanation_inputs,
            rows,
            [n["node_type"] for n in path if n["node_type"] in PLS_PREPROCESSORS],
            results[model_id]["x_scores"],
            results[model_id]["x_loadings"],
        )
        candidate = {
            **receipt,
            "pls_applicability": applicability,
            "rows": [{**row, **updates.get(row["id"], {})} for row in rows],
        }
        if len(json.dumps(candidate, allow_nan=False).encode()) > MAX_RECEIPT_BYTES:
            applicability = without_decomposition(
                applicability, "Optional terms exceed the retained review receipt budget."
            )
            candidate["pls_applicability"] = applicability
            if len(json.dumps(candidate, allow_nan=False).encode()) > MAX_RECEIPT_BYTES:
                raise ValueError("PLS applicability exceeds the retained review receipt budget.")
        for row in rows:
            row.update(
                updates.get(
                    row["id"],
                    {
                        "applicability_unavailable_reason": row.get("projection_error")
                        or "Exact projected input unavailable."
                    },
                )
            )
        receipt["pls_applicability"] = applicability
    except (ValueError, TypeError, KeyError) as exc:
        receipt["pls_applicability"] = {"unavailable_reason": str(exc)}

    from .pls_review_explanations import build_explanations

    try:
        receipt["pls_explanations"] = await asyncio.to_thread(
            build_explanations,
            state,
            envelope["state_content_digest"],
            envelope["source_contract_digest"],
            explanation_inputs,
            rows,
            [n["node_type"] for n in path if n["node_type"] in PLS_PREPROCESSORS],
            results[model_id]["x_loadings"],
        )
        if len(json.dumps(receipt, allow_nan=False).encode()) > MAX_RECEIPT_BYTES:
            raise ValueError("PLS explanations exceed the retained review budget.")
    except (ValueError, TypeError, KeyError) as exc:
        receipt["pls_explanations"] = {"unavailable_reason": str(exc)}
    try:
        display = model_input_spectral_display(explanation_inputs, [row["id"] for row in rows])
        receipt["model_input_spectral_space"] = display["space"]
        receipt["model_input_signal_units"] = display["signal_units"]
        receipt["model_input_axis_units"] = display["units"]
        if len(json.dumps({**receipt, "model_input_spectra": display}, allow_nan=False).encode()) > MAX_RECEIPT_BYTES:
            raise ValueError("Optional transformed spectra exceed the retained review receipt budget.")
        receipt["model_input_spectra"] = display
    except (ValueError, TypeError, KeyError) as exc:
        receipt["model_input_spectra"] = {"unavailable_reason": str(exc)}
    return receipt


async def project_excluded(path, edge, results, baseline, excluded, model_id, envelope):
    # Apply through the existing SDK execution authority: never reconstruct coefficients or fit.
    from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import _slice_dataset_rows

    projection = _slice_dataset_rows(
        baseline,
        baseline.X,
        np.asarray([i for i, x in enumerate(sample_ids(baseline)) if x in set(excluded)], dtype=int),
    )
    start = next(i for i, n in enumerate(path) if n["node_id"] == edge["from_node_id"]) + 1
    for node in path[start:-1]:
        if node["node_id"] == filter_id(model_id):
            continue
        if node["node_type"] in {"preprocess.scale", SHARED_SCALE}:
            # Calibration-only preprocessing uses the exact executed fit, as in PCA review.
            from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode

            history = _dataset(results, node["node_id"]).provenance.to_list()
            states = [
                h["parameters"]["transform_state"]
                for h in history
                if h.get("node_id") == node["node_id"] and h.get("op_id") == "preprocess.scale"
            ]
            if len(states) != 1:
                raise ValueError("Exact fitted scaling state unavailable.")
            projection = ScaleNode(node["node_id"], node.get("parameters") or {}).apply_fitted_state(
                projection, states[0]
            )
        else:
            projection = await apply_operation(node["node_type"], {"default": projection}, node.get("parameters"))
        if sample_ids(projection) != excluded:
            raise ValueError("Preprocessing changed calibration identity.")
    # Existing canonical DAG prediction injection (executor.py inject_result):
    # an exact just-executed producer output is cached, so only prediction runs.
    # No writer is granted; an accidental fit cannot publish an artifact.
    from spectra_sherpa.app.services.dag.executor import DAGExecutor
    from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
    from spectra_sherpa.sdk.deployment import DEPLOYMENT_INPUT_SCHEMA

    executor = DAGExecutor()
    executor.add_node(
        WorkflowNode(
            "review.input", "deploy.input", {"stream_name": "review", "schema_version": DEPLOYMENT_INPUT_SCHEMA}
        )
    )
    executor.add_node(WorkflowNode("review.fit", "model.fitted_pls", {}))
    executor.add_node(WorkflowNode("review.predict", "model.predict_regression", {}))
    executor.add_edge(WorkflowEdge("review.input", "review.fit"))
    executor.add_edge(WorkflowEdge("review.input", "review.predict"))
    executor.add_edge(WorkflowEdge("review.fit", "review.predict", "fitted_state", "fitted_state"))
    executor.inject_deployment_input("review.input", projection.copy(), stream_name="review")
    executor.inject_result("review.fit", {"fitted_state": deepcopy(envelope)})
    applied = await executor.execute()
    return projection, np.asarray(applied["review.predict"]["default"])
