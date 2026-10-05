#!/usr/bin/env python3
"""Qualify the supported public wheel profiles in isolated environments.

This is a release/readiness probe, not a per-commit CI suite. It installs the
same wheel into fresh virtual environments, proves the default Workbench and
SDK imports, verifies each optional capability's distribution boundary, and
records install time and environment size without making those measurements
brittle pass/fail performance thresholds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROFILE_REQUIREMENTS = {
    "default": frozenset(),
    "scp": frozenset({"spectrochempy"}),
    "hitran": frozenset({"hitran-api", "hitran-api2"}),
    "nist": frozenset({"beautifulsoup4"}),
    "postgres": frozenset({"asyncpg", "gunicorn"}),
    "hitran,nist": frozenset({"beautifulsoup4", "hitran-api", "hitran-api2"}),
    "scp,hitran,nist": frozenset({"beautifulsoup4", "hitran-api", "hitran-api2", "spectrochempy"}),
}
OPTIONAL_DISTRIBUTIONS = frozenset().union(*PROFILE_REQUIREMENTS.values())


def _run(*command: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )


def _environment_size(site_packages: Path) -> int:
    return sum(path.stat().st_size for path in site_packages.rglob("*") if path.is_file())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _profile_target(wheel: Path, profile: str) -> str:
    return str(wheel) if profile == "default" else f"{wheel}[{profile}]"


def _qualify_profile(*, bootstrap_python: Path, wheel: Path, profile: str, root: Path) -> dict[str, object]:
    environment = root / profile.replace(",", "-")
    _run(str(bootstrap_python), "-m", "venv", str(environment))
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    started = time.perf_counter()
    _run(
        str(executable),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        _profile_target(wheel, profile),
    )
    install_seconds = time.perf_counter() - started

    probe = _run(
        str(executable),
        "-c",
        "\n".join(
            (
                "import importlib.metadata as metadata",
                "import json, sysconfig, time",
                "started = time.perf_counter()",
                "import spectra_sherpa",
                "import spectra_sherpa.sdk",
                "from spectra_sherpa.sdk import plot as sdk_plot",
                "from spectra_sherpa.sdk.plot_spec import CanonicalPlotSpec",
                "import spectra_sherpa.cli",
                "import spectra_sherpa.app.main",
                # The published wheel must satisfy the same managed runtime
                # attestation the scientific core enforces at execution time.
                # Import ranges that resolve a different numpy/scipy/
                # scikit-learn make every canonical validation graph refuse to
                # run, so prove the pins here rather than in the user's first
                # PLS fit.
                "from spectra_sherpa.app.services.dag.managed_optimization_profile import (",
                "    managed_optimization_profile,",
                ")",
                "_profile = managed_optimization_profile()",
                "if not _profile.operation_ids:",
                "    raise SystemExit('managed optimization profile registered no operations')",
                "_attested = _profile.runtime_attestation()",
                "import plotly.graph_objects as go",
                "shown = []",
                "go.Figure.show = lambda self, renderer=None: shown.append(renderer)",
                "spec = CanonicalPlotSpec.create(",
                "    plot_type='scatter',",
                "    data=[{'type': 'scatter', 'x': [1.0], 'y': [2.0]}],",
                "    layout={},",
                ")",
                "figure = sdk_plot.show(spec, renderer='json')",
                "assert shown == ['json'] and len(figure.data) == 1",
                "elapsed = time.perf_counter() - started",
                "names = {dist.metadata['Name'] for dist in metadata.distributions()}",
                "names = sorted(name.lower().replace('_', '-') for name in names)",
                "paths = sysconfig.get_paths()",
                "payload = {'distributions': names, 'import_seconds': elapsed}",
                "payload['renderer'] = {'distribution': 'plotly', 'version': metadata.version('plotly')}",
                "payload['site_packages'] = paths['purelib']",
                "payload['runtime_attestation'] = {",
                "    requirement.distribution: requirement.version",
                "    for requirement in _attested.distributions",
                "}",
                "print(json.dumps(payload))",
            )
        ),
    )
    payload = json.loads(probe.stdout)
    distributions = set(payload["distributions"])
    expected = PROFILE_REQUIREMENTS[profile]
    present_optional = distributions & OPTIONAL_DISTRIBUTIONS
    if not expected <= present_optional:
        raise RuntimeError(
            f"profile {profile!r} lacks declared optional distributions: "
            f"expected={sorted(expected)!r}, actual={sorted(present_optional)!r}"
        )
    if profile == "default" and present_optional:
        raise RuntimeError(
            f"default profile unexpectedly installed optional distributions: {sorted(present_optional)!r}"
        )
    _run(str(executable), "-m", "spectra_sherpa.cli", "--help")
    site_packages = Path(payload["site_packages"])
    return {
        "distribution_count": len(distributions),
        "environment_bytes": _environment_size(site_packages),
        "expected_optional_distributions": sorted(expected),
        "present_optional_distributions": sorted(present_optional),
        "import_seconds": payload["import_seconds"],
        "install_seconds": install_seconds,
        "python": _run(str(executable), "--version").stdout.strip(),
        "renderer": payload["renderer"],
        "runtime_attestation": payload["runtime_attestation"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--lockfile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()

    wheel = args.wheel.resolve()
    if not wheel.is_file():
        parser.error(f"wheel does not exist: {wheel}")
    lockfile = args.lockfile.resolve()
    if not lockfile.is_file():
        parser.error(f"lockfile does not exist: {lockfile}")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="spectra-public-profiles-") as temporary:
        root = Path(temporary)
        profiles = {
            profile: _qualify_profile(
                bootstrap_python=args.python.resolve(),
                wheel=wheel,
                profile=profile,
                root=root,
            )
            for profile in PROFILE_REQUIREMENTS
        }
    report = {
        "profiles": profiles,
        "poetry_lock_sha256": _sha256(lockfile),
        "schema_version": "spectra-public-install-qualification/1",
        "source_revision": args.source_revision,
        "total_seconds": time.perf_counter() - started,
        "wheel": wheel.name,
        "wheel_bytes": wheel.stat().st_size,
        "wheel_sha256": _sha256(wheel),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
