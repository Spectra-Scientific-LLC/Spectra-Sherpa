"""Conservative project comparison of exact saved-model evidence.

This projection never promotes a calibration or adaptive-CV score to an
independent-test result. Missing source receipts remain explicit gaps.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: object) -> float | None:
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _at_response(value: object, index: int) -> float | None:
    if isinstance(value, list) and index < len(value):
        return _number(value[index])
    return None


def _selected_row(value: object, selected: int) -> Mapping[str, Any]:
    if not isinstance(value, list):
        return {}
    return next(
        (
            row
            for row in value
            if isinstance(row, Mapping) and row.get("components") == selected and row.get("status") == "available"
        ),
        {},
    )


def _response_identity(manifest: Mapping[str, Any], curve: Mapping[str, Any]) -> tuple[list[str], list[str | None]]:
    identity = _mapping(manifest.get("response_identity"))
    names = identity.get("names") or manifest.get("target_names") or curve.get("response_names")
    if manifest.get("model_type") == "plsda" and isinstance(manifest.get("selected_target"), str):
        names = [manifest["selected_target"]]
    if manifest.get("model_type") == "plsda" and not names:
        chain = manifest.get("preprocessing_chain")
        attached = set()
        if isinstance(chain, list):
            for step in chain:
                if not isinstance(step, dict) or step.get("op_id") != "data.attach_target":
                    continue
                params = _mapping(step.get("parameters"))
                authority = _mapping(params.get("target_authority"))
                candidate = authority.get("column") or params.get("target_column")
                if isinstance(candidate, str) and candidate.strip():
                    attached.add(candidate)
        if len(attached) == 1:
            names = list(attached)
    units = identity.get("units", curve.get("response_units"))
    if not isinstance(names, list) or not names or any(not isinstance(name, str) or not name.strip() for name in names):
        return [], []
    if (
        not isinstance(units, list)
        or len(units) != len(names)
        or any(unit is not None and (not isinstance(unit, str) or not unit.strip()) for unit in units)
    ):
        return names, [None] * len(names)
    return names, units


def _source_view(run_source: object) -> str | None:
    source = _mapping(run_source)
    revisions = source.get("data_selection_revisions")
    if not isinstance(revisions, list) or not revisions or any(not isinstance(item, dict) for item in revisions):
        return None
    return _digest(revisions)


def model_component_count(model: Any, manifest: Mapping[str, Any]) -> int | None:
    """Use the sealed PLS-DA fit count when older DB rows omitted it."""

    if model.model_type != "plsda":
        return model.n_components
    effective = manifest.get("effective_n_components", manifest.get("n_components"))
    stored = manifest.get("n_components")
    if (
        type(effective) is not int
        or effective < 1
        or (stored is not None and stored != effective)
        or (model.n_components is not None and model.n_components != effective)
    ):
        return None
    return effective


def verified_run_definition(value: object, integrity_hash: str | None) -> Mapping[str, Any] | None:
    """Accept an exact retained graph only when it matches the producing run."""

    from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash

    definition = _mapping(value)
    if (
        not isinstance(integrity_hash, str)
        or len(integrity_hash) != 64
        or definition.get("integrity_hash") != integrity_hash
        or not isinstance(definition.get("nodes"), list)
        or not isinstance(definition.get("edges"), list)
    ):
        return None
    try:
        return definition if compute_workflow_hash(definition["nodes"], definition["edges"]) == integrity_hash else None
    except (TypeError, ValueError, KeyError):
        return None


def heldout_evaluator_nodes(snapshot: object, model_node_id: str | None) -> list[str]:
    """Find evaluators fed by the exact model's held-out prediction path."""
    graph = _mapping(snapshot)
    if not model_node_id or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        return []
    node_types = {
        node.get("node_id"): node.get("node_type")
        for node in graph["nodes"]
        if isinstance(node, dict) and isinstance(node.get("node_id"), str)
    }
    if node_types.get(model_node_id) != "classification.plsda":
        return []
    inputs: dict[tuple[str, str], set[tuple[str, str | None]]] = {}
    for edge in graph["edges"]:
        if not isinstance(edge, dict):
            continue
        source = edge.get("from_node_id", edge.get("source", edge.get("from_node")))
        target = edge.get("to_node_id", edge.get("target", edge.get("to_node")))
        if source in node_types and target in node_types and isinstance(edge.get("to_input"), str):
            inputs.setdefault((target, edge["to_input"]), set()).add((source, edge.get("from_output")))
    applications = {
        node
        for node, kind in node_types.items()
        if kind == "classification.apply_plsda"
        and inputs.get((node, "fitted_state")) == {(model_node_id, "fitted_state")}
    }
    return sorted(
        node
        for node, kind in node_types.items()
        if kind == "diagnostics.classification_evaluator"
        and any(inputs.get((node, "default")) == {(apply, "y_pred")} for apply in applications)
    )


def verified_heldout_classification(value: object) -> bool:
    """Admit only exact evaluator output carrying executor-owned held-out authority."""
    result = _mapping(value)
    authority = _mapping(result.get("population_authority"))
    return (
        result.get("schema_version") == "spectrasherpa.classification-evaluation/1"
        and result.get("task_type") == "classification"
        and type(result.get("n_samples")) is int
        and result["n_samples"] > 0
        and _number(result.get("balanced_accuracy")) is not None
        and authority.get("schema_version") == "spectrasherpa-population-authority/1"
        and authority.get("role") == "held_out_test"
        and authority.get("qualification") == "graph_verified"
    )


def heldout_regression_evaluator_nodes(snapshot: object, model_node_id: str | None) -> list[str]:
    """Find the default PLS starter's evaluator bound to this fit and split."""
    graph = _mapping(snapshot)
    if not model_node_id or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        return []
    node_types = {
        node.get("node_id"): node.get("node_type")
        for node in graph["nodes"]
        if isinstance(node, dict) and isinstance(node.get("node_id"), str)
    }
    if node_types.get(model_node_id) != "model.fitted_pls":
        return []
    inputs: dict[tuple[str, str], set[tuple[str, str | None]]] = {}
    for edge in graph["edges"]:
        if not isinstance(edge, dict):
            continue
        source = edge.get("from_node_id", edge.get("source", edge.get("from_node")))
        target = edge.get("to_node_id", edge.get("target", edge.get("to_node")))
        if source in node_types and target in node_types and isinstance(edge.get("to_input"), str):
            inputs.setdefault((target, edge["to_input"]), set()).add((source, edge.get("from_output")))
    splits = {
        split
        for split, kind in node_types.items()
        if kind == "data.train_test_split" and inputs.get((model_node_id, "default")) == {(split, "X_train")}
        # With no explicit y port, fitted PLS uses the target embedded in X_train.
        # An explicit response must belong to this same training partition.
        and inputs.get((model_node_id, "y"), set()) in (set(), {(split, "y_train")})
    }
    return sorted(
        evaluator
        for evaluator, kind in node_types.items()
        if kind == "diagnostics.labeled_regression_evaluator"
        for split in splits
        for predictor, predictor_kind in node_types.items()
        if predictor_kind == "model.predict_regression"
        and inputs.get((predictor, "fitted_state")) == {(model_node_id, "fitted_state")}
        and inputs.get((predictor, "default")) == {(split, "X_test")}
        and inputs.get((evaluator, "default")) == {(predictor, "default")}
        and inputs.get((evaluator, "y_true")) == {(split, "y_test")}
        and inputs.get((evaluator, "sample_context")) == {(split, "X_test")}
    )


def verified_heldout_regression(value: object) -> bool:
    """Admit only finite metric output; the caller must verify graph custody."""
    result = _mapping(value)
    return (
        result.get("task_type") == "regression"
        and type(result.get("n_samples")) is int
        and result["n_samples"] > 0
        and isinstance(result.get("registry_version"), str)
        and bool(result["registry_version"])
        and (_number(result.get("rmse")) is not None and result["rmse"] >= 0)
    )


def project_model_row(
    model: Any,
    manifest: Mapping[str, Any],
    *,
    curve: Mapping[str, Any] | None = None,
    run_source: object = None,
    exclusions: Mapping[str, Any] | None = None,
    qualification: Mapping[str, Any] | None = None,
    heldout: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project only evidence tied to the verified artifact and producing run."""

    curve = _mapping(curve)
    metrics = _mapping(manifest.get("metrics"))
    names, units = _response_identity(manifest, curve)
    selected = model_component_count(model, manifest)
    curve_compatible = (
        type(selected) is int
        and selected > 0
        and selected == curve.get("selected_components")
        and (
            (model.model_type == "pls" and curve.get("schema_version") == "spectrasherpa-pls-component-curve/1")
            or (model.model_type == "plsda" and curve.get("schema_version") == "spectrasherpa-plsda-component-curve/1")
            or (model.model_type == "pca" and curve.get("schema_version") == "spectrasherpa-pca-component-curve/1")
        )
    )
    if model.model_type == "pls" and curve_compatible:
        curve_compatible = curve.get("response_names") == names and curve.get("response_units") == units
    if not curve_compatible:
        curve = {}
    calibration = _selected_row(curve.get("calibration"), selected)
    cv = _mapping(curve.get("cross_validation"))
    validation = _selected_row(cv.get("rows"), selected) if cv.get("status") == "available" else {}
    classification = model.model_type == "plsda"
    # This retained overview supports PLS response-error/qualification receipts.
    # PCA reconstruction error is not response prediction error (RMSEP).
    regression = model.model_type == "pls"
    heldout = _mapping(heldout)
    single = len(names) == 1
    measured: dict[str, float | None] = {
        "rmsec": _at_response(calibration.get("rmsec"), 0) if single else None,
        "rmsecv": _at_response(validation.get("rmsecv"), 0) if single else None,
        "rmsep": None,
        "r2_calibration": _at_response(calibration.get("r2y_cumulative"), 0) if single else None,
        "q2_cv": _at_response(validation.get("q2"), 0) if single else None,
    }
    classification_metrics = (
        {
            "calibration_balanced_accuracy": _number(calibration.get("balanced_accuracy")),
            "cv_balanced_accuracy": _number(validation.get("balanced_accuracy")),
            "held_out_balanced_accuracy": _number(heldout.get("balanced_accuracy")),
            "held_out_accuracy": _number(heldout.get("accuracy")),
        }
        if classification
        else None
    )
    # Legacy model metrics are calibration summaries unless an explicit
    # separate source and role establishes otherwise. Keep them visible as
    # labelled evidence without relabelling them RMSEP or Q².
    calibration_metrics = {
        key: value
        for key, value in metrics.items()
        if key in ("r2", "rmse", "r2_cal", "rmse_cal") and _number(value) is not None
    }
    reference = _mapping(manifest.get("reference_value_evidence"))
    context = _mapping(manifest.get("reference_fit_context"))
    method = _mapping(reference.get("method"))
    reference_method = method.get("method_id")
    precision = _mapping(method.get("precision"))
    source_view_digest = _source_view(run_source)
    split_digest = cv.get("split_digest") if cv.get("status") == "available" else None
    training_scientific_digest = model.training_scientific_digest
    admitted_exclusions = _mapping(exclusions)
    exact_excluded = admitted_exclusions.get("excluded")
    if not isinstance(exact_excluded, list) or any(not isinstance(item, str) for item in exact_excluded):
        exact_excluded = None
    comparable = (
        model.model_type == "pls"
        and single
        and all(isinstance(value, str) and value for value in (source_view_digest, split_digest))
        and isinstance(training_scientific_digest, str)
        and len(training_scientific_digest) == 64
        and exact_excluded is not None
        and model.training_dataset_id is not None
        and measured["rmsecv"] is not None
    )
    comparison_key = (
        _digest(
            {
                "target": names[0],
                "units": units[0],
                "training_dataset_id": model.training_dataset_id,
                "training_scientific_digest": training_scientific_digest,
                "source_view": source_view_digest,
                "split": split_digest,
                "excluded_sample_ids": sorted(exact_excluded),
                "metric": "rmsecv",
            }
        )
        if comparable
        else None
    )
    qualification = _mapping(qualification) or {
        "state": "unavailable",
        "reason": "No E1655 assessment is bound to this exact saved model.",
    }
    external = _mapping(qualification.get("external_validation")) if qualification.get("state") != "stale" else {}
    external_responses = external.get("responses")
    exact_external = (
        external_responses[0]
        if single and isinstance(external_responses, list) and len(external_responses) == 1
        else {}
    )
    exact_external = _mapping(exact_external)
    measured["rmsep"] = _number(exact_external.get("rmse"))
    interval_coverage = external.get("interval_coverage")
    gaps = []
    if regression and measured["rmsep"] is None:
        gaps.append("Independent-test RMSEP and count unavailable")
    if regression and (_number(exact_external.get("bias")) is None or not isinstance(interval_coverage, list)):
        gaps.append("Independent bias or interval coverage evidence unavailable")
    if classification and classification_metrics["held_out_balanced_accuracy"] is None:
        gaps.append("Exact held-out classification evaluation unavailable")
    if measured["rmsec"] is None and model.model_type == "pls":
        gaps.append("Exact selected-component calibration error unavailable")
    if measured["rmsecv"] is None and model.model_type == "pls":
        gaps.append("Executed model-bound CV error unavailable")
    if not reference_method and regression:
        gaps.append("Reference method unavailable")
    return {
        "artifact_uid": model.artifact_uid,
        "artifact_integrity_hash": model.integrity_hash,
        "evidence": {
            "source_run_id": model.source_run_id,
            "component_curve_sha256": _digest(curve) if curve else None,
            "source_view_sha256": source_view_digest,
            "executed_cv_split_sha256": split_digest,
            "training_scientific_sha256": training_scientific_digest,
            "sample_table_sha256": reference.get("sample_table_sha256"),
        },
        "name": model.display_name or model.name,
        "model_type": model.model_type,
        "regression_metrics_applicable": regression,
        "analytical_qualification_applicable": regression or classification,
        "source_run_id": model.source_run_id,
        "workflow_id": model.workflow_id,
        "training_dataset_id": model.training_dataset_id,
        "target_names": names,
        "target_units": units,
        "preprocessing": (
            manifest.get("preprocessing_chain") if isinstance(manifest.get("preprocessing_chain"), list) else None
        ),
        "components": selected,
        "calibration_count": (
            curve.get("n_calibration") if type(curve.get("n_calibration")) is int else context.get("calibration_rows")
        ),
        "validation": {
            "role": cv.get("role") if cv.get("status") == "available" else None,
            "method": cv.get("method") if cv.get("status") == "available" else None,
            "folds": cv.get("n_folds") if cv.get("status") == "available" else None,
            "split_digest": split_digest,
            "unavailable_reason": (
                None
                if cv.get("status") == "available"
                else cv.get("reason") or "No exact executed validation receipt is retained for this model."
            ),
        },
        "held_out_validation": (
            {
                "role": "held_out_test",
                "count": heldout.get("n_samples"),
                "population_authority": dict(_mapping(heldout.get("population_authority"))),
            }
            if classification and classification_metrics["held_out_balanced_accuracy"] is not None
            else (
                {
                    "role": "within_dataset_held_out_test",
                    "count": heldout.get("n_samples"),
                    "rmse": heldout.get("rmse"),
                }
                if model.model_type == "pls" and heldout.get("graph_verified") is True
                else None
            )
        ),
        "metrics": measured,
        "classification_metrics": classification_metrics,
        "legacy_calibration_metrics": calibration_metrics,
        "independent_test_count": (
            heldout.get("n_samples")
            if classification and type(heldout.get("n_samples")) is int
            else external.get("count") if not classification and type(external.get("count")) is int else None
        ),
        "reference_quality": {
            "method": reference_method if isinstance(reference_method, str) else None,
            "version": method.get("version") if isinstance(method.get("version"), str) else None,
            "measurement_basis": method.get("measurement_basis"),
            "measurements_per_label": method.get("measurements_per_label"),
            "precision": dict(precision) if precision else None,
            "precision_study_provenance": reference.get("precision_study_provenance"),
            "replicate_evidence_digest": reference.get("replicate_evidence_digest"),
            "qualification_gaps": reference.get("qualification_gaps"),
            "reason": None if reference_method else "Reference method was not retained for this saved model.",
        },
        "external_reference_quality": dict(_mapping(external.get("reference_method"))) or None,
        "applicability_method": _mapping(manifest.get("diagnostic_state")).get("method"),
        "bias": _number(exact_external.get("bias")),
        "coverage": _at_response(interval_coverage, 0) if single else None,
        "coverage_denominator": (
            external.get("interval_available_rows")
            if single and type(external.get("interval_available_rows")) is int
            else None
        ),
        "exclusions": exact_excluded,
        "qualification": dict(qualification),
        "operational_deploy_ready": model.is_deploy_ready,
        "comparison_key": comparison_key,
        "comparison_reason": (
            None
            if comparable
            else (
                "Classification results are shown without an automatic ranking."
                if classification
                else "Ranking requires one response, exact fitted cohort and exclusions, "
                "source view, and executed CV split."
            )
        ),
        "gaps": gaps,
    }
