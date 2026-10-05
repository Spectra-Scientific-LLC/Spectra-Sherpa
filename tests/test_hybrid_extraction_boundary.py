"""The public package does not acquire a dependency on extracted implementation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa"


def test_public_sources_never_import_private_hybrid_packages():
    offenders = []
    for path in ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            )
            if any(name.split(".")[0] in {"spectra_hybrid", "spectra_hybrid_contracts"} for name in names):
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders


def test_hybrid_implementations_are_absent_from_public_source():
    forbidden = (
        "commercial_hybrid.py",
        "app/api/v1/routes/hybrid.py",
        "app/services/commercial_hybrid_client.py",
        "app/services/hybrid_device_client.py",
        "app/services/hybrid_advisor_client.py",
        "app/services/network_health.py",
        "app/services/spectrasherpa.py",
        "app/contracts/hybrid_advisor.py",
        "app/contracts/hybrid_disclosure.py",
        "app/contracts/hybrid_request.py",
        "app/contracts/hybrid_workflow_proposal.py",
        "app/contracts/commercial_hybrid_egress.py",
    )
    assert not [name for name in forbidden if (ROOT / name).exists()]


def test_import_guard_rejects_guarded_and_dynamic_private_dependencies(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("guard", ROOT.parents[1] / "scripts/check_import_boundary.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    for name in ("spectra_hybrid", "spectra_hybrid_contracts", "spectrasherpa_server"):
        for source in (
            f"try:\n    import {name}\nexcept ImportError:\n    pass\n",
            f"import importlib\nimportlib.import_module('{name}.app')\n",
            f"__import__('{name}')\n",
        ):
            candidate = tmp_path / "candidate.py"
            candidate.write_text(source)
            assert guard.check_file(candidate), source
