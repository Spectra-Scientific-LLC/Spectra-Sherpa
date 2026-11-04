"""Adapt executor-owned regression/split receipts to neutral evidence.

Display labels and equal row counts never establish population identity. The
split-plan authority and retained feature/response payloads establish it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from types import SimpleNamespace
from typing import Any

import numpy as np

from spectra_sherpa.app.contracts.comparison_evidence import EvaluationEvidence
from spectra_sherpa.app.lib.array_identity import array_content_digest
from spectra_sherpa.app.lib.comparison_identity import (
    INVALID_IDENTITY_REASON,
    LEGACY_IDENTITY_REASON,
    comparison_sample_ids,
)
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.schemas.scientific_comparison import PopulationSummary
from spectra_sherpa.app.services.retained_registered_identity import (
    RegisteredIdentityUnavailable,
    RetainedRegisteredIdentity,
)
from spectra_sherpa.app.services.run_output_retention import read_output
from spectra_sherpa.app.services.run_validation_summary import (
    ValidationReadBudgetExceeded,
    _split_summaries,
    _validation_output_values,
)

logger = logging.getLogger(__name__)


class RetainedComparisonUnavailable(ValueError):
    """Closed, public-safe reasons for unavailable retained comparison evidence."""


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _retained_sample_identity(dataset, count):
    """Adapt retained wire axes to the canonical typed identity reader."""
    if not isinstance(dataset, dict):
        return None, None
    axis = dataset.get("y_axis") or {}
    return comparison_sample_ids(
        SimpleNamespace(
            sample_axis=SimpleNamespace(sample_table=axis.get("sample_table")),
            n_samples=count,
            source_identity=dataset.get("source_identity"),
            provenance=dataset.get("provenance"),
            meta=dataset.get("extra") or {},
        )
    )


def _response_edge(definition, node):
    targets = [
        edge for edge in definition.get("edges", []) if edge.get("to_node_id") == node and edge.get("to_input") == "y"
    ]
    if len(targets) > 1:
        raise RetainedComparisonUnavailable("Retained response binding is ambiguous.")
    return targets[0] if targets else None


def _target(dataset, target_edge, standalone_plan, split, branch, exact):
    if target_edge is not None:
        value = exact(target_edge["from_node_id"], target_edge.get("from_output") or "default")
    elif dataset.get("target") is None and standalone_plan is None:
        value = exact(split, "y_" + branch)
    else:
        value = dataset.get("target")
    external = target_edge is not None or (dataset.get("target") is None and standalone_plan is None)
    return (value.get("data"), value, external) if isinstance(value, dict) else (value, None, external)


def _response_units(dataset, response_source, target_names, *, external):
    context = {} if external else dataset.get("target_context") or {}
    selected = context.get("selected_target") or context.get("target_name")
    declared_names = [selected] if selected else context.get("target_names")
    if declared_names and declared_names != target_names:
        raise RetainedComparisonUnavailable("Retained response names conflict with the selected target context.")
    units = context.get("target_units")
    if response_source is not None:
        # A connected response contributes its data matrix, not the
        # predictor's unrelated embedded target or intensity units.
        units = response_source.get("units")
        response_context = (
            (response_source.get("target_context") or {}) if response_source.get("target") is None else {}
        )
        declared_units = response_context.get("target_units")
        if units and declared_units and units != declared_units:
            raise RetainedComparisonUnavailable("Retained response unit declarations conflict.")
        units = units or declared_units
        names = (response_source.get("x_axis") or {}).get("labels")
        declared_names = response_context.get("target_names")
        if any(candidate and candidate != target_names for candidate in (names, declared_names)):
            raise RetainedComparisonUnavailable("Retained response names conflict with the comparison.")
    return units


def _population_identities(
    value, dataset, fitted, response_source, plan, split, branch, *, registered, node, calibration, standalone
):
    """Admit only the exact known refusal; retain other producer refusals."""
    metadata = value.get("metadata", {})
    refusal = metadata.get("sample_identity_unavailable")
    limitations = []
    if refusal and refusal != LEGACY_IDENTITY_REASON:
        if refusal == INVALID_IDENTITY_REASON:
            limitations.append(INVALID_IDENTITY_REASON)
        return (
            None,
            None,
            [
                *limitations,
                "Sample identities were not qualified; numerical results remain inspectable.",
                "The retained producer recorded an identity refusal that cannot be recovered "
                "from registered origin.",
            ],
        )
    count = len(plan["train_indices" if branch == "train" else "test_indices"])
    cohort_ids, cohort_reason = _retained_sample_identity(dataset, count)
    fitted_ids, fitted_reason = _retained_sample_identity(fitted, len(plan["train_indices"]))
    if refusal == LEGACY_IDENTITY_REASON or LEGACY_IDENTITY_REASON in (cohort_reason, fitted_reason):
        if standalone:
            raise RegisteredIdentityUnavailable("Registered recovery requires an exact retained split input.")
        cohort_ids = registered.ids(dataset, split, branch, plan)
        fitted_ids = registered.ids(fitted, split, "train", plan)
        if not calibration:
            registered.comparison_inputs(node, split, branch, plan, value["data"])
    if cohort_ids is None or fitted_ids is None:
        # Labels/row positions cannot qualify pairing, even when values remain readable.
        limitations.extend(reason for reason in (cohort_reason, fitted_reason) if reason)
        limitations.append(
            "Typed sample identities were not retained; historical values remain inspectable "
            "but cannot establish a paired population."
        )
        return None, None, limitations
    if response_source is not None:
        response_ids, response_reason = _retained_sample_identity(response_source, count)
        if response_reason == LEGACY_IDENTITY_REASON and not standalone:
            response_ids = registered.ids(response_source, split, branch, plan)
        if response_ids != cohort_ids:
            if response_reason:
                limitations.append(response_reason)
            limitations.append("Response sample identities were not qualified against the retained population.")
            return None, None, limitations
    return cohort_ids, fitted_ids, limitations


class _BoundedOutputReader:
    """Count each checksummed port once within one comparison readout."""

    def __init__(self, run, evidence):
        self.user_id = run.user_id
        self.evidence = evidence
        self.budget = 16 * 1024 * 1024
        self.reads = {}

    def __call__(self, node, port):
        if (node, port) in self.reads:
            return self.reads[(node, port)]
        item = self.evidence.outputs.get(node, {}).get(port)
        if item is None or item.state != "exact" or item.storage != "file" or not item.byte_count:
            raise RetainedComparisonUnavailable("Exact retained population evidence is unavailable.")
        self.budget -= item.byte_count
        if self.budget < 0:
            raise RetainedComparisonUnavailable(
                "Retained comparison exceeds the bounded read budget; inspect individual run outputs."
            )
        self.reads[(node, port)] = read_output(self.user_id, item)
        return self.reads[(node, port)]


def _read_failure_reason(exc: Exception) -> str:
    if isinstance(exc, ValidationReadBudgetExceeded):
        return "Comparison incomplete: retained evidence reached the 16 MiB read limit; inspect individual outputs."
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "Retained evidence failed integrity or format validation; affected results are unavailable."
    return "A retained output could not be read; other verified results remain available."


def retained_regression_evidence(run: Any) -> tuple[tuple[EvaluationEvidence, ...], PopulationSummary, bool]:
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    if evidence.qualification != "qualified":
        return (), PopulationSummary(), False
    exact = _BoundedOutputReader(run, evidence)

    definition = exact("__workflow__", "definition")
    nodes = {node["node_id"]: node for node in definition.get("nodes", [])}
    records, populations, identity_limitations, response_facts = [], [], [], []
    registered = RetainedRegisteredIdentity(definition, exact)
    inventory_complete = True

    def read_failure(node, port, exc):
        nonlocal inventory_complete
        inventory_complete = False
        identity_limitations.append(_read_failure_reason(exc))
        logger.warning(
            "Retained comparison output unavailable run=%s node=%s port=%s error_type=%s",
            run.id,
            node,
            port,
            type(exc).__name__,
        )

    plans = {entry["node"]: entry["plan"] for entry in _split_summaries(run, definition, on_read_error=read_failure)}
    for node, port, value in _validation_output_values(run, evidence, on_read_error=read_failure):
        if value.get("schema_version") != "spectrasherpa-regression-comparison/1":
            continue
        try:
            metadata = value.get("metadata", {})
            role = metadata.get("role")
            if role not in {"calibration", "held_out_test"} or metadata.get("n_targets") != 1:
                continue
            authority = metadata.get("population_authority", {})
            dataset = None
            standalone_plan = None
            target_edge = None
            if authority.get("qualification") == "graph_verified":
                population = authority.get("population")
                fits = authority.get("fitted_populations")
                if not isinstance(population, list) or len(population) != 2 or population[0] not in plans:
                    continue
                split, branch = population
                if branch not in {"train", "test"} or fits != [[split, "train"]]:
                    continue
                if (branch == "test") != (role == "held_out_test"):
                    continue
                dataset = exact(split, "X_" + branch)
            elif (
                role == "calibration"
                and nodes.get(node, {}).get("node_type") == "model.fitted_pls"
                and port == "calibration_comparison"
            ):
                inputs = [
                    edge
                    for edge in definition.get("edges", [])
                    if edge.get("to_node_id") == node and edge.get("to_input") in {None, "default"}
                ]
                if len(inputs) != 1:
                    continue
                edge = inputs[0]
                dataset = exact(edge["from_node_id"], edge.get("from_output") or "default")
                if not isinstance(dataset, dict):
                    continue
                target_edge = _response_edge(definition, node)
                receipts = [
                    entry for entry in dataset.get("provenance", []) if entry.get("op_id") == "data.train_test_split"
                ]
                if not receipts:
                    count = dataset.get("n_samples")
                    if type(count) is not int or count < 2:
                        continue
                    split, branch = edge["from_node_id"], "train"
                    standalone_plan = {
                        "n_samples": count,
                        "train_indices": list(range(count)),
                        "test_indices": [],
                        # Display labels are not part of population identity. Bind the
                        # exact feature values and physical feature-axis declaration.
                        "x_content_digest": _digest(
                            {
                                "data": array_content_digest(np.asarray(dataset.get("data"), dtype=float)),
                                "x_axis": dataset.get("x_axis"),
                            }
                        ),
                        "digest": None,
                    }
                else:
                    split, branch = receipts[-1].get("node_id"), "train"
                    if split not in plans or receipts[-1].get("parameters", {}).get("split") != "train":
                        continue
                    raw_branch = exact(split, "X_train")
                    if dataset.get("y_axis") != raw_branch.get("y_axis"):
                        continue
                    if not dataset.get("y_axis") and edge["from_node_id"] != split:
                        # No exact sample authority survived an intervening transform.
                        continue
                    if dataset.get("target") != raw_branch.get("target"):
                        continue
            else:
                continue
            if not isinstance(dataset, dict) or dataset.get("type") != "SherpaDataset":
                continue
            plan = standalone_plan or plans[split]
            indices = plan["train_indices" if branch == "train" else "test_indices"]
            rows = value.get("data", [])
            target_names = metadata.get("target_names", [])
            if (
                len(target_names) != 1
                or len(rows) != len(indices)
                or any(row.get("target") != target_names[0] for row in rows)
            ):
                continue
            observed = tuple(float(row["reference"]) for row in rows)
            target, response_source, external_response = _target(
                dataset, target_edge, standalone_plan, split, branch, exact
            )
            target_array = np.asarray(target, dtype=float)
            if target_array.shape not in {(len(rows),), (len(rows), 1)} or not np.array_equal(
                target_array.reshape(-1), observed
            ):
                continue
            units = _response_units(dataset, response_source, target_names, external=external_response)
            # Response facts do not establish paired population identity. Keep
            # exact retained facts even when the independent identity gate refuses.
            response_facts.append((target_names[0], units))
            identity = plan.get("x_content_digest")
            if not isinstance(identity, str) or len(identity) != 64:
                continue
            # Source receipt plus original row position survives a renamed node
            # and preserves membership across different fitted preprocessing.
            source = (dataset.get("extra") or {}).get("source_collection", {}).get("source_manifest_sha256")
            if not isinstance(source, str) or len(source) != 64:
                continue
            fitted = dataset if branch == "train" else exact(split, "X_train")
            cohort_ids, fitted_ids, limitations = _population_identities(
                value,
                dataset,
                fitted,
                response_source,
                plan,
                split,
                branch,
                registered=registered,
                node=node,
                calibration=nodes.get(node, {}).get("node_type") == "model.fitted_pls"
                and port == "calibration_comparison",
                standalone=standalone_plan is not None,
            )
            identity_limitations.extend(limitations)
            if cohort_ids is None or fitted_ids is None:
                continue
            recorded_ids = metadata.get("sample_ids")
            if recorded_ids is not None and recorded_ids != cohort_ids:
                continue
            source_collection = (dataset.get("extra") or {}).get("source_collection", {})
            fit_collection = (fitted.get("extra") or {}).get("source_collection", {})
            if any(
                source_collection.get(key) != fit_collection.get(key)
                for key in ("source_manifest_sha256", "collection_definition_sha256", "scientific_collection_sha256")
            ):
                continue
            # Population identity belongs to the original split branch, not
            # the units/domain of a later fitted preprocessing representation.
            signal_source = dataset if standalone_plan is not None else exact(split, "X_" + branch)
            namespace = _digest(
                {
                    "source_manifest_sha256": source,
                    "collection_definition_sha256": source_collection.get("collection_definition_sha256"),
                    "scientific_collection_sha256": source_collection.get("scientific_collection_sha256"),
                    "x_content_digest": identity,
                    "signal": {
                        "units": signal_source.get("units"),
                        "domain": signal_source.get("domain"),
                        "data_role": signal_source.get("data_role"),
                        "value_units": (signal_source.get("metadata") or {}).get("value_units"),
                        "value_units_label": (signal_source.get("metadata") or {}).get("value_units_label"),
                    },
                }
            )
            summary = PopulationSummary(
                admitted_count=plan["n_samples"],
                development_count=len(plan["train_indices"]),
                held_out_count=None if standalone_plan else len(plan["test_indices"]),
                evaluation_count=len(indices),
                group_count=plan.get("n_groups"),
                grouped=None if standalone_plan else plan.get("groups_content_digest") is not None,
                response=target_names[0],
                units=units,
                partition_digest=plan["digest"],
                source_receipt=namespace,
                verification="partial",
                limitations=[
                    "Source exclusions and prior inspection independence are not established by the split receipt."
                ],
            )
            populations.append(summary)
            records.append(
                EvaluationEvidence(
                    role="held_out" if branch == "test" else "calibration",
                    sample_ids=tuple(f"{namespace}:{sample_id}" for sample_id in cohort_ids),
                    observations=observed,
                    predictions=tuple(float(row["predicted"]) for row in rows),
                    feature_receipt=namespace,
                    response_identity=_digest({"target": target_names[0], "units": units}),
                    response=target_names[0],
                    units=units,
                    fitted_sample_ids=tuple(f"{namespace}:{sample_id}" for sample_id in fitted_ids),
                    population=summary,
                )
            )
        except (ValueError, TypeError, KeyError, AttributeError, OSError, IndexError) as exc:
            inventory_complete = False
            # One absent or invalid retained port must not erase evidence from
            # other evaluators. Keep the refusal scoped to this record.
            reason = (
                str(exc)
                if isinstance(exc, (RetainedComparisonUnavailable, RegisteredIdentityUnavailable))
                else "Retained population evidence could not be verified; inspect individual run outputs."
            )
            if (
                isinstance(exc, RegisteredIdentityUnavailable)
                or metadata.get("sample_identity_unavailable") == LEGACY_IDENTITY_REASON
            ):
                identity_limitations.append(LEGACY_IDENTITY_REASON)
                reason = "Sample identities were not qualified; numerical results remain inspectable. " + reason
            identity_limitations.append(reason)
            logger.warning(
                "RETAINED_COMPARISON_UNAVAILABLE run_id=%s node_id=%s port=%s error_type=%s",
                run.id,
                node,
                port,
                type(exc).__name__,
            )
            continue
    common = (
        populations[0].model_copy(deep=True)
        if populations and all(p.partition_digest == populations[0].partition_digest for p in populations)
        else PopulationSummary(limitations=list(dict.fromkeys(identity_limitations)))
    )
    common.limitations = list(dict.fromkeys([*identity_limitations, *common.limitations]))
    if (
        common.verification == "unknown"
        and response_facts
        and all(fact == response_facts[0] for fact in response_facts)
    ):
        common.response, common.units = response_facts[0]
    return tuple(records), common, inventory_complete
