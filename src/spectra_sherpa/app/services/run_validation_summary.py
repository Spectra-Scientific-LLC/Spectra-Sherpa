"""Readable saved-run facts. Never substitute current editor state or infer scope from metric names."""

from __future__ import annotations

import hashlib
import json
import math
from functools import partial
from typing import TYPE_CHECKING, Any

from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.classification.plsda_permutation import validated_permutation_scores
from spectra_sherpa.app.services.dag.out_of_fold_evidence import validate_out_of_fold_evidence
from spectra_sherpa.app.services.run_output_retention import read_output
from spectra_sherpa.core.target_units import TargetUnits, resolve_response_units, resolve_target_units
from spectra_sherpa.sdk.validation_reporting import regression_reporting_notes

if TYPE_CHECKING:
    from spectra_sherpa.app.services.run_population_summary import RetainedDefinitionRead


class ValidationReadBudgetExceeded(ValueError):
    """Stop the read at its global cap; never continue to later records."""


class SplitPlanIntegrityError(ValueError):
    """Retained split contents do not establish their claimed identity/population."""


def _split_summaries(run: Any, definition: dict, *, on_read_error=None) -> list[dict]:
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    if evidence.qualification != "qualified":
        return []
    summaries = []
    budget = 16 * 1024 * 1024
    for node in definition.get("nodes", []):
        if node.get("node_type") != "data.train_test_split":
            continue
        identifier = node["node_id"]
        try:
            for item in evidence.outputs.get(identifier, {}).values():
                if item.state != "exact" or item.storage != "file" or not item.byte_count:
                    continue
                budget -= item.byte_count
                if budget < 0:
                    raise ValidationReadBudgetExceeded("Split summary read budget exceeded")
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
                    raise SplitPlanIntegrityError("Split plan does not match its retained identity")
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
                    raise SplitPlanIntegrityError("Split population is incomplete or overlaps")
                if not isinstance(plan.get("method"), str) or type(plan.get("random_seed")) is not int:
                    raise SplitPlanIntegrityError("Split method or seed is unavailable")
                held = plan.get("held_out_groups")
                if held is not None and (
                    not isinstance(held, list)
                    or not held
                    or type(plan.get("n_groups")) is not int
                    or plan["n_groups"] <= len(held)
                ):
                    raise SplitPlanIntegrityError("Group counts are incomplete")
                summaries.append({"node": identifier, "plan": plan})
                break
        except (ValueError, TypeError, KeyError, OSError) as exc:
            if on_read_error is None:
                raise
            on_read_error(identifier, "split_plan", exc)
            if isinstance(exc, ValidationReadBudgetExceeded):
                return summaries
    return summaries


def _preparation_only(definition: dict | None) -> bool:
    """Only suppress model-validation boilerplate for a known preparation graph."""
    nodes = (definition or {}).get("nodes", [])
    if not nodes:
        return False
    try:
        return all(
            node.get("node_type") != "data.train_test_split"
            and node_registry.get_metadata(node["node_type"]).category in {"data", "preprocessing", "output"}
            for node in nodes
        )
    except (KeyError, TypeError):
        # Unknown historical operations cannot establish that validation is irrelevant.
        return False


def validation_summary(
    run: Any,
    definition: dict | None,
    *,
    include_row_level_plots: bool = False,
    population_definition_read: RetainedDefinitionRead | None = None,
) -> dict:
    """Build an exportable summary, preserving explicit gaps in retained evidence."""
    rows: list[dict[str, Any]] = []
    figures: list[dict] = []
    regression_results: list[dict] = []
    summary_rows: list[dict[str, str]] = []
    preparation_only = _preparation_only(definition)

    def add(label: str, value: object, *, summary: bool = False, short: object = None, row_level: bool = False) -> None:
        rows.append({"label": label, "value": str(value), "row_level": row_level})
        if summary:
            summary_rows.append({"label": label, "value": str(value if short is None else short)})

    add("Saved run", run.id)
    from spectra_sherpa.app.services.run_population_summary import retained_population_summary

    for row in retained_population_summary(run, definition_read=population_definition_read)["rows"]:
        add(row["label"], row["value"], summary=True)
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
        add(f"Dataset ({node})", name, summary=True)
        add(
            f"Target ({node})",
            (
                f"{target.get('column', 'Not recorded')} ({target.get('target_type', 'Not recorded')}; "
                f"units: {target.get('units') or 'Not recorded'})"
                if isinstance(target, dict)
                else "No target recorded for this selection."
            ),
            summary=True,
        )
        add(f"Group field ({node})", selected.get("group_column") or "None recorded", summary=True)
    if not latest:
        add(
            "Dataset, target and group selection",
            "Not retained for this run; current selections were not substituted.",
            summary=True,
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
        add(
            "Partition details",
            "Retained split evidence could not be verified; no partition claim is made.",
            summary=True,
        )
    for split in splits:
        node, plan = split["node"], split["plan"]
        split_node = next((item for item in definition.get("nodes", []) if item.get("node_id") == node), {})
        settings = split_node.get("parameters") if isinstance(split_node.get("parameters"), dict) else {}
        if settings.get("validation_goal") == "known_specimen_cross_block":
            add(
                f"Validation question ({node})",
                "Cross-block repeatability of known specimens; this is not performance on unseen specimens.",
                summary=True,
            )
        else:
            add(
                f"Validation question ({node})",
                "Unseen-specimen intent; confirm the bound identity and executed partition.",
                summary=True,
            )
        add(f"Split method ({node})", plan["method"], summary=True)
        add(f"Split seed ({node})", plan["random_seed"])
        for role, key in (("Development", "train_indices"), ("Test", "test_indices")):
            indices = plan[key]
            preview = ", ".join(str(index + 1) for index in indices[:20])
            add(
                f"{role} population ({node})",
                f"{len(indices)} rows; active split-population positions (1-based): {preview}"
                + (
                    f"; showing first 20 of {len(indices)}. Original input indices remain in the retained split output."
                    if len(indices) > 20
                    else ""
                ),
                summary=True,
                short=f"{len(indices)} rows",
            )
        held = plan.get("held_out_groups")
        if isinstance(held, list) and held and type(plan.get("n_groups")) is int:
            add(
                f"Groups ({node})",
                f"Recorded whole-group split: {plan['n_groups'] - len(held)} development groups; "
                f"{len(held)} test groups. Test groups: " + ", ".join(map(str, held)),
                summary=True,
            )
        else:
            add(
                f"Groups ({node})",
                "No whole-group holdout recorded.",
                summary=True,
            )

    add(
        "Evaluation population",
        "Per retained output; cross-validation is not external validation.",
        summary=not preparation_only,
    )
    if not splits:
        add(
            "Groups across partitions",
            "A group field alone does not prove separation. "
            "Inspect the executed split record for group membership and counts.",
        )
    add(
        "Preprocessing within folds",
        "Not established by this summary; inspect retained fold execution.",
        summary=not preparation_only,
    )
    add(
        "Missing and excluded observations",
        "See retained sample selections and validation rows. Missing evidence is not a count of zero.",
    )
    if not include_row_level_plots:
        add("Row-level figures", "Excluded by default; opt in to include reference, prediction and residual values.")
    try:
        details, figures, regression_results = _retained_validation_details(
            run, definition, include_row_level_plots=include_row_level_plots, summary_rows=summary_rows
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
                    row_level=True,
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
            summary=True,
        )
    return {
        "schema_version": "spectrasherpa-readable-validation/1",
        "run_id": run.id,
        "rows": rows,
        "summary_rows": summary_rows,
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
    results = []
    for record in statistics["targets"]:
        context = units(record["target"])
        results.append(
            {
                **record,
                "node_id": node_id,
                "source_port": source_port,
                "role": role,
                "units": context.value if context.state == "recorded" else "Target units unavailable or ambiguous",
                "unit_context": context.as_dict(),
            }
        )
    return results


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


def _validation_output_values(run, evidence, *, on_read_error=None):
    """Skip unrelated large artifacts while bounding reads of validation evidence."""
    budget = 16 * 1024 * 1024
    for node, ports in evidence.outputs.items():
        for port, item in ports.items():
            # Only these ports can contain a validation record or source-unit
            # signature handled below. Train/test matrices can each be many MB;
            # charging them to the report budget hides small exact CV records.
            if port not in {
                "default",
                "component_curve",
                "calibration_comparison",
                "comparison",
                "cv_metrics",
                "oof_evidence",
                "repeated_evidence",
            }:
                continue
            if item.state != "exact" or item.storage != "file" or not item.byte_count:
                continue
            budget -= item.byte_count
            if budget < 0:
                exc = ValidationReadBudgetExceeded("Validation report read budget exceeded")
                if on_read_error is None:
                    raise exc
                on_read_error(node, port, exc)
                return
            try:
                value = read_output(run.user_id, item)
            except (ValueError, TypeError, KeyError, OSError) as exc:
                if on_read_error is None:
                    raise
                on_read_error(node, port, exc)
                continue
            if not isinstance(value, dict):
                continue
            yield node, port, value


def _component_curve_report_rows(node, value, context=lambda label, value, **kwargs: (label, value)):
    rows = [
        (f"Selected components ({node})", value.get("selected_components", "Not recorded")),
        (f"Requested components ({node})", value.get("requested_components", "Not recorded")),
        (f"Component calibration population ({node})", value.get("n_calibration", "Not recorded")),
    ]
    cv = value.get("cross_validation")
    if not isinstance(cv, dict) or cv.get("status") != "available":
        reason = cv.get("reason", "Not recorded") if isinstance(cv, dict) else "Not recorded"
        rows.append(context(f"Component CV unavailable ({node})", reason))
        return rows
    rows.append(
        context(
            f"Component CV design ({node})",
            json.dumps(
                {
                    "role": "development_tuning",
                    "method": cv.get("method"),
                    "folds": cv.get("n_folds"),
                    "groups": cv.get("n_groups"),
                    "split_digest": cv.get("split_digest"),
                    "notice": "Component selection CV is not an independent test.",
                },
                sort_keys=True,
            ),
            short=(
                f"{cv.get('n_folds')} folds; {cv.get('method')}; "
                + (f"{cv.get('n_groups')} groups; " if cv.get("n_groups") is not None else "row folds; ")
                + "development tuning, not an independent test."
            ),
        )
    )
    suggestions = cv.get("suggestions") or []
    for index, name in enumerate((value.get("response_names") or [])[:5]):
        if index < len(suggestions):
            rows.append(
                (
                    f"Component selection suggestion ({node}; {name})",
                    json.dumps(
                        suggestions[index],
                        sort_keys=True,
                    ),
                )
            )
    if isinstance(cv.get("suggestion"), dict):
        rows.append((f"Component selection suggestion ({node})", json.dumps(cv["suggestion"], sort_keys=True)))
    return rows


def _permutation_report_rows(node, value):
    try:
        validated_permutation_scores(value)
    except ValueError:
        return [(f"PLS-DA response permutation ({node})", "Incomplete or inconsistent retained evidence")]
    design_keys = (
        "seed",
        "folds",
        "n_calibration",
        "n_units",
        "n_blocks",
        "exchangeability_block_column",
        "grouping_sha256",
        "blocks_sha256",
        "permutations_successful",
        "exceedances",
        "model_state_sha256",
        "saved_model_components",
        "observed_reselected_components",
        "component_search_maximum",
        "selection_rule",
        "upstream_preprocessing",
    )
    return [
        (f"PLS-DA permutation observed balanced accuracy ({node})", value.get("observed")),
        (f"PLS-DA permutation p-value ({node})", value["p_value"]),
        (
            f"PLS-DA permutation design ({node})",
            json.dumps({key: value.get(key) for key in design_keys}, sort_keys=True),
        ),
        (
            f"PLS-DA permutation scope ({node})",
            "Calibration random-label evidence; independent test validity is not established. "
            "CV-ANOVA is unavailable for this PLS-DA statistic.",
        ),
    ]


def _summary_context(summary_rows, label, value, *, short=None):
    if summary_rows is not None:
        summary_rows.append({"label": label, "value": str(value if short is None else short)})
    return label, value


def _retained_validation_details(run, definition, *, include_row_level_plots=False, summary_rows=None):
    """Read exact retained outputs under one bounded budget; never current UI state."""
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    if evidence.qualification != "qualified":
        raise ValueError("retained evidence is incomplete")
    rows, figures, regression_results = [], [], []

    context = partial(_summary_context, summary_rows)

    cv_populations = []
    source_types = {"data.file_load", "data.collection_load", "data.load_group", "data.synthetic_curve"}
    source_nodes = {
        item["node_id"] for item in (definition or {}).get("nodes", []) if item.get("node_type") in source_types
    }
    spectral_units = {}
    source_spectral_flags = []
    for node, port, value in _validation_output_values(run, evidence):
        if node in source_nodes and port == "default":
            source_spectral_flags.append((value.get("metadata") or {}).get("is_spectra"))
        signature = _source_unit_signature(value) if node in source_nodes and port == "default" else None
        if signature:
            spectral_units.setdefault(signature, []).append(node)
        if port == "component_curve" and value.get("schema_version") in {
            "spectrasherpa-pls-component-curve/1",
            "spectrasherpa-pca-component-curve/1",
            "spectrasherpa-plsda-component-curve/1",
        }:
            rows.extend(_component_curve_report_rows(node, value, context))
            continue
        if port == "default" and value.get("schema_version") == "spectrasherpa-plsda-response-permutation/1":
            rows.extend(_permutation_report_rows(node, value))
            continue
        if value.get("schema_version") == "spectrasherpa-regression-comparison/1":
            if not value.get("statistics"):
                rows.append(
                    context(
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
                    units=lambda response: _retained_target_unit_context(run, definition, node, response),
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
                                {key: row[key] for key in ("sample", "reference", "predicted")} for row in observations
                            ]
                        elif include_row_level_plots:
                            rows.append(
                                context(
                                    f"Target list ({node}; {record['target']})",
                                    "Exceeds 5000-row report limit; no partial list is presented.",
                                )
                            )
                regression_results.extend(records)
            except (ValueError, TypeError, KeyError):
                rows.append(
                    context(
                        f"Regression statistics ({node}; {port})",
                        "Canonical statistics not retained. Rerun the workflow; "
                        "the report does not recompute metrics.",
                    )
                )
            continue
        if value.get("schema_version") == "spectrasherpa.repeated-nested-validation/1" and "repeats" in value:
            rows.append(context(f"Repeated validation ({node})", value["interpretation"]))
            rows.append(
                context(
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
                        context(
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
                        units=lambda response: _retained_target_unit_context(run, definition, node, response),
                    )
                )
                rows.append(
                    (
                        f"Repeat {repeat['repeat_id']} ({node})",
                        f"seed {repeat['seed']}; split {bound['split_plan_digest']}; " f"{len(observed)} observations",
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
                    context(
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
                    units=lambda response: _retained_target_unit_context(run, definition, node, response),
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
                context(
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
            rows.append(context(f"Verified metric denominator ({node})", len(observed)))
            plan = bound["split_plan"]
            rows.append((f"Evaluation scope ({node})", "Cross-validation; not an external held-out test"))
            rows.append(
                context(
                    f"Cross-validation design ({node})",
                    f"{len(plan['folds'])} executed folds; "
                    + ("grouped validation" if plan.get("grouped") else "row-wise validation"),
                )
            )
            rows.extend(_fold_count_rows(node, plan))
            rows.append(
                context(
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
    if not source_spectral_flags or not all(flag is False for flag in source_spectral_flags):
        rows.extend(context(label, value) for label, value in _source_unit_rows(spectral_units))
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
                    context(
                        f"Target list ({node}; {port})", "Exceeds 5000-row report limit; no partial list is presented."
                    )
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


def _retained_target_units(run, definition, node, response=None):
    """Compatibility display string, derived from the typed unit resolution."""
    context = _retained_target_unit_context(run, definition, node, response)
    return (
        context.value
        if context.state == "recorded"
        else "Target units unavailable or ambiguous in retained upstream selections"
    )


def _retained_target_unit_context(run, definition, node, response=None):
    """Resolve only retained ancestors and the exact requested response."""
    if not isinstance(definition, dict):
        return TargetUnits("missing")
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
        if isinstance(authority, dict) and (response is None or authority.get("column") == response):
            units.append(authority.get("units"))
    if units:
        # A missing/conflicting selected authority must not be overwritten.
        return resolve_target_units(units)
    try:
        evidence = RunEvidence.model_validate(run.evidence_completeness)
        curve_units = []
        for source_node in definition.get("nodes", []):
            source_id = source_node.get("node_id")
            if source_id not in ancestors:
                continue
            item = evidence.outputs.get(source_id, {}).get("component_curve")
            if item is None or item.state != "exact" or item.storage != "file" or not item.byte_count:
                continue
            if item.byte_count > 1024 * 1024:
                continue
            curve = read_output(run.user_id, item)
            if curve.get("schema_version") != "spectrasherpa-pls-component-curve/1":
                continue
            names = curve.get("response_names")
            if response is not None and (not isinstance(names, list) or response not in names):
                continue
            resolved = resolve_response_units(names, curve.get("response_units"), response)
            if resolved.state == "ambiguous":
                return resolved
            curve_units.append(resolved.value)
        return resolve_target_units(curve_units)
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        return TargetUnits("missing")
