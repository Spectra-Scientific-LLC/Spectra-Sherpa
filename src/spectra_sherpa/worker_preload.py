"""Clean Linux forkserver preload: import code once, never accept user work.

This module must live outside app.services.dag: importing that package already
loads NumPy. Limit native import-time thread creation before loading the stack,
so the dedicated loader remains single-threaded at every fork. Task processes
remain disposable; none of their mutations can flow back into this loader.
"""

import os
import sys


def _reset_child_random_state() -> None:
    # Fresh spawn provided independent unseeded NumPy streams. Preserve that
    # behavior; node-level explicit random_state values remain unchanged.
    import numpy as np

    np.random.seed()


def _preload() -> None:
    for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[variable] = "1"

    import spectra_sherpa.app.services.dag.nodes  # noqa: F401

    # A newly added library must not silently make forking this loader unsafe.
    if len(os.listdir("/proc/self/task")) != 1:
        raise RuntimeError("Scientific forkserver preload started native threads")
    os.register_at_fork(after_in_child=_reset_child_random_state)


# Native packaging/module discovery must remain safe on every supported OS.
if sys.platform == "linux" and not getattr(sys, "frozen", False):
    _preload()
