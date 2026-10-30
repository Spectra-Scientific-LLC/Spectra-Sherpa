"""Process pool infrastructure for DAG node offloading."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import pickle
import sys
import tempfile
import threading
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from time import perf_counter
from typing import Optional

from spectra_sherpa.core.execution_runtime import ExecutionRuntime

from .node_base import NodeResult, node_registry, resolved_runtime_worker_capabilities
from .transport import reject_spectrochempy_transport

logger = logging.getLogger(__name__)


def _watch_parent() -> None:
    """Exit when the actual owning process exits, including hard backend exits."""
    parent = multiprocessing.parent_process()
    if parent is not None:
        # The sentinel is an OS-owned handle to our actual spawning process,
        # not a PID lookup. Cover hard backend exits as well as graceful cleanup.
        def stop_when_parent_exits() -> None:
            from multiprocessing.connection import wait

            wait([parent.sentinel])
            os._exit(1)

        threading.Thread(target=stop_when_parent_exits, daemon=True, name="scientific-worker-owner").start()


def _isolated_call(output_path: str, function, args: tuple) -> None:
    """Private child-to-parent transport; never reads customer-supplied pickle."""
    _watch_parent()
    try:
        payload = (True, function(*args))
    except Exception as exc:
        payload = (False, exc)
    with open(output_path, "wb") as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)


def _workflow_call(directory: str, control) -> None:
    """Serve sequential nodes for exactly one execution, then be discarded.

    Control carries only readiness notifications. Pickles are private files
    written by the owning API process or this child, never customer files.
    Each node still creates its own instance, runtime binding and event loop.
    """
    _watch_parent()
    transport_directory = Path(directory)
    try:
        while control.recv():
            with (transport_directory / "request").open("rb") as stream:
                function, args = pickle.load(stream)  # nosec B301: own parent, private 0700 directory
            try:
                # Fresh processes previously gave nodes independent unseeded
                # streams. Do not make later nodes depend on earlier RNG use.
                import random

                import numpy as np

                random.seed()
                np.random.seed()
                payload = (True, function(*args))
            except Exception as exc:
                payload = (False, exc)
            with (transport_directory / "result").open("wb") as stream:
                pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)
            control.send(True)
            del function, args, payload
    except EOFError:
        pass
    finally:
        control.close()


class _WorkflowWorker:
    """Lazy, single-execution lease; no reuse after failure or scope exit."""

    def __init__(self, pool):
        self._pool = pool
        self._process = None
        self._control = None
        self._directory = None
        self._owns_slot = False
        self._closed = False
        self._busy = False

    async def _start(self):
        await self._pool._slots.acquire()
        self._owns_slot = True
        if self._closed or self._pool._closed:
            raise RuntimeError("Workflow worker is shut down")
        self._directory = tempfile.TemporaryDirectory(prefix="sherpa-workflow-")
        self._control, child_control = self._pool._context.Pipe()
        self._process = self._pool._context.Process(target=_workflow_call, args=(self._directory.name, child_control))
        try:
            self._process.start()
            self._pool._active.add(self._process)
        finally:
            child_control.close()

    async def run(self, function, *args, timeout: float):
        if self._closed or self._pool._closed:
            raise RuntimeError("Workflow worker is shut down")
        if self._busy:
            raise RuntimeError("Workflow worker requires sequential node execution")
        self._busy = True
        started = perf_counter()
        try:
            # Includes queueing, first-node bootstrap and result transport.
            async with asyncio.timeout(timeout):
                if self._process is None:
                    await self._start()
                transport_directory = Path(self._directory.name)
                with (transport_directory / "request").open("wb") as stream:
                    pickle.dump((function, args), stream, protocol=pickle.HIGHEST_PROTOCOL)
                try:
                    # A dead peer can surface at send, poll (Windows named
                    # pipes), or recv. Keep one failure boundary for all three.
                    self._control.send(True)
                    while True:
                        if self._closed or self._pool._closed:
                            raise RuntimeError("Workflow worker is shut down")
                        if self._control.poll():
                            break
                        if not self._process.is_alive():
                            raise RuntimeError("Scientific worker exited without a result")
                        await asyncio.sleep(0.005)
                    self._control.recv()
                except (EOFError, OSError) as exc:
                    raise RuntimeError("Scientific worker exited without a result") from exc
                with (transport_directory / "result").open("rb") as stream:
                    success, result = pickle.load(stream)  # nosec B301: own child, private 0700 directory
                if not success:
                    raise result
                if isinstance(result, NodeResult) and "worker_execution" in result.diagnostics:
                    result.diagnostics["worker_execution"].update(
                        lifetime="workflow", dispatch_seconds=perf_counter() - started
                    )
                return result
        except BaseException:
            # A failed or cancelled child cannot serve another node, even if
            # a caller catches the exception. Never retry in the API process.
            self.close()
            raise
        finally:
            self._busy = False

    def close(self):
        self._closed = True
        self.release_idle_worker()

    def release_idle_worker(self):
        """Release resources; a still-open outer scope may lazily start again."""
        if self._process is not None:
            if self._process.pid is not None:
                if self._process.is_alive():
                    self._process.kill()
                self._process.join()
            self._pool._active.discard(self._process)
            self._process.close()
            self._process = None
        if self._control is not None:
            self._control.close()
            self._control = None
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
        if self._owns_slot:
            self._pool._slots.release()
            self._owns_slot = False


class IsolatedWorkerPool:
    """Bound concurrency with separately owned, cancellable processes.

    A ProcessPoolExecutor future cannot stop a running task. Here timeout and
    cancellation reap precisely that task before releasing its capacity slot.
    Each workflow gets a fresh process; sequential nodes share only that
    execution's worker. Standalone calls still get a fresh process per call.
    No process or user state survives into another workflow execution.
    On Linux a clean forkserver preloads the scientific registry once; it never
    executes a user task or inherits the API process's sessions/data.
    """

    def __init__(self, max_workers: int):
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._slots = asyncio.Semaphore(max_workers)
        method = "spawn"
        if sys.platform == "linux" and not getattr(sys, "frozen", False):
            # Fork only the dedicated clean loader, never the threaded API.
            # Keep native desktop's existing spawn bootstrap unchanged.
            method = "forkserver"
            multiprocessing.set_forkserver_preload(["spectra_sherpa.worker_preload"])
        self._context = multiprocessing.get_context(method)
        self._active = set()
        self._closed = False
        self._workflow: ContextVar[_WorkflowWorker | None] = ContextVar("scientific_workflow_worker", default=None)

    @asynccontextmanager
    async def workflow(self):
        """Own a lazily started worker until this execution leaves its scope."""
        previous = self._workflow.get()
        if previous is not None and not previous._closed:
            if previous._busy:
                raise RuntimeError("Cannot nest workflow execution during an active node dispatch")
            # A completed-node callback can execute another workflow. Do not
            # retain the outer capacity slot while awaiting that inner scope.
            # Its state is discarded, not shared with the inner execution.
            previous.release_idle_worker()
        worker = _WorkflowWorker(self)
        token = self._workflow.set(worker)
        try:
            yield
        finally:
            replacement = self._workflow.get()
            if replacement is not None and replacement is not worker:
                replacement.close()
            worker.close()
            self._workflow.reset(token)

    def recover_optional_projection_failure(self):
        """A failed display child is discarded, never retried in the API.

        The next computational dispatch gets a fresh isolated worker under
        the same execution scope. Global shutdown and cancellation still win.
        """
        worker = self._workflow.get()
        if worker is not None and worker._closed and not self._closed:
            self._workflow.set(_WorkflowWorker(self))

    async def run(self, function, *args, timeout: float):
        workflow = self._workflow.get()
        if workflow is not None:
            return await workflow.run(function, *args, timeout=timeout)
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
    request_id: str | None = None


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


def _worker_node(node_type: str, node_id: str, parameters: dict, worker_context: WorkerExecutionContext | None):
    """One capability-checked construction path for execution and projection."""
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
    admitted = frozenset(node.metadata.resolved_required_worker_capabilities() if node.metadata else ())
    if admitted - _SUPPORTED_WORKER_CAPABILITIES:
        raise PermissionError(f"unsupported worker capabilities: {sorted(admitted - _SUPPORTED_WORKER_CAPABILITIES)}")
    required = frozenset(resolved_runtime_worker_capabilities(node))
    if required:
        if worker_context is None:
            raise PermissionError("worker execution context is required")
        missing = required - frozenset(worker_context.capabilities)
        if missing:
            raise PermissionError(f"worker capabilities are missing: {sorted(missing)}")
    node.bind_execution_runtime(ExecutionRuntime() if worker_context is None else worker_context.runtime)
    return node


def _with_worker_logging(function):
    @wraps(function)
    def logged(*args, **kwargs):
        from spectra_sherpa.core.diagnostic_context import diagnostic_identifier, use_request_id
        from spectra_sherpa.core.diagnostic_logging import configure_logging

        configure_logging()
        context = kwargs.get("worker_context", args[5] if len(args) > 5 else None)
        node_id = diagnostic_identifier(kwargs.get("node_id", args[1] if len(args) > 1 else "unknown"))
        execution_id = context.execution_id if context is not None else None
        started = perf_counter()
        with use_request_id(context.request_id if context is not None else None):
            logger.info("NODE_WORKER_START node_id=%s execution_id=%s", node_id, execution_id)
            try:
                result = function(*args, **kwargs)
            except BaseException as exc:
                logger.warning(
                    "NODE_WORKER_FAILED node_id=%s execution_id=%s error_type=%s duration_ms=%.1f",
                    node_id,
                    execution_id,
                    type(exc).__name__,
                    (perf_counter() - started) * 1000,
                )
                raise
            logger.info(
                "NODE_WORKER_DONE node_id=%s execution_id=%s duration_ms=%.1f",
                node_id,
                execution_id,
                (perf_counter() - started) * 1000,
            )
            return result

    return logged


@_with_worker_logging
def _run_population_in_worker(node_type, node_id, parameters, outputs, inputs, worker_context):
    """Apply a declared display operation in the same isolated workflow lease."""
    reject_spectrochempy_transport((outputs, inputs), boundary="population worker input")
    node = _worker_node(node_type, node_id, parameters, worker_context)
    projector = getattr(node, "project_population", None)
    if projector is None:
        return {}
    try:
        result = asyncio.run(projector(outputs, inputs))
    except Exception as exc:
        # An honest display refusal is not a worker failure: keep the lease
        # healthy for subsequent computational nodes in this workflow.
        result = {"__projection_refusal": f"{type(exc).__name__}: {exc}"}
    reject_spectrochempy_transport(result, boundary="population worker output")
    return result


@_with_worker_logging
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
    registry_started = perf_counter()
    reject_spectrochempy_transport(args, boundary="worker input")
    reject_spectrochempy_transport(kwargs, boundary="worker input")
    node = _worker_node(node_type, node_id, parameters, worker_context)
    execution_started = perf_counter()
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
        "start_method": multiprocessing.get_start_method(),
        "registry_seconds": execution_started - registry_started,
        "execution_seconds": perf_counter() - execution_started,
        "worker_pid": os.getpid(),
        "origin_pid": worker_context.origin_pid if worker_context is not None else 0,
        "execution_id": worker_context.execution_id if worker_context is not None else None,
    }
    reject_spectrochempy_transport(result, boundary="worker output")
    return result
