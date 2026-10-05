"""Readable saved-run facts. Never substitute current editor state or infer scope from metric names."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.dag.out_of_fold_evidence import validate_out_of_fold_evidence
from spectra_sherpa.app.services.run_output_retention import read_output
from spectra_sherpa.sdk.validation_reporting import regression_reporting_notes


def _split_summaries(run: Any, definition: dict) -> list[dict]:
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    if evidence.qualification != "qualified":
        return []
    summaries = []
    budget = 16 * 1024 * 1024
    for node in definition.get("nodes", []):
        if node.get("node_type") != "data.train_test_split":
            continue
        identifier = node["node_id"]
        for item in evidence.outputs.get(identifier, {}).values():
            if item.state != "exact" or item.storage != "file" or not item.byte_count:
                continue
            budget -= item.byte_count
            if budget < 0:
                raise ValueError("Split summary read budget exceeded")
            value = read_output(run.user_id, item)
            if not isinstance(value, dict) or value.get("type") != "SherpaDataset":
                continue
            entries = [
                entry
                for entry in value.get("provenance", [])
                if entry.get("op_id") == "data.train_test_split" and entry.get("node_id") == identifier
            ]
            if not entries:
                continue
            plan = entries[-1].get("parameters", {})
            if plan.get("schema") != "spectrasherpa-split-plan/2":
                continue
            unsigned = {key: value for key, value in plan.items() if key not in {"split", "digest"}}
            digest = hashlib.sha256(
                json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
            ).hexdigest()
            if digest != plan.get("digest"):
                raise ValueError("Split plan does not match its retained identity")
            train, test = plan.get("train_indices"), plan.get("test_indices")
            count = plan.get("n_samples")
            if (
                not isinstance(train, list)
                or not isinstance(test, list)
                or type(count) is not int
                or not train
                or not test
                or any(type(i) is not int for i in train + test)
                or len(set(train + test)) != len(train + test)
                or len(train + test) != count
                or any(i < 0 or i >= count for i in train + test)
            ):
                raise ValueError("Split population is incomplete or overlaps")
            if not isinstance(plan.get("method"), str) or type(plan.get("random_seed")) is not int:
                raise ValueError("Split method or seed is unavailable")
            held = plan.get("held_out_groups")
            if held is not None and (
                not isinstance(held, list)
                or not held
                or type(plan.get("n_groups")) is not int
                or plan["n_groups"] <= len(held)
            ):
                raise ValueError("Group counts are incomplete")
            summaries.append({"node": identifier, "plan": plan})
            break
    return summaries


def validation_summary(run: Any, definition: dict | None, *, include_row_level_plots: bool = False) -> dict:
    """Build an exportable summary, preserving explicit gaps in retained evidence."""
    rows: list[dict[str, str]] = []
    figures: list[dict] = []
    regression_results: list[dict] = []

    def add(label: str, value: object) -> None:
        rows.append({"label": label, "value": str(value)})

    add("Saved run", run.id)
    for label, detail in regression_reporting_notes().items():
        add(f"Metric interpretation: {label}", detail)
    add("Run outcome", getattr(run, "status", "Not recorded"))
    add("Interpretation", "Saved execution evidence; not a certification of suitability for your intended use.")
    source = getattr(run, "source_metadata", None)
    source = source if isinstance(source, dict) else {}
    revisions = source.get("data_selection_revisions", [])
    revisions = revisions if isinstance(revisions, list) else []
    latest: dict[str, dict] = {}
    for revision in revisions:
        if (
            not isinstance(revision, dict)
            or not isinstance(revision.get("selection"), dict)
            or type(revision.get("revision_number")) is not int
        ):
            continue
        node = str(revision.get("source_node_id", "Unknown source"))
        if revision.get("revision_number", 0) >= latest.get(node, {}).get("revision_number", -1):
            latest[node] = revision
    for node, revision in latest.items():
        selected = revision["selection"]
        target = selected.get("target_authority")
        name = selected.get("dataset_name", node)
        add(f"Dataset ({node})", name)
        add(
            f"Target ({node})",
            (
                f"{target.get('column', 'Not recorded')} ({target.get('target_type', 'Not recorded')}; "
                f"units: {target.get('units') or 'Not recorded'})"
                if isinstance(target, dict)
                else "No target recorded for this selection."
            ),
        )
        add(f"Group field ({node})", selected.get("group_column") or "None recorded")
    if not latest:
        add(
            "Dataset, target and group selection", "Not retained for this run; current selections were not substituted."
        )

    if definition is None:
        add(
            "Execution settings", "Saved workflow definition unavailable; current editor settings were not substituted."
        )
    else:
        snapshots = getattr(run, "params_snapshot", None)
        snapshots = snapshots if isinstance(snapshots, dict) else {}
        statuses = getattr(run, "node_statuses", None)
        statuses = statuses if isinstance(statuses, dict) else {}
        for node in definition.get("nodes", []):
            identifier = node["node_id"]
            add(f"Operation ({identifier})", node["node_type"])
            add(f"Operation outcome ({identifier})", statuses.get(identifier, "Not recorded"))
            parameters = snapshots.get(identifier)
            if not isinstance(parameters, dict):
                add(f"Saved settings ({identifier})", "Not retained; defaults were not reconstructed.")
                continue
            add(f"Saved settings ({identifier})", json.dumps(parameters, sort_keys=True, ensure_ascii=False))
            for key in ("random_seed", "random_state", "seed"):
                if key in parameters:
                    add(f"Seed ({identifier}; {key})", parameters[key])

    try:
        splits = _split_summaries(run, definition) if definition else []
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        splits = []
        add("Partition details", "Retained split evidence could not be verified; no partition claim is made.")
    for split in splits:
        node, plan = split["node"], split["plan"]
        add(f"Split method ({node})", plan["method"])
        add(f"Split seed ({node})", plan["random_seed"])
        for role, key in (("Development", "train_indices"), ("Test", "test_indices")):
            indices = plan[key]
            preview = ", ".join(str(index + 1) for index in indices[:20])
            add(
                f"{role} population ({node})",
                f"{len(indices)} rows; split-input row positions (1-based): {preview}"
                + (
                    f"; showing first 20 of {len(indices)}. Complete indices remain in the retained split output."
                    if len(indices) > 20
                    else ""
                ),
            )
        held = plan.get("held_out_groups")
        if isinstance(held, list) and held and type(plan.get("n_groups")) is int:
            add(
                f"Groups ({node})",
                f"Recorded whole-group split: {plan['n_groups'] - len(held)} development groups; "
                f"{len(held)} test groups. Test groups: " + ", ".join(map(str, held)),
            )
        else:
            add(
                f"Groups ({node})",
                "No whole-group holdout recorded; row separation alone does not establish group separation.",
            )

    add(
        "Evaluation population",
        "Reported per retained workflow output below. Cross-validation is not external validation.",
    )
    if not splits:
        add(
            "Groups across partitions",
            "A group field alone does not prove separation. "
            "Inspect the executed split record for group membership and counts.",
        )
    add(
        "Preprocessing within folds",
        "Not established by this summary. "
        "Inspect the producer's retained fold execution before claiming fold-local fitting.",
    )
    add(
        "Missing and excluded observations",
        "See retained sample selections and validation rows. Missing evidence is not a count of zero.",
    )
    if not include_row_level_plots:
        add("Row-level figures", "Excluded by default; opt in to include reference, prediction and residual values.")
    try:
        details, figures, regression_results = _retained_validation_details(
            run, definition, include_row_level_plots=include_row_level_plots
        )
        for label, detail in details:
            add(label, detail)
        for result in regression_results:
            label = f"{result['role']} ({result['node_id']}/{result['source_port']}; {result['target']})"
            add(f"Regression population {label}", f"{result['metrics']['n_samples']} samples; units: {result['units']}")
            add(f"Reference range {label}", f"{result['reference_min']} to {result['reference_max']}")
            if result.get("reference_mean") is not None:
                add(f"Reference mean {label}", result["reference_mean"])
            add(f"Reference SD {label}", result["reference_sd"])
            for observation in result.get("observations", []):
                add(
                    f"Observation {observation['sample']} — {label}",
                    f"Reference: {observation['reference']}; predicted: {observation['predicted']}",
                )
            for key, value in result["metrics"].items():
                if key != "registry_version" and value is not None:
                    add(f"{key} {label}", value)
        if regression_results:
            add(
                "Regression definitions",
                "RMSE uses n; it is not SEC adjusted for model degrees of freedom. "
                "Bias is predicted minus reference; SEP is bias-corrected residual SD with n-1 denominator. "
                "Reference replicate weighting, bias significance and ASTM compliance are not established.",
            )
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        add(
            "Detailed validation evidence",
            "Unavailable or unverified; no missing count, plot or independence claim is inferred.",
        )
    return {
        "schema_version": "spectrasherpa-readable-validation/1",
        "run_id": run.id,
        "rows": rows,
        "figures": figures,
        "regression_results": regression_results,
    }


def _stored_statistics(statistics, *, role, node_id, source_port, units):
    """Pure projection of canonical node output. No metric calculation or fallback."""
    if not statistics:
        return []
    if statistics.get("schema_version") != "spectrasherpa-regression-statistics/1":
        raise ValueError("Unsupported retained regression statistics")
    if role not in {"calibration", "cross_validation", "held_out_test", "unqualified_evaluation"}:
        raise ValueError("Retained regression statistics lack population scope")
    for record in statistics["targets"]:
        if not isinstance(record.get("target"), str) or not record["target"]:
            raise ValueError("Retained regression statistics lack target identity")
        if record.get("bias_definition") != "predicted_minus_reference":
            raise ValueError("Unknown retained bias definition")
        metrics = record["metrics"]
        if type(metrics.get("n_samples")) is not int or metrics["n_samples"] < 1:
            raise ValueError("Invalid retained regression population")
        for value in [record["reference_min"], record["reference_max"], record["reference_sd"], *metrics.values()]:
            if isinstance(value, (int, float)) and not math.isfinite(value):
                raise ValueError("Nonfinite retained regression statistics")
    return [
        {**record, "node_id": node_id, "source_port": source_port, "role": role, "units": units}
        for record in statistics["targets"]
    ]


def _source_unit_signature(value):
    metadata = value.get("metadata") or {}
    if value.get("type") != "SherpaDataset" or metadata.get("is_spectra") is not True:
        return None
    axis = value.get("x_axis") or {}
    return (
        axis.get("title") or "Axis type not recorded",
        axis.get("units") or "Not recorded",
        metadata.get("value_units_label") or metadata.get("value_units") or value.get("units") or "Not recorded",
    )


def _source_unit_rows(spectral_units):
    if not spectral_units:
        return [
            ("Spectral axis (X)", "Not recorded in retained source outputs"),
            ("Spectral intensity", "Not recorded in retained source outputs"),
        ]
    rows = []
    for (title, axis_units, intensity_units), sources in spectral_units.items():
        scope = ", ".join(sources)
        rows.append((f"Spectral axis (X; {scope})", f"{title}; units: {axis_units}"))
        rows.append((f"Spectral intensity ({scope})", str(intensity_units)))
    return rows


def _fold_count_rows(node, plan):
    return [
        (f"Fold {index} ({node})", f"{len(fold['train'])} training rows; {len(fold['test'])} validation rows")
        for index, fold in enumerate(plan["folds"], 1)
    ]


def _retained_validation_details(run, definition, *, include_row_level_plots=False):
    """Read exact retained outputs under one bounded budget; never current UI state."""
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    if evidence.qualification != "qualified":
        raise ValueError("retained evidence is incomplete")
    rows, figures, regression_results = [], [], []
    cv_populations = []
    source_types = {"data.file_load", "data.collection_load", "data.load_group", "data.synthetic_curve"}
    source_nodes = {
        item["node_id"] for item in (definition or {}).get("nodes", []) if item.get("node_type") in source_types
    }
    spectral_units = {}
    budget = 16 * 1024 * 1024
    for node, ports in evidence.outputs.items():
        for port, item in ports.items():
            if item.state != "exact" or item.storage != "file" or not item.byte_count:
                continue
            budget -= item.byte_count
            if budget < 0:
                raise ValueError("validation report read budget exceeded")
            value = read_output(run.user_id, item)
            if not isinstance(value, dict):
                continue
            signature = _source_unit_signature(value) if node in source_nodes and port == "default" else None
            if signature:
                spectral_units.setdefault(signature, []).append(node)
            if value.get("schema_version") == "spectrasherpa-regression-comparison/1":
                if not value.get("statistics"):
                    rows.append(
                        (
                            f"Regression statistics ({node}; {port})",
                            "Canonical statistics not retained. Rerun the workflow; "
                            "the report does not recompute metrics.",
                        )
                    )
                try:
                    records = _stored_statistics(
                        value.get("statistics"),
                        role=value.get("metadata", {}).get("role"),
                        node_id=node,
                        source_port=port,
                        units=_retained_target_units(run, definition, node),
                    )
                    for record in records:
                        observations = [row for row in value.get("data", []) if row.get("target") == record["target"]]
                        # Descriptive arithmetic on complete retained values is allowed;
                        # fitting and validation metrics remain workflow-owned.
                        if len(observations) == record["metrics"]["n_samples"] and all(
                            isinstance(row.get("reference"), (int, float)) and math.isfinite(row["reference"])
                            for row in observations
                        ):
                            record["reference_mean"] = math.fsum(
                                row["reference"] / len(observations) for row in observations
                            )
                            if include_row_level_plots and len(observations) <= 5000:
                                record["observations"] = [
                                    {key: row[key] for key in ("sample", "reference", "predicted")}
                                    for row in observations
                                ]
                            elif include_row_level_plots:
                                rows.append(
                                    (
                                        f"Target list ({node}; {record['target']})",
                                        "Exceeds 5000-row report limit; no partial list is presented.",
                                    )
                                )
                    regression_results.extend(records)
                except (ValueError, TypeError, KeyError):
                    rows.append(
                        (
                            f"Regression statistics ({node}; {port})",
                            "Canonical statistics not retained. Rerun the workflow; "
                            "the report does not recompute metrics.",
                        )
                    )
                continue
            if value.get("schema_version") == "spectrasherpa.repeated-nested-validation/1" and "repeats" in value:
                rows.append((f"Repeated validation ({node})", value["interpretation"]))
                rows.append(
                    (
                        f"Repeated population ({node})",
                        f"{value['n_rows']} original rows; "
                        f"{value['n_groups']} groups; {value['n_repeats']} repeats; not pooled",
                    )
                )
                for metric, spread in value["distributions"].items():
                    rows.append((f"Repeat distribution ({node}; {metric})", json.dumps(spread, sort_keys=True)))
                for repeat in value["repeats"]:
                    bound, observed, predicted, _ = validate_out_of_fold_evidence(repeat["outputs"]["oof_evidence"])
                    cv_populations.append((node, f"{port} / repeat {repeat['repeat_id']}", observed, predicted))
                    if not repeat["outputs"]["cv_metrics"].get("statistics"):
                        rows.append(
                            (
                                f"Regression statistics ({node}; repeat {repeat['repeat_id']})",
                                "Canonical statistics not retained; rerun workflow.",
                            )
                        )
                    regression_results.extend(
                        _stored_statistics(
                            repeat["outputs"]["cv_metrics"].get("statistics"),
                            role="cross_validation",
                            node_id=node,
                            source_port=f"{port} / repeat {repeat['repeat_id']}",
                            units=_retained_target_units(run, definition, node),
                        )
                    )
                    rows.append(
                        (
                            f"Repeat {repeat['repeat_id']} ({node})",
                            f"seed {repeat['seed']}; split {bound['split_plan_digest']}; "
                            f"{len(observed)} observations",
                        )
                    )
                    metrics = repeat["outputs"]["cv_metrics"]
                    rows.append(
                        (
                            f"Inner tuning ({node}; repeat {repeat['repeat_id']})",
                            f"{metrics.get('inner_selection_scope', 'Not recorded')}; "
                            f"components by fold {metrics['per_fold_n_components']}",
                        )
                    )
                    # Plots remain per repeat, never pooled into an inflated population.
                    if include_row_level_plots:
                        figures.extend(
                            _validation_figures(
                                observed,
                                predicted,
                                node,
                                port,
                                repeat["repeat_id"],
                                _retained_target_units(run, definition, node),
                            )
                        )
            elif value.get("metadata", {}).get("type") == "RegressionCV" and "split_plan_digest" in value:
                if not value.get("statistics"):
                    rows.append(
                        (
                            f"Regression statistics ({node}; {port})",
                            "Canonical statistics not retained; rerun workflow.",
                        )
                    )
                regression_results.extend(
                    _stored_statistics(
                        value.get("statistics"),
                        role="cross_validation",
                        node_id=node,
                        source_port=port,
                        units=_retained_target_units(run, definition, node),
                    )
                )
                for key in (
                    "selector_profile",
                    "inner_selection_scope",
                    "per_fold_n_components",
                    "per_fold_n_selected",
                    "random_seed",
                    "population_scope",
                ):
                    rows.append((f"Retained tuning ({node}; {key})", json.dumps(value.get(key, "Not recorded"))))
                plan = value.get("split_plan", {})
                rows.append(
                    (
                        f"Cross-validation method ({node})",
                        f"{value.get('n_folds', 'Not recorded')} folds; method {plan.get('method', 'Not recorded')}; "
                        f"population {value.get('population_scope', 'Not recorded')}; "
                        f"root seed {value.get('random_seed', 'Not recorded')}; "
                        f"component selection {value.get('component_selection', 'Not recorded')} "
                        f"within {value.get('inner_selection_scope', 'Not recorded')}.",
                    )
                )
            elif value.get("schema_version") == "spectrasherpa-out-of-fold-evidence/1":
                bound, observed, predicted, _ = validate_out_of_fold_evidence(value)
                cv_populations.append((node, "cv_metrics", observed, predicted))
                rows.append((f"Validation identity ({node})", bound["evidence_sha256"]))
                rows.append((f"Verified metric denominator ({node})", len(observed)))
                plan = bound["split_plan"]
                rows.append((f"Evaluation scope ({node})", "Cross-validation; not an external held-out test"))
                rows.extend(_fold_count_rows(node, plan))
                rows.append(
                    (
                        f"Validation groups ({node})",
                        len(set(plan["groups"])) if plan.get("grouped") else "No groups recorded; row-wise evaluation",
                    )
                )
                if include_row_level_plots:
                    figures.extend(
                        _validation_figures(
                            observed, predicted, node, port, None, _retained_target_units(run, definition, node)
                        )
                    )
    rows.extend(_source_unit_rows(spectral_units))
    for node, port, observed, predicted in cv_populations:
        for record in regression_results:
            if record["node_id"] != node or record["source_port"] != port or record["role"] != "cross_validation":
                continue
            record["reference_mean"] = math.fsum(float(value) / len(observed) for value in observed)
            if include_row_level_plots and len(observed) <= 5000:
                record["observations"] = [
                    {"sample": str(index + 1), "reference": float(reference), "predicted": float(prediction)}
                    for index, (reference, prediction) in enumerate(zip(observed, predicted, strict=True))
                ]
            elif include_row_level_plots:
                rows.append(
                    (f"Target list ({node}; {port})", "Exceeds 5000-row report limit; no partial list is presented.")
                )
    return rows, figures, regression_results


def _validation_figures(observed, predicted, node, port, repeat, units="Target units not recorded"):
    # No subsampling: refuse an oversized chart while retaining numeric evidence.
    if len(observed) > 5000:
        return [
            {
                "state": "unavailable",
                "reason": "Plot exceeds 5000-row display limit; no subsampling applied",
                "node_id": node,
                "source_port": port,
                "repeat_id": repeat,
                "total_rows": len(observed),
            }
        ]
    return [
        {
            "state": "available",
            "kind": "prediction_and_residual",
            "node_id": node,
            "source_port": port,
            "repeat_id": repeat,
            "total_rows": len(observed),
            "visible_rows": len(observed),
            "units": units,
            "observed": observed.tolist(),
            "predicted": predicted.tolist(),
            "residual": (predicted - observed).tolist(),
            "scope": "cross_validation; each repeat shown separately",
        }
    ]


def _retained_target_units(run, definition, node):
    """Use only saved upstream target authority; ambiguous/missing units remain explicit."""
    return _retained_target_value(run, definition, node, "units")


def _retained_target_value(run, definition, node, field):
    if not isinstance(definition, dict):
        return f"Target {field} not recorded"
    ancestors, pending = set(), [node]
    edges = definition.get("edges", [])
    while pending:
        current = pending.pop()
        if current in ancestors:
            continue
        ancestors.add(current)
        pending.extend(
            edge.get("from_node_id", edge.get("from_node"))
            for edge in edges
            if edge.get("to_node_id", edge.get("to_node")) == current
        )
    latest = {}
    source = getattr(run, "source_metadata", None) or {}
    for revision in source.get("data_selection_revisions", []):
        identity = revision.get("source_node_id")
        if identity in ancestors and revision.get("revision_number", -1) >= latest.get(identity, {}).get(
            "revision_number", -1
        ):
            latest[identity] = revision
    units = []
    for revision in latest.values():
        authority = revision.get("selection", {}).get("target_authority")
        if isinstance(authority, dict):
            units.append(authority.get(field))
    if units and all(isinstance(unit, str) and unit.strip() for unit in units) and len(set(units)) == 1:
        return units[0]
    return f"Target {field} unavailable or ambiguous in retained upstream selections"
