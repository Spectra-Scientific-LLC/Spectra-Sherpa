"""Worker-side helper for the spawned custom-node test; importable by name."""

import asyncio
import os

import numpy as np


def run_despike():
    import spectra_sherpa.sdk as ss
    from spectra_sherpa.app.services.dag.node_base import node_registry

    values = np.tile(np.sin(np.linspace(0, 6, 50)), (3, 1))
    values[1, 20] += 5
    node = node_registry.create_node("user.whitaker-hayes.despike", "worker", {})
    result = asyncio.run(node.run(ss.data.from_array(values, x=np.linspace(400, 1800, 50), units="cm-1")))
    return os.getpid(), result.outputs["default"].X.round(12).tolist()
