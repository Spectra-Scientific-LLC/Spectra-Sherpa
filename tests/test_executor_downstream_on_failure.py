"""M1 — when a node fails mid-DAG, downstream nodes must NOT be left in PENDING.

Before this fix, ``get_status()['node_statuses']`` on a failed run showed
the failing node as ``error`` and every downstream as ``pending`` — which
reads as "didn't run yet" in the run-history UI and misleads users about
what actually happened.

The executor now walks the transitive descendants of the failed node and
marks each as ``error`` with a clear ``error_message`` distinguishing it
from a node that failed on its own.
"""

from __future__ import annotations

from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge

# ---------------------------------------------------------------------------
# _transitive_descendants (pure graph)
# ---------------------------------------------------------------------------


def test_transitive_descendants_walks_full_subgraph():
    """A -> B -> C
          \\-> D -> E
    descendants(A) = {B, C, D, E}; descendants(B) = {C, D, E};
    descendants(D) = {E}; descendants(E) = {}.
    """
    ex = DAGExecutor()
    ex.edges = [
        WorkflowEdge(from_node="A", to_node="B"),
        WorkflowEdge(from_node="B", to_node="C"),
        WorkflowEdge(from_node="B", to_node="D"),
        WorkflowEdge(from_node="D", to_node="E"),
    ]
    assert ex._transitive_descendants("A") == {"B", "C", "D", "E"}
    assert ex._transitive_descendants("B") == {"C", "D", "E"}
    assert ex._transitive_descendants("D") == {"E"}
    assert ex._transitive_descendants("E") == set()


def test_transitive_descendants_handles_diamond_without_double_visit():
    """A -> B -> D
         \\-> C -> D
    descendants(A) should yield {B, C, D} with no infinite loop /
    duplicate work."""
    ex = DAGExecutor()
    ex.edges = [
        WorkflowEdge(from_node="A", to_node="B"),
        WorkflowEdge(from_node="A", to_node="C"),
        WorkflowEdge(from_node="B", to_node="D"),
        WorkflowEdge(from_node="C", to_node="D"),
    ]
    assert ex._transitive_descendants("A") == {"B", "C", "D"}


# ---------------------------------------------------------------------------
# _mark_descendants_failed (status mutation)
# ---------------------------------------------------------------------------


def _make_executor_with_nodes(graph: list[tuple[str, str]]) -> DAGExecutor:
    """Build an executor with stub Node objects for each unique id."""
    from spectra_sherpa.app.services.dag.node_base import Node, NodeStatus

    class _StubNode(Node):
        def __init__(self, node_id: str) -> None:  # type: ignore[no-untyped-def]
            self.node_id = node_id
            self.status = NodeStatus.PENDING
            self.error_message: str | None = None

        async def execute(self, **kwargs):  # pragma: no cover - unused in unit tests
            return {}

    ex = DAGExecutor()
    ex.edges = [WorkflowEdge(from_node=f, to_node=t) for f, t in graph]
    ids = {n for edge in graph for n in edge}
    for nid in ids:
        ex.nodes[nid] = _StubNode(nid)  # type: ignore[assignment]
    return ex


def test_mark_descendants_failed_sets_downstream_error_with_reason():
    from spectra_sherpa.app.services.dag.node_base import NodeStatus

    ex = _make_executor_with_nodes([("A", "B"), ("B", "C"), ("B", "D")])
    ex.nodes["A"].status = NodeStatus.ERROR  # the failing node itself
    ex.nodes["A"].error_message = "boom"

    ex._mark_descendants_failed("A")

    for downstream in ("B", "C", "D"):
        assert ex.nodes[downstream].status == NodeStatus.ERROR
        assert "upstream" in (ex.nodes[downstream].error_message or "").lower()
        assert "'A'" in (ex.nodes[downstream].error_message or "")
    # The originating node's message is preserved.
    assert ex.nodes["A"].error_message == "boom"


def test_mark_descendants_failed_preserves_already_completed_nodes():
    from spectra_sherpa.app.services.dag.node_base import NodeStatus

    # A -> B (completed earlier) -> C (pending).
    # If B was already completed before A's later failure, its status must
    # not be overwritten to ERROR.
    ex = _make_executor_with_nodes([("A", "B"), ("B", "C")])
    ex.nodes["B"].status = NodeStatus.COMPLETED
    ex._mark_descendants_failed("A")
    assert ex.nodes["B"].status == NodeStatus.COMPLETED
    assert ex.nodes["C"].status == NodeStatus.ERROR


def test_mark_descendants_failed_skips_nodes_already_in_error():
    from spectra_sherpa.app.services.dag.node_base import NodeStatus

    ex = _make_executor_with_nodes([("A", "B"), ("B", "C")])
    ex.nodes["B"].status = NodeStatus.ERROR
    ex.nodes["B"].error_message = "B failed on its own"
    ex._mark_descendants_failed("A")
    # B's original message must not be overwritten by "upstream A failed"
    assert ex.nodes["B"].error_message == "B failed on its own"
    # C downstream of A (via B) still gets marked
    assert ex.nodes["C"].status == NodeStatus.ERROR


# An end-to-end test through ``executor.execute()`` would require
# registering real Node subclasses with full NodeMetadata (input/output
# port specs the validator accepts), which adds a substantial fixture
# surface for a one-line behaviour change. The five unit tests above
# pin the contract directly:
#   * descendants are discovered correctly across linear / branching /
#     diamond graphs;
#   * status is overwritten only when the downstream is still PENDING /
#     RUNNING, never when it had its own COMPLETED / ERROR outcome.
# The call sites in DAGExecutor.execute (the except blocks for
# asyncio.TimeoutError and the broader Exception) are a single line
# each, so any regression would be a code-review catch.
