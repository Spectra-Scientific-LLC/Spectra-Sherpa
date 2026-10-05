"""Closed, deterministic parameter search above a saved canonical baseline.

This is intentionally *not* an optimizer and it does not execute a model.  It
answers one smaller but important question before M4.17 is allowed to schedule
anything: given a user-owned, already-admitted workbench DAG, which exact
parameter-only candidates are permitted?  The answer is a finite,
digest-bound object that later admission and Runner code must consume without
re-enumerating or inventing candidates.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping

from spectra_sherpa.app.services.dag import canonical_selection_policy as _canonical_selection_policy
from spectra_sherpa.app.services.dag.canonical_workbench_baseline import CanonicalWorkbenchBaseline
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.validation_graph import (
    ValidationGraph,
    ValidationGraphError,
    admit_validation_graph,
)

CANONICAL_SEARCH_SPACE_VERSION = "spectra-canonical-search-space/3"
CANONICAL_SEARCH_STRATEGY = "finite_declared_parameter_grid"
CANONICAL_SEARCH_HARD_MAX_CANDIDATES = 64


class CanonicalSearchSpaceError(ValueError):
    """A requested variation escapes the saved canonical scientific DAG."""


@dataclass(frozen=True)
class CanonicalSearchSlot:
    """One exact baseline parameter and its closed proposed values."""

    node_id: str
    parameter: str
    values: tuple[object, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id or len(self.node_id) > 128:
            raise CanonicalSearchSpaceError("search slot node_id must be bounded text")
        if not isinstance(self.parameter, str) or not self.parameter or len(self.parameter) > 128:
            raise CanonicalSearchSpaceError("search slot parameter must be bounded text")
        if not self.values:
            raise CanonicalSearchSpaceError("search slot requires at least one declared value")
        for value in self.values:
            _require_json_scalar(value, field="search slot value")
        encoded = tuple(_canonical_value(value) for value in self.values)
        if len(set(encoded)) != len(encoded):
            raise CanonicalSearchSpaceError("search slot values must be unique")
        if encoded != tuple(sorted(encoded)):
            raise CanonicalSearchSpaceError("search slot values must use canonical order")

    def as_dict(self) -> dict[str, object]:
        return {"node_id": self.node_id, "parameter": self.parameter, "values": list(self.values)}


@dataclass(frozen=True)
class CanonicalSearchCandidate:
    """One exact graph produced by the finite declared grid."""

    ordinal: int
    candidate_id: str
    graph: ValidationGraph
    mutations: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "candidate_id": self.candidate_id,
            "graph": self.graph.as_dict(),
            "graph_digest": self.graph.digest,
            "mutations": [deepcopy(item) for item in self.mutations],
        }


@dataclass(frozen=True)
class CanonicalSearchSpace:
    """The exact, complete candidate set permitted for one baseline.

    ``validation_budget`` is deliberately an equality rather than a maximum:
    a user either knows every candidate that may consume validation budget or
    the request is rejected.  A later stopping rule may conclude early, but
    it cannot change this pre-admitted set or add a candidate after admission.
    """

    baseline_digest: str
    baseline_graph_digest: str
    mutable_slots: tuple[CanonicalSearchSlot, ...]
    validation_budget: int
    selection_policy: _canonical_selection_policy.CanonicalSelectionPolicy
    candidates: tuple[CanonicalSearchCandidate, ...]

    def __post_init__(self) -> None:
        if not _is_digest(self.baseline_digest) or not _is_digest(self.baseline_graph_digest):
            raise CanonicalSearchSpaceError("search space baseline identity is malformed")
        if not self.mutable_slots:
            raise CanonicalSearchSpaceError("search space requires at least one mutable slot")
        if not all(isinstance(slot, CanonicalSearchSlot) for slot in self.mutable_slots):
            raise CanonicalSearchSpaceError("search space slots must use the closed slot contract")
        if not all(isinstance(candidate, CanonicalSearchCandidate) for candidate in self.candidates):
            raise CanonicalSearchSpaceError("search space candidates must use the closed candidate contract")
        names = [(slot.node_id, slot.parameter) for slot in self.mutable_slots]
        if names != sorted(names) or len(set(names)) != len(names):
            raise CanonicalSearchSpaceError("search slots must be unique and canonically ordered")
        if not 2 <= len(self.candidates) <= CANONICAL_SEARCH_HARD_MAX_CANDIDATES:
            raise CanonicalSearchSpaceError("search space candidate count is outside the bounded range")
        if self.validation_budget != len(self.candidates):
            raise CanonicalSearchSpaceError("validation budget must equal the complete declared candidate count")
        if not isinstance(self.selection_policy, _canonical_selection_policy.CanonicalSelectionPolicy):
            raise CanonicalSearchSpaceError("search space requires a closed selection policy")
        if self.candidates[0].ordinal != 1 or self.candidates[0].candidate_id != "canonical-baseline-001":
            raise CanonicalSearchSpaceError("search space must begin with the immutable baseline candidate")
        if tuple(candidate.ordinal for candidate in self.candidates) != tuple(range(1, len(self.candidates) + 1)):
            raise CanonicalSearchSpaceError("search candidate ordinals must be contiguous")
        if len({candidate.candidate_id for candidate in self.candidates}) != len(self.candidates):
            raise CanonicalSearchSpaceError("search candidate identities must be unique")
        if len({candidate.graph.digest for candidate in self.candidates}) != len(self.candidates):
            raise CanonicalSearchSpaceError("declared search produces duplicate scientific candidate identities")
        if self.candidates[0].graph.digest != self.baseline_graph_digest or self.candidates[0].mutations:
            raise CanonicalSearchSpaceError("search baseline candidate must preserve the saved graph exactly")

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self._identity_dict())).hexdigest()

    @property
    def minimum_improvement(self) -> float:
        """Expose the pre-declared task-scale margin without duplicating it."""

        return float(self.selection_policy.payload["minimum_improvement"])

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": CANONICAL_SEARCH_SPACE_VERSION,
            "strategy": {
                "candidate_generation": CANONICAL_SEARCH_STRATEGY,
                "selection_policy": self.selection_policy.as_dict(),
            },
            "baseline_digest": self.baseline_digest,
            "baseline_graph_digest": self.baseline_graph_digest,
            "mutable_slots": [slot.as_dict() for slot in self.mutable_slots],
            "validation_budget": self.validation_budget,
            "candidate_count": len(self.candidates),
            "candidates": [candidate.as_dict() for candidate in self.candidates],
        }

    def as_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "search_space_digest": self.digest}


def canonical_search_space_from_request(
    baseline: CanonicalWorkbenchBaseline,
    request: Mapping[str, object],
) -> CanonicalSearchSpace:
    """Project an untrusted closed request into exact admitted candidates.

    No caller supplies a candidate graph.  Each variant starts from the saved
    baseline graph, changes only one declared existing parameter per slot, and
    passes through the live validation-graph authority again.  Therefore a
    request cannot use the search feature to add a node, alter an edge, swap a
    dependency/contract, or smuggle a new parameter field.
    """

    if not isinstance(baseline, CanonicalWorkbenchBaseline):
        raise CanonicalSearchSpaceError("search space requires a saved canonical baseline")
    if not isinstance(request, Mapping) or set(request) != {"slots", "validation_budget", "minimum_improvement"}:
        raise CanonicalSearchSpaceError("search request fields are not closed")
    raw_slots = request["slots"]
    if not isinstance(raw_slots, list) or not raw_slots:
        raise CanonicalSearchSpaceError("search request requires a non-empty slots array")
    slots = tuple(sorted((_slot_from_dict(raw) for raw in raw_slots), key=lambda item: (item.node_id, item.parameter)))
    if len({(slot.node_id, slot.parameter) for slot in slots}) != len(slots):
        raise CanonicalSearchSpaceError("search request repeats a mutable parameter slot")

    budget = request["validation_budget"]
    if (
        isinstance(budget, bool)
        or not isinstance(budget, int)
        or not 2 <= budget <= CANONICAL_SEARCH_HARD_MAX_CANDIDATES
    ):
        raise CanonicalSearchSpaceError(
            f"validation budget must be an integer from 2 through {CANONICAL_SEARCH_HARD_MAX_CANDIDATES}"
        )
    # The selection margin is declared before any candidate runs and is bound
    # into the space digest, so an operator cannot lower the bar after seeing
    # the scores. Validate the untrusted value here rather than letting
    # ``float()`` raise a bare TypeError past this module's closed contract.
    margin = request["minimum_improvement"]
    if (
        isinstance(margin, bool)
        or not isinstance(margin, (int, float))
        or not math.isfinite(float(margin))
        or margin < 0
    ):
        raise CanonicalSearchSpaceError("minimum primary-metric improvement must be a finite non-negative value")
    baseline_graph = baseline.graph
    parameters = {node.node_id: dict(node.parameters) for node in baseline_graph.nodes}
    for slot in slots:
        if slot.node_id not in parameters:
            raise CanonicalSearchSpaceError("search slot names a node outside the saved baseline")
        if slot.parameter not in parameters[slot.node_id]:
            raise CanonicalSearchSpaceError("search slot names a parameter absent from the saved baseline")

    combinations = tuple(itertools.product(*(slot.values for slot in slots)))
    expected_count = 1 + len(combinations)
    if expected_count > CANONICAL_SEARCH_HARD_MAX_CANDIDATES:
        raise CanonicalSearchSpaceError("declared search grid exceeds the hard candidate limit")
    if budget != expected_count:
        raise CanonicalSearchSpaceError("validation budget must exactly cover the complete declared grid and baseline")

    candidates = [
        CanonicalSearchCandidate(
            ordinal=1,
            candidate_id="canonical-baseline-001",
            graph=baseline_graph,
            mutations=(),
        )
    ]
    for ordinal, values in enumerate(combinations, start=2):
        variant_parameters = deepcopy(parameters)
        mutations: list[dict[str, object]] = []
        for slot, value in zip(slots, values):
            variant_parameters[slot.node_id][slot.parameter] = value
            mutations.append({"node_id": slot.node_id, "parameter": slot.parameter, "value": value})
        graph = _re_admit_variant(baseline_graph, variant_parameters)
        candidates.append(
            CanonicalSearchCandidate(
                ordinal=ordinal,
                candidate_id=f"canonical-grid-{ordinal:03d}",
                graph=graph,
                mutations=tuple(mutations),
            )
        )
    return CanonicalSearchSpace(
        baseline_digest=baseline.digest,
        baseline_graph_digest=baseline_graph.digest,
        mutable_slots=slots,
        validation_budget=budget,
        selection_policy=_canonical_selection_policy.CanonicalSelectionPolicy.build(
            float(request["minimum_improvement"]),
            task_type=_graph_supervised_task(baseline_graph),
        ),
        candidates=tuple(candidates),
    )


def canonical_search_space_from_record(
    baseline: CanonicalWorkbenchBaseline,
    record: Mapping[str, object],
) -> CanonicalSearchSpace:
    """Rebuild a stored v2 search record without trusting its candidate list.

    The persisted form names every candidate for evidence review, but those
    entries are never an execution authority.  This reader reconstructs the
    plan only from its slots and exact budget, then demands byte-for-byte
    semantic equality with the stored identity.  A later campaign Runner can
    therefore detect a changed candidate, graph digest, or mutation before it
    opens a dataset capability.
    """

    required = {
        "schema_version",
        "strategy",
        "baseline_digest",
        "baseline_graph_digest",
        "mutable_slots",
        "validation_budget",
        "candidate_count",
        "candidates",
        "search_space_digest",
    }
    if not isinstance(record, Mapping) or set(record) != required:
        raise CanonicalSearchSpaceError("stored search space fields are not closed")
    if (
        record["schema_version"] != CANONICAL_SEARCH_SPACE_VERSION
        or not isinstance(record["strategy"], Mapping)
        or record["baseline_digest"] != baseline.digest
        or record["baseline_graph_digest"] != baseline.graph.digest
    ):
        raise CanonicalSearchSpaceError("stored search space is not bound to the saved baseline")
    slots = record["mutable_slots"]
    if not isinstance(slots, list):
        raise CanonicalSearchSpaceError("stored search space slots must be an array")
    strategy = record["strategy"]
    if set(strategy) != {"candidate_generation", "selection_policy"} or (
        strategy["candidate_generation"] != CANONICAL_SEARCH_STRATEGY
    ):
        raise CanonicalSearchSpaceError("stored search strategy is unsupported")
    try:
        selection_policy = _canonical_selection_policy.CanonicalSelectionPolicy.from_dict(strategy["selection_policy"])
    except (TypeError, ValueError) as exc:
        raise CanonicalSearchSpaceError("stored search selection policy is invalid") from exc
    rebuilt = canonical_search_space_from_request(
        baseline,
        {
            "slots": slots,
            "validation_budget": record["validation_budget"],
            "minimum_improvement": selection_policy.payload["minimum_improvement"],
        },
    )
    if record["candidate_count"] != len(rebuilt.candidates) or record["candidates"] != [
        candidate.as_dict() for candidate in rebuilt.candidates
    ]:
        raise CanonicalSearchSpaceError("stored search space candidate identities do not match its closed grid")
    if record["search_space_digest"] != rebuilt.digest:
        raise CanonicalSearchSpaceError("stored search space digest does not match its closed grid")
    return rebuilt


def _slot_from_dict(raw: object) -> CanonicalSearchSlot:
    if not isinstance(raw, Mapping) or set(raw) != {"node_id", "parameter", "values"}:
        raise CanonicalSearchSpaceError("search slot fields are not closed")
    values = raw["values"]
    if not isinstance(values, list):
        raise CanonicalSearchSpaceError("search slot values must be an array")
    return CanonicalSearchSlot(raw["node_id"], raw["parameter"], tuple(sorted(values, key=_canonical_value)))


def _graph_supervised_task(graph: ValidationGraph) -> str:
    tasks = {
        str(node.contract.payload["supervised_task"])
        for node in graph.nodes
        if node.contract.payload["supervised_task"] != "none"
    }
    if len(tasks) != 1:
        raise CanonicalSearchSpaceError("saved canonical baseline has no single supervised task")
    return next(iter(tasks))


def _re_admit_variant(
    baseline_graph: ValidationGraph,
    parameters: Mapping[str, Mapping[str, object]],
) -> ValidationGraph:
    payload = baseline_graph.as_dict()
    nodes = payload["nodes"]
    assert isinstance(nodes, list)  # constructed locally by ValidationGraph
    for node in nodes:
        assert isinstance(node, dict)
        node_id = node["node_id"]
        assert isinstance(node_id, str)
        node["parameters"] = dict(parameters[node_id])
    # Re-admission binds every altered value to the current first-party
    # parameter grammar, operation contract, typed topology, and runtime.
    try:
        raw_nodes = payload["nodes"]
        raw_edges = payload["edges"]
        assert isinstance(raw_nodes, list) and isinstance(raw_edges, list)
        candidate = admit_validation_graph(
            [WorkflowNode(node["node_id"], node["operation_id"], node["parameters"]) for node in raw_nodes],
            [
                WorkflowEdge(edge["from_node"], edge["to_node"], edge["from_output"], edge["to_input"])
                for edge in raw_edges
            ],
        )
        return candidate
    except (KeyError, TypeError, ValueError, ValidationGraphError) as exc:
        raise CanonicalSearchSpaceError("declared search value is outside the admitted scientific envelope") from exc


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:  # pragma: no cover - guarded at inputs
        raise CanonicalSearchSpaceError("search identity must be finite JSON") from exc


def _canonical_value(value: object) -> str:
    return _canonical_json(value).decode("ascii")


def _require_json_scalar(value: object, *, field: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise CanonicalSearchSpaceError(f"{field} must be a finite JSON scalar")


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


__all__ = [
    "CANONICAL_SEARCH_HARD_MAX_CANDIDATES",
    "CANONICAL_SEARCH_SPACE_VERSION",
    "CanonicalSearchCandidate",
    "CanonicalSearchSlot",
    "CanonicalSearchSpace",
    "CanonicalSearchSpaceError",
    "canonical_search_space_from_record",
    "canonical_search_space_from_request",
]
