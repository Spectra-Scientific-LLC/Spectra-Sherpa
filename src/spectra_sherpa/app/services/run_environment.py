"""Best-effort environment evidence captured at run record creation.

This records installed package versions and loaded numerical libraries, not a
promise of deterministic replay or a retrospective reconstruction of old runs.
"""

from __future__ import annotations

import json
import platform
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

NUMERICAL_DISTRIBUTIONS = (
    "numpy",
    "scipy",
    "scikit-learn",
    "pandas",
    "spectra-sherpa",
    "spectrasherpa-server",
    "spectrochempy",
)


def _build_commit() -> str | None:
    try:
        if hasattr(sys, "_MEIPASS"):
            value = json.loads((Path(sys._MEIPASS) / "provenance.json").read_text())["build_commit"]
        else:
            value = Path("/usr/local/share/spectra/source-revision").read_text().strip()
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) and value != "0" * 40:
            return value
    except Exception:
        pass
    return None


def build_run_environment_snapshot() -> dict[str, Any]:
    """Return evidence with explicit unavailable states; do not block execution."""
    packages = {}
    for name in NUMERICAL_DISTRIBUTIONS:
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "not installed"
        except Exception:
            packages[name] = "unavailable"
    try:
        python_version = platform.python_version()
    except Exception:
        python_version = "unavailable"
    try:
        from threadpoolctl import threadpool_info

        # Exclude absolute library paths and other incidental host details.
        keys = ("user_api", "internal_api", "version", "num_threads", "threading_layer", "architecture")
        libraries = [{key: item.get(key) for key in keys} for item in threadpool_info()]
        library_status = "recorded" if libraries else "no loaded libraries detected"
    except Exception:
        libraries = []
        library_status = "unavailable"
    return {
        "schema_version": 2,
        "capture_scope": "run record creation; installed packages and currently loaded numerical libraries",
        "python": python_version,
        "packages": packages,
        "backend_build_commit": _build_commit(),
        "numerical_libraries": {"state": library_status, "libraries": libraries},
    }
