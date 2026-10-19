"""Read-only, bounded scientific facts from a caller-verified review receipt.

This projector performs no fit, filesystem read or disclosure decision. The caller
must authenticate and verify retained-run custody, then gate this packet on every
provider round. Aliases conceal labels, not the sensitivity of scientific values.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

import numpy as np

SCHEMA = "diagnostic-review-summary/1"
MAX_BYTES = 16 * 1024
MAX_SELECTED = 5000
MAX_DETAILS = 5
MAX_VARIABLES = 10
ROLES = ("calibration", "excluded_projected", "held_out_test")


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


def _text(value, maximum=80):
    # These are bounded scientific labels, never free-form annotation text.
    return value[:maximum] if isinstance(value, str) else None


def _at(value, index):
    return value[index] if isinstance(value, (list, tuple)) and 0 <= index < len(value) else None


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _hash(value):
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


def _validate_scope(receipt, selected_ids, response_index, variable_ids):
    rows = receipt.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > 5000:
        raise ValueError("A bounded retained diagnostic receipt is required.")
    ids = [row.get("id") for row in rows]
    if any(not isinstance(identity, str) for identity in ids) or len(set(ids)) != len(ids):
        raise ValueError("Receipt observation identity is invalid.")
    if (
        not isinstance(selected_ids, list)
        or not 1 <= len(selected_ids) <= MAX_SELECTED
        or any(not isinstance(identity, str) for identity in selected_ids)
        or len(set(selected_ids)) != len(selected_ids)
        or not set(selected_ids).issubset(ids)
    ):
        raise ValueError("Selection must contain unique observations from the retained receipt.")
    if any(row.get("role") not in ROLES for row in rows):
        raise ValueError("Unsupported diagnostic population.")
    kind = receipt.get("model_kind", "pca")
    if kind not in {"pca", "pls"}:
        raise ValueError("Only retained PCA and PLS diagnostic receipts are supported.")
    if isinstance(response_index, bool) or not isinstance(response_index, int) or response_index < 0:
        raise ValueError("Response index must identify a retained response.")
    names = receipt.get("target_names") or []
    if kind == "pls" and response_index >= len(names):
        raise ValueError("Response index must identify a retained response.")
    if kind == "pca" and response_index != 0:
        raise ValueError("PCA does not have response targets.")
    explanation = receipt.get("pls_explanations" if kind == "pls" else "explanations") or {}
    available = isinstance(explanation.get("rows"), dict)
    applicability = receipt.get("pls_applicability") or {} if kind == "pls" else {}
    applicability_available = isinstance(applicability.get("rows"), dict)
    if (
        available
        and applicability_available
        and explanation.get("feature_identity") != applicability.get("feature_identity")
    ):
        raise ValueError("Prediction and applicability fitted variable identities disagree.")
    variable_basis = explanation if available else applicability
    feature_identity = variable_basis.get("feature_identity")
    requested_variables = []
    if variable_ids:
        if len(variable_ids) > MAX_VARIABLES or len(set(variable_ids)) != len(variable_ids):
            raise ValueError("Select at most ten unique fitted variables.")
        for identity in variable_ids:
            match = re.fullmatch(r"(.+):(0|[1-9][0-9]*)", identity) if isinstance(identity, str) else None
            if (
                not (available or applicability_available)
                or match is None
                or match[1] != feature_identity
                or int(match[2]) >= variable_basis.get("feature_count", 0)
            ):
                raise ValueError("Variable identity does not belong to the retained fitted axis.")
            requested_variables.append(int(match[2]))
    return rows, ids, kind, names, explanation, available, requested_variables


def _population_facts(receipt, rows, selected, kind, response_index, units, fact, result):
    for role in ROLES:
        population = [row for row in rows if row["role"] == role]
        if not population:
            continue
        subset = [row for _, row in selected if row["role"] == role]
        counts = {"total": len(population), "selected": len(subset)}
        result["populations"][role] = counts
        for key, value in counts.items():
            fact(f"{role}.{key}", value, key + " observations", role)
        if kind == "pls":
            references = [_number(_at(row.get("reference"), response_index)) for row in population]
            references = [x for x in references if x is not None]
            for label, fn in (("minimum", min), ("maximum", max)):
                fact(
                    f"{role}.reference.{label}",
                    fn(references) if references else None,
                    "Observed reference " + label,
                    role,
                    units,
                )
        diagnostics = ("t2", "q") if kind == "pca" else ("residual",)
        for diagnostic in diagnostics:
            values = [
                _number(_at(row.get(diagnostic), response_index) if kind == "pls" else row.get(diagnostic))
                for row in population
            ]
            finite = [x for x in values if x is not None]
            fact(f"{role}.{diagnostic}.valid", len(finite), "Finite diagnostic denominator", role)
            fact(f"{role}.{diagnostic}.missing", len(values) - len(finite), "Missing diagnostic values", role)
            quantiles = np.quantile(finite, [0.25, 0.5, 0.75], method="linear") if finite else [None] * 3
            for label, value in zip(("q1", "median", "q3"), quantiles):
                fact(
                    f"{role}.{diagnostic}.{label}",
                    float(value) if value is not None else None,
                    diagnostic + " " + label + ", linear quantile",
                    role,
                    units if kind == "pls" else None,
                )
        if subset:
            selected_handles = {}
            for diagnostic in diagnostics + (("absolute_residual",) if kind == "pls" else ()):
                field = "residual" if diagnostic == "absolute_residual" else diagnostic
                reuse = len(subset) == len(population) and diagnostic != "absolute_residual"
                prefix = f"{role}.{diagnostic}" if reuse else f"{role}.selected.{diagnostic}"
                if not reuse:
                    values = [
                        _number(_at(row.get(field), response_index) if kind == "pls" else row.get(field))
                        for row in subset
                    ]
                    finite = [abs(x) if diagnostic == "absolute_residual" else x for x in values if x is not None]
                    fact(prefix + ".valid", len(finite), "Selected finite denominator", role)
                    fact(prefix + ".missing", len(values) - len(finite), "Selected missing values", role)
                    quantiles = np.quantile(finite, [0.25, 0.5, 0.75], method="linear") if finite else [None] * 3
                    for label, value in zip(("q1", "median", "q3"), quantiles):
                        fact(
                            prefix + "." + label,
                            float(value) if value is not None else None,
                            "Selected " + diagnostic + " " + label,
                            role,
                            units if kind == "pls" else None,
                        )
                selected_handles[diagnostic] = {
                    label: prefix + "." + label for label in ("valid", "missing", "q1", "median", "q3")
                }
            result.setdefault("selected_population_statistics", {})[role] = selected_handles
        if kind == "pca":
            t_limit = _number(receipt.get("calibration_t2_limit" if role == "calibration" else "application_t2_limit"))
            q_limit = _number(receipt.get("q_limit"))
            bins = dict.fromkeys(("t2_only", "q_only", "both", "neither", "unknown"), 0)
            for row in subset:
                t, q = _number(row.get("t2")), _number(row.get("q"))
                if None in (t, q, t_limit, q_limit):
                    bins["unknown"] += 1
                else:
                    high_t, high_q = t > t_limit, q > q_limit
                    bins[
                        "both" if high_t and high_q else "t2_only" if high_t else "q_only" if high_q else "neither"
                    ] += 1
            for key, value in bins.items():
                fact(f"{role}.selected.{key}", value, "Selected screening count, strict greater-than limits", role)


def _bound_packet(result):
    facts = result["facts"]

    def size():
        return len(json.dumps(result, allow_nan=False, separators=(",", ":")).encode()) + 100

    # Keep exact population summaries and totals before sparse variable details.
    while size() > MAX_BYTES and any(
        any(not group.get("requested") for group in d["variables"]) for d in result["samples"]
    ):
        detail = max(result["samples"], key=lambda d: sum(not group.get("requested") for group in d["variables"]))
        index = next(
            i for i in reversed(range(len(detail["variables"]))) if not detail["variables"][i].get("requested")
        )
        group = detail["variables"].pop(index)
        for key in group["facts"]:
            del facts[key]
        result["omissions"]["variable_details"] += 1
    while size() > MAX_BYTES and result["profiles"]:
        profile = result["profiles"].pop()
        for key in profile["facts"]:
            del facts[key]
        result["omissions"]["profile_values"] += len(profile["facts"])
    while size() > MAX_BYTES and len(result["samples"]) > 1:
        detail = result["samples"].pop()
        for key in detail["facts"]:
            del facts[key]
        for group in detail["variables"]:
            for key in group["facts"]:
                del facts[key]
            result["omissions"]["variable_details"] += 1
        result["omissions"]["sample_details"] += 1
    if size() > MAX_BYTES:
        for detail in result["samples"]:
            for handle in list(detail["facts"]):
                if size() <= MAX_BYTES:
                    break
                if ".applicability.score" in handle:
                    del facts[handle]
                    detail["facts"].remove(handle)
                    result["omissions"]["score_coordinates"] = result["omissions"].get("score_coordinates", 0) + 1
    if size() > MAX_BYTES and result.get("applicability_statistics"):
        optional = [key for key in facts if key.endswith((".q1", ".q3", ".median"))]
        optional.sort(key=lambda key: key.endswith(".median"))
        for handle in optional:
            if size() <= MAX_BYTES:
                break
            del facts[handle]
            for role_stats in result.get("selected_population_statistics", {}).values():
                for metric_stats in role_stats.values():
                    for name in [name for name, value in metric_stats.items() if value == handle]:
                        del metric_stats[name]
            result["omissions"]["aggregate_quantiles"] = result["omissions"].get("aggregate_quantiles", 0) + 1
    if size() > MAX_BYTES and result.get("applicability_statistics"):
        # Missing custody/baseline scalars add no measured evidence. Keep the
        # custody limitations and explicit omission count; never discard a
        # retained identity, count, or verified baseline statistic here.
        unknown_context = [
            key
            for key, value in facts.items()
            if key.startswith(("dataset.", "review_baseline.")) and value["value"] is None
        ]
        if unknown_context:
            result["limitations"].append("Omitted unknown dataset/baseline context remains unavailable.")
        for handle in unknown_context:
            if size() <= MAX_BYTES:
                break
            del facts[handle]
            result["omissions"]["unknown_context_values"] = result["omissions"].get("unknown_context_values", 0) + 1
    if size() > MAX_BYTES and result.get("applicability_statistics"):
        # Reference extrema are optional descriptive context, never the
        # performance denominator or predictor-space applicability limits.
        for handle in [key for key in facts if key.endswith((".reference.minimum", ".reference.maximum"))]:
            if size() <= MAX_BYTES:
                break
            del facts[handle]
            result["omissions"]["reference_bounds"] = result["omissions"].get("reference_bounds", 0) + 1
    if size() > MAX_BYTES:
        raise ValueError("Essential diagnostic evidence exceeds 16 KiB; select a narrower scope.")


def _curation_facts(receipt, fact, result):
    """Retained dataset binding is historical custody, never current edit state."""
    binding = receipt.get("dataset_curation_source")
    present = isinstance(binding, dict) and bool(binding)
    binding = binding if present else {}
    fact("dataset.binding_present", present, "Saved dataset curation binding retained", "dataset_source")
    observations = binding.get("observations")
    fact(
        "dataset.source_observations",
        len(observations) if isinstance(observations, list) else None,
        "Observations with saved source custody, after any source curation",
        "dataset_source",
    )
    for key, meaning in (
        ("source_manifest_sha256", "Saved source manifest identity"),
        ("collection_definition_sha256", "Saved source collection definition identity"),
        ("scientific_collection_sha256", "Saved scientific collection identity"),
        ("parent_sha256", "Saved parent dataset-view definition identity"),
    ):
        fact("dataset." + key, _hash(binding.get(key)), meaning, "dataset_source")
    for key, meaning in (
        ("source_exclusion_count", "Source exclusion count not retained"),
        ("curation_exclusion_count", "Dataset curation exclusion count not retained"),
        ("current_definition_matches", "Current dataset definition match not verified by saved receipt"),
        ("workflow_updated", "Workflow rebinding and rerun status not verified by saved receipt"),
    ):
        fact("dataset." + key, None, meaning, "dataset_source")
    result["limitations"].append(
        "Dataset identities describe the saved run only. A missing parent identity is unknown; "
        "source/curation exclusions cannot be inferred from surviving observations or workflow review exclusions. "
        "Current dataset edits and workflow rebinding/rerun require separate verification."
    )


def _pls_applicability_facts(receipt, selected, requested_variables, fact, result):
    evidence = receipt.get("pls_applicability") or {}
    if evidence.get("schema_version") != "spectrasherpa-pls-applicability-review/1":
        fact(
            "applicability.unavailable",
            _text(evidence.get("unavailable_reason"), 180) or "No retained applicability evidence",
            "Applicability unavailable",
        )
        return
    result["applicability"] = {
        key: evidence.get(key)
        for key in (
            "calibration_t2_limit_method",
            "application_t2_limit_method",
            "q_limit_method",
            "space",
            "q_units",
            "score_units",
            "neighborhood_support",
            "t2_unavailable_reason",
            "q_unavailable_reason",
        )
    }
    for key in (
        "reference_count",
        "components",
        "score_covariance_rank",
        "rank_tolerance",
        "confidence",
        "calibration_t2_limit",
        "application_t2_limit",
        "q_limit",
    ):
        fact("applicability." + key, _number(evidence.get(key)), "PLS " + key, "calibration_reference")
    result["limitations"].append(
        "PLS T² uses full score covariance; Q measures predictor reconstruction error. "
        "Neither measures response error. "
        "Calibration/application limits differ; passing global screening cannot establish local support or certainty. "
        "Q terms cannot cancel; signed T² terms can. Cancellation does not rank evidence strength."
    )
    statistics = {}
    for role in ROLES:
        subset = [row for _, row in selected if row["role"] == role]
        if not subset:
            continue
        handles = []
        for metric in ("t2", "q"):
            finite = [value for row in subset if (value := _number(row.get(metric))) is not None]
            values = {"finite": len(finite), "missing": len(subset) - len(finite)}
            values.update(zip(("q1", "median", "q3"), np.quantile(finite, [0.25, 0.5, 0.75]) if finite else [None] * 3))
            for statistic, value in values.items():
                handle = f"applicability.{role}.{metric}.{statistic}"
                handles.append(
                    fact(
                        handle,
                        float(value) if isinstance(value, np.floating) else value,
                        "Selected " + metric + " " + statistic,
                        role,
                    )
                )
        bins = dict.fromkeys(("t2_only", "q_only", "both", "neither", "unknown"), 0)
        for row in subset:
            t, q = row.get("outside_t2"), row.get("outside_q")
            bins[
                (
                    "unknown"
                    if t is None or q is None
                    else "both" if t and q else "t2_only" if t else "q_only" if q else "neither"
                )
            ] += 1
        for name, count in bins.items():
            handles.append(fact(f"applicability.{role}.{name}", count, "Selected screening " + name, role))
        statistics[role] = {"population": "selected", "quantile_method": "linear"}
    result["applicability_statistics"] = statistics
    detail_by_alias = {detail["alias"]: detail for detail in result["samples"]}
    for index, row in selected[:MAX_DETAILS]:
        alias = f"S{index + 1}"
        detail = detail_by_alias[alias]
        for metric in ("t2", "q"):
            detail["facts"].append(
                fact(
                    f"{alias}.applicability.{metric}",
                    _number(row.get(metric)),
                    "PLS predictor " + metric,
                    row["role"],
                    "dimensionless" if metric == "t2" else _text(evidence.get("q_units")),
                )
            )
        for component, value in enumerate((row.get("scores") or [])[:2]):
            detail["facts"].append(
                fact(
                    f"{alias}.applicability.score{component + 1}",
                    _number(value),
                    "Fitted PLS latent predictor coordinate",
                    row["role"],
                )
            )
        result["omissions"]["score_coordinates"] = result["omissions"].get("score_coordinates", 0) + max(
            0, len(row.get("scores") or []) - 2
        )
        saved = (evidence.get("rows") or {}).get(row["id"], {})
        for reason, value in (
            ("unavailable_reason", row.get("applicability_unavailable_reason")),
            ("decomposition_unavailable_reason", saved.get("decomposition_unavailable_reason")),
        ):
            if value:
                detail["facts"].append(
                    fact(f"{alias}.applicability.{reason}", _text(value, 180), "PLS " + reason, row["role"])
                )
        for metric in ("omitted_q", "omitted_t2", "omitted_t2_absolute"):
            detail["facts"].append(
                fact(
                    f"{alias}.applicability.{metric}",
                    _number(saved.get(metric)),
                    "Saved applicability " + metric,
                    row["role"],
                )
            )
        variables = saved.get("variables") or []
        if requested_variables:
            retained = {item[0]: item for item in variables}
            leading = [retained.get(j, [j, None, None]) for j in requested_variables]
        else:
            chosen = {item[0] for item in sorted(variables, key=lambda item: -abs(item[1]))[:5]}
            chosen.update(item[0] for item in sorted(variables, key=lambda item: -abs(item[2] or 0))[:5])
            leading = [item for item in variables if item[0] in chosen]
        result["omissions"]["variable_details"] += max(0, len(variables) - len(leading))
        for j, q, t in leading:
            group = {"index": j, "family": "pls_applicability", "requested": bool(requested_variables), "facts": []}
            for metric, value in (("q_contribution", q), ("t2_contribution", t)):
                group["facts"].append(
                    fact(f"{alias}.applicability.v{j}.{metric}", _number(value), "PLS predictor " + metric, row["role"])
                )
            detail["variables"].append(group)


def _executed_pls_preprocessing_facts(receipt, kind, result, fact):
    """Project only bounded, typed, server-verified transformation evidence."""
    if kind != "pls":
        return
    split = receipt.get("executed_split")
    if split is not None:
        if not isinstance(split, dict) or split.get("method") not in {
            "random",
            "stratified",
            "sequential",
            "group_holdout",
            "kennard_stone",
            "duplex",
            "spxy",
        }:
            raise ValueError("Executed split evidence is malformed.")
        plan_digest = _hash(split.get("plan_digest"))
        groups_digest = _hash(split.get("groups_content_digest")) if split.get("groups_content_digest") else None
        if plan_digest is None or split.get("groups_content_digest") and groups_digest is None:
            raise ValueError("Executed split custody is malformed.")
        result["executed_split"] = {}
        for key in ("method", "n_groups"):
            if key in split and split[key] is not None:
                handle = "split." + key
                value = split[key]
                if key != "method" and value is not None and (not isinstance(value, int) or value < 0):
                    raise ValueError("Executed split count is invalid.")
                fact(handle, value, "Executed split " + key, "original_partition")
                result["executed_split"][key] = handle
        fact("split.grouping_applied", groups_digest is not None, "Executed split used attached grouping authority")
        result["executed_split"]["grouping_applied"] = "split.grouping_applied"
        result["provenance"]["split.plan"] = plan_digest
        result["provenance"]["split.groups"] = groups_digest
    executed = receipt.get("preprocessing") or []
    if not isinstance(executed, list) or len(executed) > 12:
        raise ValueError("Executed preprocessing evidence is not bounded.")
    result["executed_preprocessing"] = []
    for index, step in enumerate(executed):
        if not isinstance(step, dict) or not isinstance(step.get("operation"), str):
            raise ValueError("Executed preprocessing evidence is malformed.")
        operation = step["operation"]
        if operation not in {
            "preprocess.normalize",
            "preprocess.smooth",
            "preprocess.derivative",
            "preprocess.scale",
            "preprocess.shared_reference_scale",
        }:
            raise ValueError("Executed preprocessing operation is unsupported.")
        population = step.get("fitting_population")
        if population not in {"sample_local", "retained_calibration"}:
            raise ValueError("Executed preprocessing fitting population is invalid.")
        handle = f"preprocessing.step{index + 1}"
        fact(handle + ".operation", operation, "Executed spectral transformation in saved order")
        fact(handle + ".fitting_population", population, "Population used to establish this transformation")
        detail = {"operation": handle + ".operation", "fitting_population": handle + ".fitting_population"}
        allowed = {
            "preprocess.normalize": {"method", "std_ddof", "scale_method"},
            "preprocess.smooth": {"method", "size", "order", "lam", "d", "sigma"},
            "preprocess.derivative": {"method", "deriv", "size", "order", "gap", "segment", "delta"},
            "preprocess.scale": {"method", "center"},
            "preprocess.shared_reference_scale": {"method", "center"},
        }[operation]
        parameters = step.get("parameters", {})
        if not isinstance(parameters, dict) or not set(parameters).issubset(allowed):
            raise ValueError("Executed preprocessing parameters are malformed.")
        detail["parameters"] = {}
        for key, value in sorted(parameters.items()):
            if not (
                isinstance(value, bool) or isinstance(value, str) and len(value) <= 40 or _number(value) is not None
            ):
                raise ValueError("Executed preprocessing parameter is not bounded.")
            parameter_handle = handle + "." + key
            fact(parameter_handle, value, "Executed " + operation + " setting " + key, population)
            detail["parameters"][key] = parameter_handle
        if operation in {"preprocess.scale", "preprocess.shared_reference_scale"}:
            fitted = _hash(step.get("fitted_state_sha256"))
            fitting_ids = _hash(step.get("fitting_ids_sha256"))
            count = step.get("fitting_count")
            if fitted is None or fitting_ids is None or not isinstance(count, int) or count < 1:
                raise ValueError("Calibration-fitted preprocessing custody is incomplete.")
            fact(handle + ".fitting_count", count, "Retained calibration observations used to fit scale", "calibration")
            detail["fitting_count"] = handle + ".fitting_count"
            result["provenance"][handle + ".state"] = fitted
            result["provenance"][handle + ".fitting_ids"] = fitting_ids
        result["executed_preprocessing"].append(detail)
    source_display = receipt.get("spectra") or {}
    transformed_display = receipt.get("model_input_spectra") or {}
    if not executed:
        return
    fact("spectra.source_space", _text(receipt.get("source_spectral_space")), "Saved source spectral display space")
    fact(
        "spectra.source_signal_units",
        _text(source_display.get("signal_units")) if isinstance(source_display, dict) else None,
        "Source spectral signal units",
    )
    fact(
        "spectra.model_input_signal_units",
        _text(receipt.get("model_input_signal_units")),
        "Executed PLS model-input signal units",
    )
    fact(
        "spectra.model_input_space",
        _text(receipt.get("model_input_spectral_space")),
        "Executed PLS model-input spectral display space",
    )
    fact(
        "spectra.model_input_available",
        isinstance(transformed_display, dict) and isinstance(transformed_display.get("rows"), dict),
        "Linked model-input curves are retained",
    )
    if isinstance(source_display, dict) and source_display.get("display_count") != source_display.get("variable_count"):
        result["limitations"].append(
            "Source curves are display-sampled; fitting uses the executed complete feature matrix."
        )
    if isinstance(transformed_display, dict) and transformed_display.get("downsampled"):
        result["limitations"].append("Model-input curves are display-sampled; narrow features may be hidden.")
    if any(step.get("operation") in {"preprocess.scale", "preprocess.shared_reference_scale"} for step in executed):
        result["limitations"].append("Fitted scaling uses only the retained calibration observations.")
        if receipt.get("heldout_ids"):
            result["limitations"].append("The original held-out cohort uses that saved fitted scaling state.")
    result["limitations"].append(
        "Changes in source versus model-input curves identify transformations, not chemical causes."
    )


def _append_reference_value_summary(receipt: dict, fact: Any, result: dict, *, kind: str) -> None:
    """Add declared laboratory Y context without deriving precision from fit error."""
    if kind != "pls":
        return
    reference = receipt.get("reference_value_evidence")
    if not isinstance(reference, dict) or reference.get("schema_version") != "spectrasherpa.reference-value-evidence/1":
        result["limitations"].append(
            "No bound laboratory reference declaration is retained for this model; reference precision is unknown."
        )
        return
    method = reference.get("method")
    method = method if isinstance(method, dict) else None
    fact("reference.method_recorded", method is not None, "Laboratory response method recorded")
    fact(
        "reference.method_id",
        _text(method.get("method_id"), 80) if method else None,
        "Declared laboratory response method",
    )
    fact(
        "reference.method_version",
        _text(method.get("version"), 100) if method else None,
        "Declared laboratory response method version",
    )
    for field, meaning in (
        ("source_file_id", "Bound source file ID"),
        ("sample_table_file_id", "Bound sample-table file ID"),
    ):
        fact(f"reference.{field}", _number(reference.get(field)), meaning)
    table_sha = reference.get("sample_table_sha256")
    fact(
        "reference.sample_table_sha256",
        (
            table_sha
            if isinstance(table_sha, str) and len(table_sha) == 64 and all(c in "0123456789abcdef" for c in table_sha)
            else None
        ),
        "Bound sample-table SHA-256",
    )
    fact(
        "reference.value_basis",
        method.get("measurement_basis") if method else None,
        "Declared basis of each reference value",
    )
    fact(
        "reference.measurements_per_label",
        _number(method.get("measurements_per_label")) if method else None,
        "Declared measurements combined per response label",
    )
    fact(
        "reference.source_included_count",
        _number(reference.get("source_included_count")),
        "Included source rows before calibration/test split",
        "source",
    )
    fact(
        "reference.calibration_count",
        _number(receipt.get("n_calibration")),
        "Rows fitted after the executed calibration split and exclusions",
        "calibration",
    )
    fact(
        "reference.missing_excluded_count",
        _number(reference.get("missing_excluded_count")),
        "Excluded source rows with a missing selected reference value",
        "source",
    )
    fact(
        "reference.precision_recorded",
        isinstance(method.get("precision"), dict) if method else False,
        "Laboratory precision reported separately; not estimated from model residuals",
    )
    fact(
        "reference.precision_provenance_recorded",
        bool(reference.get("precision_study_provenance")),
        "Separate precision-study note recorded; free-form note withheld from Advisor",
    )
    precision = method.get("precision") if method else None
    precision_digest = precision.get("evidence_digest") if isinstance(precision, dict) else None
    fact(
        "reference.precision_evidence_digest",
        (
            precision_digest
            if isinstance(precision_digest, str)
            and len(precision_digest) == 64
            and all(c in "0123456789abcdef" for c in precision_digest)
            else None
        ),
        "User-supplied precision-study digest; source measurements unverified",
    )
    fact(
        "reference.method_note_status",
        "withheld from Advisor" if reference.get("provenance") else "not recorded",
        "Free-form laboratory method note disclosure status",
    )
    gaps = reference.get("qualification_gaps")
    if isinstance(gaps, list):
        for gap in gaps[:8]:
            if isinstance(gap, str) and len(gap) <= 180:
                result["limitations"].append(gap)
    result["limitations"].append(
        "Reference precision is unverified; model residuals do not establish laboratory precision "
        "or interval coverage."
    )


def build_summary(
    receipt: dict,
    *,
    selected_ids: list[str],
    response_index: int = 0,
    variable_ids: list[str] | None = None,
    state: dict | None = None,
) -> dict:
    """Project exact saved facts; refuse foreign scope instead of guessing identity.

    ``facts`` is the citation catalog. Its values are scalar, finite (or explicit
    unknown ``None``); sample detail contains only aliases and catalog handles.
    Numerical quantiles use NumPy's linear method on complete role populations.
    ``state`` is a caller-verified *current* durable review state, separate from
    the execution populations in the receipt. Free-form reasons are never copied.
    """
    rows, ids, kind, names, explanation, available, requested_variables = _validate_scope(
        receipt, selected_ids, response_index, variable_ids
    )
    provenance_basis = explanation if available else receipt.get("pls_applicability") or explanation
    selected_set = set(selected_ids)
    selected = [(i, row) for i, row in enumerate(rows) if row["id"] in selected_set]
    state = state or {}
    state_sets = {}
    for key in ("marked", "excluded", "heldout_excluded"):
        members = state.get(key, [])
        if not isinstance(members, list) or any(not isinstance(x, str) for x in members):
            raise ValueError("Verified review state must use observation identity lists.")
        if not set(members).issubset(ids):
            raise ValueError("Review state contains observations outside this receipt.")
        state_sets[key] = set(members)
    from spectra_sherpa.core.target_units import resolve_response_units

    unit_context = resolve_response_units(names, receipt.get("target_units"), response_index)
    units = unit_context.value if kind == "pls" else None
    facts: dict[str, dict[str, Any]] = {}

    def fact(key, value, meaning, population="model", units=None):
        if not (value is None or isinstance(value, (str, bool)) or _number(value) is not None):
            value = None
        facts[key] = {"value": value, "meaning": meaning}
        if units is not None:
            facts[key]["units"] = units
        if population != "model":
            facts[key]["population"] = population
        return key

    result = {
        "schema_version": SCHEMA,
        "model_kind": kind,
        "selection_count": len(selected),
        "contains_held_out": any(row["role"] == "held_out_test" for row in rows),
        "response": (
            {
                "index": response_index,
                "name": _text(_at(names, response_index)),
                "units": units,
                "unit_context": unit_context.as_dict(),
            }
            if kind == "pls"
            else None
        ),
        "facts": facts,
        "populations": {},
        "samples": [],
        "provenance": {
            key: _hash(source.get(key))
            for source, keys in (
                (receipt, ("graph_digest", "source_digest", "source_execution_digest")),
                (provenance_basis, ("model_digest", "source_contract_digest", "feature_identity", "reference_digest")),
            )
            for key in keys
        },
        "limitations": [
            "Statistical screening, scientist marks, exclusion and proven measurement defects are distinct.",
            "Exclusion after inspecting results is adaptive model development; no automatic benefit is established.",
            "No refit or execution is performed. Current review decisions do not change saved numerical results.",
            "Quartiles use linear interpolation on complete finite values within each named execution population.",
            "Details are the first selected members in retained receipt order, not a representative subsample.",
        ],
        "omissions": {"sample_details": 0, "variable_details": 0, "profile_values": 0},
    }
    _curation_facts(receipt, fact, result)
    fact("selection.count", len(selected), "Selected observations", "selected")
    fact("model.components", _number(receipt.get("n_components")), "Retained model components")
    fact(
        "model.reference_count", _number(provenance_basis.get("reference_count")), "Fitted calibration reference count"
    )
    _append_reference_value_summary(receipt, fact, result, kind=kind)
    fact(
        "model.space",
        _text(explanation.get("space"), 160) if kind == "pca" else "Exact PLS input space",
        "Space of contribution variables",
    )
    fact(
        "model.internal_scale",
        explanation.get("internal_scale") if kind == "pls" else None,
        "Internal PLS scaling already incorporated in coefficients",
    )
    preprocessing = explanation.get("preprocessing") or []
    result["preprocessing"] = [_text(item) for item in preprocessing[:12]]
    if len(preprocessing) > 12:
        result["limitations"].append("Only the first twelve saved preprocessing step types are listed.")
    _executed_pls_preprocessing_facts(receipt, kind, result, fact)
    for key in state_sets:
        fact(f"review.{key}", len(state_sets[key]), "Current review " + key + " count", "current_review")
    fact("review.post_review", bool(state.get("post_review", False)), "Test-informed review flag", "current_review")
    if kind == "pca":
        for key, meaning in (
            ("calibration_t2_limit", "T² calibration screening limit"),
            ("application_t2_limit", "T² application screening limit"),
            ("q_limit", "Q screening limit"),
            ("confidence", "Screening confidence level"),
        ):
            fact("model." + key, _number(receipt.get(key)), meaning)
        fact("model.q_limit_method", _text(receipt.get("q_limit_method")), "Saved Q limit method")
        result["limitations"].append(
            "T² measures score-space distance; Q measures unexplained fitted-space residual. Neither "
            "identifies a cause."
        )
    else:
        fact(
            "model.response_baseline",
            _number(_at(explanation.get("baseline"), response_index)),
            "Fitted calibration Y mean for selected response",
            units=units,
        )
        for key, population in (("calibration_statistics", "calibration"), ("full_test_statistics", "held_out_test")):
            target = _at((receipt.get(key) or {}).get("targets"), response_index) or {}
            for metric in ("n_samples", "rmse", "r2", "bias"):
                fact(
                    f"{population}.{metric}",
                    _number(target.get("metrics", {}).get(metric)),
                    "Saved " + population + " " + metric,
                    population,
                    units if metric in {"rmse", "bias"} else None,
                )
        from .pls_review_evidence import statistics

        subset_rows = [
            row for row in rows if row["role"] == "held_out_test" and row["id"] not in state_sets["heldout_excluded"]
        ]
        masked_statistics = statistics(subset_rows, names)
        baseline = (state.get("test_baseline") or {}).get("statistics")
        for prefix, stored in (("report_subset", masked_statistics), ("review_baseline", baseline)):
            target = _at((stored or {}).get("targets"), response_index) or {}
            for metric in ("n_samples", "rmse", "r2", "bias"):
                fact(
                    f"{prefix}.{metric}",
                    _number(target.get("metrics", {}).get(metric)),
                    "Descriptive " + prefix + " " + metric,
                    "held_out_test",
                    units if metric in {"rmse", "bias"} else None,
                )
        fact(
            "review_baseline.run_id",
            _number((state.get("test_baseline") or {}).get("run_id")),
            "Verified original test review baseline run",
            "held_out_test",
        )
        result["limitations"].append(
            "Report-subset metrics omit the current review mask and are post-review descriptive only; "
            "full-test metrics remain primary. Baseline statistics require caller-verified retained-run custody."
        )
        result["limitations"].extend(
            [
                "Canonical performance bias = mean(prediction minus reference); its sign is opposite to mean residual.",
                "Residual = reference minus prediction. Contributions explain prediction, not error or "
                "causal chemistry.",
                "Calibration RMSE is not RMSECV. Full-test metrics retain all original test "
                "observations, including report masks.",
                "Held-out inspection makes subsequent test-informed development adaptive; test "
                "performance is not uncertainty.",
                "VIP is combined across responses and is not a significance test. PLS loadings are not "
                "orthonormal PCA directions.",
            ]
        )
    _population_facts(receipt, rows, selected, kind, response_index, units, fact, result)
    if not available:
        result["limitations"].append(
            "Retained per-variable explanations are unavailable; no explanation is reconstructed."
        )
    candidates = []
    for index, row in selected[:MAX_DETAILS]:
        alias = f"S{index + 1}"
        role = row["role"]
        detail = {"alias": alias, "role": role, "facts": [], "variables": []}
        fields = ("reference", "predicted", "residual") if kind == "pls" else ("t2", "q")
        for field in fields:
            value = _at(row.get(field), response_index) if kind == "pls" else row.get(field)
            detail["facts"].append(
                fact(
                    f"{alias}.{field}",
                    _number(value),
                    field + " for selected observation",
                    role,
                    units if kind == "pls" else None,
                )
            )
        detail["facts"].append(
            fact(f"{alias}.marked", row["id"] in state_sets["marked"], "Scientist marked observation", role)
        )
        evidence = explanation.get("rows", {}).get(row["id"]) if available else None
        evidence = _at(evidence, response_index) if kind == "pls" else evidence
        if isinstance(evidence, dict):
            totals = (
                ("contribution_total", "omitted_signed", "omitted_absolute")
                if kind == "pls"
                else ("q_total", "t2_total", "omitted_q", "omitted_t2", "omitted_t2_absolute")
            )
            for key in totals:
                detail["facts"].append(
                    fact(
                        f"{alias}.{key}",
                        _number(evidence.get(key)),
                        "Saved " + key,
                        role,
                        units if kind == "pls" else None,
                    )
                )
            variables = evidence.get("variables", [])
            if requested_variables:
                retained = {v[0]: v for v in variables}
                leading = [retained.get(j, [j] + [None] * (1 if kind == "pls" else 2)) for j in requested_variables]
                omitted = len(variables) - sum(j in retained for j in requested_variables)
            elif kind == "pls":
                leading = sorted(variables, key=lambda v: (-abs(v[1]), v[0]))[:MAX_VARIABLES]
                omitted = len(variables) - len(leading)
            else:
                # Do not compare Q and T² term magnitudes: their scales differ.
                leading_indices = {v[0] for v in sorted(variables, key=lambda v: (-abs(v[1]), v[0]))[:5]}
                leading_indices.update(v[0] for v in sorted(variables, key=lambda v: (-abs(v[2]), v[0]))[:5])
                leading = [v for v in variables if v[0] in leading_indices]
                omitted = len(variables) - len(leading)
            result["omissions"]["variable_details"] += omitted
            for variable in leading:
                j = variable[0]
                group = {"index": j, "requested": bool(requested_variables), "facts": []}
                group["facts"].append(
                    fact(
                        f"{alias}.v{j}.coordinate",
                        _number(_at(explanation.get("feature_values"), j)),
                        "Fitted variable coordinate",
                        role,
                        _text(explanation.get("feature_units")),
                    )
                )
                for k, label in enumerate(
                    ("prediction_contribution",) if kind == "pls" else ("q_contribution", "t2_contribution"), 1
                ):
                    group["facts"].append(
                        fact(
                            f"{alias}.v{j}.{label}", _number(variable[k]), label, role, units if kind == "pls" else None
                        )
                    )
                detail["variables"].append(group)
        candidates.append(detail)
    # Only requested variables receive bounded fitted-profile facts, once per packet.
    if requested_variables:
        result["limitations"].append(
            "A requested variable outside retained sparse contributions has an unknown term, not zero."
        )
    result["limitations"].append(
        "Leading variables: largest absolute prediction terms for PLS; union of top five Q and top five "
        "absolute T² terms for PCA. "
        "Display omissions are additional to the saved sparse remainder."
    )
    profiles = []
    for j in requested_variables:
        profile = {"index": j, "facts": []}
        if kind == "pls":
            coefficient = _at(_at(explanation.get("coefficients"), response_index), j)
            signal_units = _text(explanation.get("signal_units"))
            coefficient_units = f"{units}/{signal_units}" if units and signal_units else None
            profile["facts"].append(
                fact(
                    f"variable.v{j}.coefficient",
                    _number(coefficient),
                    "Selected response coefficient in PLS input signal units",
                    units=coefficient_units,
                )
            )
            profile["facts"].append(
                fact(f"variable.v{j}.vip", _number(_at(explanation.get("vip"), j)), "Combined VIP across responses")
            )
        for component, loading in enumerate((explanation.get("loadings") or [])[:3]):
            profile["facts"].append(
                fact(
                    f"variable.v{j}.loading{component + 1}",
                    _number(_at(loading, j)),
                    "Fitted X loading for component " + str(component + 1),
                )
            )
        result["omissions"]["profile_values"] += max(0, len(explanation.get("loadings") or []) - 3)
        profiles.append(profile)
    result["profiles"] = profiles
    result["samples"] = candidates
    result["omissions"]["sample_details"] = len(selected) - len(candidates)

    if kind == "pls":
        _pls_applicability_facts(receipt, selected, requested_variables, fact, result)
    _bound_packet(result)
    result["evidence_digest"] = _digest(result)
    return result


def _comparison_rows(receipt):
    rows = receipt.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_SELECTED:
        raise ValueError("Comparison requires bounded verified receipt populations.")
    indexed = {}
    for row in rows:
        identity = row.get("id")
        if not isinstance(identity, str) or identity in indexed or row.get("role") not in ROLES:
            raise ValueError("Comparison observation identity is invalid.")
        indexed[identity] = row
    return indexed


def _response_contract(receipt):
    names, units = receipt.get("target_names"), receipt.get("target_units")
    if (
        not isinstance(names, list)
        or not 1 <= len(names) <= 16
        or any(not isinstance(name, str) for name in names)
        or not isinstance(units, list)
        or len(units) != len(names)
        or any(unit is not None and not isinstance(unit, str) for unit in units)
    ):
        return None
    return names, units


def _reference_signature(indexed, contract):
    if contract is None:
        return None
    references = {}
    for identity, row in indexed.items():
        if row["role"] != "held_out_test":
            continue
        values = row.get("reference")
        if not isinstance(values, list) or len(values) != len(contract[0]) or any(_number(x) is None for x in values):
            return None
        references[identity] = values
    return references or None


def compare_receipts(before: dict, current: dict) -> dict:
    """Compare two caller-authenticated retained receipts without reconstructing data.

    Comparable held-out deltas require the same source digest, model node and
    response contract, and exactly identical held-out identities *and* reference
    values. The caller separately binds the two run IDs and disclosure scopes.
    This describes changes after review; it never establishes an exclusion benefit
    or restores independence after test-informed model development.
    """
    old, new = _comparison_rows(before), _comparison_rows(current)
    old_contract, new_contract = _response_contract(before), _response_contract(current)
    old_test = {key for key, row in old.items() if row["role"] == "held_out_test"}
    new_test = {key for key, row in new.items() if row["role"] == "held_out_test"}
    old_cal = {key for key, row in old.items() if row["role"] == "calibration"}
    new_cal = {key for key, row in new.items() if row["role"] == "calibration"}
    source = _hash(before.get("source_digest"))
    node = before.get("pca_node_id")
    kind = before.get("model_kind", "pca")
    old_reference = _reference_signature(old, old_contract)
    new_reference = _reference_signature(new, new_contract)
    checks = {
        "source_matches": source is not None and source == _hash(current.get("source_digest")),
        "model_node_matches": isinstance(node, str) and bool(node) and node == current.get("pca_node_id"),
        "model_kind_matches": kind in {"pca", "pls"} and kind == current.get("model_kind", "pca"),
        "heldout_membership_matches": bool(old_test) and old_test == new_test,
        "response_matches": old_contract is not None and old_contract == new_contract,
        "heldout_references_match": old_reference is not None and old_reference == new_reference,
    }
    comparable = kind == "pls" and all(checks.values())
    facts = {}

    def add(key, value, meaning, population="comparison", units=None):
        facts[key] = {"value": value, "meaning": meaning}
        if units is not None:
            facts[key]["units"] = units
        if population != "model":
            facts[key]["population"] = population

    for label, count in (
        ("calibration_added", len(new_cal - old_cal)),
        ("calibration_removed", len(old_cal - new_cal)),
        ("calibration_before", len(old_cal)),
        ("calibration_current", len(new_cal)),
        ("heldout_before", len(old_test)),
        ("heldout_current", len(new_test)),
    ):
        add("comparison." + label, count, label.replace("_", " "))
    for label, check in checks.items():
        add("comparison." + label, check, label.replace("_", " "))
    add("comparison.components_before", _number(before.get("n_components")), "Previous retained components")
    add("comparison.components_current", _number(current.get("n_components")), "Current retained components")
    before_explanations = before.get("pls_explanations" if kind == "pls" else "explanations") or {}
    current_explanations = current.get("pls_explanations" if kind == "pls" else "explanations") or {}
    preprocessing_before = before_explanations.get("preprocessing")
    preprocessing_current = current_explanations.get("preprocessing")
    preprocessing_same = (
        preprocessing_before == preprocessing_current
        if isinstance(preprocessing_before, list) and isinstance(preprocessing_current, list)
        else None
    )
    add("comparison.preprocessing_matches", preprocessing_same, "Saved preprocessing step-type sequence matches")
    before_chain = before.get("preprocessing")
    current_chain = current.get("preprocessing")
    if isinstance(before_chain, list) and isinstance(current_chain, list):

        def signature(chain, key):
            return [(step.get("operation"), step.get(key)) for step in chain if isinstance(step, dict)]

        add(
            "comparison.preprocessing_parameters_match",
            signature(before_chain, "parameters") == signature(current_chain, "parameters"),
            "Executed transformation operations and parameters match",
        )
        add(
            "comparison.preprocessing_fitted_state_matches",
            signature(before_chain, "fitted_state_sha256") == signature(current_chain, "fitted_state_sha256")
            and signature(before_chain, "fitting_ids_sha256") == signature(current_chain, "fitting_ids_sha256"),
            "Executed fitted preprocessing state and calibration membership match",
        )
    result = {
        "schema_version": "diagnostic-review-comparison/1",
        "facts": facts,
        "comparable_heldout_metrics": comparable,
        "contains_held_out": bool(old_test or new_test),
        "limitations": [
            "Changes are descriptive, not evidence that exclusion caused improvement.",
            "Matching held-out data does not restore independence after test-informed development.",
            "Calibration populations may change; calibration performance is not independent validation.",
            "Matching preprocessing step types does not establish equal fitted parameters or model settings.",
        ],
        "omissions": {"response_metrics": 0},
    }
    if not comparable:
        result["limitations"].append(
            "Comparable held-out deltas unavailable: "
            + ", ".join(key for key, passed in checks.items() if not passed)
            + ("; PCA receipts do not retain supervised performance metrics." if kind == "pca" else ".")
        )
    for response in range(min(len(new_contract[0]) if new_contract else 0, 16)):
        response_units = _text(new_contract[1][response])
        for label, contract in (("before", old_contract), ("current", new_contract)):
            add(
                f"comparison.response{response}.name.{label}",
                _text(_at(contract[0], response)) if contract else None,
                "Response name " + label,
                "held_out_test",
            )
        for metric in ("rmse", "r2", "bias"):
            values = []
            for label, receipt, population in (("before", before, old_test), ("current", current, new_test)):
                contract = old_contract if label == "before" else new_contract
                saved_units = _text(_at(contract[1], response)) if contract else None
                target = _at((receipt.get("full_test_statistics") or {}).get("targets"), response) or {}
                saved = target.get("metrics", {})
                value = _number(saved.get(metric))
                # Retained metrics must refer to the entire exact test population.
                if _number(saved.get("n_samples")) != len(population) or not population:
                    value = None
                values.append(value)
                add(
                    f"comparison.response{response}.{metric}.{label}",
                    value,
                    "Saved full-test " + metric + " " + label,
                    "held_out_test",
                    saved_units if metric != "r2" else None,
                )
            if comparable and all(value is not None for value in values):
                delta = _number(values[1] - values[0])
                add(
                    f"comparison.response{response}.{metric}.delta",
                    delta,
                    "Current minus previous full-test " + metric + "; descriptive change",
                    "held_out_test",
                    response_units if metric != "r2" else None,
                )
    # Never send arbitrary response arrays; reduce optional metrics if sixteen
    # targets would crowd the initial packet. Cohort checks always remain.
    while len(json.dumps(result, allow_nan=False, separators=(",", ":")).encode()) + 100 > MAX_BYTES:
        metric_keys = [key for key in facts if re.match(r"comparison\.response[0-9]+\.", key)]
        if not metric_keys:
            raise ValueError("Essential diagnostic comparison exceeds the evidence budget.")
        del facts[metric_keys[-1]]
        result["omissions"]["response_metrics"] += 1
    result["evidence_digest"] = _digest(result)
    return result
