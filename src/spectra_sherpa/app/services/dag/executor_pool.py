"""Process pool infrastructure for DAG node offloading."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor
from typing import Optional

from .node_base import NodeResult, node_registry

logger = logging.getLogger(__name__)

_default_process_pool: Optional[ProcessPoolExecutor] = None


def set_default_pool(pool: Optional[ProcessPoolExecutor]) -> None:
    """Set the module-level default ProcessPoolExecutor.

    Called once during app lifespan startup so that every ``DAGExecutor()``
    created afterwards automatically offloads CPU-bound nodes.
    """
    global _default_process_pool
    _default_process_pool = pool


def get_default_pool() -> Optional[ProcessPoolExecutor]:
    """Return the current module-level default ProcessPoolExecutor."""
    return _default_process_pool


def _run_node_in_worker(
    node_type: str,
    node_id: str,
    parameters: dict,
    args: tuple,
    kwargs: dict,
) -> NodeResult:
    """Execute a node in a worker process.

    Top-level function (required for pickling by ProcessPoolExecutor).
    Creates a fresh node instance in the worker process and runs it via
    a throwaway event loop (the node's execute() is async-declared but
    does only CPU-bound work — no real I/O awaits).
    """
    # Import node modules to populate the registry in the worker process.
    # These are guarded at module scope in the main process by conftest /
    # app startup, but spawned workers start fresh.
    import spectra_sherpa.app.services.dag.nodes.classification  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401

    try:
        import spectra_sherpa.app.services.dag.nodes.output  # noqa: F401
    except Exception:
        pass  # output nodes are rarely offloaded

    node = node_registry.create_node(node_type, node_id, parameters)
    if kwargs:
        if list(kwargs.keys()) == ["default"]:
            result = asyncio.run(node.run(kwargs["default"]))
        else:
            result = asyncio.run(node.run(**kwargs))
    else:
        result = asyncio.run(node.run(*args))
    return result
