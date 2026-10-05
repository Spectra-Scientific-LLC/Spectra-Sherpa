"""Process pool infrastructure for DAG node offloading."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import pickle
import tempfile
import threading
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from spectra_sherpa.core.execution_runtime import ExecutionRuntime

from .node_base import NodeResult, node_registry, resolved_runtime_worker_capabilities
from .transport import reject_spectrochempy_transport

logger = logging.getLogger(__name__)


def _isolated_call(output_path: str, function, args: tuple) -> None:
    """Private child-to-parent transport; never reads customer-supplied pickle."""
    parent = multiprocessing.parent_process()
    if parent is not None:
        # The sentinel is an OS-owned handle to our actual spawning process,
        # not a PID lookup. Cover hard backend exits as well as graceful cleanup.
        def stop_when_parent_exits() -> None:
            from multiprocessing.connection import wait

            wait([parent.sentinel])
            os._exit(1)

        threading.Thread(target=stop_when_parent_exits, daemon=True, name="scientific-worker-owner").start()
    try:
        payload = (True, function(*args))
    except Exception as exc:
        payload = (False, exc)
    with open(output_path, "wb") as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)


class IsolatedWorkerPool:
    """Bound concurrency with a separately owned, cancellable process per call.

    A ProcessPoolExecutor future cannot stop a running task. Here timeout and
    cancellation reap precisely that task before releasing its capacity slot.
    Fresh spawn costs more than reusable workers, but cannot leave abandoned
    computations consuming the shared application's worker capacity.
    """

    def __init__(self, max_workers: int):
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._slots = asyncio.Semaphore(max_workers)
        self._context = multiprocessing.get_context("spawn")
        self._active = set()
        self._closed = False

    async def run(self, function, *args, timeout: float):
        # Queue time counts against the same budget as computation.
        async with asyncio.timeout(timeout):
            async with self._slots:
                if self._closed:
                    raise RuntimeError("Worker pool is shut down")
                with tempfile.TemporaryDirectory(prefix="sherpa-worker-") as directory:
                    output = Path(directory) / "result"
                    process = self._context.Process(target=_isolated_call, args=(str(output), function, args))
                    try:
                        process.start()
                        self._active.add(process)
                        while process.is_alive():
                            await asyncio.sleep(0.02)
                        process.join()
                        if process.exitcode != 0 or not output.exists():
                            raise RuntimeError("Scientific worker exited without a result")
                        # Only this process's private child can produce this file.
                        with output.open("rb") as stream:
                            success, result = pickle.load(stream)  # nosec B301: own spawned child, private 0700 tempdir
                        if not success:
                            raise result
                        return result
                    finally:
                        # No await here: cancellation cannot interrupt reaping.
                        # kill() avoids waiting for arbitrary native cleanup or
                        # a signal handler in a timed-out scientific library.
                        if process.pid is not None:
                            if process.is_alive():
                                process.kill()
                            process.join()
                        self._active.discard(process)
                        process.close()

    def shutdown(self, wait=True, *, cancel_futures=False):
        self._closed = True
        for process in tuple(self._active):
            if process.is_alive():
                process.kill()
            process.join()


_default_process_pool: Optional[ProcessPoolExecutor | IsolatedWorkerPool] = None
_SUPPORTED_WORKER_CAPABILITIES = frozenset({"read_dataset", "read_model_artifact", "read_canonical_fitted_artifact"})


class WorkerImplementationUnavailable(RuntimeError):
    """The spawned registry cannot resolve a requested implementation."""


@dataclass(frozen=True)
class WorkerExecutionContext:
    """Trusted, serializable least-privilege context for one worker call."""

    execution_id: str
    runtime: ExecutionRuntime
    capabilities: tuple[str, ...] = ()
    # The main process sets this immediately before handing the trusted context
    # to a spawned worker. It is evidence only, never an authorization input.
    origin_pid: int = 0


def set_default_pool(pool: Optional[ProcessPoolExecutor | IsolatedWorkerPool]) -> None:
    """Set the module-level default ProcessPoolExecutor.

    Called once during app lifespan startup so that every ``DAGExecutor()``
    created afterwards automatically offloads CPU-bound nodes.
    """
    global _default_process_pool
    _default_process_pool = pool


def get_default_pool() -> Optional[ProcessPoolExecutor | IsolatedWorkerPool]:
    """Return the current module-level default ProcessPoolExecutor."""
    return _default_process_pool


def _run_node_in_worker(
    node_type: str,
    node_id: str,
    parameters: dict,
    args: tuple,
    kwargs: dict,
    worker_context: WorkerExecutionContext | None = None,
) -> NodeResult:
    """Execute a node in a worker process.

    Top-level function (required for pickling by ProcessPoolExecutor).
    Creates a fresh node instance in the worker process and runs it via
    a throwaway event loop (the node's execute() is async-declared but
    does only CPU-bound work — no real I/O awaits).
    """
    reject_spectrochempy_transport(args, boundary="worker input")
    reject_spectrochempy_transport(kwargs, boundary="worker input")
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

    try:
        node = node_registry.create_node(node_type, node_id, parameters)
    except (KeyError, ValueError) as exc:
        raise WorkerImplementationUnavailable(f"implementation_unavailable: {node_type}") from exc
    admitted_capabilities = frozenset(node.metadata.resolved_required_worker_capabilities() if node.metadata else ())
    unknown_capabilities = admitted_capabilities - _SUPPORTED_WORKER_CAPABILITIES
    if unknown_capabilities:
        raise PermissionError(f"unsupported worker capabilities: {sorted(unknown_capabilities)}")
    required_capabilities = frozenset(resolved_runtime_worker_capabilities(node))
    if required_capabilities:
        if worker_context is None:
            raise PermissionError("worker execution context is required")
        missing_capabilities = required_capabilities - frozenset(worker_context.capabilities)
        if missing_capabilities:
            raise PermissionError(f"worker capabilities are missing: {sorted(missing_capabilities)}")
    if worker_context is None:
        node.bind_execution_runtime(ExecutionRuntime())
    else:
        node.bind_execution_runtime(worker_context.runtime)
    if kwargs:
        if list(kwargs.keys()) == ["default"]:
            result = asyncio.run(node.run(kwargs["default"]))
        else:
            result = asyncio.run(node.run(**kwargs))
    else:
        result = asyncio.run(node.run(*args))
    # This reserved diagnostic is produced only inside the child process.
    # It lets the M3 cross-machine procedure distinguish a real spawned
    # execution from the executor's deliberate in-process fallback.
    result.diagnostics["worker_execution"] = {
        "mode": "spawned_worker",
        "worker_pid": os.getpid(),
        "origin_pid": worker_context.origin_pid if worker_context is not None else 0,
        "execution_id": worker_context.execution_id if worker_context is not None else None,
    }
    reject_spectrochempy_transport(result, boundary="worker output")
    return result
