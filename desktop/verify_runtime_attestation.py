#!/usr/bin/env python3
"""Fail the desktop build unless its environment satisfies the managed runtime.

Every canonical node contract declares the exact ``numpy``, ``scipy``, and
``scikit-learn`` versions the first-party scientific profile was qualified
against, and ``runtime_attestation()`` refuses any other version at execution
time.  A bundle built against a drifted resolution therefore installs and
launches cleanly but fails on the user's first PLS fit, which is the worst
place to discover it -- and worse still once the bundle has been signed and
notarized.

Run this after the build environment is installed and before PyInstaller
collects it, so a drifted resolution stops the lane instead of shipping.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import sys
from pathlib import Path


def dependency_provenance(attestation) -> dict:
    build = {}
    for dist in importlib.metadata.distributions():
        name = re.sub(r"[-_.]+", "-", dist.metadata["Name"]).lower()
        if name in build and build[name] != dist.version:
            raise RuntimeError(f"Ambiguous installed distribution: {name}")
        build[name] = dist.version
    return {
        "schema_version": 1,
        "build_environment": {
            "scope": "resolved_build_environment_not_bundle_inventory",
            "distributions": dict(sorted(build.items())),
        },
        "scientific_runtime": {
            "scope": "canonical_profile_runtime_attestation",
            "profile_id": attestation.profile_id,
            "profile_digest": attestation.profile_digest,
            "distributions": {item.distribution: item.version for item in attestation.distributions},
        },
    }


def main(output: Path | None = None) -> int:
    # Importing the app wires the node registry that carries the contracts.
    import spectra_sherpa.app.main  # noqa: F401
    from spectra_sherpa.app.services.dag.managed_optimization_profile import (
        ManagedOptimizationProfileError,
        managed_optimization_profile,
    )

    profile = managed_optimization_profile()
    if not profile.operation_ids:
        print(
            "FAIL: the managed optimization profile registered no operations, so "
            "the build environment cannot be attested at all.",
            file=sys.stderr,
        )
        return 1

    try:
        attestation = profile.runtime_attestation()
    except ManagedOptimizationProfileError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        print(
            "\nThe build environment does not match the versions the scientific "
            "core attests.\nReconcile pyproject.toml, requirements.txt, and "
            "poetry.lock with the\n`runtime_requirements` on the node execution "
            "contracts before building.",
            file=sys.stderr,
        )
        return 1

    print(f"Managed runtime attestation satisfied for profile {attestation.profile_id!r}:")
    for requirement in attestation.distributions:
        print(f"  {requirement.distribution}=={requirement.version}")
    if output is not None:
        output.write_text(json.dumps(dependency_provenance(attestation), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    raise SystemExit(main(parser.parse_args().output))
