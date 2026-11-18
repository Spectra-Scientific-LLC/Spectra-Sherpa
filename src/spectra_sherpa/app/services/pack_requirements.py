"""Application transport for retained pack binding admission."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from spectra_sherpa.app.services.dag.pack_requirements import (
    PackBindingAdmissionError,
    capture_pack_graph_binding,
    require_matching_pack_binding,
)
from spectra_sherpa.core.pack_manifest import PackManifestError
from spectra_sherpa.core.pack_requirements import PackGraphBinding


def read_stored_pack_binding(value: Any) -> PackGraphBinding | None:
    """Read persisted JSON facts without attributing them to today's registry."""
    if value is None:
        return None
    import json

    from spectra_sherpa.core.pack_requirements import parse_pack_graph_binding

    return parse_pack_graph_binding(
        json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def require_stored_pack_binding(nodes: Sequence[Mapping[str, Any]], value: Any) -> PackGraphBinding:
    """Application boundary with structured, public-safe compatibility refusals."""
    from fastapi import HTTPException

    try:
        retained = read_stored_pack_binding(value)
        return require_matching_pack_binding(nodes, retained)
    except PackBindingAdmissionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "pack_binding_unavailable",
                "message": "This saved graph requires its recorded pack builds and execution contracts.",
                "nodes": [
                    {
                        "node_id": problem.node_id,
                        "node_type": problem.node_type,
                        "reason": problem.reason,
                        "retained": problem.retained.model_dump(mode="json") if problem.retained else None,
                        "current": problem.current.model_dump(mode="json") if problem.current else None,
                    }
                    for problem in exc.problems
                ],
            },
        ) from exc
    except (TypeError, ValueError, RecursionError) as exc:
        raise HTTPException(status_code=409, detail={"code": "invalid_pack_binding"}) from exc


def capture_saved_pack_binding(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Capture before mutation, with a bounded HTTP refusal for unsavable bindings."""
    from fastapi import HTTPException
    from pydantic import ValidationError

    try:
        binding = capture_pack_graph_binding(nodes)
    except (PackManifestError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail={"code": "pack_binding_not_retainable"}) from exc
    return binding.model_dump(mode="json") if binding.nodes else None


def require_saved_workflow_pack_binding(workflow: Any) -> PackGraphBinding:
    """Check an existing recipe before export source reads or node callbacks."""
    return require_matching_pack_binding(
        [{"node_id": node.node_id, "node_type": node.node_type} for node in workflow.nodes],
        read_stored_pack_binding(getattr(workflow, "pack_binding", None)),
    )
