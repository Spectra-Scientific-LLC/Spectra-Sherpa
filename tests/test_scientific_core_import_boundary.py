"""Structural import gates for the reusable canonical scientific core."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa"
_DAG = _SOURCE / "app" / "services" / "dag"
_WEB_ROOTS = frozenset({"fastapi", "starlette", "uvicorn"})
_COUPLING_INVENTORY = _SOURCE.parents[3] / "docs" / "evidence" / "scientific-core-coupling-inventory.json"
_EXTRA_MEASURED_FILES = (_SOURCE / "app" / "lib" / "eigenvector.py",)
_APPLICATION_PREFIXES = (
    "spectra_sherpa.app.core",
    "spectra_sherpa.app.db",
    "spectra_sherpa.app.models",
    "spectra_sherpa.app.services",
)
_APPLICATION_DISTRIBUTIONS = frozenset(
    {"alembic", "fastapi", "pydantic_settings", "sqlalchemy", "starlette", "uvicorn"}
)


def _import_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _boundary_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "spectra_sherpa.app.services":
                names.extend(f"{node.module}.{alias.name}" for alias in node.names)
            else:
                names.append(node.module)
        for name in names:
            if name.startswith("spectra_sherpa.app.services.dag"):
                continue
            if name.startswith(_APPLICATION_PREFIXES) or name.split(".", 1)[0] in _APPLICATION_DISTRIBUTIONS:
                imports.add(name)
    return imports


def _measured_couplings() -> dict[str, list[str]]:
    paths = [*_DAG.rglob("*.py"), *_EXTRA_MEASURED_FILES]
    return {str(path.relative_to(_SOURCE)): sorted(imports) for path in paths if (imports := _boundary_imports(path))}


def test_dag_tree_has_no_direct_web_framework_imports() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _DAG.rglob("*.py"):
        forbidden = _import_roots(path) & _WEB_ROOTS
        if forbidden:
            offenders[str(path.relative_to(_SOURCE))] = sorted(forbidden)
    assert offenders == {}, f"scientific DAG modules import web frameworks: {offenders}"


def test_post_664_coupling_inventory_matches_source_exactly() -> None:
    document = json.loads(_COUPLING_INVENTORY.read_text(encoding="utf-8"))
    recorded = {entry["path"]: entry["imports"] for entry in document["entries"]}

    assert document["schema_version"] == "spectra-scientific-core-coupling-inventory/1"
    assert document["measurement_basis"]["baseline_commit"] == "17f39657a82ecf0ddd7bad59650b5b73f5caf23d"
    assert document["measurement_basis"]["post_664_coupled_file_count"] == 17
    assert document["measurement_basis"]["current_unresolved_file_count"] == len(recorded) == 0
    assert recorded == _measured_couplings()


def test_scientific_metadata_contract_import_does_not_load_orm() -> None:
    source = _SOURCE.parent
    probe = (
        "import sys; "
        "import spectra_sherpa.core.spectra_meta; "
        "assert 'sqlalchemy' not in sys.modules; "
        "assert not any(name.startswith('spectra_sherpa.app.models') for name in sys.modules)"
    )
    subprocess.run(
        [sys.executable, "-c", probe],
        check=True,
        cwd=source,
        env={**os.environ, "PYTHONPATH": str(source), "PYTHONNOUSERSITE": "1"},
    )


def test_retired_orm_metadata_module_is_absent() -> None:
    assert not (_SOURCE / "app" / "models" / "spectra_meta.py").exists()
