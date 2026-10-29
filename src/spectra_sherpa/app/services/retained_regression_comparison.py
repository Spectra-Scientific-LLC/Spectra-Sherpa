"""Adapt executor-owned regression/split receipts to neutral evidence.

Display labels and equal row counts never establish population identity. The
split-plan authority and retained feature/response payloads establish it.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import numpy as np

from spectra_sherpa.app.contracts.comparison_evidence import EvaluationEvidence
from spectra_sherpa.app.lib.sample_identity import sample_ids
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.schemas.scientific_comparison import PopulationSummary
from spectra_sherpa.app.services.run_output_retention import read_output
from spectra_sherpa.app.services.run_validation_summary import _split_summaries, _validation_output_values


class RetainedComparisonUnavailable(ValueError):
    """Closed, public-safe reasons for unavailable retained comparison evidence."""


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _retained_sample_ids(dataset, count):
    """Adapt retained wire axes to the canonical typed identity reader."""
    if not isinstance(dataset, dict):
        return None
    axis = dataset.get("y_axis") or {}
    return sample_ids(
        SimpleNamespace(
            sample_axis=SimpleNamespace(sample_table=axis.get("sample_table")),
            n_samples=count,
        )
    )


def _target(dataset, target_edge, standalone_plan, split, branch, exact):
    if target_edge is not None:
        value = exact(target_edge["from_node_id"], target_edge.get("from_output") or "default")
    elif dataset.get("target") is None and standalone_plan is None:
        value = exact(split, "y_" + branch)
    else:
        value = dataset.get("target")
    return value.get("data") if isinstance(value, dict) else value


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


def retained_regression_evidence(run: Any) -> tuple[tuple[EvaluationEvidence, ...], PopulationSummary]:
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    if evidence.qualification != "qualified":
        return (), PopulationSummary()
    exact = _BoundedOutputReader(run, evidence)

    definition = exact("__workflow__", "definition")
    plans = {entry["node"]: entry["plan"] for entry in _split_summaries(run, definition)}
    nodes = {node["node_id"]: node for node in definition.get("nodes", [])}
    records, populations, identity_limitations = [], [], []
    for node, port, value in _validation_output_values(run, evidence):
        if value.get("schema_version") != "spectrasherpa-regression-comparison/1":
            continue
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
                    "x_content_digest": _digest({"data": dataset.get("data"), "x_axis": dataset.get("x_axis")}),
                    "digest": None,
                }
                targets = [
                    e for e in definition.get("edges", []) if e.get("to_node_id") == node and e.get("to_input") == "y"
                ]
                if len(targets) == 1:
                    target_edge = targets[0]
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
        target = _target(dataset, target_edge, standalone_plan, split, branch, exact)
        target_array = np.asarray(target, dtype=float)
        if target_array.shape not in {(len(rows),), (len(rows), 1)} or not np.array_equal(
            target_array.reshape(-1), observed
        ):
            continue
        identity = plan.get("x_content_digest")
        if not isinstance(identity, str) or len(identity) != 64:
            continue
        # Source receipt plus original row position survives a renamed node
        # and preserves membership across different fitted preprocessing.
        source = (dataset.get("extra") or {}).get("source_collection", {}).get("source_manifest_sha256")
        if not isinstance(source, str) or len(source) != 64:
            continue
        cohort_ids = _retained_sample_ids(dataset, len(indices))
        fitted = dataset if branch == "train" else exact(split, "X_train")
        fitted_ids = _retained_sample_ids(fitted, len(plan["train_indices"]))
        if cohort_ids is None or fitted_ids is None:
            # Historical values remain inspectable; display labels and row
            # positions cannot establish an identity-qualified comparison.
            identity_limitations.append(
                "Typed sample identities were not retained; historical values remain inspectable "
                "but cannot establish a paired population."
            )
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
        namespace = _digest(
            {
                "source_manifest_sha256": source,
                "collection_definition_sha256": source_collection.get("collection_definition_sha256"),
                "scientific_collection_sha256": source_collection.get("scientific_collection_sha256"),
                "x_content_digest": identity,
                "signal": {
                    "units": dataset.get("units"),
                    "domain": dataset.get("domain"),
                    "data_role": dataset.get("data_role"),
                    "value_units": (dataset.get("metadata") or {}).get("value_units"),
                    "value_units_label": (dataset.get("metadata") or {}).get("value_units_label"),
                },
            }
        )
        context = dataset.get("target_context") or {}
        units = context.get("target_units")
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
    common = (
        populations[0]
        if populations and all(p.partition_digest == populations[0].partition_digest for p in populations)
        else PopulationSummary(limitations=list(dict.fromkeys(identity_limitations)))
    )
    common.limitations = list(dict.fromkeys([*identity_limitations, *common.limitations]))
    return tuple(records), common
