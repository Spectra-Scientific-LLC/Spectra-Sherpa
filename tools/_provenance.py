"""Shared environment-provenance guard for standalone evidence-generation scripts.

Every tool in this directory imports ``spectra_sherpa`` outside pytest (whose
own ``pythonpath = ["src"]`` setting already makes it immune to this). A
shared interpreter with another editable Spectra Sherpa checkout installed
(a ``.pth`` file pointing at a different worktree) can silently resolve the
import to the WRONG checkout even after ``sys.path.insert(0, ...)``, because
site-installed ``.pth`` entries and prior imports in the same interpreter
session are not guaranteed to lose to a later path insertion. A generator
script that "succeeds" against the wrong checkout produces evidence that
looks valid and is not: it silently corrupted a real evidence-regeneration
run once already. Every tool here must call `require_local_checkout()`
immediately after importing `spectra_sherpa`, not just insert a path and
hope. See manifest.md, "Machine gates enforce what review bandwidth cannot."
"""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_local_checkout_on_path(script_file: str) -> Path:
    """Prepend this script's own package `src/` to `sys.path`. Call first."""

    package_root = Path(script_file).resolve().parents[1]
    sys.path.insert(0, str(package_root / "src"))
    return package_root


def require_local_checkout(package_root: Path) -> None:
    """Fail loudly if `spectra_sherpa` did not resolve under `package_root`.

    Call this immediately after importing `spectra_sherpa`, not just after
    inserting its path — the insertion alone does not prove the import
    actually honored it.
    """

    import spectra_sherpa

    expected = (package_root / "src").resolve()
    imported = Path(spectra_sherpa.__file__).resolve()
    try:
        imported.relative_to(expected)
    except ValueError:
        raise RuntimeError(
            "Environment provenance check failed.\n"
            f"  This tool's own checkout is at:          {expected}\n"
            f"  But `import spectra_sherpa` resolved to: {imported}\n"
            "  These are different checkouts. Any evidence this tool "
            "generates would silently describe the WRONG code.\n"
            "  Fix: run with an interpreter that has no other editable "
            "Spectra Sherpa install shadowing this one, or explicitly set "
            f"PYTHONPATH={expected} before this script's own sys.path "
            "insertion can be shadowed."
        ) from None
