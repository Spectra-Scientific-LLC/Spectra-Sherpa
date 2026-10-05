"""Offline qualification inside the frozen backend, using disposable cache only."""

from __future__ import annotations

import importlib.metadata
import json
import os
import sys
import tempfile
from pathlib import Path


def _offline_cache(output: Path) -> Path:
    """Create a disposable cache owned by the receipt's parent process."""
    return Path(tempfile.mkdtemp(prefix="sherpa-hitran-offline-", dir=output.parent))


def check(output: Path) -> None:
    # This mode runs in a dedicated process. Any attempted connection is a failure,
    # including a connection from an imported client; no real key or cache is read.
    def refuse_network(event, args):
        if event == "socket.connect":
            raise RuntimeError("HITRAN offline qualification attempted a network connection")

    sys.addaudithook(refuse_network)
    sys.dont_write_bytecode = True
    output = output.resolve()
    original = Path.cwd()
    # The parent verifier owns output.parent and removes it after this frozen
    # process exits. HAPI2 opens a second provenance SQLite database during
    # import; on Windows that file can remain locked until process teardown.
    # Deleting this cache inside the same process would fail with WinError 32.
    cache = _offline_cache(output)
    try:
        os.chdir(cache)
        import numba

        # Match the application's profile-owned cache, not a prior build's
        # user-global cache. HAPI2 imports cached @njit functions immediately.
        numba.config.CACHE_DIR = str(cache / "numba-cache")
        import hapi
        import hapi2
        import numpy as np
        from hapi2.opacity.lbl.numba.hum1_wei_numba import hum1_wei
        from scipy.special import wofz
        from sqlalchemy import text

        try:
            values = hapi.PROFILE_LORENTZ(0.0, 1.0, 0.0, np.array([-1.0, 0.0, 1.0]))
            np.testing.assert_allclose(values, [1 / (2 * np.pi), 1 / np.pi, 1 / (2 * np.pi)])
            jit_value = complex(*hum1_wei(0.0, 1.0))
            np.testing.assert_allclose(jit_value, wofz(1j), rtol=1e-6, atol=1e-10)
            result = hapi2.session.execute(text("select 1")).scalar()
            if result != 1 or hapi2.SETTINGS.get("api_key") is not None:
                raise RuntimeError("HAPI2 offline cache qualification failed")
            # Public entry points used by the application's HITRAN integration.
            for name in ("fetch_molecules", "fetch_transitions", "fetch_cross_sections", "storage2cache"):
                if not callable(getattr(hapi2, name, None)):
                    raise RuntimeError(f"HAPI2 runtime entry point missing: {name}")
            receipt = {
                "versions": {name: importlib.metadata.version(name) for name in ("hitran-api", "hitran-api2")},
                "lorentz_profile": values.tolist(),
                "sqlite_query": result,
                "jit_profile": [jit_value.real, jit_value.imag],
                "offline": True,
            }
        finally:
            hapi2.session.close()
            hapi2.VARSPACE["engine"].dispose()
    finally:
        os.chdir(original)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    check(Path(sys.argv[1]))
