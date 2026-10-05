"""Qualify a narrow comparison using existing, exact out-of-fold evidence."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
from math import isfinite
from typing import Any

from spectra_sherpa.app.schemas.execution_runs import ComparisonResultPair, EvaluationSelection
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.dag.out_of_fold_evidence import (
    OUT_OF_FOLD_EVIDENCE_TYPE,
    validate_out_of_fold_evidence,
)
from spectra_sherpa.app.services.run_comparison import declared_result_roles, saved_scientific_ledger
from spectra_sherpa.app.services.run_output_retention import read_output
from spectra_sherpa.sdk import validate as sdk_validate


@dataclass(frozen=True)
class Evaluation:
    inputs: tuple[tuple[str, str], ...]
    split: str
    observations: tuple[Any, ...]
    metrics: dict[str, float]
    node_id: str
    presentation_id: str
    source_port: str
    split_plan: dict[str, Any]


def _evaluation(run: Any, selection: EvaluationSelection | None = None) -> Evaluation:
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    if evidence.qualification != "qualified":
        raise ValueError("Run evidence is not qualified.")
    values = saved_scientific_ledger(run, "_scientific_values")
    candidates = [
        (node, port)
        for node, ports in values.items()
        if isinstance(ports, Mapping)
        for port, descriptor in ports.items()
        if isinstance(descriptor, Mapping) and descriptor.get("type_ref") == OUT_OF_FOLD_EVIDENCE_TYPE
    ]
    declared = declared_result_roles(saved_scientific_ledger(run, "_scientific_presentations"))
    if not candidates and any(role.kind in {"classification_model", "classification_responses"} for role in declared):
        raise ValueError(
            "Classification evaluation ranking is not yet supported. Saved classification results remain inspectable."
        )
    if selection is not None:
        chosen = [
            role
            for role in declared
            if role.node_id == selection.node_id
            and role.presentation_id == selection.presentation_id
            and role.kind == "out_of_fold_evidence"
        ]
        if len(chosen) != 1:
            raise ValueError("Selected evaluation is not a declared saved out-of-fold result.")
        candidates = [
            (node, port) for node, port in candidates if node == selection.node_id and port in chosen[0].source_ports
        ]
    if len(candidates) != 1:
        raise ValueError(
            "Choose one explicit saved out-of-fold evaluation per run."
            if len(candidates) > 1
            else "Bound out-of-fold evaluation evidence is unavailable."
        )
    node, port = candidates[0]
    roles = [
        role
        for role in declared
        if role.node_id == node
        and role.kind == "out_of_fold_evidence"
        and port in role.source_ports
        and (selection is None or role.presentation_id == selection.presentation_id)
    ]
    if len(roles) != 1:
        raise ValueError("Bound evaluation presentation correspondence is unavailable or ambiguous.")
    remaining = 16 * 1024 * 1024

    def exact(source: str, output: str) -> tuple[Any, str]:
        nonlocal remaining
        item = evidence.outputs.get(source, {}).get(output)
        if item is None or item.state != "exact" or item.storage != "file" or not item.sha256:
            raise ValueError("Exact retained evaluation inputs and outputs are required.")
        if item.byte_count is None or item.byte_count <= 0:
            raise ValueError("Retained evaluation evidence has no valid byte count.")
        remaining -= item.byte_count
        if remaining < 0:
            raise ValueError("Evaluation evidence exceeds the 16 MiB per-run comparison read budget.")
        return read_output(run.user_id, item), item.sha256

    record, _ = exact(node, port)
    normalized, observed, predicted, _ = validate_out_of_fold_evidence(record)
    if normalized["producer"]["node_id"] != node:
        raise ValueError("Out-of-fold producer does not match its saved node.")
    definition, _ = exact("__workflow__", "definition")
    if not isinstance(definition, Mapping) or definition.get("schema_version") != 1:
        raise ValueError("Saved workflow definition is unavailable.")
    nodes = [item for item in definition.get("nodes", []) if item.get("node_id") == node]
    if len(nodes) != 1 or nodes[0].get("node_type") != normalized["producer"]["operation_id"]:
        raise ValueError("Saved workflow does not identify the bound evaluation producer.")
    inputs = {}
    for edge in definition.get("edges", []):
        if edge.get("to_node_id") != node:
            continue
        name = edge.get("to_input")
        if name not in {"X", "y"} or name in inputs:
            raise ValueError("Evaluation input correspondence is ambiguous.")
        payload, digest = exact(edge.get("from_node_id"), edge.get("from_output") or "default")
        if name == "X":
            # Dataset UUIDs are transport identity, not scientific identity.
            # Use the existing retained scientific receipt, verified in its
            # checksummed file, rather than inventing another projection.
            if not isinstance(payload, Mapping) or payload.get("type") != "SherpaDataset":
                raise ValueError("Evaluation population lacks a retained scientific dataset identity.")
            manifest = payload.get("manifest") or {}
            source = (payload.get("extra") or {}).get("source_collection") or {}
            scientific = manifest.get("scientific_digest")
            source_digest = source.get("source_manifest_sha256")
            if (
                manifest.get("scientific_projection_schema") != "spectrasherpa-dataset-scientific-projection/1"
                or not isinstance(scientific, str)
                or not re.fullmatch(r"[0-9a-f]{64}", scientific)
                or not isinstance(source_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", source_digest)
            ):
                raise ValueError("Evaluation population lacks a complete retained scientific/source receipt.")
            digest = f"{source_digest}:{scientific}"
        inputs[name] = digest
    if set(inputs) != {"X", "y"}:
        raise ValueError("Exact separately bound feature and target inputs are required for automatic ranking.")
    metrics = sdk_validate.metrics(observed, predicted).as_dict()
    return Evaluation(
        node_id=node,
        presentation_id=roles[0].presentation_id,
        source_port=port,
        inputs=tuple(sorted(inputs.items())),
        split=normalized["split_plan_digest"],
        split_plan=normalized["split_plan"],
        observations=tuple(normalized["observations"]),
        metrics={
            f"qualified_cv.{key}": float(metrics[key])
            for key in ("rmse", "mae", "r2")
            if metrics[key] is not None and isfinite(float(metrics[key]))
        },
    )


def qualified_evaluation_comparison(
    runs: list[Any],
    selections: dict[int, EvaluationSelection] | None = None,
) -> tuple[list[ComparisonResultPair], dict[str, dict[str, float]]]:
    """Rank only one unambiguous, identically bound evaluation per selected run.

    Read through the retained-file checksum authority, not results_summary.
    Different training choices are permitted; different populations or folds
    are not a common evaluation. Unsupported history remains inspectable.
    """
    evaluations, reasons = {}, {}
    for run in runs:
        try:
            evaluations[run.id] = _evaluation(run, (selections or {}).get(run.id))
        except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            reasons[run.id] = str(exc) or "Bound evaluation evidence is unavailable."
    pairs = []
    all_comparable = len(runs) >= 2
    for left, right in combinations(runs, 2):
        lhs, rhs = evaluations.get(left.id), evaluations.get(right.id)
        if lhs is None or rhs is None:
            state = "insufficient_evidence"
            reason = reasons.get(left.id) or reasons[right.id]
        elif (lhs.inputs, lhs.split, lhs.observations) != (rhs.inputs, rhs.split, rhs.observations):
            state = "incompatible"
            reason = "Retained evaluation inputs, target observations, or validation folds differ."
        else:
            state = "comparable"
            reason = "Exact feature/target inputs and validation folds match; bound out-of-fold metrics may be ranked."
        all_comparable &= state == "comparable"

        def result_role(item: Evaluation | None) -> list[dict[str, Any]]:
            return (
                []
                if item is None
                else [
                    {
                        "node_id": item.node_id,
                        "presentation_id": item.presentation_id,
                        "kind": "out_of_fold_evidence",
                        "source_ports": [item.source_port],
                    }
                ]
            )

        def choices(run: Any, item: Evaluation | None) -> list[dict[str, Any]]:
            if item is not None:
                return result_role(item)
            return [
                {
                    "node_id": role.node_id,
                    "presentation_id": role.presentation_id,
                    "kind": role.kind,
                    "source_ports": list(role.source_ports),
                }
                for role in declared_result_roles(saved_scientific_ledger(run, "_scientific_presentations"))
                if role.kind == "out_of_fold_evidence"
            ]

        left_choices, right_choices = choices(left, lhs), choices(right, rhs)
        pairs.append(
            ComparisonResultPair(
                left_run_id=left.id,
                right_run_id=right.id,
                kind="out_of_fold_evaluation",
                left=left_choices,
                right=right_choices,
                requires_pairing=len(left_choices) > 1 or len(right_choices) > 1,
                state=state,
                reason=reason,
            )
        )
    if not all_comparable:
        return pairs, {}
    keys = set.intersection(*(set(item.metrics) for item in evaluations.values()))
    return pairs, {key: {str(run.id): evaluations[run.id].metrics[key] for run in runs} for key in sorted(keys)}
