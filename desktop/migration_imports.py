"""Discover first-party imports in Alembic scripts without executing migrations.

Alembic loads these Python files as data. PyInstaller cannot see their imports
through the normal application module graph, so include them explicitly.
"""

import ast
from pathlib import Path


def migration_hidden_imports(migration_root: Path) -> list[str]:
    modules: set[str] = set()
    for path in sorted(migration_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names if alias.name.startswith("spectra_sherpa."))
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("spectra_sherpa."):
                modules.add(node.module)
    return sorted(modules)
