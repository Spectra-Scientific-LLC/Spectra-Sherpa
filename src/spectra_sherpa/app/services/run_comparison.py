"""Semantic correspondence spike for retained scientific presentations.

Correspondence is distinct from permission to rank evaluation metrics. This
module never treats node IDs or similar metric names as scientific evidence.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any, Literal

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.schemas.execution_runs import ComparisonResultPair
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.run_output_retention import read_output


@dataclass(frozen=True)
class ResultRole:
    node_id: str
    presentation_id: str
    kind: str
    source_ports: tuple[str, ...]


@dataclass(frozen=True)
class RolePair:
    kind: str
    left: tuple[ResultRole, ...]
    right: tuple[ResultRole, ...]
    requires_pairing: bool
    reason: str


def declared_result_roles(records: Mapping[str, Any]) -> list[ResultRole]:
    """Read saved executed presentation declarations, never today's registry."""
    roles = []
    for node_id, record in records.items():
        if not isinstance(record, Mapping):
            continue
        contract = record.get("contract")
        if not isinstance(contract, Mapping) or contract.get("schema_version") != "spectrasherpa-node-presentation/1":
            continue
        presentations = contract.get("presentations")
        if not isinstance(presentations, list):
            continue
        executed = record.get("presentations")
        if "presentations" in record and not isinstance(executed, list):
            continue
        executed_ids = (
            {
                item.get("presentation_id")
                for item in executed
                if isinstance(item, Mapping) and isinstance(item.get("presentation_id"), str)
            }
            if isinstance(executed, list)
            else None
        )
        for item in presentations:
            if not isinstance(item, Mapping):
                continue
            identifier, kind, ports = item.get("presentation_id"), item.get("kind"), item.get("source_ports")
            if not isinstance(identifier, str) or not isinstance(kind, str):
                continue
            if executed_ids is not None and identifier not in executed_ids:
                continue
            if not isinstance(ports, list) or not ports or not all(isinstance(port, str) for port in ports):
                continue
            roles.append(ResultRole(node_id, identifier, kind, tuple(ports)))
    return roles


def pair_result_roles(left: list[ResultRole], right: list[ResultRole]) -> list[RolePair]:
    """Propose only unique semantic-role pairs; leave ambiguity to the scientist."""
    left_by_kind: dict[str, list[ResultRole]] = defaultdict(list)
    right_by_kind: dict[str, list[ResultRole]] = defaultdict(list)
    for role in left:
        left_by_kind[role.kind].append(role)
    for role in right:
        right_by_kind[role.kind].append(role)
    pairs = []
    for kind in sorted(left_by_kind.keys() | right_by_kind.keys()):
        lhs, rhs = tuple(left_by_kind[kind]), tuple(right_by_kind[kind])
        ambiguous = len(lhs) > 1 or len(rhs) > 1
        reason = (
            "Choose an explicit result pairing; this role occurs more than once."
            if ambiguous
            else (
                "No corresponding declared result exists in the other run."
                if not lhs or not rhs
                else "Unique declared role correspondence; evaluation compatibility is not yet established."
            )
        )
        pairs.append(RolePair(kind, lhs, rhs, ambiguous, reason))
    return pairs


def saved_run_result_pairs(runs: list[ExecutionRun]) -> list[ComparisonResultPair]:
    """Expose correspondence without inferring evaluation from metric names."""
    presentations = {run.id: saved_scientific_ledger(run, "_scientific_presentations") for run in runs}
    values = {run.id: saved_scientific_ledger(run, "_scientific_values") for run in runs}

    def roles(run: ExecutionRun) -> list[ResultRole]:
        return declared_result_roles(presentations[run.id])

    result = []
    for left_run, right_run in combinations(runs, 2):
        pairs = pair_result_roles(roles(left_run), roles(right_run))
        for pair in pairs:
            state: Literal["comparable", "incompatible", "insufficient_evidence"] = "insufficient_evidence"
            reason = pair.reason
            if not pair.requires_pairing and len(pair.left) == len(pair.right) == 1:
                left_types = _role_types(values[left_run.id], pair.left[0])
                right_types = _role_types(values[right_run.id], pair.right[0])
                left_hashes = _exact_role_hashes(left_run, pair.left[0])
                right_hashes = _exact_role_hashes(right_run, pair.right[0])
                if left_types is not None and right_types is not None and left_types != right_types:
                    state = "incompatible"
                    reason = "Saved scientific value types differ; automatic result comparison is not qualified."
                elif left_hashes is not None and left_hashes == right_hashes:
                    state = "comparable"
                    reason = (
                        "Declared results have identical exact retained payloads. This does not qualify metric ranking."
                    )
            result.append(
                ComparisonResultPair(
                    left_run_id=left_run.id,
                    right_run_id=right_run.id,
                    kind=pair.kind,
                    left=[asdict(role) for role in pair.left],
                    right=[asdict(role) for role in pair.right],
                    requires_pairing=pair.requires_pairing,
                    state=state,
                    reason=reason,
                )
            )
        if not pairs:
            result.append(
                ComparisonResultPair(
                    left_run_id=left_run.id,
                    right_run_id=right_run.id,
                    kind="unknown",
                    left=[],
                    right=[],
                    requires_pairing=False,
                    state="insufficient_evidence",
                    reason="Saved scientific presentation declarations are unavailable for these runs.",
                )
            )
    return result


def _exact_role_hashes(run: ExecutionRun, role: ResultRole) -> tuple[str, ...] | None:
    try:
        evidence = RunEvidence.model_validate(getattr(run, "evidence_completeness", None))
    except (ValueError, TypeError):
        return None
    if evidence.qualification != "qualified":
        return None
    ports = evidence.outputs.get(role.node_id, {})
    selected = [ports.get(port) for port in role.source_ports]
    if not selected or any(item is None or item.state != "exact" or item.storage != "file" for item in selected):
        return None
    return tuple(item.sha256 for item in selected if item is not None and item.sha256 is not None)


def saved_scientific_ledger(run: Any, name: str) -> Mapping[str, Any]:
    """Retained declarations are authoritative; a broken file cannot use a preview."""
    try:
        evidence = RunEvidence.model_validate(getattr(run, "evidence_completeness", None))
    except (ValueError, TypeError):
        evidence = None
    item = evidence.outputs.get("__diagnostics__", {}).get(name) if evidence is not None else None
    if item is not None:
        if item.state != "exact":
            return {}
        try:
            value = read_output(run.user_id, item)
            return value if isinstance(value, Mapping) else {}
        except (ValueError, OSError, TypeError, AttributeError):
            return {}
    diagnostics = getattr(run, "diagnostics", None)
    value = diagnostics.get(name) if isinstance(diagnostics, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def _role_types(values: Mapping[str, Any], role: ResultRole) -> tuple[str, ...] | None:
    node = values.get(role.node_id) if isinstance(values, Mapping) else None
    if not isinstance(node, Mapping):
        return None
    types = []
    for port in role.source_ports:
        descriptor = node.get(port)
        if (
            not isinstance(descriptor, Mapping)
            or descriptor.get("schema_version") != "spectrasherpa-scientific-value/1"
        ):
            return None
        type_ref = descriptor.get("type_ref")
        if not isinstance(type_ref, str) or not type_ref:
            return None
        types.append(type_ref)
    return tuple(types)
