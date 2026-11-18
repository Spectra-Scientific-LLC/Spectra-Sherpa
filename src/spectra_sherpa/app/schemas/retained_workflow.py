"""Read-only projection of retained workflow identity availability."""

from pydantic import Field, computed_field

from spectra_sherpa.core.pack_manifest import Frozen
from spectra_sherpa.core.retained_graph import RetainedGraph


class RetainedWorkflowInspection(Frozen):
    graph: RetainedGraph
    unavailable_node_ids: tuple[str, ...] = Field(default_factory=tuple)
    binding_unavailable: bool = False

    @computed_field
    @property
    def read_only(self) -> bool:
        return bool(self.unavailable_node_ids or self.binding_unavailable)
