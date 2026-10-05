#!/usr/bin/env python3
"""Exercise default Workbench startup and deterministic canonical execution."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import socket
import sys
import threading
from pathlib import Path
from typing import Any

import numpy as np

# Current-release runtime qualification authority. Historical R1 evidence
# remains frozen at the node count recorded by its originating commit.
EXPECTED_NODE_COUNT = 101
EXPECTED_OPTIONAL_OPERATION_COUNT = 3
EXPECTED_BASE_OPERATION_COUNT = EXPECTED_NODE_COUNT - EXPECTED_OPTIONAL_OPERATION_COUNT
_NETWORK_ATTEMPTS: list[str] = []


def _install_network_guard() -> None:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_socketpair = socket.socketpair
    socketpair_scope = threading.local()

    def blocked_connect(instance: socket.socket, address: object) -> None:
        if getattr(socketpair_scope, "active", False):
            original_connect(instance, address)
            return
        _NETWORK_ATTEMPTS.append(f"connect:{address!r}")
        raise RuntimeError(f"Workbench runtime attempted network access: {address!r}")

    def blocked_connect_ex(instance: socket.socket, address: object) -> int:
        if getattr(socketpair_scope, "active", False):
            return original_connect_ex(instance, address)
        blocked_connect(instance, address)
        return 1

    def blocked_getaddrinfo(*args: object, **kwargs: object) -> list[object]:
        del kwargs
        _NETWORK_ATTEMPTS.append(f"dns:{args!r}")
        raise RuntimeError(f"Workbench runtime attempted DNS resolution: {args!r}")

    def guarded_socketpair(*args: object, **kwargs: object) -> tuple[socket.socket, socket.socket]:
        # On Windows, CPython implements socketpair() with a private loopback
        # listener and one connect call.  That transport is an in-process
        # event-loop wakeup mechanism, not application network access.  Scope
        # the exception to the stdlib call itself so arbitrary loopback,
        # outbound, and DNS access remain fail-closed in every other callsite.
        previous = getattr(socketpair_scope, "active", False)
        socketpair_scope.active = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            socketpair_scope.active = previous

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    socket.socketpair = guarded_socketpair  # type: ignore[assignment]
    socket.getaddrinfo = blocked_getaddrinfo  # type: ignore[assignment]


def _result_digest(value: Any) -> str:
    if isinstance(value, dict) and "default" in value:
        value = value["default"]
    data = getattr(value, "data", value)
    if hasattr(data, "magnitude"):
        data = data.magnitude
    array = np.asarray(data, dtype=np.float64)
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


async def _execute_once() -> str:
    from spectra_sherpa.app.services.dag.executor import DAGExecutor
    from spectra_sherpa.app.services.dag.executor_types import WorkflowNode

    executor = DAGExecutor(process_pool=None)
    executor.add_node(
        WorkflowNode(
            node_id="curve",
            node_type="data.synthetic_curve",
            parameters={
                "curve_type": "gaussian",
                "n_points": 32,
                "max_concentration": 2.0,
                "center": 0.4,
                "width": 0.12,
                "duration_seconds": 8.0,
            },
        )
    )
    return _result_digest((await executor.execute())["curve"])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scp", choices=("absent", "available"), required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    expected_ready = args.scp == "available"
    home = Path.home()
    scp_home = home / ".spectrochempy"
    if not expected_ready and scp_home.exists():
        raise RuntimeError("the isolated base Workbench HOME is not pristine")

    try:
        importlib.metadata.version("spectrochempy")
        distribution_available = True
    except importlib.metadata.PackageNotFoundError:
        distribution_available = False
    spec_available = importlib.util.find_spec("spectrochempy") is not None
    if distribution_available != expected_ready or spec_available != expected_ready:
        raise RuntimeError(
            "SpectroChemPy distribution/import availability differs from the requested Workbench profile"
        )
    if not expected_ready:
        try:
            importlib.import_module("spectrochempy")
        except ModuleNotFoundError as exc:
            if exc.name != "spectrochempy":
                raise
        else:
            raise RuntimeError("the base Workbench unexpectedly imported SpectroChemPy")
    _install_network_guard()

    from fastapi.testclient import TestClient

    import spectra_sherpa.app.services.dag.nodes  # noqa: F401
    from spectra_sherpa.app.main import app
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.services.dag.node_catalog_contract import dependency_readiness

    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        if response.status_code != 200:
            raise RuntimeError(f"Workbench health failed: {response.status_code}: {response.text[:500]}")

    metadata = node_registry.list_nodes()
    if len(metadata) != EXPECTED_NODE_COUNT:
        raise RuntimeError(f"expected {EXPECTED_NODE_COUNT} canonical nodes, found {len(metadata)}")
    if any(item.resolved_execution_contract() is None for item in metadata):
        raise RuntimeError("the Workbench catalog contains an uncontracted node")
    scp_operations = {item.node_type for item in metadata if item.requires_scp}
    if len(scp_operations) != EXPECTED_OPTIONAL_OPERATION_COUNT:
        raise RuntimeError(f"expected three optional operations, found {sorted(scp_operations)}")
    base_ready = [item.node_type for item in metadata if not item.requires_scp and dependency_readiness(item).ready]
    if len(base_ready) != EXPECTED_BASE_OPERATION_COUNT:
        raise RuntimeError(f"expected {EXPECTED_BASE_OPERATION_COUNT} ready base operations, found {len(base_ready)}")
    readiness = {item.node_type: dependency_readiness(item).ready for item in metadata if item.requires_scp}
    if any(ready != expected_ready for ready in readiness.values()):
        raise RuntimeError(f"SCP readiness differs from the {args.scp!r} profile: {readiness}")
    if any(name == "spectrochempy" or name.startswith("spectrochempy.") for name in sys.modules):
        raise RuntimeError("Workbench startup eagerly imported the optional SpectroChemPy runtime")

    first = asyncio.run(_execute_once())
    reproduced = asyncio.run(_execute_once())
    if first != reproduced:
        raise RuntimeError("default Workbench canonical execution is not deterministic")
    if _NETWORK_ATTEMPTS:
        raise RuntimeError(f"Workbench runtime attempted network access: {_NETWORK_ATTEMPTS}")
    if not expected_ready and scp_home.exists():
        raise RuntimeError("base Workbench startup created the SpectroChemPy home directory")

    print(
        json.dumps(
            {
                "profile": "R4" if expected_ready else "R3",
                "status": "passed",
                "health": 200,
                "node_count": len(metadata),
                "base_ready_count": len(base_ready),
                "spectrochempy_distribution": "installed" if distribution_available else "absent",
                "spectrochempy_import_spec": "available" if spec_available else "absent",
                "spectrochempy_home_created": scp_home.exists(),
                "network_attempts": list(_NETWORK_ATTEMPTS),
                "scp_operations": sorted(scp_operations),
                "result_digest": first,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
